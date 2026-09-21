<#
Creates the Pdf Rename shortcuts (desktop and Start Menu).
Called by pdf_renamer_launcher.bat, which supplies the folder and the
pythonw.exe path. Not meant to be run on its own.

The shortcut starts the app directly through pythonw, so no console window
appears. Its icon is read from Pdf Rename.exe rather than app_icon.ico:
Windows caches icons by file path, and the exe is the file that changes when
the icon changes, so the cache never shows a stale picture.
#>

param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [Parameter(Mandatory = $true)][string]$PythonW
)

$ErrorActionPreference = "Stop"

$dir    = (Resolve-Path $AppDir).Path
$script = Join-Path $dir "pdf_renamer_app.py"
$exe    = Join-Path $dir "Pdf Rename.exe"
$icon   = Join-Path $dir "app_icon.ico"

if (-not (Test-Path $script)) {
    Write-Host "Could not find pdf_renamer_app.py next to the launcher." -ForegroundColor Red
    exit 1
}

function New-AppShortcut([string]$LinkPath) {
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($LinkPath)
    $sc.TargetPath       = $PythonW
    $sc.Arguments        = '"' + $script + '"'
    $sc.WorkingDirectory = $dir
    $sc.WindowStyle      = 1
    $sc.Description      = "Rename academic PDFs to YYYY_Title using the publisher record"
    if (Test-Path $exe)       { $sc.IconLocation = "$exe,0" }
    elseif (Test-Path $icon)  { $sc.IconLocation = "$icon,0" }
    $sc.Save()
}

# GetFolderPath resolves a OneDrive redirected Desktop correctly.
$desktop  = [Environment]::GetFolderPath("Desktop")
$deskLink = Join-Path $desktop "Pdf Rename.lnk"
New-AppShortcut $deskLink
Write-Host "Desktop shortcut:    $deskLink" -ForegroundColor Green

# Start Menu entry so it also appears when you search Windows.
$programs = [Environment]::GetFolderPath("Programs")
if (Test-Path $programs) {
    $menuLink = Join-Path $programs "Pdf Rename.lnk"
    New-AppShortcut $menuLink
    Write-Host "Start Menu shortcut: $menuLink" -ForegroundColor Green
}

exit 0
