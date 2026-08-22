param(
    [switch]$Run
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $projectRoot ".devtools"
$flet = Join-Path $projectRoot ".venv\Scripts\flet.exe"
$flutterRoot = Join-Path $toolRoot "Flutter\3.44.8"
$outputDir = Join-Path $projectRoot "build\local-windows"
$iconSource = Join-Path $projectRoot "assets\app-icon.png"
$appIcon = Join-Path $projectRoot "assets\app-icon.ico"
$windowsIcon = Join-Path $projectRoot "assets\icon_windows.ico"

if (-not (Test-Path -LiteralPath $flet)) {
    throw "Flet virtual environment not found: $flet"
}
if (-not (Test-Path -LiteralPath (Join-Path $flutterRoot "bin\flutter.bat"))) {
    throw "Flutter SDK not found on drive G: $flutterRoot"
}

$productName = -join ([char[]](0x45, 0x4e, 0x54, 0x50, 0x20, 0x81ea, 0x5f3a, 0x624b, 0x518c))
$description = -join ([char[]](0x597d, 0x5947, 0x5fc3, 0x52a8, 0x529b, 0x56de, 0x6d41, 0x7cfb, 0x7edf))

$env:APPDATA = Join-Path $toolRoot "AppData\Roaming"
$env:LOCALAPPDATA = Join-Path $toolRoot "AppData\Local"
$env:PUB_CACHE = Join-Path $toolRoot "PubCache"
$env:FLET_CACHE_DIR = Join-Path $toolRoot "FletCache"
$env:TEMP = Join-Path $toolRoot "Temp"
$env:TMP = $env:TEMP
$env:USERPROFILE = Join-Path $toolRoot "UserHome"
$env:HOME = $env:USERPROFILE
$env:FLUTTER_SUPPRESS_ANALYTICS = "true"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:SERIOUS_PYTHON_VERSION = "3.13"
$env:PATH = (Join-Path $flutterRoot "bin") + ";" + $env:PATH

# The SDK was copied by the workspace sandbox and is executed by the Windows
# desktop account. Trust it only for this process; do not change global Git.
$env:GIT_CONFIG_COUNT = "1"
$env:GIT_CONFIG_KEY_0 = "safe.directory"
$env:GIT_CONFIG_VALUE_0 = ($flutterRoot -replace "\\", "/")

New-Item -ItemType Directory -Force -Path @(
    $env:APPDATA,
    $env:LOCALAPPDATA,
    $env:PUB_CACHE,
    $env:FLET_CACHE_DIR,
    $env:TEMP
    $env:USERPROFILE
) | Out-Null

# Flet first looks for its managed Flutter SDK under the current user home.
# Keep that home on G: and point the expected version directory at the local
# SDK so the build never downloads a second multi-gigabyte copy.
$managedFlutterParent = Join-Path $env:USERPROFILE "flutter"
$managedFlutter = Join-Path $managedFlutterParent "3.44.8"
New-Item -ItemType Directory -Force -Path $managedFlutterParent | Out-Null
if (-not (Test-Path -LiteralPath $managedFlutter)) {
    New-Item -ItemType Junction -Path $managedFlutter -Target $flutterRoot | Out-Null
}

# A cancelled Flet build can leave a committed template hash without the
# generated Flutter project. Invalidate only that generated stamp so the next
# run recreates the shell instead of failing with an invalid working directory.
$flutterProject = Join-Path $projectRoot "build\flutter\pubspec.yaml"
$templateStamp = Join-Path $projectRoot "build\.hash\template-1"
if (-not (Test-Path -LiteralPath $flutterProject) -and (Test-Path -LiteralPath $templateStamp)) {
    Remove-Item -LiteralPath $templateStamp -Force
}
$extensionStamp = Join-Path $projectRoot "build\.hash\template-2"
if ((Test-Path -LiteralPath $flutterProject) -and (Test-Path -LiteralPath $extensionStamp)) {
    $generatedPubspec = Get-Content -LiteralPath $flutterProject -Raw
    if ($generatedPubspec -notmatch "(?m)^\s*flet_quill_editor:") {
        Remove-Item -LiteralPath $extensionStamp -Force
    }
}

Push-Location $projectRoot
try {
    & (Join-Path $projectRoot ".venv\Scripts\python.exe") `
        (Join-Path $projectRoot "scripts\generate_windows_icon.py") `
        $iconSource $appIcon $windowsIcon
    if ($LASTEXITCODE -ne 0) {
        throw "Multi-resolution icon generation failed with exit code $LASTEXITCODE"
    }

    & $flet build windows . `
        --output $outputDir `
        --project entp_manual `
        --artifact ENTPManual `
        --product $productName `
        --company "ENTP Manual" `
        --description $description `
        --build-version 2.1.9 `
        --python-version 3.13 `
        --template "vendor\flet-build-template" `
        --exclude .git .github .venv .devtools build release tests vendor extensions scripts outputs logs backups designs installer markdown tmppdauzxck __pycache__ "*.pyc" "*.db" "*.spec" `
        --yes --no-rich-output -v

    if ($LASTEXITCODE -ne 0) {
        throw "Windows build failed with exit code $LASTEXITCODE"
    }

    # flutter_launcher_icons writes a single 256px image into the Windows
    # runner even when its ICO input contains multiple frames. Replace that
    # generated resource with our real multi-resolution ICO and rebuild the
    # native runner so Explorer, the taskbar, and shortcuts can select the
    # correct frame for each DPI scale.
    $runnerIcon = Join-Path $projectRoot "build\flutter\windows\runner\resources\app_icon.ico"
    $flutterProject = Join-Path $projectRoot "build\flutter"
    $flutterRelease = Join-Path $flutterProject "build\windows\x64\runner\Release"
    Copy-Item -LiteralPath $appIcon -Destination $runnerIcon -Force

    Push-Location $flutterProject
    try {
        & (Join-Path $flutterRoot "bin\flutter.bat") build windows `
            --build-name 2.1.9 `
            --no-version-check `
            --suppress-analytics
        if ($LASTEXITCODE -ne 0) {
            throw "Windows icon resource rebuild failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    # Replace the first-stage bundle instead of merging into it. A merge can
    # preserve a stale python3xx.dll from an earlier build.
    if (Test-Path -LiteralPath $outputDir) {
        Remove-Item -LiteralPath $outputDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $outputDir | Out-Null
    Copy-Item -Path (Join-Path $flutterRelease "*") `
        -Destination $outputDir -Recurse -Force

    & (Join-Path $projectRoot ".venv\Scripts\python.exe") `
        (Join-Path $projectRoot "scripts\verify_windows_bundle.py") `
        $outputDir --python-version 3.13
    if ($LASTEXITCODE -ne 0) {
        throw "Windows bundle runtime verification failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$exe = Join-Path $outputDir "ENTPManual.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build completed but executable was not found: $exe"
}

Write-Host "Windows development build created: $exe"
if ($Run) {
    Start-Process -FilePath $exe -WorkingDirectory $outputDir
}
