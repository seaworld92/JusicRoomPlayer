# Jusic 轻量房间播放器（Jusic Room Player）

一个**占用内存尽可能小**的开源方案 Python 音乐播放器，用来直接播放
「一起听歌吧」房间点歌台（[Jusic-Serve-Houses](https://github.com/JumpAlang/Jusic-Serve-Houses)）里正在播放的歌曲，
并支持**房间列表 / 进入房间 / 随时切换房间**。提供两个前端：

- `jusic_room_player.py`：命令行版（零 GUI，内存最小）；
- `jusic_gui.py`：基于 **ttk/Tkinter** 的图形界面版（房间列表双击进入、密码房询问、音量滑块、队列与日志）。

- 网页版界面（数据来源）：<https://happy.alang.run/modern-ui/>
- 播放器默认对接该网页使用的公开后端：`https://tx.alang.run/api`（可 `--host` 改成自建后端）
- 播放内核：**[mpv](https://github.com/mpv-player/mpv)**（开源、C 语言、极轻量的媒体引擎）

## 为什么内存小

1. **播放内核选 mpv 而非重型播放器**：mpv 是轻量开源媒体引擎，本项目只用它的音频解码/播放能力；
2. **Python 只做“协议 + 控制”**：不引入 PyQt/WebView 等图形库，不装音频解码库，全部音频交给 mpv；
3. **不复制网页逻辑**：直接走后端 REST + WSS 实时通道，比“开个浏览器/套壳网页”省几个数量级。

| 实测（Windows，本机） | 占用内存 |
|---|---|
| Python 播放器进程 | ≈ 37 MB |
| mpv 播放进程 | ≈ 53 MB |
| **合计** | **≈ 90 MB** |

> 浏览器运行该网页通常要 300 MB+；本方案约为其 1/4~1/3。

## 快速开始

```bat
:: 1. 安装依赖（只需一个 websockets 库）
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

两个版本都会自动进入默认房「一起听歌吧(DEFAULT)」，并跟随房间实时播放当前歌曲。

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
| `q` / `Ctrl+C` | 退出 |

进入密码房时会提示输入密码；密码错误会自动提示且不影响原房间。
断线后自动按指数退避重连（默认最多 6 次）。

### 图形界面版（jusic_gui.py）

- 左侧房间列表按“在线人数”排序；**双击**（或选中后回车/点“进入选中房间”）即可切换房间；
  密码房会弹出密码输入框；
- 搜索框输入关键字后点“过滤”，实时筛选房间名/简介；
- 右侧显示当前播放歌曲、房间与在线人数、音量滑块、**歌词面板（LRC 随播放同步高亮当前句）**、点歌队列、动态日志；
- **下载▾ 菜单**可保存当前正在播放的**歌曲音频**、**歌词（.lrc）**，或**两者一起下载**（歌词自动存为与音频同名的 `.lrc`）；
- 勾选“显示聊天”可查看房间聊天流；关闭窗口即退出。

### 命令行参数

`jusic_room_player.py` 与 `jusic_gui.py` 均支持：

```text
--host 域名        对接的 Jusic 后端（默认 tx.alang.run，支持自建实例）
--house 房间ID     启动后直接进入指定房间
--password 密码    房间密码
--mpv 路径         mpv.exe 绝对路径
--volume 0-100     播放音量（默认 90）
```

`jusic_room_player.py` 额外支持：

```text
--chat             控制台显示房间聊天流
--auto-seconds N   运行 N 秒后自动退出（脚本/自测用）
```

示例：命令行直接进某房间并打开聊天、调低音量：

```bat
python jusic_room_player.py --house 73DlCti8 --chat --volume 60
```

## 打包 Windows 发行版（内置 mpv，自动带版本号）

用 PyInstaller 把 GUI 与 **mpv 一起打进 exe**，目标机器无需安装 Python / mpv。
**产物自动带版本号**：版本号只需改根目录 `VERSION` 文件（如 `1.0.1`），
打包后会体现在产物文件名与 exe 属性（文件版本/产品版本）。

**单文件版**（便于单个文件分发，首次启动稍慢）：

```bat
build_exe.bat
```

产物：`dist\JusicRoomPlayer <版本>.exe`（约 62 MB）。

**便携版 ZIP**（免安装、启动快、不每次解压；产物直接是 ZIP）：

```bat
build_exe_dir.bat
```

产物：`dist\JusicRoomPlayerPortable_<版本>.zip`（约 62 MB 压缩，含
`_internal\_engine\mpv\mpv.exe`）。解压后顶层即版本文件夹，运行其中的
`JusicRoomPlayerPortable_<版本>.exe` 即可；打包完成后中间文件夹会被自动清理。

两个版本共同特性：

- 内置 mpv 自动发现并使用；也可用界面右下角“选mpv…”改为外部 mpv；
- 程序异常时会在 exe 同目录写 `JusicRoomPlayer-error.log`；
- 分发给其他 Windows 用户即可（如被杀软误报，可加白名单或对 exe 签名）。

## 工作原理（对接 Jusic 后端）

1. `POST /api/house/search`：匿名拉取房间列表（名称/人数/是否密码房）；
2. 建立 WSS 连接：`/api/server/000/<会话>/websocket?houseId=..&housePwd=..`；
3. 后端经 SockJS 推送“类 STOMP”帧：`MUSIC`（当前歌曲，含真实播放地址 `url`、歌词、封面）、
   `PICK`（点歌队列）、`ONLINE`（在线人数）、`CHAT`、公告等；
4. 收到 `MUSIC` 后把 `url` 交给 mpv 播放；服务端切歌时推送新 `MUSIC`，客户端随之换歌，
   从而和网页端完全同步。

## 目录结构

```text
本地音乐播放器/
├─ jusic_core.py          # 共享核心：REST/WSS 会话、事件化 RoomClient、mpv 引擎（无界面）
├─ jusic_room_player.py   # 命令行前端（复用 jusic_core）
├─ jusic_gui.py           # ttk/Tkinter 图形界面前端（复用 jusic_core）
├─ jusic_gui.pyw          # 无控制台双击副本（可选）
├─ requirements.txt       # 依赖：websockets
├─ run.bat                # 命令行版一键启动
├─ run_gui.bat            # GUI（带控制台输出）备用启动
├─ VERSION               # 版本号来源（如 1.0.0），打包产物名/属性自动使用
├─ make_version_file.py  # 由 VERSION 生成 exe 版本资源（build 用）
├─ make_zip.py           # 把便携版目录压成同版本 ZIP（build 用）
├─ build_exe.bat          # 打包【单文件】exe（内置 mpv，带版本）→ dist\JusicRoomPlayer <版本>.exe
├─ build_exe_dir.bat      # 打包【便携版 ZIP】（内置 mpv，带版本）→ dist\JusicRoomPlayerPortable_<版本>.zip
├─ dist\JusicRoomPlayer <版本>.exe         # 单文件发行版（约 62MB）
├─ dist\JusicRoomPlayerPortable_<版本>.zip # 便携版发行 ZIP（约 62MB）
└─ README.md
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
