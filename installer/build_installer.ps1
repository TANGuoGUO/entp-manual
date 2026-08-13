$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Flet = Join-Path $ProjectRoot ".venv\Scripts\flet.exe"
$IsccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $Iscc) { throw "Inno Setup 6 was not found." }

Push-Location $ProjectRoot
try {
    & $Flet pack flet_app.py -n "ENTPManual" --distpath release `
        --add-data "assets:assets" `
        --product-name "ENTP Manual" `
        --file-description "Curiosity Momentum Loop" `
        --product-version "2.0.0" `
        --file-version "2.0.0.0" `
        --company-name "ENTP Manual" -y
    if ($LASTEXITCODE -ne 0) { throw "EXE packaging failed: $LASTEXITCODE" }

    & $Iscc (Join-Path $PSScriptRoot "entp_installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed: $LASTEXITCODE" }
}
finally {
    Pop-Location
}
