# Jusic Room Player

English | [简体中文](README.md)

An open-source **memory-frugal** Python music player that plays whatever is currently playing in a
["Sing Along Together" (Jusic)](https://github.com/JumpAlang/Jusic-Serve-Houses) room jukebox,
with support for **room listing / joining / switching at any time**. Three frontends are provided:

- `jusic_room_player.py`: command-line frontend (no GUI, lowest memory; includes `p` search / `pick` request commands);
- `jusic_gui.py`: **ttk/Tkinter** GUI (double-click a room to join, password prompt, volume slider,
  **song-request panel**, lyrics, queue and log);
- `jusic_gui_bootstrap.py`: **ttkbootstrap** multi-theme GUI (identical features, Bootstrap-style skin,
  **15 styles × light/dark = 30 themes**, switchable at runtime and remembered automatically).

- Web UI (data source): <https://happy.alang.run/modern-ui/>
- The player talks to the public backend used by that web UI by default: `https://tx.alang.run/api`
  (use `--host` to point at your own self-hosted backend)
- Playback engine: **[mpv](https://github.com/mpv-player/mpv)** (open source, C, extremely lightweight media engine)

## Why is it so small?

1. **mpv instead of a heavyweight player**: mpv is a lightweight open-source media engine; this project only uses its audio decoding/playback.
2. **Python only does "protocol + control"**: no PyQt/WebView, no audio-decoding libraries — all audio is handled by mpv.
3. **No web logic duplication**: it talks directly to the backend over REST + WSS, which is orders of magnitude lighter than opening a browser or wrapping the web page.
4. **The tray icon is native too**: the minimize-to-tray feature uses pure `ctypes` calls into Win32 (`jusic_tray.py`),
   with no pystray / Pillow dependency, so it adds almost no memory
   (only `jusic_gui_bootstrap.py` drags in Pillow indirectly through ttkbootstrap — see the cost in the table below).

Measured (Windows, **working set**, stable state during playback; re-measure with `tools/mem_bench.py` as described below):

| Frontend | Python process | mpv process | Total |
|---|---|---|---|
| `jusic_room_player.py` (CLI) | ≈ 37 MB | ≈ 53 MB | **≈ 90 MB** |
| `jusic_gui.py` (classic ttk UI) | ≈ 66 MB | ≈ 57 MB | **≈ 123 MB** |
| `jusic_gui_bootstrap.py` (themed UI) | ≈ 76 MB | ≈ 57 MB | **≈ 134 MB** |

> Running the web UI in a browser usually takes 300 MB+; this project is roughly 1/4 to 1/2 of that.
>
> The themed UI costs about **10 MB** more than the classic one (~+15%), and that cost comes almost entirely from
> `ttkbootstrap` itself: importing it pulls in Pillow (`import tkinter` 21 MB →
> `import tkinter, ttkbootstrap` 34 MB, then creating a `ttb.Window` reaches 52 MB), while
> our own UI code (`BootstrapGui` extends `JusicGui` and only replaces the layout) adds almost nothing.
> So **use `jusic_gui.py` for the absolute minimum memory**, or pay the ~10 MB for 30 switchable themes.

## Memory benchmark (tools/mem_bench.py)

To reproduce the numbers locally (the script will open windows and actually play for a while — that is expected):

```bat
python tools/mem_bench.py                  :: classic UI + themed UI (~55s each)
python tools/mem_bench.py --cli            :: also include the CLI frontend
python tools/mem_bench.py --only theme --seconds 30      :: themed UI only, shorter run
python tools/mem_bench.py --imports-only   :: import cost only (no UI launched)
python tools/mem_bench.py --json out.json  :: also save results to JSON for release-to-release comparison
```

Method and details:

- Memory is the Windows **working set** (same metric as the Task Manager "Memory" column); commit size and handle count are also reported; the median of 3 samples in stable state is used;
- Each frontend is launched **serially**, with `python <frontend> --console` and `JUSIC_GUI_PYW=1`,
  so the program does not relaunch itself under `pythonw` and get counted as two processes;
- Samples are taken at "UI just built" and "joined room, playback stable" to reflect real usage;
- mpv is a separate process and is measured with `tasklist`, hence the "player + engine" total in the summary table;
- After measuring, `taskkill /F /T` cleans up children (mpv) as well (`--keep` keeps the windows for debugging).

`--imports-only` pinpoints where the difference comes from — local result (2026-10-02, Python 3.13 / ttkbootstrap 2.2.3):

| Scenario | Working set | Commit size |
|---|---|---|
| empty python process baseline | 18 MB | 11 MB |
| `import tkinter` | 21 MB | 12 MB |
| `import tkinter, ttkbootstrap` | **34 MB** (pulls in Pillow) | 23 MB |
| plus creating `ttb.Window()` | 52 MB | 32 MB |

In other words: **the themed UI's extra cost is almost entirely the ttkbootstrap library itself**.

> Windows only (relies on psapi / tasklist / taskkill).

## Quick start

```bat
:: 1. Install dependencies (websockets + ttkbootstrap for the themed UI)
python -m pip install -r requirements.txt
```

- **GUI (ttk)**: just **double-click `jusic_gui.py`** (it automatically relaunches under
  `pythonw` so no black console window appears). If double-clicking opens an editor instead of running it,
  right-click the file → "Open with" → "Choose another app" → select Python and check "Always use this app".
  You can also run:
  ```bat
  python jusic_gui.py --console     :: keep console output for debugging
  ```
- **CLI**: double-click `run.bat`, or run `python jusic_room_player.py`
- **Themed UI (ttkbootstrap)**: double-click `jusic_gui_bootstrap.pyw` (or
  `python jusic_gui_bootstrap.py`); themes can be switched from the top-right corner at any time:
  ```bat
  python jusic_gui_bootstrap.py --console                  :: keep console output
  python jusic_gui_bootstrap.py --theme dracula-dark       :: start with a specific theme
  ```

All three versions automatically join the default room "一起听歌吧(DEFAULT)" and follow whatever the room plays.

### Playback engine (mpv) setup

On first run it tries to install mpv via winget (`shinchiro.mpv`).
You can also install it manually and pass the path:

```bat
python jusic_room_player.py --mpv "C:\Program Files\MPV Player\mpv.exe"
```

mpv lookup order: `--mpv` argument → `JUSIC_MPV` environment variable → `mpv` on `PATH` → common install paths.

## Interactive usage (including room switching)

After startup, type commands into the input line:

| Input | Action |
|---|---|
| room number (e.g. `2`) | **Switch/join that room**; stops the previous room and plays the new room's current song |
| `l` | Refresh and re-list rooms (busier rooms first, 🔒 = password-protected) |
| `s keyword` | Search by room name/description, then list numbered rooms |
| `f` | Show all rooms |
| `m` | Show the currently playing song and the request queue |
| `p keyword` | **Search songs** (for requesting): lists the first 20 by current source, with album, duration and an "unavailable" mark |
| `pick N [flac]` | **Request a song**: add the N-th search result to the room queue (320k by default; add `flac`/`高清` for FLAC) |
| `pn` | Load more search results (next page, appended) |
| `ph` | Hot chart (equivalent to searching `*热歌榜`) |
| `src [source]` | View/switch the request source: `src`, `src QQ`, `src 2` (wy/qq/kw/kg/mg) |
| `que` | Show the full request queue (with numbers and like marks, used together with `like N`) |
| `like [N]` | **Like**: with a number = like the N-th queued song (alias `赞`); without = like the currently playing song. Liked rows are prefixed with `[已赞]` |
| `q` / `Ctrl+C` | Quit |

Request example: `p 晴天` → check the list → `pick 2 flac` (request the 2nd song in FLAC).
Room numbers and song numbers are different namespaces — always prefix song requests with `pick`.
Search is synchronous (waits up to ~12 seconds) and input is not accepted meanwhile.

When joining a password-protected room you will be prompted for the password; a wrong password is reported without
affecting the current room. After a disconnect it reconnects automatically with exponential backoff (up to 6 times by default).

### GUI (jusic_gui.py)

- The room list on the left is sorted by "online count"; **double-click** (or select and press Enter / click "Join selected room") to switch rooms; password-protected rooms prompt for a password;
- Type a keyword in the search box and click "Filter" to filter room names/descriptions live;
- The right side shows the current song, room and online count, a **volume slider (dragging takes effect immediately, no need to wait for the next track)**, a **lyric panel (LRC highlights the current line in sync with playback)**, the request queue and a live log;
- **Skip (vote)** button: sends `/music/skip/vote` to the room; regular members vote (skipping happens when votes pass the threshold) while admins skip directly;
- **Liking queued songs**: select a song in the queue and click "👍 点赞选中歌曲" below; liked rows show 👍 in a dedicated **"Like" column**,
  so you can see at a glance what you liked; the same song is only sent once per room (deduplicated) and the record is cleared on room change.
  **Note: this backend matches against the "request ownership table" and only accepts songs you requested yourself** — liking someone else's song triggers
  "点歌列表未发现此歌" from the server, in which case the UI **automatically retracts the 👍 mark** and explains why (it never shows a fake liked state);
  if the room enables "sort by likes", liking changes playback order (the queue refreshes automatically);
- **点歌… (Request…)** button: searches the real catalog by title/artist (sources: NetEase / QQ / Kuwo / Kugou / Migu, same as the web UI);
  the result list shows "song / artist · album / duration", **clicking a row selects it** (the whole row is highlighted — the themed UI follows the
  current theme's primary color, the classic UI uses bright blue — and a `▶` mark appears before the title), then click "点歌 · 标准" to add it to the queue,
  or "点歌 · 高清" to request it in FLAC; there are also "热歌榜" (hot chart) and "加载更多" (load more) buttons;
  tracks without a playable version are marked "unavailable"; if the room forbids guest requests, the server pushes a notice;
  **double-clicking a result row does not request it** (to avoid accidental requests; select and confirm with the button instead);
- **Chat input + send button** (Enter also works): sends text to the room chat; you can set a **nickname** first (the server default is used if empty);
- **下载▾ (Download) menu** saves the currently playing **song audio**, the **lyrics (.lrc)**, or **both** (lyrics are saved as a `.lrc` file next to the audio with the same name);
- **分享房间… (Share room…)** button: generates a **direct room link** identical to the web UI
  (`https://happy.alang.run/modern-ui?houseId=..&housePwd=..`), supporting **copy to clipboard**,
  **open in browser**, **save QR code PNG** (scan with a phone to join) and **save WeChat mini-program code**;
  QR codes are generated in pure Python (`jusic_qr.py`, no third-party library). For password-protected rooms the password is embedded in the link following the web UI's rules,
  so only share it with people you trust;
- **"显示聊天" (Show chat) is on by default** (☑️/☐ checkbox, toggleable in settings); the room list **auto-refreshes every 10 minutes** (silently, keeping the selection);
- **Minimize to system tray**: clicking minimize hides the window into a tray icon (playback continues in the background, no taskbar entry);
  **double-click** the tray icon to restore, **right-click** for a menu with "Show main window / Quit"
  (on Windows 11, if the icon is collapsed into the overflow area, click `^` at the bottom-right of the taskbar to see it — you can drag it out to pin it);
- Closing the window (✕) quits the program.

### Themed UI (jusic_gui_bootstrap.py)

The same feature set with a ttkbootstrap Bootstrap-style skin; the highlight is **free-form theming**:

- **Theme switching**: the "主题" dropdown in the top-right picks a style (bootstrap / catppuccin / dracula /
  everforest / gruvbox / minty / nord / one / pulse / pydata / sandstone /
  solarized / tokyo-night / united / vapor — 15 styles in total), and the "深色" switch next to it flips
  light/dark, giving **30 themes** in combination; "全部主题 ▾" expands the full list, which also offers
  "toggle light/dark" and "pick a random theme";
- **Shortcut**: `Ctrl+T` (or `F2`) toggles light/dark;
- **Settings are remembered**: theme and window size are stored in `%APPDATA%\JusicRoomPlayer\ui.json` and restored
  on next launch (delete the file to reset; `--theme` can override it temporarily);
- **Dark-mode adaptation**: lyric/log text, secondary text, and the text colors of the share/request/about dialogs all
  follow the theme, staying legible in dark mode too;
- **Playback progress bar**: the current-song area gains a progress bar with times (`elapsed / total`), driven by the same clock as the lyrics;
- **Layout**: the right side splits "lyrics / request queue / live log (including chat and nickname)" into three tabs,
  with a draggable splitter between the left and right panes;
- All other features (room list and search, skip vote, song requests, likes, downloads, share QR codes, system tray, …)
  are identical to `jusic_gui.py` — in code it is a subclass of `jusic_gui.JusicGui`, so there is
  **only one copy of the business logic** and the two UIs cannot drift apart.

Dependency: `ttkbootstrap` (`python -m pip install ttkbootstrap`, already in requirements.txt).

### Command-line arguments

`jusic_room_player.py`, `jusic_gui.py` and `jusic_gui_bootstrap.py` all support:

```text
--host domain        Jusic backend to use (default tx.alang.run; self-hosted instances supported)
--house room ID      join the given room right after startup
--password password  room password
--mpv path           absolute path to mpv.exe
--volume 0-100       playback volume (default 90)
```

`jusic_gui_bootstrap.py` (themed UI) additionally supports:

```text
--theme name         startup theme, e.g. dracula-dark / nord-light
                     (defaults to the last remembered theme; 30 available — see --theme help and the "All themes" menu)
```

`jusic_room_player.py` additionally supports:

```text
--chat               print the room chat stream in the console
--source source      default request source (wy/qq/kw/kg/mg, or 网易/QQ/酷我/酷狗/咪咕)
--auto-seconds N     exit automatically after N seconds (for scripts/self-tests)
```

Example — join a room, enable chat and lower the volume:

```bat
python jusic_room_player.py --house 73DlCti8 --chat --volume 60
```

## Building a Windows release (bundles mpv, versioned automatically)

Use PyInstaller to pack the GUI **together with mpv** into an exe, so target machines need neither Python nor mpv.
**Artifacts are versioned automatically**: just edit the `VERSION` file in the repository root (e.g. `1.0.1`);
the version then appears in the artifact filename and the exe properties (file/product version).

**Single-file build** (easy to distribute as one file; slightly slower first launch):

```bat
build_exe.bat
```

Artifact: `dist\JusicRoomPlayer <version>.exe` (~62 MB).

**Portable ZIP** (no installation, fast startup, no per-launch extraction; the artifact is the ZIP itself):

```bat
build_exe_dir.bat
```

Artifact: `dist\JusicRoomPlayerPortable_<version>.zip` (~62 MB compressed, containing
`_internal\_engine\mpv\mpv.exe`). After extraction the top level is the version folder; run
`JusicRoomPlayerPortable_<version>.exe` inside it. Intermediate folders are cleaned up automatically after packaging.

Both builds share these traits:

- The bundled mpv is discovered and used automatically; you can also switch to an external mpv via "选mpv…" at the bottom-right of the UI;
- On a crash, `JusicRoomPlayer-error.log` is written next to the exe;
- Just hand it to other Windows users (if antivirus flags it, whitelist it or sign the exe).

## How it works (talking to the Jusic backend)

1. `POST /api/house/search`: anonymously fetch the room list (name/online count/password-protected flag);
2. Open a WSS connection: `/api/server/000/<session>/websocket?houseId=..&housePwd=..`;
3. The backend pushes "STOMP-like" frames over SockJS: `MUSIC` (current song, including the real playback `url`, lyrics and cover),
   `PICK` (request queue), `ONLINE` (online count), `CHAT`, announcements, etc.;
4. On `MUSIC`, the `url` is handed to mpv; when the server switches songs it pushes a new `MUSIC` and the client follows,
   staying perfectly in sync with the web UI;
5. Song requests: `SEND /music/search {name,source,pageIndex,pageSize}` searches the catalog and the server replies with a `SEARCH` frame
   (`data.data` = song array, `data.totalSize` = total); `SEND /music/pick {name,id,source,quality}`
   requests a song (`quality` is `320k` or `flac`); on success the server pushes the `NOTICE` "点歌成功" and broadcasts the new `PICK` queue;
6. Likes: `SEND /music/good/<songId>` with body `{}`. Measured behavior: this backend matches against the "request ownership table" and **only accepts songs you requested yourself** —
   someone else's song immediately returns `NOTICE` "点歌列表未发现此歌", while your own song is accepted silently (if the room enables "sort by likes" it affects playback order).
   Like counts are not pushed to clients (the `MUSIC` frame has no counter field), so the client only sends, deduplicates, and displays server messages verbatim.

## Directory structure

```text
local-music-player/
├─ jusic_core.py          # shared core: REST/WSS session, event-based RoomClient, mpv engine (no UI)
├─ jusic_room_player.py   # command-line frontend (reuses jusic_core)
├─ jusic_gui.py           # ttk/Tkinter GUI frontend (reuses jusic_core)
├─ jusic_gui.pyw          # console-free double-click launcher (only calls jusic_gui, avoiding two drifting UI copies)
├─ jusic_gui_bootstrap.py     # ttkbootstrap multi-theme UI (business logic inherits jusic_gui.JusicGui)
├─ jusic_gui_bootstrap.pyw    # console-free double-click launcher for the themed UI
├─ jusic_tray.py          # system tray (Windows; pure ctypes into Win32; minimize-to-tray)
├─ jusic_qr.py            # pure-Python QR code generator (for room sharing; zero third-party dependencies)
├─ requirements.txt       # dependencies: websockets (+ ttkbootstrap for the themed UI)
├─ run.bat                # one-click launcher for the CLI
├─ run_gui.bat            # alternative launcher for the GUI (with console output)
├─ VERSION               # version source (e.g. 1.0.0); used automatically in artifact names/properties
├─ make_version_file.py  # generates the exe version resource from VERSION (build helper)
├─ make_zip.py           # zips the portable directory into a matching versioned ZIP (build helper)
├─ publish_release.py    # publishes dist artifacts to GitHub / Gitee Releases (writes SHA256 and changelog)
├─ tools\
│  └─ mem_bench.py       # memory benchmark (compares real usage of each frontend; Windows only)
├─ build_exe.bat          # build the single-file exe (bundles mpv, versioned) → dist\JusicRoomPlayer <version>.exe
├─ build_exe_dir.bat      # build the portable ZIP (bundles mpv, versioned) → dist\JusicRoomPlayerPortable_<version>.zip
├─ dist\JusicRoomPlayer <version>.exe         # single-file release (~62MB)
├─ dist\JusicRoomPlayerPortable_<version>.zip # portable release ZIP (~62MB)
├─ README.md
└─ README_EN.md
```

## License

This project is licensed under **GPL-3.0**; see [LICENSE](LICENSE) for the full text.
Licenses and acknowledgements for third-party components are in [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

## Acknowledgements and compliance notes

- Room protocol/data format reference: [Jusic-Serve-Houses](https://github.com/JumpAlang/Jusic-Serve-Houses) (**GPL-3.0**)
- Playback engine: [mpv](https://github.com/mpv-player/mpv) (LGPL-2.1+ / ISC)
- Realtime library: [websockets](https://github.com/python-websockets/websockets) (BSD-3)

Please use this tool only for personal learning and lawful listening; all song copyrights belong to their respective
owners — follow the terms of service and copyright rules of the target website/service. The default backend is a public
demo instance; for long-term use, self-host the backend (`docker-compose up -d`) and point `--host` at your own domain.
