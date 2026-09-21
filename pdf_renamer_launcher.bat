@echo off
setlocal EnableDelayedExpansion
title Pdf Rename
cd /d "%~dp0"

rem  Everything the person does not need to see is hidden, so the folder shows
rem  the exe, the README and the two Python files, like an installed app.
rem  Explorer > View > Show > Hidden items reveals them. Skipped inside a git
rem  clone, where a developer needs all of it visible.
if not exist "%~dp0.git" (
    attrib +h "%~dp0pdf_renamer_launcher.bat" "%~dp0make_shortcut.ps1" "%~dp0requirements.txt" "%~dp0app_icon.ico" >nul 2>&1
    attrib +h "%~dp0CITATION.cff" "%~dp0.gitattributes" "%~dp0.gitignore" >nul 2>&1
    for %%d in (docs launcher tests) do if exist "%~dp0%%d" attrib +h "%~dp0%%d" >nul 2>&1
)

rem =====================================================================
rem  Pdf Rename launcher. Started by Pdf Rename.exe, which only exists to
rem  carry the icon; double clicking this file directly works the same way.
rem  First run on a computer: finds or installs Python (per user, no admin
rem  needed), installs the two libraries, makes a desktop icon, opens the app.
rem  Every run after that: opens the app straight away.
rem =====================================================================

set "PYEXE="
set "PYVER_WANTED=3.13.15"
set "ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=arm64"

call :FINDPY
if defined PYEXE (
    "!PYEXE!" -c "import tkinter, pypdf, requests, renamer_core, pdf_renamer_app" >nul 2>&1
    if not errorlevel 1 goto LAUNCH
)

echo.
echo  ===========================================
echo    Pdf Rename         first time setup
echo  ===========================================
echo.
echo  This runs once. It needs an internet connection.
echo.

rem ---- Python without its window toolkit is not usable: get a fresh one --
if defined PYEXE (
    "!PYEXE!" -c "import tkinter" >nul 2>&1
    if errorlevel 1 (
        echo  Found Python at !PYEXE! but it has no window toolkit.
        echo  Installing a complete copy alongside it.
        set "PYEXE="
    )
)

if not defined PYEXE call :INSTALLPY
if not defined PYEXE goto NOPYTHON

set "PYVER="
"!PYEXE!" -c "import sys;print(sys.version.split()[0])" > "%TEMP%\pdfrenamer_pyver.txt" 2>nul
set /p PYVER=<"%TEMP%\pdfrenamer_pyver.txt"
del "%TEMP%\pdfrenamer_pyver.txt" >nul 2>&1
echo  Using Python !PYVER!
echo      !PYEXE!
echo.

rem ---- the two libraries -------------------------------------------------
echo  Installing pypdf and requests...
"!PYEXE!" -m pip --version >nul 2>&1
if errorlevel 1 "!PYEXE!" -m ensurepip --upgrade >nul 2>&1
"!PYEXE!" -m pip install -r requirements.txt --disable-pip-version-check --quiet
if errorlevel 1 (
    echo  Retrying as a per user install...
    "!PYEXE!" -m pip install --user -r requirements.txt --disable-pip-version-check --quiet
    if errorlevel 1 goto PIPFAIL
)

"!PYEXE!" -c "import tkinter, pypdf, requests, renamer_core, pdf_renamer_app" >nul 2>&1
if errorlevel 1 goto IMPORTFAIL

rem ---- desktop icon --------------------------------------------------------
call :FINDPYW
echo  Creating the desktop icon...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_shortcut.ps1" -AppDir "%~dp0." -PythonW "!PYW!" >nul 2>&1
if errorlevel 1 (
    echo  The desktop icon could not be created. Keep using Pdf Rename.exe to start the app.
) else (
    echo  A Pdf Rename icon is now on your desktop.
)
echo.
echo  Setup finished. Opening the app.
timeout /t 2 >nul
goto LAUNCH


rem =====================================================================
:LAUNCH
call :FINDPYW
call :ENSURESHORTCUT
start "" "!PYW!" "%~dp0pdf_renamer_app.py" %*
exit /b 0


