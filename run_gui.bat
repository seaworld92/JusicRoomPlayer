@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 提示：本程序现在可直接【双击 jusic_gui.py】运行（会自动用 pythonw 无窗口启动），
rem 此 bat 仅作为“带控制台输出”的可选启动方式。

where mpv >nul 2>nul
if errorlevel 1 if not exist "C:\Program Files\MPV Player\mpv.exe" (
    echo [提示] 未找到 mpv，正在尝试安装...
    winget install -e --id shinchiro.mpv --accept-source-agreements --accept-package-agreements --silent
)

python jusic_gui.py --console %*
endlocal
