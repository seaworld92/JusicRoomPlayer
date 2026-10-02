# MEMORY（长期）

## 项目
`d:\BaiduSyncdisk\编程\本地音乐播放器` —— 「一起听歌吧」Jusic 房间的低内存音乐播放器（工作区名"本地音乐播放器"）。
- 目标：内存尽量小，播放 https://happy.alang.run/modern-ui/（后端 https://tx.alang.run/api，源自 GitHub JumpAlang/Jusic-Serve-Houses）的歌曲，支持房间列表与切换。
- **许可证（2026-09-03 用户确认）：本项目采用 GPL-3.0**。根目录有 LICENSE（GPL-3.0 官方文本）、THIRD_PARTY_NOTICES；源码文件头 SPDX-License-Identifier: GPL-3.0-only + Copyright (C) 2026 The JusicRoomPlayer Authors。README 开源致谢中 Jusic-Serve-Houses 标 GPL-3.0（曾误标 MIT，已修正）。
- 上游 Jusic-Serve-Houses 真实许可证：GPL-3.0（经 GitHub API 确认）。mpv=LGPL2.1+/ISC，websockets=BSD-3。

## 架构与产物（2026-09-03 起）
- `jusic_core.py`：共享核心。含 RoomClient（后台 asyncio 线程 + listener(event,data) 回调）、MpvEngine、REST/WSS 协议、帧解析。**RoomClient._amain 必须设 self._loop = get_running_loop()**，否则线程安全请求被吞。
- `jusic_room_player.py`：命令行前端；`jusic_gui.py`：ttk GUI 前端（需在 main 中 root.after 调度 _poll，GUI 线程桥=queue+after）。`jusic_gui.pyw` 自 2026-09-30 起是**薄启动器**（只 `from jusic_gui import main`），不再是全量副本——两份界面代码曾因副本漂移而缺功能。
- GUI 功能：房间列表/搜索/切换、歌词 LRC 同步高亮、角落"关于·GPL-3.0"、**下载▾（保存当前歌曲音频 + .lrc 歌词，core.download_file 流式下载）**。
- **主题界面版（2026-10-02 新增）**：`jusic_gui_bootstrap.py`（+ 薄启动器 `jusic_gui_bootstrap.pyw`）。用 **ttkbootstrap 2.2.3** 重做皮肤与布局：`class BootstrapGui(JusicGui)` **只覆写 `_build_ui/_sync_chat_text/_show_about/_on_close` 等 UI 层**，业务逻辑（房间/协议/点歌/点赞/歌词/下载/托盘）100% 继承 `jusic_gui.JusicGui`，因此不存在两份逻辑漂移。主题 = 15 风格 × 明/暗 = **30 种**（bootstrap/catppuccin/dracula/everforest/gruvbox/minty/nord/one/pulse/pydata/sandstone/solarized/tokyo-night/united/vapor）；右上角「风格下拉 + 深色开关 + 全部主题▾菜单（含明暗切换/随机主题）」，Ctrl+T / F2 一键明暗；主题与窗口尺寸存 `%APPDATA%\JusicRoomPlayer\ui.json`；新增播放进度条（复用 `_lyric_t0` 时钟）。README/THIRD_PARTY_NOTICES/requirements.txt 已同步（ttkbootstrap 为 MIT，只在主题界面版用到）。
  - 深色适配要点：歌词/日志文本用 `ttb.Text`（AutoStyleMixin，跟随主题自动换色，但 **tag 颜色要自己重设**）；"次要文字"用注册表 `_muted_widgets` + 明暗两色（#6c757d / #9aa0a5）手动刷；父类对话框里硬编码的浅色（#555/#0a6/#333…）由 `_retint_dialog` 按 `_FG_MAP` 映射成主题色，**必须把识别到的"语义色名"记在 `_tint_keys`**，否则第二次切换时已变成主题色的控件认不出来。
