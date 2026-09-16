@echo off
rem ===========================================================================
rem  build_exe_dir.bat  --  build JusicRoomPlayerPortable folder build + ZIP
rem ---------------------------------------------------------------------------
rem  Usage:  build_exe_dir.bat [options]
rem    -n, --no-deps      skip dependency install / upgrade step
rem    -k, --keep-cache   keep PyInstaller work dir and unpacked folder
rem    -d, --deep         additionally purge PyInstaller global cache + pip cache
rem    -h, --help         show this help
rem ---------------------------------------------------------------------------
rem  All PyInstaller scratch data (work dir + generated .spec) is written under
rem  .\build and removed again after the build, so nothing is left behind.
rem  Output: dist\JusicRoomPlayerPortable_<VERSION>.zip   (mpv embedded)
rem ===========================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "APPNAME=JusicRoomPlayerPortable"
set "ENTRY=%~dp0jusic_gui.py"
set "MPV=C:\Program Files\MPV Player\mpv.exe"
set "WORKDIR=%~dp0build"
set "DISTDIR=%~dp0dist"

rem ---- option defaults ----
set "SKIP_DEPS="
set "KEEP_CACHE="
set "DEEP="

rem ---- parse command line ----
:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="-h"           goto :usage
if /i "%~1"=="--help"       goto :usage
if /i "%~1"=="-n"           goto :opt_nodeps
if /i "%~1"=="--no-deps"    goto :opt_nodeps
if /i "%~1"=="-k"           goto :opt_keep
if /i "%~1"=="--keep-cache" goto :opt_keep
if /i "%~1"=="-d"           goto :opt_deep
if /i "%~1"=="--deep"       goto :opt_deep
echo [WARN] Unknown option ignored: %~1   -- see -h for help
shift
goto :parse

:opt_nodeps
set "SKIP_DEPS=1"
shift
goto :parse
:opt_keep
set "KEEP_CACHE=1"
shift
goto :parse
:opt_deep
set "DEEP=1"
shift
goto :parse
:parsed

echo ============================================================
echo  Build %APPNAME%  --  onedir, auto ZIP, versioned
echo ============================================================

rem ---- sanity checks ----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] "python" not found in PATH. Install Python 3.10+ first.
    goto :err
)
if not exist "%ENTRY%" (
    echo [ERROR] Entry script missing: "%ENTRY%"
    goto :err
)

rem ---- read version from VERSION file ----
set "VER="
if exist "%~dp0VERSION" for /f "usebackq delims=" %%v in ("%~dp0VERSION") do set "VER=%%v"
if "%VER%"=="" set "VER=0.0.0"
set "OUTDIR=%DISTDIR%\%APPNAME%_%VER%"
set "ZIPFILE=%DISTDIR%\%APPNAME%_%VER%.zip"
echo Version : %VER%
echo Target  : %ZIPFILE%

rem ---- start timer ----
set "T0=0"
for /f "delims=" %%t in ('python -c "import time;print(int(time.time()))" 2^>nul') do set "T0=%%t"

rem ---- [1/7] dependencies ----
if defined SKIP_DEPS goto :deps_skip
echo [1/7] Install / refresh dependencies ...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :err
goto :deps_done
:deps_skip
echo [1/7] Dependencies: skipped  [flag -n]
:deps_done

rem ---- [2/7] version resource ----
echo [2/7] Generate version resource ...
python make_version_file.py
if errorlevel 1 goto :err

rem ---- [3/7] mpv ----
echo [3/7] Make sure mpv.exe exists ...
if exist "%MPV%" goto :mpv_ok
echo        mpv not found, installing via winget ...
winget install -e --id shinchiro.mpv --accept-source-agreements --accept-package-agreements --silent
if exist "%MPV%" goto :mpv_ok
echo [ERROR] mpv.exe still missing. Install it first:  winget install shinchiro.mpv
goto :err
:mpv_ok

