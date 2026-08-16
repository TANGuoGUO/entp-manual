param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$Image,
    [Parameter(Mandatory = $true)][string]$Database,
    [Parameter(Mandatory = $true)][string]$Screenshot
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class EntpPasteQaWin32 {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr processId);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint attach, uint attachTo, bool value);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr insertAfter, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
}
"@

$source = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $Image))
try {
    $clipboardBitmap = New-Object System.Drawing.Bitmap $source
    [System.Windows.Forms.Clipboard]::SetImage($clipboardBitmap)
} finally {
    $source.Dispose()
}

$databasePath = [System.IO.Path]::GetFullPath($Database)
$screenshotPath = [System.IO.Path]::GetFullPath($Screenshot)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($databasePath)) | Out-Null
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($screenshotPath)) | Out-Null

$env:ENTP_QA_DB = $databasePath
$env:ENTP_QA_TASK_DETAIL = "1"
$env:ENTP_QA_PASTE_ON_MOUNT = "1"
$process = Start-Process -FilePath $Exe -WorkingDirectory ([System.IO.Path]::GetDirectoryName($Exe)) -PassThru

try {
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 250
        $process.Refresh()
    } while ($process.MainWindowHandle -eq [IntPtr]::Zero -and [DateTime]::UtcNow -lt $deadline)

    if ($process.MainWindowHandle -eq [IntPtr]::Zero) {
        throw "The QA application did not create a window."
    }

    Start-Sleep -Seconds 3
    $handle = $process.MainWindowHandle
    [EntpPasteQaWin32]::ShowWindow($handle, 9) | Out-Null
    # Temporarily place the QA window above existing always-on-top apps so the
    # keyboard event cannot be consumed by another desktop program.
    [EntpPasteQaWin32]::SetWindowPos($handle, [IntPtr](-1), 0, 0, 0, 0, 0x0013) | Out-Null
    $windowThread = [EntpPasteQaWin32]::GetWindowThreadProcessId($handle, [IntPtr]::Zero)
    $currentThread = [EntpPasteQaWin32]::GetCurrentThreadId()
    [EntpPasteQaWin32]::AttachThreadInput($currentThread, $windowThread, $true) | Out-Null
    try {
        [EntpPasteQaWin32]::SetForegroundWindow($handle) | Out-Null
    } finally {
        [EntpPasteQaWin32]::AttachThreadInput($currentThread, $windowThread, $false) | Out-Null
    }
    $rect = New-Object EntpPasteQaWin32+RECT
    [EntpPasteQaWin32]::GetWindowRect($handle, [ref]$rect) | Out-Null

    # The task-detail editor occupies the center/right modal body. A click
    # guarantees the Quill document owns the caret before the real Ctrl+V.
    $x = $rect.Left + [Math]::Min(760, [Math]::Max(420, ($rect.Right - $rect.Left) / 2))
    $y = $rect.Top + [Math]::Min(350, [Math]::Max(260, ($rect.Bottom - $rect.Top) / 3))
    [EntpPasteQaWin32]::SetCursorPos([int]$x, [int]$y) | Out-Null
    [EntpPasteQaWin32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [EntpPasteQaWin32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("^v")
    Start-Sleep -Seconds 3

    [EntpPasteQaWin32]::SetWindowPos($handle, [IntPtr](-2), 0, 0, 0, 0, 0x0013) | Out-Null

    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    $capture = New-Object System.Drawing.Bitmap $width, $height
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($capture)
        try {
            $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $capture.Size)
        } finally {
            $graphics.Dispose()
        }
        $capture.Save($screenshotPath, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $capture.Dispose()
    }
} finally {
    if ($clipboardBitmap) { $clipboardBitmap.Dispose() }
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}
