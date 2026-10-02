# MEMORY（长期）

## 项目
- 路径 `d:\BaiduSyncdisk\编程\本地音乐播放器`；「一起听歌吧」Jusic 房间的**低内存** Python 播放器（工作区名「本地音乐播放器」）。播放 https://happy.alang.run/modern-ui/（后端 https://tx.alang.run/api，源自 JumpAlang/Jusic-Serve-Houses），支持房间列表与切换。
- **许可证 GPL-3.0**（2026-09-03 用户确认）：LICENSE + THIRD_PARTY_NOTICES；源码头 `SPDX-License-Identifier: GPL-3.0-only` + `Copyright (C) 2026 The JusicRoomPlayer Authors`。上游 Jusic-Serve-Houses 亦为 GPL-3.0（README 曾误标 MIT，已修正）；mpv=LGPL2.1+/ISC，websockets=BSD-3，ttkbootstrap=MIT。
- 交流语言：简体中文。平台现状：**仅 Windows 完整可用**。

## 架构与产物
- `jusic_core.py` 共享核心：RoomClient（后台 asyncio 线程 + `listener(event,data)` 回调；**`_amain` 必须设 `self._loop = get_running_loop()`**，否则线程安全请求被吞）、MpvEngine、REST/WSS 协议与帧解析。
- 三个前端：`jusic_room_player.py`（CLI）、`jusic_gui.py`（ttk GUI）、`jusic_gui_bootstrap.py`（ttkbootstrap 多主题版，`class BootstrapGui(JusicGui)` 只覆写 UI 层，业务逻辑单一来源）。两个 `.pyw` 均为**薄启动器**（只 `from xxx import main`），避免副本漂移。GUI 线程桥 = queue + `root.after(_poll)`。
- 支撑模块：`jusic_tray.py`（Win32 托盘，纯 ctypes；非 Windows 下 `available()=False` → 退化为普通最小化）、`jusic_qr.py`（纯 Python 二维码，零依赖）、`tools/mem_bench.py`（Windows 内存基准，唯一入库测试工具）。
- 功能：房间列表/搜索/切换、密码房、音量即时生效、歌词 LRC 高亮、切歌投票、点歌（5 音源）、点赞、下载（音频 + .lrc）、房间分享（链接/二维码/小程序码）、聊天、托盘。
- 打包（2026-10-02 起默认双前端）：`build_exe.bat`（单文件 exe）/ `build_exe_dir.bat`（onedir + ZIP），版本取自 `VERSION`；**默认同时打经典 `jusic_gui.py` 与主题 `jusic_gui_bootstrap.py`**，开关 `-n` 跳依赖 / `-k` 保留缓存 / `-d` 深度清缓存 / `-c` 只经典 / `-t` 只主题 / `-a` 两个 / `-h` 帮助。产物：`JusicRoomPlayer <ver>.exe`、`JusicRoomPlayerTheme <ver>.exe`、`JusicRoomPlayerPortable_<ver>.zip`、`JusicRoomPlayerThemePortable_<ver>.zip`。约定 `--distpath dist --workpath build --specpath build`，打包后清 `build\` 与 `__pycache__`，不传 `--clean` 以复用分析缓存；**`--exclude-module PIL` 只能给经典版**（ttkbootstrap 连带依赖 Pillow，主题版排除 PIL 会运行时崩）；`make_zip.py` 可传第一个参数=文件夹名（默认经典名，兼容旧调用）。两个 bat 用 **CRLF 行尾**（LF + `chcp 65001` 曾出现间歇性 `cannot find the batch label`）。`publish_release.py` 发布 Release 到 GitHub/Gitee（纯 urllib，`GH_TOKEN`/`GITEE_TOKEN`，幂等复用同名附件，`--dry-run` 免凭证），`artifacts()` 现已列出**全部 4 个产物**（经典/主题 × 单文件/便携，缺任一个即报错退出）。`.gitignore` 排除 `build/ dist/ *.spec`，但 **`.codebuddy/memory/` 有意跟踪**。
- 文档：README.md（中文，含内存基准章节与三前端对比表）+ `README_EN.md`（英文，供 GitHub/Gitee 发布用）。

## 关键协议事实
- 房间列表 `POST /api/house/search`（头 AccessToken，匿名可用）。实时 `WSS /api/server/000/<随机>/websocket?houseId&housePwd&connectType=enter`，纯监听收 MUSIC(含可直接播放 url)/PICK/ONLINE/CHAT/NOTICE/公告；**不要发非 sockjs 帧**（会被 1007 关闭），无需 STOMP。帧格式 `a["TYPE\nheaders\n\n{json}"]`。
- 点歌：`SEND /music/search {name,source,pageIndex,pageSize,sendTime}` → `SEARCH` 帧（`data.data` 数组、`data.totalSize` 总数）；`SEND /music/pick {name,id,source,quality}`，quality=320k|flac → NOTICE「点歌成功」+ 新 PICK 队列。搜索结果字段：**无 `source`**（用当前音源回填），`fl`/`st` 在 `privilege` 子对象（fl==0 或 st<0 视为不可用），`album` 是**对象**（取 `.name`），有 `duration`(ms)/`picture_url`。
- 点赞：`SEND /music/good/<歌曲id>`，body `{}`。服务端按「点歌归属表」匹配，**只认自己本会话点的歌**（他人/换会话 → NOTICE「点歌列表未发现此歌」）；点赞数不下发。`GOODMODEL` 帧 = 房间「点赞排序」开关，`ROOM_STATE` 含 `goodModel`。GUI 只保留队列点赞（收到失败提示自动撤回 👍，靠 `_last_like`/`_rollback_last_like`）。
- 删除自己点的歌：`SEND /music/delete {id: <歌名>}`（**传歌名有效**，数字 id 无效）→ NOTICE「删除成功」；他人/跨会话静默。`/music/clear`、`/music/top {id}` 属房管权限。
- 官网分享链接：`https://happy.alang.run/modern-ui?houseId=<id>&housePwd=<pwd>`；小程序码 `POST /api/house/getMiniCode {"id":roomId}` → base64 JPEG。

