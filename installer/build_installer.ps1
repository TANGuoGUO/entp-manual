param(
    [string]$FletPath,
    [string]$IsccPath,
    [string]$OutputPath = "build\windows"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Flet = if ($FletPath) { $FletPath } else { Join-Path $ProjectRoot ".venv\Scripts\flet.exe" }
$IsccCandidates = @(
    $IsccPath,
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
 ) | Where-Object { $_ }
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $Iscc) { throw "Inno Setup 6 was not found." }

Push-Location $ProjectRoot
try {
    & $Flet build windows . --output $OutputPath `
        --project "entp_manual" `
        --artifact "ENTPManual" `
        --product "ENTP 自强手册" `
        --company "ENTP Manual" `
        --description "好奇心动力回流系统" `
        --build-version "2.1.3" `
        --python-version "3.13" `
        --exclude ".venv" "build" "release" "tests" "vendor" "outputs" "logs" "backups" "designs" "installer" "markdown" "*.db" "*.spec" `
        --yes --no-rich-output
    if ($LASTEXITCODE -ne 0) { throw "Windows app build failed: $LASTEXITCODE" }

    $BundlePath = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot $OutputPath)).Path
    & $Iscc "/DAppBundleDir=$BundlePath" (Join-Path $PSScriptRoot "entp_installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed: $LASTEXITCODE" }

    $BuiltInstaller = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "release") `
        -Filter "*2.1.3*.exe" | Where-Object { $_.Name -ne "ENTPManual.exe" } | `
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $BuiltInstaller) { throw "Built installer was not found." }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $PSScriptRoot "create_update_manifest.ps1") `
        -Version "2.1.3" `
        -InstallerPath $BuiltInstaller.FullName `
        -OutputPath (Join-Path $ProjectRoot "release\update.json")
    if ($LASTEXITCODE -ne 0) { throw "Update manifest generation failed: $LASTEXITCODE" }
}
finally {
    Pop-Location
}
