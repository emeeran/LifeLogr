# Vendor Tesseract OCR for the Windows build (run once, before `make build`).
#
# Downloads the UB-Mannheim Tesseract installer, silently installs it into
# desktop/vendor/tesseract, and prunes the language packs to the two the app
# offers (eng + tam - see SUPPORTED_OCR_LANGS in
# backend/app/services/ocr_service.py); tam is fetched from the upstream
# tessdata repo because stock installs ship only eng + osd.
# pyinstaller.spec bundles the directory when it exists; Linux never runs this.
#
# Unattended-runner hardening: the pinned direct release URL avoids
# api.github.com (which intermittently stalls runners' connections), and the
# installer gets a hard 10-minute timeout so a wedged install fails fast
# instead of hanging the build for an hour.
#
# Usage (from desktop/):  powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1

$ErrorActionPreference = "Stop"

$vendor = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\vendor\tesseract"))
if (Test-Path (Join-Path $vendor "tesseract.exe")) {
    Write-Host "Tesseract already vendored at $vendor - skipping."
    exit 0
}

$tessVersion = "5.4.0.20240606"
$url = "https://github.com/UB-Mannheim/tesseract/releases/download/v$tessVersion/tesseract-ocr-w64-setup-$tessVersion.exe"

$tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP "lifelogr-tesseract") -Force
$installer = Join-Path $tmp (Split-Path $url -Leaf)
Write-Host "Downloading $url ..."
curl.exe -L --fail --retry 3 -o $installer $url
if ($LASTEXITCODE -ne 0) { throw "Download failed (curl exit $LASTEXITCODE)." }

Write-Host "Installing into $vendor ..."
# Inno Setup flags: silent, no reboot, custom install dir. WaitForExit caps a
# wedged install at 10 minutes (a bare -Wait has hung CI for an hour).
$proc = Start-Process $installer "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$vendor`"" -PassThru
if (-not $proc.WaitForExit(600000)) {
    $proc.Kill()
    throw "Tesseract installer did not finish within 10 minutes - killed."
}
if ($proc.ExitCode -ne 0) { throw "Installer exited with code $($proc.ExitCode)." }
if (-not (Test-Path (Join-Path $vendor "tesseract.exe"))) {
    throw "Install finished but tesseract.exe is missing at $vendor"
}

# Keep only the languages the app offers - the stock install carries dozens of
# packs we'd otherwise bundle for nothing.
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