- **房间分享（2026-09-30）**：新增 `jusic_qr.py`（纯 Python 二维码：字节模式/等级 L-M-Q-H/自动版本 1-10/8 掩码按 ISO 4 规则择优/导出灰度 PNG，**零第三方依赖**）；`jusic_core` 增加 `SHARE_UI_URL`、`room_share_url()`、`get_mini_code()`；GUI「当前播放」面板加「分享房间…」→ 分享面板（复制链接/浏览器打开/保存二维码 PNG/微信小程序码/关闭），二维码用 tkinter Canvas 绘制（不依赖 Pillow）。
  - 官网分享链接格式：`https://happy.alang.run/modern-ui?houseId=<id>&housePwd=<pwd>`（前端仓库 JumpAlang/Jusic-ui 的 `roomShareUrl()`，密文一并带上；进房时读 location.search 自动入房）。官网二维码为 QrcodeVue size=210 level=H。
  - 小程序码接口：`POST /api/house/getMiniCode {"id":roomId}` → `data` 为 base64 JPEG。
- **点歌（2026-09-30）**：core 有 `SONG_SOURCE_CODES`(网易/QQ/酷我/酷狗/咪咕 → wy/qq/kw/kg/mg)、`source_code()`、`song_unavailable()`、`song_album()`、`RoomClient.search_songs()`/`pick_song()`，`SEARCH` 帧 → `search` 事件 `{songs,total,page,ok}`；GUI「点歌…」面板（关键词+音源+搜索/热歌榜 `*热歌榜`+结果表+标准/高清+加载更多）。
  - 命令行版同源命令（2026-09-30）：`p 关键字` 搜歌、`pick 序号 [flac]`（别名 `点`）点歌、`pn` 加载更多、`ph` 热歌榜、`src [音源]` 切换音源，`--source` 启动参数；搜索用 `threading.Event` 同步等待（12s 超时），房间序号与歌曲序号靠 `pick` 前缀区分。
