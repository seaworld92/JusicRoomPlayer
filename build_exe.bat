@echo off
rem ===========================================================================
rem  build_exe.bat  --  build JusicRoomPlayer single-file Windows EXEs
rem ---------------------------------------------------------------------------
rem  Usage:  build_exe.bat [options]
rem    -n, --no-deps      skip dependency install / upgrade step
rem    -k, --keep-cache   keep PyInstaller work dir  [default: cleaned up]
rem    -d, --deep         additionally purge PyInstaller global cache + pip cache
rem    -c, --classic      build only the classic ttk UI     [jusic_gui.py]
rem    -t, --theme        build only the ttkbootstrap UI    [jusic_gui_bootstrap.py]
rem    -a, --all          build both  [default]
rem    -h, --help         show this help
rem ---------------------------------------------------------------------------
rem  Both front-ends are packaged by default:
rem    dist\JusicRoomPlayer <VERSION>.exe         classic ttk UI
rem    dist\JusicRoomPlayerTheme <VERSION>.exe    ttkbootstrap theme UI
rem  Every PyInstaller scratch file (work dir + generated .spec) is written under
rem  .\build and removed again after the build, so nothing is left behind.
rem ===========================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "APPNAME=JusicRoomPlayer"
set "APPNAME_THEME=JusicRoomPlayerTheme"
set "ENTRY_CLASSIC=%~dp0jusic_gui.py"
set "ENTRY_THEME=%~dp0jusic_gui_bootstrap.py"
set "MPV=C:\Program Files\MPV Player\mpv.exe"
set "WORKDIR=%~dp0build"
set "DISTDIR=%~dp0dist"

rem ---- option defaults ----
set "SKIP_DEPS="
set "KEEP_CACHE="
set "DEEP="
set "DO_CLASSIC=1"
set "DO_THEME=1"

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
if /i "%~1"=="-c"           goto :opt_classic
if /i "%~1"=="--classic"    goto :opt_classic
if /i "%~1"=="-t"           goto :opt_theme
if /i "%~1"=="--theme"      goto :opt_theme
if /i "%~1"=="-a"           goto :opt_all
if /i "%~1"=="--all"        goto :opt_all
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
:opt_classic
set "DO_THEME="
shift
goto :parse
:opt_theme
set "DO_CLASSIC="
shift
goto :parse
:opt_all
set "DO_CLASSIC=1"
set "DO_THEME=1"
shift
goto :parse
:parsed

rem ---- -c together with -t means "both" ----
if defined DO_CLASSIC goto :sel_ok
if defined DO_THEME goto :sel_ok
set "DO_CLASSIC=1"
set "DO_THEME=1"
:sel_ok

echo ============================================================
echo  Build %APPNAME%  --  single-file EXE, versioned
echo ============================================================

rem ---- sanity checks ----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] "python" not found in PATH. Install Python 3.10+ first.
    goto :err
)
if not defined DO_CLASSIC goto :ck_theme
if exist "%ENTRY_CLASSIC%" goto :ck_theme
echo [ERROR] Entry script missing: "%ENTRY_CLASSIC%"
goto :err
:ck_theme
if not defined DO_THEME goto :ck_done
if exist "%ENTRY_THEME%" goto :ck_done
echo [ERROR] Entry script missing: "%ENTRY_THEME%"
goto :err
:ck_done

rem ---- read version from VERSION file ----
set "VER="
if exist "%~dp0VERSION" for /f "usebackq delims=" %%v in ("%~dp0VERSION") do set "VER=%%v"
if "%VER%"=="" set "VER=0.0.0"
set "EXE_CLASSIC=%DISTDIR%\%APPNAME% %VER%.exe"
set "EXE_THEME=%DISTDIR%\%APPNAME_THEME% %VER%.exe"
echo Version : %VER%
if defined DO_CLASSIC echo Target  : %EXE_CLASSIC%
if defined DO_THEME   echo Target  : %EXE_THEME%

rem ---- start timer ----
set "T0=0"
for /f "delims=" %%t in ('python -c "import time;print(int(time.time()))" 2^>nul') do set "T0=%%t"

rem ---- [1/6] dependencies ----
if defined SKIP_DEPS goto :deps_skip
echo [1/6] Install / refresh dependencies ...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :err
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :err
goto :deps_done
:deps_skip
echo [1/6] Dependencies: skipped  [flag -n]
:deps_done

rem ---- [2/6] version resource ----
echo [2/6] Generate version resource ...
python make_version_file.py
if errorlevel 1 goto :err

rem ---- [3/6] mpv ----
echo [3/6] Make sure mpv.exe exists ...
if exist "%MPV%" goto :mpv_ok
echo        mpv not found, installing via winget ...
winget install -e --id shinchiro.mpv --accept-source-agreements --accept-package-agreements --silent
if exist "%MPV%" goto :mpv_ok
echo [ERROR] mpv.exe still missing. Install it first:  winget install shinchiro.mpv
goto :err
:mpv_ok

if not exist "%WORKDIR%" mkdir "%WORKDIR%"
if not exist "%DISTDIR%" mkdir "%DISTDIR%"