rem ---- [4/7] build ----
echo [4/7] Building onedir package ... no extraction on launch
if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
if exist "%ZIPFILE%" del /q "%ZIPFILE%"
if not exist "%WORKDIR%" mkdir "%WORKDIR%"
if not exist "%DISTDIR%" mkdir "%DISTDIR%"
python -m PyInstaller --noconfirm --onedir --windowed ^
  --name "%APPNAME%_%VER%" ^
  --distpath "%DISTDIR%" ^
  --workpath "%WORKDIR%" ^
  --specpath "%WORKDIR%" ^
  --version-file "%WORKDIR%\version_info.txt" ^
  --exclude-module numpy --exclude-module PIL --exclude-module matplotlib ^
  --exclude-module pandas --exclude-module scipy --exclude-module pytest ^
  --exclude-module setuptools --exclude-module pip --exclude-module IPython ^
  --add-data "%MPV%;_engine\mpv" ^
  --add-data "%~dp0VERSION;." ^
  "%ENTRY%"
if errorlevel 1 goto :err

rem ---- [5/7] license / notices ----
echo [5/7] Copy LICENSE and THIRD_PARTY_NOTICES ...
copy /Y "%~dp0LICENSE" "%OUTDIR%\" >nul 2>&1
copy /Y "%~dp0THIRD_PARTY_NOTICES" "%OUTDIR%\THIRD_PARTY_NOTICES.txt" >nul 2>&1

rem ---- [6/7] zip ----
echo [6/7] Creating ZIP package ...
python make_zip.py
if errorlevel 1 goto :zipfail
if not defined KEEP_CACHE rmdir /s /q "%OUTDIR%"

rem ---- [7/7] cleanup ----
echo [7/7] Cleanup
call :clean_caches

rem ---- report ----
set "T1=%T0%"
for /f "delims=" %%t in ('python -c "import time;print(int(time.time()))" 2^>nul') do set "T1=%%t"
set /a "ELAPSED=%T1% - %T0%" >nul 2>&1
if not defined ELAPSED set "ELAPSED=0"
set /a "EMIN=%ELAPSED% / 60" >nul 2>&1
set /a "ESEC=%ELAPSED% %% 60" >nul 2>&1
set "SIZE=?"
for %%F in ("%ZIPFILE%") do set /a "SIZE=%%~zF / 1048576"
echo.
echo Done in %EMIN%m %ESEC%s :  %ZIPFILE%  [%SIZE% MB]
echo A versioned portable ZIP with mpv embedded. Share it with Windows users.
endlocal
exit /b 0

:zipfail
echo.
echo ZIP creation FAILED. Kept the folder instead:  %OUTDIR%
call :clean_caches
endlocal
exit /b 1

:err
echo.
echo Build FAILED. See messages above.
call :clean_caches
endlocal
exit /b 1

rem ---------------------------------------------------------------------------
rem  clean_caches -- drop PyInstaller scratch data and python bytecode caches
rem ---------------------------------------------------------------------------
:clean_caches
if defined KEEP_CACHE (
    echo        keep-cache flag given - nothing removed
    goto :clean_deep
)
echo        removing PyInstaller work dir / spec files under .\build ...
if exist "%WORKDIR%" (
    for /d %%d in ("%WORKDIR%\*") do rd /s /q "%%~fd" >nul 2>&1
    del /q "%WORKDIR%\*.spec" >nul 2>&1
    del /q "%WORKDIR%\*.toc" >nul 2>&1
    del /q "%WORKDIR%\xref-*.html" >nul 2>&1
)
echo        removing python bytecode caches ...
if exist "%~dp0__pycache__" rd /s /q "%~dp0__pycache__" >nul 2>&1
del /q "%~dp0*.pyc" >nul 2>&1
:clean_deep
if not defined DEEP goto :clean_done
echo        deep clean: purging PyInstaller global cache and pip download cache ...
if exist "%LOCALAPPDATA%\pyinstaller" rd /s /q "%LOCALAPPDATA%\pyinstaller" >nul 2>&1
python -m pip cache purge >nul 2>&1
:clean_done
exit /b 0

:usage
echo Usage: %~nx0 [options]
echo   -n, --no-deps      skip pip install / upgrade step  -- faster rebuilds
echo   -k, --keep-cache   keep PyInstaller work dir and unpacked folder
echo   -d, --deep         also purge PyInstaller global cache and pip download cache
echo   -h, --help         show this help
echo.
echo Output: dist\%APPNAME%_^<VERSION^>.zip
endlocal
exit /b 0