- **音量即时生效（2026-09-20）**：每首 mpv 加 `--input-ipc-server=`（Win `\\.\pipe\jusic-mpv-<pid>-<seq>`，其它平台 tempdir 下 .sock），`MpvEngine.set_volume()` 只改值 + 唤醒常驻守护线程 `_pump_loop` 异步下发，GUI 永不阻塞；`_ipc_push` 必须**一次一连接**（写→读回执→关），因为同一 Windows 命名管道句柄上并发读写会永久阻塞。实测 ~0.02s 生效、300 次连发无失败。
- `requirements.txt`（2026-10-02 改为 `websockets>=13.1,<16` + `ttkbootstrap>=2.0`）、`run.bat`、`run_gui.bat`、`README.md`。
- 打包（2026-09-17 重写）：`build_exe.bat`=单文件 exe、`build_exe_dir.bat`=onedir+ZIP，均由 VERSION 取版本；开关 `-n` 跳过依赖、`-k` 保留缓存、`-d` 深度清缓存、`-h` 帮助。约定：`--distpath dist --workpath build --specpath build` + 入口绝对路径，**打包后自动清理 `build\` 工作目录与 `__pycache__`**，`.spec` 只生成在 `build\`（不再落仓库根）；不传 `--clean` 以复用 PyInstaller 全局分析缓存（重建仅 ~16–25s）。
- 版本控制约定（2026-09-17）：新增 `.gitignore`，**`build/`、`dist/`、`*.spec` 不入库**（发布产物走 Release 附件）；`.codebuddy/memory/` 是有意跟踪的，勿忽略。
- 发布流程（2026-09-18 新增 `publish_release.py`）：读 VERSION → 取 `dist\JusicRoomPlayer <ver>.exe` + `dist\JusicRoomPlayerPortable_<ver>.zip` → 在 GitHub/Gitee 建同名 tag 的 Release 并上传附件。纯标准库 urllib；凭证走环境变量 `GH_TOKEN`/`GITEE_TOKEN` 或 `--github-token/--gitee-token`；`git remote get-url` 自动解析 owner/repo（github=seaworld92/JusicRoomPlayer，origin=gitee seaworld/JusicRoomPlayer）；已存在 release/同名附件自动复用跳过（幂等）；`--dry-run` 无需凭证。**GitHub 会把附件名里的空格替换成点**（`JusicRoomPlayer 1.2.0.exe` → 远端 `JusicRoomPlayer.1.2.0.exe`）；Gitee API 的 `assets[].size` 恒为 0，不能用于校验。
- 平台适配现状（2026-09-18 确认）：**仅 Windows 完整可用**。`jusic_tray.py` 的托盘（Shell_NotifyIconW/CreateIconFromResourceEx）是 Win32 专属，非 Windows 下 `IS_WINDOWS=False` → 占位 `TrayIcon.available()=False`，GUI 自动退化为普通最小化（窗口留在任务栏，不会藏窗口）；但**图标字节生成 `icon_image_bytes()` 是纯 Python 计算（math/struct），任何系统都能生成同样 4264 字节**。`MpvEngine.find_mpv` 路径偏 Windows（Program Files/WinGet，Linux 靠 PATH）、`run.bat` 仅 Windows。真正跨平台托盘需分平台实现或引入 pystray+Pillow，与低内存定位冲突，暂未做。

## 关键协议事实（勿忘）
- 房间列表：POST /api/house/search，头 AccessToken: token，匿名可用。
- 实时：WSS /api/server/000/<随机>/websocket?houseId&housePwd&connectType=enter；纯监听收 MUSIC(含可直接播放 url)/PICK/ONLINE/CHAT/公告；不要发非 sockjs 帧(会被 1007 关闭)；无需 STOMP。
- 帧格式：a["TYPE\ncontent-type:application/json\ncontent-length:N\n\n{json}"]，解析取首行类型+末 json。
- 点歌（SEND，已实测通过）：`/music/search {name,source,pageIndex,pageSize,sendTime}` → `SEARCH` 帧（`data.data` 歌曲数组、`data.totalSize` 总数）；`/music/pick {name,id,source,quality,sendTime}`，quality=320k|flac，成功推 NOTICE「点歌成功」+ 新 `PICK` 队列。同源还有 `/music/top {id}`、`/music/good/<id>`、`/music/clear`、`/music/delete {id}`（delete 实测对普通用户无效=房管权限）。
- **搜索结果字段实测**：**无 `source`**（需用当前所选音源回填）、`fl`/`st` 藏在 `privilege` 子对象（`{"fl":1,"st":1}`，fl==0 或 st<0 视为不可用）、`album` 是**对象**（取 `album.name`）、有 `duration`(ms)/`picture_url`。
- **点赞（2026-09-30，已实测）**：`SEND /music/good/<歌曲id>`，body `{}`；服务端按「点歌归属表」匹配，**只认自己（本会话）点的歌**——别人的歌立刻回 `NOTICE`「点歌列表未发现此歌」，自己点的歌静默接受；换会话后连自己的歌也会失败。点赞数不下发（MUSIC 帧无计数字段，官网 `#like-count` 只是本地 +1）。`GOODMODEL` 帧 = 房间「点赞排序」开关（data=="GOOD"，切换时才推）；`ROOM_STATE` 帧含 `goodModel`（EVENT_TYPES 已加）。core 有 `good_song()` 与 `good-mode` 事件。
- **点赞入口（2026-09-30 用户要求调整后）**：GUI 只保留**点歌队列**的点赞（选中行 → 「👍 点赞选中歌曲」），队列有独立「点赞」列显示 👍；**「当前播放」标题右侧的点赞按钮已按用户要求删除**（`_like_current` 也删了）。收到「未发现此歌」会**自动撤回 👍 标记**（`_last_like` + `_rollback_last_like`）。CLI 对应 `like 序号`（`que`/`m` 行首 `[已赞]` 文本标记）。改队列渲染时记得：队列数据统一走 `_queue_songs` + `_render_queue()`，换房间清空点赞记录后**必须重绘队列**。
- **删除自己点的歌（2026-09-30 实测有效）**：`SEND /music/delete {id: <歌名>}`（官网传 `String(song.name || song.id)`，**传歌名有效、传数字 id 无效/q静默**）→ 回 `NOTICE`「删除成功」；跨会话或他人的歌静默无响应。可用于将来做「移除我点的歌」。

