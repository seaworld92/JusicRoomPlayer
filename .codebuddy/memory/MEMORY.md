# MEMORY（长期）

## 项目
`d:\BaiduSyncdisk\编程\本地音乐播放器` —— 「一起听歌吧」Jusic 房间的低内存音乐播放器（工作区名"本地音乐播放器"）。
- 目标：内存尽量小，播放 https://happy.alang.run/modern-ui/（后端 https://tx.alang.run/api，源自 GitHub JumpAlang/Jusic-Serve-Houses）的歌曲，支持房间列表与切换。
- **许可证（2026-09-03 用户确认）：本项目采用 GPL-3.0**。根目录有 LICENSE（GPL-3.0 官方文本）、THIRD_PARTY_NOTICES；源码文件头 SPDX-License-Identifier: GPL-3.0-only + Copyright (C) 2026 The JusicRoomPlayer Authors。README 开源致谢中 Jusic-Serve-Houses 标 GPL-3.0（曾误标 MIT，已修正）。
- 上游 Jusic-Serve-Houses 真实许可证：GPL-3.0（经 GitHub API 确认）。mpv=LGPL2.1+/ISC，websockets=BSD-3。

## 架构与产物（2026-09-03 起）
- `jusic_core.py`：共享核心。含 RoomClient（后台 asyncio 线程 + listener(event,data) 回调）、MpvEngine、REST/WSS 协议、帧解析。**RoomClient._amain 必须设 self._loop = get_running_loop()**，否则线程安全请求被吞。
- `jusic_room_player.py`：命令行前端；`jusic_gui.py`：ttk GUI 前端（需在 main 中 root.after 调度 _poll，GUI 线程桥=queue+after）。
- GUI 功能：房间列表/搜索/切换、歌词 LRC 同步高亮、角落"关于·GPL-3.0"、**下载▾（保存当前歌曲音频 + .lrc 歌词，core.download_file 流式下载）**。
- `requirements.txt`（websockets==15.0.1）、`run.bat`、`run_gui.bat`、`README.md`。

## 关键协议事实（勿忘）
- 房间列表：POST /api/house/search，头 AccessToken: token，匿名可用。
- 实时：WSS /api/server/000/<随机>/websocket?houseId&housePwd&connectType=enter；纯监听收 MUSIC(含可直接播放 url)/PICK/ONLINE/CHAT/公告；不要发非 sockjs 帧(会被 1007 关闭)；无需 STOMP。
- 帧格式：a["TYPE\ncontent-type:application/json\ncontent-length:N\n\n{json}"]，解析取首行类型+末 json。

## 环境约定（Windows 本机，重要）
- 目标服务器拒部分 TLS1.3 握手 → Python 固定 TLS1.2；websockets.connect(proxy=None) 绕本机系统代理 127.0.0.1:10808。
- websockets 用 v15（additional_headers 参数；v17 有 bug）。
- 播放引擎 mpv 0.41.0 位于 `C:\Program Files\MPV Player\mpv.exe`（winget id shinchiro.mpv）。
- 实测内存：python≈37MB + mpv≈53MB。
- PowerShell 命令含中文路径参数编码不可靠 → 用 ASCII 临时目录（如 %LOCALAPPDATA% 下）写 python runner，脚本内用 unicode 路径读写/测试。
- 工作区是百度网盘同步盘：read_file 等工具对该盘某些文件可见性不稳；必要时用 python 直接读取确认。
- 用户交流语言：简体中文。
