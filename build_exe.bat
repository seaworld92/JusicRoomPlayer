@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ============================================================
echo  Build JusicRoomPlayer  (single-file exe, versioned)
echo ============================================================

rem ---- read version from VERSION file ----
set "VER="
if exist "%~dp0VERSION" for /f "usebackq delims=" %%v in ("%~dp0VERSION") do set "VER=%%v"
if "%VER%"=="" set "VER=0.0.0"
echo Version: %VER%

echo [1/4] Install / upgrade PyInstaller ...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err

echo [2/4] Generate version resource ...
python make_version_file.py
if errorlevel 1 goto :err

echo [3/4] Make sure mpv.exe exists ...
if not exist "C:\Program Files\MPV Player\mpv.exe" (
    echo      mpv not found, installing via winget ...
    winget install -e --id shinchiro.mpv --accept-source-agreements --accept-package-agreements --silent
)
if not exist "C:\Program Files\MPV Player\mpv.exe" (
    echo [ERROR] mpv.exe still missing. Install it first:  winget install shinchiro.mpv
    goto :err
)

echo [4/4] Building single-file EXE (bundles mpv.exe, takes a few minutes) ...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "JusicRoomPlayer %VER%" ^
  --version-file "build\version_info.txt" ^
  --add-data "C:\Program Files\MPV Player\mpv.exe;_engine\mpv" ^
  --add-data "%~dp0VERSION;." ^
  jusic_gui.py
if errorlevel 1 goto :err

copy /Y "%~dp0LICENSE" "dist\" >nul 2>&1
copy /Y "%~dp0THIRD_PARTY_NOTICES" "dist\THIRD_PARTY_NOTICES.txt" >nul 2>&1

echo.
echo Done:  dist\JusicRoomPlayer %VER%.exe
echo A portable single-file app with mpv embedded. Share it with Windows users.
goto :eof

:err
echo.
echo Build FAILED. See messages above.
endlocal
