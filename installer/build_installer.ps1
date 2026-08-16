param(
    [string]$IsccPath,
    [string]$OutputPath = "build\local-windows"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
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
    $localBuild = Join-Path $ProjectRoot "scripts\build_windows_local.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $localBuild
    if ($LASTEXITCODE -ne 0) { throw "Windows app build failed: $LASTEXITCODE" }

    $BundlePath = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot $OutputPath)).Path
    & $Iscc "/DAppBundleDir=$BundlePath" (Join-Path $PSScriptRoot "entp_installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed: $LASTEXITCODE" }

    $BuiltInstaller = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "release") `
        -Filter "*2.1.4*.exe" | Where-Object { $_.Name -ne "ENTPManual.exe" } | `
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $BuiltInstaller) { throw "Built installer was not found." }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $PSScriptRoot "create_update_manifest.ps1") `
        -Version "2.1.4" `
        -InstallerPath $BuiltInstaller.FullName `
        -OutputPath (Join-Path $ProjectRoot "release\update.json")
    if ($LASTEXITCODE -ne 0) { throw "Update manifest generation failed: $LASTEXITCODE" }
}
finally {
    Pop-Location
}
