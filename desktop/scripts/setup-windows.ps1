# Vendor Tesseract OCR for the Windows build (run once, before `make build`).
#
# Downloads the current UB-Mannheim Tesseract release, silently installs it
# into desktop/vendor/tesseract, and prunes the language packs to the two the
# app offers (eng + tam - see SUPPORTED_OCR_LANGS in
# backend/app/services/ocr_service.py). pyinstaller.spec collects the
# directory into the sidecar when it exists; Linux builds never run this.
#
# Usage (from desktop/):  powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1

$ErrorActionPreference = "Stop"

$vendor = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\vendor\tesseract"))
if (Test-Path (Join-Path $vendor "tesseract.exe")) {
    Write-Host "Tesseract already vendored at $vendor - skipping."
    exit 0
}

Write-Host "Finding the latest UB-Mannheim Tesseract release..."
$release = Invoke-RestMethod "https://api.github.com/repos/UB-Mannheim/tesseract/releases/latest"
$asset = $release.assets |
    Where-Object { $_.name -like "tesseract-ocr-w64-setup-*.exe" } |
    Select-Object -First 1
if (-not $asset) { throw "No w64 installer asset found in the latest release." }

$tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP "lifelogr-tesseract") -Force
$installer = Join-Path $tmp $asset.name
Write-Host "Downloading $($asset.name) ..."
# curl.exe (ships with Windows 10+) - Invoke-WebRequest under PowerShell 5.1
# crawls on large downloads due to progress-bar rendering.
curl.exe -L --fail --retry 3 -o $installer $asset.browser_download_url
if ($LASTEXITCODE -ne 0) { throw "Download failed (curl exit $LASTEXITCODE)." }

Write-Host "Installing into $vendor ..."
# Inno Setup flags: silent, no reboot, custom install dir.
$proc = Start-Process $installer "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$vendor`"" -Wait -PassThru
if ($proc.ExitCode -ne 0) { throw "Installer exited with code $($proc.ExitCode)." }
if (-not (Test-Path (Join-Path $vendor "tesseract.exe"))) {
    throw "Install finished but tesseract.exe is missing at $vendor"
}

# Keep only the languages the app offers - the stock install carries dozens of
# packs we'd otherwise bundle for nothing.
$tessdata = Join-Path $vendor "tessdata"
if (Test-Path $tessdata) {
    Get-ChildItem $tessdata -File |
        Where-Object { $_.Name -notmatch '^(eng|tam)\.traineddata$' } |
        Remove-Item -Force
    $scriptDir = Join-Path $tessdata "script"
    if (Test-Path $scriptDir) { Remove-Item $scriptDir -Recurse -Force }
}

Remove-Item $tmp -Recurse -Force
Write-Host "Done: tesseract.exe + eng/tam tessdata vendored at $vendor"
