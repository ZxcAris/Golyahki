param(
    [string]$ExecutablePath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\Golyahki\Golyahki.exe')
)

$ErrorActionPreference = 'Stop'
$applicationPath = (Resolve-Path -LiteralPath $ExecutablePath).Path
$desktopPath = [Environment]::GetFolderPath('DesktopDirectory')
if (-not $desktopPath) { throw 'Windows desktop folder is unavailable.' }
$shortcutPath = Join-Path $desktopPath 'Golyahki.lnk'
$shell = New-Object -ComObject WScript.Shell
try {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $applicationPath
    $shortcut.WorkingDirectory = Split-Path -Parent $applicationPath
    $shortcut.IconLocation = "$applicationPath,0"
    $shortcut.Description = 'Golyahki - words from your world. Capture: Alt+Q.'
    $shortcut.Save()
    $saved = $shell.CreateShortcut($shortcutPath)
    if ($saved.TargetPath -ne $applicationPath -or -not (Test-Path -LiteralPath $shortcutPath)) {
        throw 'Shortcut verification failed.'
    }
    if (-not ('GolyahkiShortcutShell' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class GolyahkiShortcutShell {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern void SHChangeNotify(uint eventId, uint flags, string item, IntPtr other);
}
'@
    }
    [GolyahkiShortcutShell]::SHChangeNotify(0x2000, 0x0005, $applicationPath, [IntPtr]::Zero)
    [GolyahkiShortcutShell]::SHChangeNotify(0x2000, 0x0005, $shortcutPath, [IntPtr]::Zero)
    Write-Output "Desktop shortcut: $shortcutPath"
    Write-Output "Application: $($saved.TargetPath)"
} finally {
    if ($saved) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($saved) }
    if ($shortcut) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) }
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
}