## 环境约定（Windows 本机，重要）
- 目标服务器拒部分 TLS1.3 握手 → Python 固定 TLS1.2；`proxy=None` 用于绕开本机系统代理 127.0.0.1:10808。
- **websockets 版本坑（2026-10-02 实测）**：本机 `python`（`C:\Users\love5\AppData\Local\Python\python3-13-14`）实际装的是 **websockets 13.1**（被同环境的 ocp-viewer-core 带装），而代码原来写死了 15.x 的 `additional_headers` 与 `proxy=None` → websockets 13 会把这两个未知参数**透传给 `loop.create_connection`**（该函数在 Python 3.13 既无 proxy 也无这两个参数），报 `TypeError: ... unexpected keyword argument 'proxy'`，WSS 完全连不上（两个 GUI + CLI 都受影响）。已在 `jusic_core.ws_connect_extras()` 做能力探测：14+ 用 `additional_headers`、13.x 用 `user_agent_header`、`proxy=None` 仅在 `BaseEventLoop.create_connection` 真有该参数时才传。requirements 放宽为 `>=13.1,<16`（v17 有 bug 的旧结论仍有效）。**以后改连接参数务必保持这种探测式写法。**
- ttkbootstrap 2.x 关键 API（2026-10-02 实测，2.2.3）：**`ttb.Style()` 一旦创建就绑定当时的根窗口，之后再 `ttb.Window()` 会报 "single application root window"** → 启动前校验主题名只能用数据模块 `ttkbootstrap.themes.builtin.CURATED_THEMES`（15 个风格 Theme 对象的 `.name`）+ `themes.legacy.STANDARD_THEMES`，绝不能先 `ttb.Style()`。`Style.theme` 返回 **Theme 对象**（取名字用 `.theme.name`），明暗用 `style.theme_mode`；运行时 `style.theme_use(name)` 会自动重绘整棵控件树（`_theme_walk`），但**普通 tk 控件（tk.Text/tkMenu/tkToplevel）与显式写死的颜色不在其列** → 用 `ttb.Text`、`root.option_add("*Background"/"*Foreground", …)` 让后建对话框跟随主题。旧主题名（darkly/superhero…）仍可用但会发 DeprecationWarning。
- 播放引擎 mpv 0.41.0 位于 `C:\Program Files\MPV Player\mpv.exe`（winget id shinchiro.mpv）。
- 实测内存：命令行版 python≈37MB + mpv≈53MB ≈ 90MB；GUI 版（jusic_gui.py，2026-09-17 实测）python/tk≈55MB + mpv≈57MB ≈ 113MB。
- PowerShell 命令含中文路径参数编码不可靠 → 用 ASCII 临时目录（如 %LOCALAPPDATA% 下）写 python runner，脚本内用 unicode 路径读写/测试。
- 工作区是百度网盘同步盘：read_file 等工具对该盘某些文件可见性不稳；必要时用 python 直接读取确认。
- tkinter 陷阱（2026-09-30）：`ttk.Entry(textvariable=var)` 里 var 若为**函数局部变量**，函数返回后它被 GC → 控件文本变空。需持有引用，或（推荐）直接 `insert` 文本后置为 readonly。
- **ttk.Panedwindow 陷阱（2026-10-02）**：窗口还没映射完成时（paned 的 `winfo_width()` 仍是 1）调 `sashpos(0, N)` 会把分栏位置截成 0，**第一个窗格被压成 0 宽（内容 1x1，整个面板消失）**。必须等 `<Map>`/`<Configure>` 事件里 `winfo_ismapped()` 且宽度正常后再设，且只设一次（别再用 `after(120, ...)` 盲设）。排查这类“界面少了一块”的问题时，先打印各面板 `winfo_width/height`、`winfo_ismapped()` 与 `sashpos()`，别只看控件树里有没有数据。
- **ttk.Treeview 选中行配色（2026-10-02，Tk 8.6.15 实测）**：`ttk::treeview` **没有任何颜色控件选项**（`tree.cget("selectbackground")` 直接 TclError，`configure()` 只有 12 个选项），只能走样式。做法是给列表挂一个派生样式（如 `Pick.Treeview`），同时 `style.configure(style, selectbackground=…, selectforeground=…)` **并且** `style.map(style, background=[("selected",…)], foreground=[("selected",…)])`——只 configure 时（clam）渲染可能仍用主题默认（本机为系统高亮色 #9e9a91），两者都设才在各主题下稳定可见。取主题色时注意：`tkinter.ttk.Style(root)` **不是** ttkbootstrap 的引擎（没有 `.colors`），要拿主色得用 `ttkbootstrap.Style` 实例或直接传 GUI 里的 `self.style`。
- 自研事物的验证套路（2026-09-30）：把参考库（如 segno）`pip install --target %TEMP%\<dir>` 临时安装做逐位对比，用后即删；二进制/图片类结果可借助在线服务（如 api.qrserver.com 的 read-qr-code）回读校验，再用 PIL ImageGrab 截图人工确认 GUI 效果。
- 用户交流语言：简体中文。
