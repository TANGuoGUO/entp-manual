param([Parameter(Mandatory = $true)][int]$ProcessId)

$ErrorActionPreference = "Stop"
Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class EntpWindowActivator {
    [StructLayout(LayoutKind.Sequential)]
    private struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr hWnd, int command);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr hWnd, IntPtr insertAfter, int x, int y, int cx, int cy, uint flags);

    public static bool Show(int targetProcessId) {
        IntPtr best = IntPtr.Zero;
        long largestArea = 0;
        EnumWindows((hWnd, lParam) => {
            uint owner;
            GetWindowThreadProcessId(hWnd, out owner);
            if (owner != targetProcessId) return true;
            RECT rect;
            if (GetWindowRect(hWnd, out rect)) {
                long area = Math.Max(0, rect.Right - rect.Left) * (long)Math.Max(0, rect.Bottom - rect.Top);
                if (area > largestArea) { largestArea = area; best = hWnd; }
            }
            return true;
        }, IntPtr.Zero);
        if (best == IntPtr.Zero) return false;
        ShowWindow(best, 9);
        SetWindowPos(best, new IntPtr(-1), 0, 0, 0, 0, 0x0013);
        SetForegroundWindow(best);
        SetWindowPos(best, new IntPtr(-2), 0, 0, 0, 0, 0x0013);
        return true;
    }
}
"@

if (-not [EntpWindowActivator]::Show($ProcessId)) {
    throw "No top-level window was found for process $ProcessId."
}
