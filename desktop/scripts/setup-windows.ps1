# Vendor Tesseract OCR for the Windows build (run once, before `make build`).
#
# Downloads the current UB-Mannheim Tesseract release and unpacks it with
# innoextract - the installer binary is never executed (silent Inno installs
# hang indefinitely on unattended runners). Falls back to running the
# installer for humans when innoextract isn't available. Prunes language
# packs to the two the app offers (eng + tam - see SUPPORTED_OCR_LANGS in
# backend/app/services/ocr_service.py); tam is fetched from the upstream
# tessdata repo because stock installs ship only eng + osd.
# pyinstaller.spec bundles the directory when it exists; Linux never runs this.
#
# Usage (from desktop/):  powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1

$ErrorActionPreference = "Stop"

$vendor = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\vendor\tesseract"))
if (Test-Path (Join-Path $vendor "tesseract.exe")) {
    Write-Host "Tesseract already vendored at $vendor - skipping."
    exit 0
}

Write-Host "Finding the latest UB-Mannheim Tesseract release..."
$release = Invoke-RestMethod -TimeoutSec 60 "https://api.github.com/repos/UB-Mannheim/tesseract/releases/latest"
$asset = $release.assets |
    Where-Object { $_.name -like "tesseract-ocr-w64-setup-*.exe" } |
    Select-Object -First 1
if (-not $asset) { throw "No w64 installer asset found in the latest release." }

$tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP "lifelogr-tesseract") -Force
$installer = Join-Path $tmp $asset.name
Write-Host "Downloading $($asset.name) ..."
curl.exe -L --fail --retry 3 -o $installer $asset.browser_download_url
if ($LASTEXITCODE -ne 0) { throw "Download failed (curl exit $LASTEXITCODE)." }

$appRoot = $null
if (Get-Command innoextract -ErrorAction SilentlyContinue) {
    # CI path: unpack the Inno {app} tree without executing anything.
    Write-Host "Extracting with innoextract ..."
    $extractDir = Join-Path $tmp "extract"
    innoextract -d $extractDir $installer
    if ($LASTEXITCODE -ne 0) { throw "innoextract failed (exit $LASTEXITCODE)." }
    $exe = Get-ChildItem $extractDir -Recurse -Filter "tesseract.exe" |
        Select-Object -First 1
    if (-not $exe) { throw "tesseract.exe not found in the extracted installer." }
    $appRoot = $exe.Directory.FullName
    New-Item -ItemType Directory -Path $vendor -Force | Out-Null
    Copy-Item (Join-Path $appRoot "*") $vendor -Recurse -Force
} else {
    # Human path: no innoextract, so run the (Inno Setup) installer directly.
    Write-Host "Installing into $vendor ..."
    $proc = Start-Process $installer "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$vendor`"" -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw "Installer exited with code $($proc.ExitCode)." }
}
if (-not (Test-Path (Join-Path $vendor "tesseract.exe"))) {
    throw "Setup finished but tesseract.exe is missing at $vendor"
}

# Keep only the languages the app offers - the stock install carries dozens
# of packs we'd otherwise bundle for nothing.
$tessdata = Join-Path $vendor "tessdata"
Get-ChildItem $tessdata -File |
    Where-Object { $_.Name -notmatch '^(eng|tam)\.traineddata$' } |
    Remove-Item -Force
Remove-Item (Join-Path $tessdata "script") -Recurse -Force -ErrorAction SilentlyContinue

# Stock installs ship eng + osd only; fetch the Tamil pack the app offers.
if (-not (Test-Path (Join-Path $tessdata "tam.traineddata"))) {
    Write-Host "Fetching tam.traineddata ..."
    curl.exe -L --fail --retry 3 -o (Join-Path $tessdata "tam.traineddata") `
        "https://github.com/tesseract-ocr/tessdata/raw/main/tam.traineddata"
    if ($LASTEXITCODE -ne 0) { throw "tam.traineddata download failed." }
}

Remove-Item $tmp -Recurse -Force
Write-Host "Done: tesseract.exe + eng/tam tessdata vendored at $vendor"
