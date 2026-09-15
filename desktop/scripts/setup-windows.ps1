# Vendor Tesseract OCR for the Windows build (run once, before `make build`).
#
# Puts tesseract.exe + eng/tam tessdata into desktop/vendor/tesseract; the
# PyInstaller spec bundles the directory so OCR works out of the box. Linux
# builds get tesseract from apt and never run this.
#
# Two install routes (languages pruned to eng + tam either way - see
# SUPPORTED_OCR_LANGS in backend/app/services/ocr_service.py; tam comes from
# the upstream tessdata repo since stock installs ship only eng + osd):
#
#   1. chocolatey `tesseract` package - the standard unattended-runner recipe.
#   2. Direct UB-Mannheim installer fallback with a hard 10-minute timeout and
#      an Inno /LOG dump, after a bare silent install was observed to hang CI
#      for an hour. For humans the same fallback is the normal path.

$ErrorActionPreference = "Stop"

$vendor = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\vendor\tesseract"))
if (Test-Path (Join-Path $vendor "tesseract.exe")) {
    Write-Host "Tesseract already vendored at $vendor - skipping."
    exit 0
}

$tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP "lifelogr-tesseract") -Force
$tessVersion = "5.5.0.20241111"
$installed = $false

# Route 1: chocolatey (installs to C:\Program Files\Tesseract-OCR).
$choco = Join-Path $env:ProgramData "chocolatey\choco.exe"
if (-not (Test-Path $choco)) { $choco = "choco" }
if (Get-Command $choco -ErrorAction SilentlyContinue) {
    Write-Host "Installing tesseract $tessVersion via chocolatey ..."
    $proc = Start-Process $choco `
        -ArgumentList "install", "tesseract", "-y", "--no-progress", "--version=$tessVersion" `
        -PassThru -NoNewWindow
    if ($proc.WaitForExit(900000)) {
        # Don't gate on ExitCode - it comes back empty when choco is launched
        # via its shim. The installed binary is the source of truth.
        Write-Host "choco exited with code $($proc.ExitCode)."
        $src = Join-Path ${env:ProgramFiles} "Tesseract-OCR"
        if (Test-Path (Join-Path $src "tesseract.exe")) {
            New-Item -ItemType Directory -Path $vendor -Force | Out-Null
            Copy-Item (Join-Path $src "*") $vendor -Recurse -Force
            $installed = $true
        } else {
            Write-Host "tesseract.exe not found in $src - trying direct installer."
        }
    } else {
        $proc.Kill()
        Write-Host "choco install timed out after 15 min - trying direct installer."
    }
}

# Route 2: direct UB-Mannheim installer (fallback on CI, primary for humans
# without chocolatey). Bounded so a wedged setup fails fast, with the Inno
# log in the error for diagnosis.
if (-not $installed) {
    # 5.4.0 is the newest release whose asset name matches this URL pattern;
    # the 5.5.0 tag ships a different (unresolved) asset name.
    $fallbackVersion = "5.4.0.20240606"
    $url = "https://github.com/UB-Mannheim/tesseract/releases/download/v$fallbackVersion/tesseract-ocr-w64-setup-$fallbackVersion.exe"
    $installer = Join-Path $tmp (Split-Path $url -Leaf)
    Write-Host "Downloading $url ..."
    curl.exe -L --fail --retry 3 -o $installer $url
    if ($LASTEXITCODE -ne 0) { throw "Download failed (curl exit $LASTEXITCODE)." }

    Write-Host "Installing into $vendor ..."
    $log = Join-Path $tmp "inno.log"
    $proc = Start-Process $installer `
        -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /FORCECLOSEAPPLICATIONS /DIR=`"$vendor`" /LOG=`"$log`"" `
        -PassThru
    if (-not $proc.WaitForExit(600000)) {
        $proc.Kill()
        if (Test-Path $log) {
            Write-Host "--- inno.log tail ---"
            Get-Content $log -Tail 30 | Write-Host
        }
        throw "Tesseract installer did not finish within 10 minutes - killed."
    }
    if ($proc.ExitCode -ne 0) { throw "Installer exited with code $($proc.ExitCode)." }
    if (-not (Test-Path (Join-Path $vendor "tesseract.exe"))) {
        throw "Install finished but tesseract.exe is missing at $vendor"
    }
}

# Keep only the languages the app offers - stock installs carry dozens of
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