:ENSURESHORTCUT
rem  Shortcuts left over from the old name "PDF Renamer" point at the old
rem  folder and would open nothing. Remove them wherever the app put them.
for %%d in ("%USERPROFILE%\Desktop" "%USERPROFILE%\OneDrive\Desktop" "%OneDrive%\Desktop" "%APPDATA%\Microsoft\Windows\Start Menu\Programs") do (
    if exist "%%~d\PDF Renamer.lnk" del "%%~d\PDF Renamer.lnk" >nul 2>&1
)
rem  Recreate the desktop icon if it was deleted. The Desktop can live under
rem  OneDrive, so both usual places are checked before running PowerShell.
if exist "%USERPROFILE%\Desktop\Pdf Rename.lnk" exit /b 0
if exist "%USERPROFILE%\OneDrive\Desktop\Pdf Rename.lnk" exit /b 0
if exist "%OneDrive%\Desktop\Pdf Rename.lnk" exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_shortcut.ps1" -AppDir "%~dp0." -PythonW "!PYW!" >nul 2>&1
exit /b 0


rem =====================================================================
:FINDPY
rem  Sets PYEXE to a working python.exe, or leaves it empty.
rem  The "python" alias on a fresh Windows is a stub that opens the Store
rem  and fails, so every candidate is tested by actually running it.
set "PYEXE="
for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
if defined PYEXE if exist "!PYEXE!" exit /b 0
set "PYEXE="
for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
if defined PYEXE if exist "!PYEXE!" exit /b 0
set "PYEXE="
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%~d\python.exe" set "PYEXE=%%~d\python.exe"
if defined PYEXE exit /b 0
for /d %%d in ("%ProgramFiles%\Python3*") do if exist "%%~d\python.exe" set "PYEXE=%%~d\python.exe"
if defined PYEXE exit /b 0
for /d %%d in ("C:\Python3*") do if exist "%%~d\python.exe" set "PYEXE=%%~d\python.exe"
if defined PYEXE exit /b 0
for %%d in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3") do if exist "%%~d\python.exe" set "PYEXE=%%~d\python.exe"
exit /b 0


:FINDPYW
rem  pythonw.exe opens the app with no black console window behind it.
set "PYW=!PYEXE!"
for %%i in ("!PYEXE!") do if exist "%%~dpipythonw.exe" set "PYW=%%~dpipythonw.exe"
exit /b 0


:INSTALLPY
rem  Per user install: no administrator rights, no reboot.
echo  Python is not on this computer. Installing it now (a few minutes).
echo.

winget --version >nul 2>&1
if not errorlevel 1 (
    echo  Using the Windows package manager...
    winget install --id Python.Python.3.13 -e --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    call :FINDPY
    if defined PYEXE exit /b 0
    echo  That did not work. Trying a direct download.
    echo.
)

set "PYURL=https://www.python.org/ftp/python/%PYVER_WANTED%/python-%PYVER_WANTED%-%ARCH%.exe"
set "PYSETUP=%TEMP%\python-%PYVER_WANTED%-%ARCH%.exe"
echo  Downloading %PYURL%
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYSETUP%' -UseBasicParsing; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
    echo  Download failed. Check the internet connection.
    exit /b 0
)
echo  Installing...
start /wait "" "%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_launcher=1 Include_test=0 AssociateFiles=0 Shortcuts=0
del "%PYSETUP%" >nul 2>&1
call :FINDPY
exit /b 0


rem =====================================================================
:NOPYTHON
echo.
echo  Python could not be installed automatically.
echo.
echo  Install it by hand from  https://www.python.org/downloads/
echo  On the first screen of the installer tick "Add python.exe to PATH",
echo  then double click this file again.
echo.
pause
exit /b 1

:PIPFAIL
echo.
echo  The libraries did not install.
echo.
echo  Usual causes: no internet connection, or a proxy blocking pip.
echo  To see the full error, run this in a Command Prompt:
echo      "!PYEXE!" -m pip install pypdf requests
echo.
pause
exit /b 1

:IMPORTFAIL
echo.
echo  Everything installed but the app does not start.
echo  To see why, run this in a Command Prompt inside this folder:
echo      "!PYEXE!" -c "import pdf_renamer_app"
echo.
pause
exit /b 1
