@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ============================================================
echo  Build JusicRoomPlayerPortable  (onedir -^> auto ZIP, versioned)
echo ============================================================

rem ---- read version from VERSION file ----
set "VER="
if exist "%~dp0VERSION" for /f "usebackq delims=" %%v in ("%~dp0VERSION") do set "VER=%%v"
if "%VER%"=="" set "VER=0.0.0"
echo Version: %VER%

set "OUTDIR=dist\JusicRoomPlayerPortable_%VER%"
set "ZIPFILE=dist\JusicRoomPlayerPortable_%VER%.zip"

echo [1/5] Install / upgrade PyInstaller ...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err

echo [2/5] Generate version resource ...
python make_version_file.py
if errorlevel 1 goto :err

echo [3/5] Make sure mpv.exe exists ...
if not exist "C:\Program Files\MPV Player\mpv.exe" (
    echo      mpv not found, installing via winget ...
    winget install -e --id shinchiro.mpv --accept-source-agreements --accept-package-agreements --silent
)
if not exist "C:\Program Files\MPV Player\mpv.exe" (
    echo [ERROR] mpv.exe still missing. Install it first:  winget install shinchiro.mpv
    goto :err
)

echo [4/5] Building onedir package (no extraction on launch) ...
if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
if exist "%ZIPFILE%" del /q "%ZIPFILE%"
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name "JusicRoomPlayerPortable_%VER%" ^
  --version-file "build\version_info.txt" ^
  --add-data "C:\Program Files\MPV Player\mpv.exe;_engine\mpv" ^
  --add-data "%~dp0VERSION;." ^
  jusic_gui.py
if errorlevel 1 goto :err

copy /Y "%~dp0LICENSE" "%OUTDIR%\" >nul 2>&1
copy /Y "%~dp0THIRD_PARTY_NOTICES" "%OUTDIR%\THIRD_PARTY_NOTICES.txt" >nul 2>&1

echo [5/5] Creating ZIP package ...
python make_zip.py
if errorlevel 1 goto :zipfail

rem keep only the ZIP as deliverable, remove the intermediate folder
rmdir /s /q "%OUTDIR%"

echo.
echo Done:  %ZIPFILE%
echo A versioned portable ZIP with mpv embedded. Share it with Windows users.
goto :eof

:zipfail
echo.
echo ZIP creation FAILED. Kept the folder instead:  %OUTDIR%
goto :eof

:err
echo.
echo Build FAILED. See messages above.
endlocal
