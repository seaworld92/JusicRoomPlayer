@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 播放内核 mpv（轻量开源播放器）优先用 winget 官方包；也可用 --mpv 参数指定
where mpv >nul 2>nul
if errorlevel 1 if not exist "C:\Program Files\MPV Player\mpv.exe" (
    echo [提示] 未找到 mpv，正在尝试安装...
    winget install -e --id shinchiro.mpv --accept-source-agreements --accept-package-agreements --silent
)

python jusic_room_player.py %*
endlocal
