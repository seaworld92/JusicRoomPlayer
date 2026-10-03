# Jusic 轻量房间播放器（Jusic Room Player）

[English](README_EN.md) | 简体中文

一个**占用内存尽可能小**的开源方案 Python 音乐播放器，用来直接播放
「一起听歌吧」房间点歌台（[Jusic-Serve-Houses](https://github.com/JumpAlang/Jusic-Serve-Houses)）里正在播放的歌曲，
并支持**房间列表 / 进入房间 / 随时切换房间**。提供三个前端：

- `jusic_room_player.py`：命令行版（零 GUI，内存最小；含 `p` 搜歌 / `pick` 点歌命令）；
- `jusic_gui.py`：基于 **ttk/Tkinter** 的图形界面版（房间列表双击进入、密码房询问、音量滑块、
  **点歌面板**、歌词、队列、**我的收藏**与日志）；
- `jusic_gui_bootstrap.py`：基于 **ttkbootstrap** 的**多主题界面版**（功能与上一版完全一致，
  界面换成 Bootstrap 风格，**15 套风格 × 明/暗 = 30 种主题**可随时切换并自动记住）。

- 网页版界面（数据来源）：<https://happy.alang.run/modern-ui/>
- 播放器默认对接该网页使用的公开后端：`https://tx.alang.run/api`（可 `--host` 改成自建后端）
- 播放内核：**[mpv](https://github.com/mpv-player/mpv)**（开源、C 语言、极轻量的媒体引擎）

## 为什么内存小

1. **播放内核选 mpv 而非重型播放器**：mpv 是轻量开源媒体引擎，本项目只用它的音频解码/播放能力；
2. **Python 只做“协议 + 控制”**：不引入 PyQt/WebView 等图形库，不装音频解码库，全部音频交给 mpv；
3. **不复制网页逻辑**：直接走后端 REST + WSS 实时通道，比“开个浏览器/套壳网页”省几个数量级；
4. **托盘也是系统原生的**：最小化驻留托盘由纯 `ctypes` 调用 Win32（`jusic_tray.py`）实现，
   不引入 pystray / Pillow 等依赖，几乎不增加内存占用
   （只有 `jusic_gui_bootstrap.py` 会因 ttkbootstrap 间接带入 Pillow，代价见下表）。

实测（Windows 本机，**工作集**口径、播放中稳定态，可用 `tools/mem_bench.py`
按下节方法复测）：

| 前端 | Python 进程 | mpv 进程 | 合计 |
|---|---|---|---|
| `jusic_room_player.py`（命令行版） | ≈ 37 MB | ≈ 53 MB | **≈ 90 MB** |
| `jusic_gui.py`（经典 ttk 界面） | ≈ 66 MB | ≈ 57 MB | **≈ 123 MB** |
| `jusic_gui_bootstrap.py`（主题界面） | ≈ 76 MB | ≈ 57 MB | **≈ 134 MB** |

> 浏览器运行该网页通常要 300 MB+；本方案约为其 1/4~1/2。
>
> 主题界面版比经典界面多约 **10 MB**（约 +15%），而这部分几乎全部来自
> `ttkbootstrap` 自身：它一被导入就连带载入 Pillow（`import tkinter` 21 MB →
> `import tkinter, ttkbootstrap` 34 MB，再建 `ttb.Window` 达 52 MB），
> 我们自己的界面代码（`BootstrapGui` 继承 `JusicGui`，只替换布局）几乎不额外占内存。
> 因此**追求极限内存请用 `jusic_gui.py`**，想要 30 种可切换主题则多花这 ~10 MB。

## 内存基准测试（tools/mem_bench.py）

想在本机自己复测一遍（脚本会自动弹窗、用 mpv 真的播一小会儿，属于正常现象）：

```bat
python tools/mem_bench.py                  :: 经典界面 + 主题界面（每项约 55s）
python tools/mem_bench.py --cli            :: 再把命令行版也算上
python tools/mem_bench.py --only theme --seconds 30      :: 只测主题界面，缩短时长
python tools/mem_bench.py --imports-only   :: 只测库导入开销（不启动界面）
python tools/mem_bench.py --json out.json  :: 结果另存 JSON，便于发版前后对比
```

测量口径与细节：

- 内存取 Windows **工作集**（与任务管理器“内存”列同口径），同时给出提交大小与句柄数，
  取稳定态 3 次采样的中位数；
- 每个前端**单独串行**启动，命令为 `python <前端> --console`，并设 `JUSIC_GUI_PYW=1`，
  避免程序自动改用 pythonw 重启而测到两个进程；
- 分别在「界面刚建好」与「进入房间、播放稳定」两个阶段采样，体现真实使用时的占用；
- mpv 是独立进程，用 `tasklist` 单独抓取，因此汇总表给出“播放器 + 内核”的合计；
- 测量结束用 `taskkill /F /T` 连子进程（mpv）一起清干净（`--keep` 可保留窗口调试）。

`--imports-only` 用于定位差距来源，本机结果（2026-10-02，Python 3.13 / ttkbootstrap 2.2.3）：

| 场景 | 工作集 | 提交大小 |
|---|---|---|
| python 空进程基线 | 18 MB | 11 MB |
| `import tkinter` | 21 MB | 12 MB |
| `import tkinter, ttkbootstrap` | **34 MB**（连带载入 Pillow） | 23 MB |
| 再创建 `ttb.Window()` | 52 MB | 32 MB |

即：**主题界面的额外开销几乎全在 ttkbootstrap 这个库本身**。

> 仅 Windows 可用（依赖 psapi / tasklist / taskkill）。

## 快速开始

```bat
:: 1. 安装依赖（websockets + 主题界面用的 ttkbootstrap）
python -m pip install -r requirements.txt
```

- **图形界面版（ttk）**：直接**双击 `jusic_gui.py`** 即可打开（程序会自动改用
  `pythonw` 无黑色控制台窗口方式运行）。若双击后是打开编辑器而不是运行，
  请在该文件上右键 →“打开方式”→“选择其他应用”→ 选 Python 并勾选“始终使用”。
  也可运行：
  ```bat
  python jusic_gui.py --console     :: 需要保留控制台调试输出时
  ```
- **命令行版**：双击 `run.bat` 或运行 `python jusic_room_player.py`
- **主题界面版（ttkbootstrap）**：双击 `jusic_gui_bootstrap.pyw`（或
  `python jusic_gui_bootstrap.py`），界面右上角可随时切换主题：
  ```bat
  python jusic_gui_bootstrap.py --console                  :: 保留控制台调试输出
  python jusic_gui_bootstrap.py --theme dracula-dark       :: 指定启动主题
  ```

三个版本都会自动进入默认房「一起听歌吧(DEFAULT)」，并跟随房间实时播放当前歌曲。

### 播放内核 mpv 准备

本机首次运行会自动尝试用 winget 安装 mpv（`shinchiro.mpv`）。
也可以手动安装后用参数指定：

```bat
python jusic_room_player.py --mpv "C:\Program Files\MPV Player\mpv.exe"
```

支持 mpv 的搜索顺序：`--mpv` 参数 → 环境变量 `JUSIC_MPV` → `PATH` 中的 `mpv` → 常见安装路径。

## 交互使用（含“房间切换”）

启动后在输入框直接操作：

| 输入 | 功能 |
|---|---|
| 房间序号（如 `2`） | **切换/进入对应房间**，自动停止上一房间并播放新房当前歌曲 |
| `l` | 刷新并重列房间列表（人多的房间排前面，🔒 为密码房） |
| `s 关键字` | 按房间名/简介搜索后再列序号 |
| `f` | 显示全部房间 |
| `m` | 显示当前播放歌曲与点歌队列 |
| `p 关键字` | **搜索歌曲**（点歌用）：按当前音源列出前 20 首，含专辑、时长与「不可用」标记 |
| `pick 序号 [flac]` | **点歌**：把搜索结果第 N 首加入房间队列（默认 320k，加 `flac`/`高清` 为 FLAC 高清） |
| `pn` | 加载更多搜索结果（下一页，追加显示） |
| `ph` | 热歌榜（等价于搜索 `*热歌榜`） |
| `src [音源]` | 查看/切换点歌音源：`src`、`src QQ`、`src 2`（wy/qq/kw/kg/mg） |
| `que` | 查看完整点歌队列（带序号与点赞标记，配合 `like 序号` 用） |
| `like [序号]` | **点赞**：带序号=给队列第 N 首点赞（别名 `赞`）；不带序号=给当前播放的歌曲点赞。已赞的行首会显示 `[已赞]` |
| `q` / `Ctrl+C` | 退出 |

点歌示例：`p 晴天` → 看列表 → `pick 2 flac`（点第 2 首的高清版）。
房间列表与搜索结果的序号用途不同，点歌请务必带 `pick` 前缀。
搜索是同步等待结果（最长约 12 秒），期间不接收输入。

进入密码房时会提示输入密码；密码错误会自动提示且不影响原房间。
断线后自动按指数退避重连（默认最多 6 次）。

### 图形界面版（jusic_gui.py）

- 左侧房间列表按“在线人数”排序；**双击**（或选中后回车/点“进入选中房间”）即可切换房间；
  密码房会弹出密码输入框；
- 搜索框输入关键字后点“过滤”，实时筛选房间名/简介；
- 右侧显示当前播放歌曲、房间与在线人数、**音量滑块（拖动即时生效，无需等下一首）**、**歌词面板（LRC 随播放同步高亮当前句）**、点歌队列、动态日志；
- **切歌（投票）** 按钮：向房间发送 `/music/skip/vote`；普通成员为投票切歌（票数达标自动切），管理员身份则直接切歌；
- **点歌队列点赞**：队列里选中一首后点下方「👍 点赞选中歌曲」，已点赞的行会在**「点赞」列显示 👍**，
  一眼就能看出自己赞过哪些；同一首歌本房间内只发一次（去重），换房间自动清空。
  **注意：该后端按「点歌归属表」匹配，只接受自己点的歌**——给别人点的歌点赞会收到服务端提示
  「点歌列表未发现此歌」，此时界面会**自动撤回 👍 标记**并说明原因（不会显示假的已赞状态）；
  若房间开启「点赞排序」，点赞会调整播放顺序（队列会自动刷新）；
- **我的收藏（♡ 收藏）**：点「♡ 收藏」把**当前播放的歌曲**加入收藏（再点一次取消收藏），
  队列里已收藏的行会在**「收藏」列显示 ♥**（队列下方也有「♡ 收藏选中歌曲」按钮）；
  点「我的收藏…」打开收藏列表，可**点歌（标准 320k / 高清 FLAC）**、**取消收藏**、
  **▶ 播放全部**（把收藏依次加入房间点歌队列）、**导出 / 导入 JSON**、**清空**。
  与网页端「我的收藏」同款：**只保存在本机**（`%APPDATA%\JusicRoomPlayer\favorites.json`），
  不上传服务端；导出的 JSON 与网页端「导出」格式一致，可两端互相导入；
- **点歌…** 按钮：按歌名/歌手搜索真实曲库（音源可选 网易 / QQ / 酷我 / 酷狗 / 咪咕，与网页端一致），
  结果列表显示「歌曲 / 歌手 · 专辑 / 时长」，**单击选中歌曲**（选中行会整行高亮——主题界面版
  跟随当前主题主色、经典界面为亮蓝——并在歌名前带 `▶` 标记），再点「点歌 · 标准」加入点歌队列，
  点「点歌 · 高清」按 FLAC 音质点歌；还有「热歌榜」一键搜热门与「加载更多」翻页；
  搜索不到可播版本的曲目会标为「不可用」；房间禁止访客点歌时服务端会推送通知；
  **双击结果行不会直接点歌**（避免误点，需选中后点按钮确认）；
- **聊天输入框 + 发送按钮**（回车也可）：把文字发送到房间聊天窗口；可先设置**昵称**（不填则用服务端默认昵称）；
- **下载▾ 菜单**可保存当前正在播放的**歌曲音频**、**歌词（.lrc）**，或**两者一起下载**（歌词自动存为与音频同名的 `.lrc`）；
- **分享房间…** 按钮：生成与网页端完全一致的**房间直达链接**
  （`https://happy.alang.run/modern-ui?houseId=..&housePwd=..`），支持**复制到剪贴板**、
  **浏览器打开**、**保存二维码 PNG**（手机扫码进房）以及**保存微信小程序码**；
  二维码由纯 Python 生成（`jusic_qr.py`，不引入第三方库）。密码房按网页端规则把密码写入链接，
  请只分享给可信的朋友；
- **“显示聊天”默认开启**（☑️/☐ 样式，可在设置里开关）；房间列表**每 10 分钟自动刷新**一次（静默进行并保留选中项）；
- **最小化到系统托盘**：点最小化按钮后窗口收进托盘图标（后台继续播放，不占任务栏）；
  **双击**托盘图标恢复窗口，**右键**图标弹出菜单可选“显示主界面 / 退出程序”
  （Windows 11 若图标被折叠进溢出区，点任务栏右下角 `^` 即可看到，可拖出固定）；
- 关闭窗口（点 ✕）即退出程序。

### 主题界面版（jusic_gui_bootstrap.py）

同一套功能，界面换成 ttkbootstrap 的 Bootstrap 风格，重点是**主题随便换**：

- **主题切换**：右上角「主题」下拉框选风格（bootstrap / catppuccin / dracula /
  everforest / gruvbox / minty / nord / one / pulse / pydata / sandstone /
  solarized / tokyo-night / united / vapor，共 15 套），旁边的「深色」开关一键
  切明/暗，二者组合就是 **30 种主题**；点「全部主题 ▾」可展开完整列表，里面还有
  「明暗一键切换」和「随机换一个主题」；
- **快捷键**：`Ctrl+T`（或 `F2`）明暗对调；
- **记住设置**：主题与窗口大小写在 `%APPDATA%\JusicRoomPlayer\ui.json`，
  下次启动自动恢复（想重置直接删掉该文件；也可用 `--theme` 临时指定）；
- **深色适配**：歌词/日志文本、次要文字，以及分享/点歌/关于等弹窗的文字配色都会
  随主题一起调整，暗色下同样清晰；
- **播放进度条**：当前播放区多了带时间（`已播 / 总长`）的进度条，与歌词同一时钟；
- **布局**：右侧把「歌词 / 点歌队列 / ♥ 我的收藏 / 动态日志（含聊天与昵称）」分成四个标签页，
  左右分栏宽度可拖动；「我的收藏…」按钮会直接切到该标签页（不再另开窗口）；
- 其余功能（房间列表与搜索、切歌投票、点歌、点赞、**我的收藏**、下载、分享二维码、系统托盘等）
  与 `jusic_gui.py` 完全一致——代码上它是 `jusic_gui.JusicGui` 的子类，
  **业务逻辑只有一份**，不会出现两套逻辑各自漂移。

依赖：`ttkbootstrap`（`python -m pip install ttkbootstrap`，已写入 requirements.txt）。

### 命令行参数

`jusic_room_player.py`、`jusic_gui.py` 与 `jusic_gui_bootstrap.py` 均支持：

```text
--host 域名        对接的 Jusic 后端（默认 tx.alang.run，支持自建实例）
--house 房间ID     启动后直接进入指定房间
--password 密码    房间密码
--mpv 路径         mpv.exe 绝对路径
--volume 0-100     播放音量（默认 90）
```

`jusic_gui_bootstrap.py`（主题界面版）额外支持：

```text
--theme 主题名     启动主题，如 dracula-dark / nord-light
                   （默认使用上次记住的主题；可用 30 种，见 --theme 说明与界面「全部主题」）
```

`jusic_room_player.py` 额外支持：

```text
--chat             控制台显示房间聊天流
--source 音源      点歌默认音源（wy/qq/kw/kg/mg，也可写 网易/QQ/酷我/酷狗/咪咕）
--auto-seconds N   运行 N 秒后自动退出（脚本/自测用）
```

示例：命令行直接进某房间并打开聊天、调低音量：

```bat
python jusic_room_player.py --house 73DlCti8 --chat --volume 60
```

## 打包 Windows 发行版（内置 mpv，自动带版本号）

用 PyInstaller 把界面与 **mpv 一起打进 exe**，目标机器无需安装 Python / mpv。
**产物自动带版本号**：版本号只需改根目录 `VERSION` 文件（如 `1.0.1`），
打包后会体现在产物文件名与 exe 属性（文件版本/产品版本）。

两个脚本**默认同时打包两个界面**（经典 ttk 界面 + ttkbootstrap 主题界面）；
只想要其中一个时用 `-c`（只打经典）/ `-t`（只打主题）。其他开关：
`-n` 跳过依赖安装（日常快速重建）、`-k` 保留中间缓存便于排错、
`-d` 额外清理 PyInstaller / pip 全局缓存、`-h` 帮助。

**单文件版**（便于单个文件分发，首次启动稍慢）：

```bat
build_exe.bat              :: 默认：经典 + 主题 都打
build_exe.bat -n -t        :: 只打主题界面版
```

产物：

- `dist\JusicRoomPlayer <版本>.exe`（经典界面，约 58 MB）
- `dist\JusicRoomPlayerTheme <版本>.exe`（主题界面，约 66 MB）

**便携版 ZIP**（免安装、启动快、不每次解压；产物直接是 ZIP）：

```bat
build_exe_dir.bat
```

产物：

- `dist\JusicRoomPlayerPortable_<版本>.zip`（经典界面，约 58 MB 压缩）
- `dist\JusicRoomPlayerThemePortable_<版本>.zip`（主题界面，约 66 MB 压缩）

两者都内置 `_internal\_engine\mpv\mpv.exe`。解压后顶层即版本文件夹，运行其中的同名 exe
即可；打包完成后中间文件夹与 `build\` 缓存会被自动清理。

> 主题界面版依赖 ttkbootstrap（连带 Pillow），因此体积多约 8 MB、内存多约 10 MB；
> 追求最小体积/内存请用经典版。脚本里 `--exclude-module PIL` **只对经典版生效**
> （主题版必须保留 Pillow），改动打包脚本时注意不要混用。

两个界面共同特性：

- 内置 mpv 自动发现并使用；也可用界面右下角“选mpv…”改为外部 mpv；
- 程序异常时会在 exe 同目录写 `JusicRoomPlayer-error.log`（主题界面版为 `JusicRoomPlayer-theme-error.log`）；
- 分发给其他 Windows 用户即可（如被杀软误报，可加白名单或对 exe 签名）。

## 工作原理（对接 Jusic 后端）

1. `POST /api/house/search`：匿名拉取房间列表（名称/人数/是否密码房）；
2. 建立 WSS 连接：`/api/server/000/<会话>/websocket?houseId=..&housePwd=..`；
3. 后端经 SockJS 推送“类 STOMP”帧：`MUSIC`（当前歌曲，含真实播放地址 `url`、歌词、封面）、
   `PICK`（点歌队列）、`ONLINE`（在线人数）、`CHAT`、公告等；
4. 收到 `MUSIC` 后把 `url` 交给 mpv 播放；服务端切歌时推送新 `MUSIC`，客户端随之换歌，
   从而和网页端完全同步；
5. 点歌：`SEND /music/search {name,source,pageIndex,pageSize}` 搜索曲库，服务端回 `SEARCH` 帧
   （`data.data` 为歌曲数组、`data.totalSize` 为总数）；`SEND /music/pick {name,id,source,quality}`
   点歌（`quality` 为 `320k` 或 `flac`），成功后服务端推送 `NOTICE`「点歌成功」并广播新的 `PICK` 队列；
6. 点赞：`SEND /music/good/<歌曲id>`（body `{}`）。实测该后端按「点歌归属表」匹配，**只认自己点的歌**：
   别人的歌会立刻回 `NOTICE`「点歌列表未发现此歌」，自己点的歌则静默接受（房间开启「点赞排序」后会影响播放顺序）。
   点赞数不下发（`MUSIC` 帧没有计数字段），因此客户端只负责发送与去重，并把服务端提示原样展示。
7. 收藏（我的收藏）是**纯本地功能，不涉及任何服务端接口**：网页端存在浏览器
   `localStorage` 的 `collectMusic`（`{歌曲id: 歌曲}`），本程序存在本机
   `%APPDATA%\JusicRoomPlayer\favorites.json`（同结构、同样最新的排最前）。
   点歌时只用到收藏里记录的**歌曲 id / 音源 / 曲名**，因此收藏的歌曲即使播放地址过期也能正常点歌；
   导出的 JSON 与网页端「我的收藏 → 导出」格式完全一致，可两端互相导入。

## 目录结构

```text
本地音乐播放器/
├─ jusic_core.py          # 共享核心：REST/WSS 会话、事件化 RoomClient、mpv 引擎（无界面）
├─ jusic_room_player.py   # 命令行前端（复用 jusic_core）
├─ jusic_gui.py           # ttk/Tkinter 图形界面前端（复用 jusic_core）
├─ jusic_gui.pyw          # 无控制台双击启动器（仅调用 jusic_gui，避免两份界面代码不同步）
├─ jusic_gui_bootstrap.py     # ttkbootstrap 多主题界面版（业务逻辑继承 jusic_gui.JusicGui）
├─ jusic_gui_bootstrap.pyw    # 主题界面版的无控制台双击启动器
├─ jusic_tray.py          # 系统托盘（Windows，纯 ctypes 调 Win32，最小化驻留）
├─ jusic_qr.py            # 纯 Python 二维码生成（分享房间用，零第三方依赖）
├─ requirements.txt       # 依赖：websockets（+ 主题界面版所需的 ttkbootstrap）
├─ run.bat                # 命令行版一键启动
├─ run_gui.bat            # GUI（带控制台输出）备用启动
├─ VERSION               # 版本号来源（如 1.0.0），打包产物名/属性自动使用
├─ make_version_file.py  # 由 VERSION 生成 exe 版本资源（build 用）
├─ make_zip.py           # 把便携版目录压成同版本 ZIP，可传入文件夹名（build 用）
├─ publish_release.py    # 把 dist 的 4 个产物发布到 GitHub / Gitee Releases（自动写 SHA256 与变更）
├─ tools\
│  └─ mem_bench.py       # 内存基准测试（对比各前端实际占用，仅 Windows）
├─ build_exe.bat          # 打【单文件】exe（内置 mpv，带版本；默认同时打经典界面与主题界面）
├─ build_exe_dir.bat      # 打【便携版 ZIP】（内置 mpv，带版本；默认同时打经典界面与主题界面）
├─ dist\JusicRoomPlayer <版本>.exe              # 经典界面 · 单文件发行版（约 58MB）
├─ dist\JusicRoomPlayerTheme <版本>.exe         # 主题界面 · 单文件发行版（约 66MB）
├─ dist\JusicRoomPlayerPortable_<版本>.zip      # 经典界面 · 便携版发行 ZIP（约 58MB）
├─ dist\JusicRoomPlayerThemePortable_<版本>.zip # 主题界面 · 便携版发行 ZIP（约 66MB）
├─ README.md              # 中文说明（本文件）
└─ README_EN.md           # 英文说明（English README，便于发布到 GitHub / Gitee）
```

## 许可证

本项目采用 **GPL-3.0** 授权，全文见 [LICENSE](LICENSE)。
第三方组件的许可与致谢见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES)。

## 开源致谢与合规提示

- 房间协议/数据格式参考：[Jusic-Serve-Houses](https://github.com/JumpAlang/Jusic-Serve-Houses)（**GPL-3.0**）
- 播放引擎：[mpv](https://github.com/mpv-player/mpv)（LGPL-2.1+ / ISC）
- 实时库：[websockets](https://github.com/python-websockets/websockets)（BSD-3）

请仅将本工具用于个人学习与合法收听场景；歌曲版权归原权利人所有，请遵守
目标网站/服务的使用条款与版权规定。默认对接的是公开演示实例，如需长期使用请自行部署后端
（`docker-compose up -d` 即可），并用 `--host` 指向自己的域名。