## 环境约定与踩坑（Windows 本机）
- TLS：目标服务器拒部分 TLS1.3 → 固定 TLS1.2；`proxy=None` 绕开系统代理 127.0.0.1:10808。
- **websockets 版本坑**：本机实装 13.1，而代码原写死 15.x 的 `additional_headers`/`proxy=None` → 被透传给 `loop.create_connection` 报 TypeError，WSS 全挂。已在 `jusic_core.ws_connect_extras()` 能力探测（14+ 用 `additional_headers`，13.x 用 `user_agent_header`，`proxy=None` 仅有该参数时才传）；requirements 为 `websockets>=13.1,<16`。**改连接参数务必保持探测式写法。**
- **ttkbootstrap 2.2.3 API**：`ttb.Style()` 一创建即绑定根窗口，之后 `ttb.Window()` 报 "single application root window" → 启动前校验主题名只能用数据模块 `themes.builtin.CURATED_THEMES`（15 风格 `.name`）+ `themes.legacy.STANDARD_THEMES`。`Style.theme` 返回 Theme 对象（名字用 `.theme.name`），明暗用 `style.theme_mode`；`theme_use()` 重绘整棵控件树（`_theme_walk`），但**普通 tk 控件与写死颜色不在其列** → 用 `ttb.Text`、`root.option_add("*Background"/"*Foreground", …)`。深色适配：歌词/日志 tag 颜色需自行重设；次要文字走 `_muted_widgets`；父类对话框硬编码浅色由 `_retint_dialog` + `_FG_MAP` 映射，**语义色名须记进 `_tint_keys`**（否则二次切换认不出来）。
- 音量即时生效：每首 mpv 加 `--input-ipc-server=`（Win 命名管道，其它平台 tempdir 下 .sock），`set_volume()` 只改值 + 唤醒常驻线程 `_pump_loop` 异步下发；`_ipc_push` **一次一连接**（同句柄并发读写会永久阻塞）。实测 ~0.02s 生效。
- mpv 0.41.0 位于 `C:\Program Files\MPV Player\mpv.exe`（winget `shinchiro.mpv`）；搜索顺序 `--mpv` → `JUSIC_MPV` → PATH → 常见路径。
- 内存（2026-10-02 工作集）：CLI ≈ 37 + 53 = **90 MB**；`jusic_gui.py` ≈ 66 + 57 = **123 MB**；主题版 ≈ 76 + 57 = **134 MB**（差 ~10 MB 全来自 ttkbootstrap：`import tkinter` 21 MB → `+ttkbootstrap` 34 MB（连带 Pillow）→ `ttb.Window` 52 MB；python 空进程基线 18 MB）。
- tkinter 陷阱：`ttk.Entry(textvariable=局部变量)` 变量会被 GC → 持引用或直接 insert 后设为 readonly。
- `ttk.Panedwindow` 陷阱：窗口未映射时（`winfo_width()==1`）设 `sashpos` 会把首窗格压成 0 宽 → 等 `<Map>`/`<Configure>` 且 `winfo_ismapped()` 后只设一次。
- `ttk.Treeview` 选中行配色：无颜色选项，需派生样式 + `style.configure(selectbackground/selectforeground)` **并且** `style.map(background/foreground=[("selected",…)])`，两者都设才在各主题稳定；`tkinter.ttk.Style(root)` 没有 `.colors`，取主题色要用 `ttkbootstrap.Style` 实例。
- 验证套路：参考库 `pip install --target %TEMP%\<dir>` 做逐位对比，用后即删；图片结果用在线回读或 PIL ImageGrab 截图确认。工作区是百度网盘同步盘，工具可见性偶有不稳（必要时用 python 直读）；PowerShell 传中文路径不可靠 → 用 ASCII 临时目录 + python runner。
