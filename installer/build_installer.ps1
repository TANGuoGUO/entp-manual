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
        --icon "assets\app-icon.ico" `
        --add-data "assets:assets" `
        --product-name "ENTP Manual" `
        --file-description "Curiosity Momentum Loop" `
        --product-version "2.1.0" `
        --file-version "2.1.0.0" `
        --company-name "ENTP Manual" -y
    if ($LASTEXITCODE -ne 0) { throw "EXE packaging failed: $LASTEXITCODE" }

    & $Iscc (Join-Path $PSScriptRoot "entp_installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed: $LASTEXITCODE" }

    $BuiltInstaller = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "release") `
        -Filter "*2.1.0*.exe" | Where-Object { $_.Name -ne "ENTPManual.exe" } | `
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $BuiltInstaller) { throw "Built installer was not found." }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $PSScriptRoot "create_update_manifest.ps1") `
        -Version "2.1.0" `
        -InstallerPath $BuiltInstaller.FullName `
        -OutputPath (Join-Path $ProjectRoot "release\update.json")
    if ($LASTEXITCODE -ne 0) { throw "Update manifest generation failed: $LASTEXITCODE" }
}
finally {
    Pop-Location
}