rem ---- [4/6] classic UI exe ----
if not defined DO_CLASSIC goto :skip_classic
echo [4/6] Building classic ttk UI exe ... takes a few minutes
set "BUILD_KIND=classic ttk UI"
set "BUILD_NAME=%APPNAME% %VER%"
set "BUILD_ENTRY=%ENTRY_CLASSIC%"
set "BUILD_OUT=%EXE_CLASSIC%"
set "BUILD_EXCLUDE_PIL=1"
call :build_one
if errorlevel 1 goto :err
goto :skip_classic_done
:skip_classic
echo [4/6] Classic ttk UI: skipped
:skip_classic_done

rem ---- [5/6] theme UI exe ----
if not defined DO_THEME goto :skip_theme
echo [5/6] Building ttkbootstrap theme UI exe ... takes a few minutes
set "BUILD_KIND=ttkbootstrap theme UI"
set "BUILD_NAME=%APPNAME_THEME% %VER%"
set "BUILD_ENTRY=%ENTRY_THEME%"
set "BUILD_OUT=%EXE_THEME%"
set "BUILD_EXCLUDE_PIL="
call :build_one
if errorlevel 1 goto :err
goto :skip_theme_done
:skip_theme
echo [5/6] ttkbootstrap theme UI: skipped
:skip_theme_done

rem ---- [6/6] licenses + cleanup ----
echo [6/6] Copy LICENSE / THIRD_PARTY_NOTICES and clean caches
copy /Y "%~dp0LICENSE" "%DISTDIR%\" >nul 2>&1
copy /Y "%~dp0THIRD_PARTY_NOTICES" "%DISTDIR%\THIRD_PARTY_NOTICES.txt" >nul 2>&1
call :clean_caches

rem ---- report ----
set "T1=%T0%"
for /f "delims=" %%t in ('python -c "import time;print(int(time.time()))" 2^>nul') do set "T1=%%t"
set /a "ELAPSED=%T1% - %T0%" >nul 2>&1
if not defined ELAPSED set "ELAPSED=0"
set /a "EMIN=%ELAPSED% / 60" >nul 2>&1
set /a "ESEC=%ELAPSED% %% 60" >nul 2>&1
echo.
echo Done in %EMIN%m %ESEC%s
if not defined DO_CLASSIC goto :rp_theme
if not exist "%EXE_CLASSIC%" goto :rp_theme
set "SZ=?"
for %%F in ("%EXE_CLASSIC%") do set /a "SZ=%%~zF / 1048576"
echo   %APPNAME% %VER%.exe  [%SZ% MB]
:rp_theme
if not defined DO_THEME goto :rp_done
if not exist "%EXE_THEME%" goto :rp_done
set "SZ=?"
for %%F in ("%EXE_THEME%") do set /a "SZ=%%~zF / 1048576"
echo   %APPNAME_THEME% %VER%.exe  [%SZ% MB]
:rp_done
echo Portable single-file apps with mpv embedded. Share them with Windows users.
endlocal
exit /b 0

:err
echo.
echo Build FAILED. See messages above.
call :clean_caches
endlocal
exit /b 1

rem ---------------------------------------------------------------------------
rem  build_one -- package one front-end into a single-file exe
rem  in : BUILD_NAME, BUILD_ENTRY, BUILD_OUT, BUILD_KIND, BUILD_EXCLUDE_PIL
rem ---------------------------------------------------------------------------
:build_one
set "PIL_OPT="
if defined BUILD_EXCLUDE_PIL set "PIL_OPT=--exclude-module PIL"
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name "%BUILD_NAME%" ^
  --distpath "%DISTDIR%" ^
  --workpath "%WORKDIR%" ^
  --specpath "%WORKDIR%" ^
  --version-file "%WORKDIR%\version_info.txt" ^
  --exclude-module numpy --exclude-module matplotlib %PIL_OPT% ^
  --exclude-module pandas --exclude-module scipy --exclude-module pytest ^
  --exclude-module setuptools --exclude-module pip --exclude-module IPython ^
  --add-data "%MPV%;_engine\mpv" ^
  --add-data "%~dp0VERSION;." ^
  "%BUILD_ENTRY%"
if errorlevel 1 exit /b 1
if not exist "%BUILD_OUT%" (
    echo [ERROR] Build reported success but the EXE is missing: "%BUILD_OUT%"
    exit /b 1
)
echo        ok: %BUILD_KIND% -^> "%BUILD_OUT%"
exit /b 0

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
echo   -k, --keep-cache   keep PyInstaller work dir       -- debug failed builds
echo   -d, --deep         also purge PyInstaller global cache and pip download cache
echo   -c, --classic      build only dist\%APPNAME% ^<VERSION^>.exe
echo   -t, --theme        build only dist\%APPNAME_THEME% ^<VERSION^>.exe
echo   -a, --all          build both  [default]
echo   -h, --help         show this help
echo.
echo Note: the theme UI needs ttkbootstrap (and its PIL dependency), so PIL is
echo       bundled for it and excluded only from the classic exe.
echo       Example: build_exe.bat -n -t
endlocal
exit /b 0
