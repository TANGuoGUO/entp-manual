param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$Installer = Get-Item -LiteralPath $InstallerPath
$AssetName = "ENTP-Manual-$Version-Setup.exe"
$Hash = (Get-FileHash -LiteralPath $Installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$Notes = Get-Content -LiteralPath (Join-Path $PSScriptRoot "update_notes.txt") -Raw -Encoding UTF8
$Manifest = [ordered]@{
    version = $Version
    tag_name = "v$Version"
    notes = $Notes.Trim()
    html_url = "https://github.com/TANGuoGUO/entp-manual/releases/tag/v$Version"
    asset_name = $AssetName
    download_url = "https://github.com/TANGuoGUO/entp-manual/releases/download/v$Version/$AssetName"
    size = $Installer.Length
    sha256 = $Hash
}
$Json = $Manifest | ConvertTo-Json -Depth 3
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$OutputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
[System.IO.File]::WriteAllText($OutputFullPath, $Json, $Utf8NoBom)
