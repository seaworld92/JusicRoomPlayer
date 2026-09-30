#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
Jusic 房间播放器 · 图形界面版 (ttk/tkinter)
==============================================
复用 jusic_core.RoomClient，零额外依赖（websockets 除外）。

双击运行: 直接双击 jusic_gui.py（或 jusic_gui.pyw）即可打开界面；
          为免弹黑色控制台，程序会自动改用 pythonw 无窗口方式运行。
命令行:
    python jusic_gui.py --console        # 保留控制台（调试时用）
    python jusic_gui.py --host 你的域名  # 对接自建 Jusic-Serve-Houses
    python jusic_gui.py --mpv mpv路径    # 手动指定 mpv

操作:
    * 左侧双击房间 / 选中后回车或点「进入房间」即可切换房间（密码房会询问密码）
    * 搜索框支持按房间名/简介过滤
    * 下方日志区显示连接/切歌/公告等动态；勾选“显示聊天”可看房间聊天流
    * 音量滑块即时生效（拖动过程中声音实时变化，无需等下一首）
    * 点「点歌…」可按歌名/歌手搜索各音源曲库并加入房间队列（标准 320k / 高清 FLAC）
    * 点「分享房间…」可复制/打开直达链接，并生成二维码（手机扫码进房）
    * 最小化窗口时自动隐藏到系统托盘（后台继续播放）；双击托盘图标恢复窗口，
      右键托盘图标弹出菜单可“显示主界面 / 退出程序”；关闭窗口即退出
"""

import argparse
import base64
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

# ---- 双击/打包(冻结)启动支持 ----
# 普通运行时 BASE_DIR=脚本目录；PyInstaller 单文件 exe 运行时 BASE_DIR=解包临时目录(sys._MEIPASS)
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = BASE_DIR
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
if not getattr(sys, "frozen", False):
    try:
        os.chdir(SCRIPT_DIR)          # 冻结时不解压目录改工作目录
    except OSError:
        pass


def bundled_mpv_path() -> str:
    """PyInstaller 打包进 exe 的内置 mpv（映射到 _engine/mpv/mpv.exe）。"""
    path = os.path.join(BASE_DIR, "_engine", "mpv", "mpv.exe")
    return path if os.path.isfile(path) else ""


def _fatal_error(msg: str) -> None:
    """无控制台环境（双击 / pythonw）也能让用户看到致命错误。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "Jusic 房间播放器", 0x10)  # MB_ICONERROR
    except Exception:
        try:
            print(msg, file=sys.stderr)
        except Exception:
            pass
    sys.exit(1)


try:
    import websockets  # noqa: F401
    import jusic_qr                          # 纯 Python 二维码（分享房间用）
    from jusic_core import (DEFAULT_HOST, MUSIC_API, SONG_SOURCE_CODES, UI_URL,
                            RoomClient, MpvEngine, DownloadCancelled,
                            download_file, get_mini_code, guess_audio_ext,
                            human_seconds, lyric_index, parse_lyrics,
                            room_share_url, sanitize_filename, song_album,
                            song_unavailable, sort_rooms, source_code)
    try:
        from jusic_tray import TrayIcon      # 纯 ctypes 托盘（Windows）
    except Exception:                        # 缺失/不支持时退化为普通最小化
        TrayIcon = None
except (ImportError, SystemExit) as exc:
    _fatal_error("缺少运行依赖，请先执行：\n\n"
                 "    python -m pip install -r requirements.txt\n\n"
                 f"详细信息：{exc}")

FONT = "Microsoft YaHei UI"


class JusicGui:
    def __init__(self, root: tk.Tk, args):
        self.root = root
        self.args = args
        self.rooms = []
        self._room_by_iid = {}
        self._auto_entered = False
        self._lyrics = []            # [(start_ms, text), ...]
        self._lyric_t0 = 0.0         # 本曲本地起播时刻（time.monotonic）
        self._lyric_idx = -1
        self._lyric_after = None
        self._current_music = None   # 最近一次 MUSIC（用于下载）
        self._downloading = False    # 是否有下载任务进行中
        self._pending_reselect = None  # 刷新房间列表后要恢复选中的房间 id

        # 跨线程事件桥
        self.evq = queue.Queue()

        # 系统托盘：最小化时驻留托盘、后台继续播放
        self._tray = None
        self._in_tray = False

        # 点歌面板（打开时才创建）与搜索结果上下文
        self._pick_win = None
        self._pick_state = None
        self._pick_songs = {}

        # 未显式指定 mpv 时，优先使用打进 exe 的内置 mpv
        mpv_path = args.mpv or bundled_mpv_path()
        self.client = RoomClient(host=args.host, volume=args.volume,
                                 mpv_path=mpv_path, listener=self._on_core_event)

        self._build_ui()
        self._init_tray()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ===================================================================== #
    # UI 搭建
    # ===================================================================== #
    def _build_ui(self):
        root = self.root
        self._version = self._app_version()
        root.title(f"Jusic 房间播放器 v{self._version}（低内存 · mpv 内核）")
        root.geometry("1000x720")
        root.minsize(860, 560)
        # 最小化 → 隐藏到系统托盘（见 _on_unmap）
        root.bind("<Unmap>", self._on_unmap)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # ---- 总布局 ---- #
        outer = ttk.Frame(root, padding=6)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")
        outer.rowconfigure(1, weight=0)
        outer.columnconfigure(1, weight=0)

        # ---- 左：房间列表 ---- #
        left = ttk.Frame(paned, padding=4)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="房间列表（双击进入）",
                  font=(FONT, 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))

        search_row = ttk.Frame(left)
        search_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        search_row.columnconfigure(0, weight=1)
        self.kw_var = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.kw_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(search_row, text="过滤", command=self._apply_filter).grid(row=0, column=1, padx=(4, 0))
        ttk.Button(search_row, text="刷新", command=self._refresh).grid(row=0, column=2, padx=(4, 0))

        tree_frame = ttk.Frame(left)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        cols = ("name", "pop", "lock", "desc")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=16)
        self.tree.heading("name", text="房间")
        self.tree.heading("pop", text="在线")
        self.tree.heading("lock", text="锁")
        self.tree.heading("desc", text="简介")
        self.tree.column("name", width=210, anchor="w")
        self.tree.column("pop", width=52, anchor="center")
        self.tree.column("lock", width=40, anchor="center")
        self.tree.column("desc", width=180, anchor="w")
        vs = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<Double-1>", lambda e: self._enter_selected())
        self.tree.bind("<Return>", lambda e: self._enter_selected())

        btn_row = ttk.Frame(left)
        btn_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        btn_row.columnconfigure(0, weight=1)
        ttk.Button(btn_row, text="进入选中房间", command=self._enter_selected).grid(row=0, column=0, sticky="ew")
        ttk.Button(btn_row, text="离开房间", command=self._leave).grid(row=0, column=1, padx=(6, 0))

        # ---- 右：播放信息 + 队列 + 日志 ---- #
        right = ttk.Frame(paned, padding=4)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=2)     # 歌词区（可伸缩）
        right.rowconfigure(4, weight=1)     # 日志区

        info = ttk.Labelframe(right, text="当前播放", padding=6)
        info.grid(row=0, column=0, sticky="ew")
        info.columnconfigure(1, weight=1)
        self.track_var = tk.StringVar(value="—")
        ttk.Label(info, textvariable=self.track_var, font=(FONT, 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.sub_var = tk.StringVar(value="等待房间歌曲推送…")
        ttk.Label(info, textvariable=self.sub_var, foreground="#555").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.room_var = tk.StringVar(value="未进入房间")
        self.online_var = tk.StringVar(value="—")
        ttk.Label(info, textvariable=self.room_var, foreground="#0a6").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(info, textvariable=self.online_var, foreground="#06a").grid(row=2, column=1, sticky="e", pady=(4, 0))
        act = ttk.Frame(info)
        act.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        act.columnconfigure(2, weight=1)
        ttk.Button(act, text="切歌（投票）",
                   command=self._skip_vote).grid(row=0, column=0, sticky="w")
        ttk.Button(act, text="点歌…",
                   command=self._open_pick_dialog).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Button(act, text="分享房间…",
                   command=self._share_room).grid(row=0, column=2, sticky="e")
        ttk.Label(act, text="普通成员投票，票数达标自动切歌",
                  foreground="#888", font=(FONT, 8)).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        vol_row = ttk.Frame(right)
        vol_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        vol_row.columnconfigure(1, weight=1)
        ttk.Label(vol_row, text="音量").grid(row=0, column=0, sticky="w")
        self.vol_var = tk.DoubleVar(value=self.args.volume)
        ttk.Scale(vol_row, from_=0, to=100, variable=self.vol_var,
                  command=lambda v: self.client.set_volume(int(float(v)))).grid(
            row=0, column=1, sticky="ew", padx=6)
        self.vol_label = ttk.Label(vol_row, text=f"{int(self.args.volume)}%", width=6)
        self.vol_label.grid(row=0, column=2, sticky="e")
        self.vol_var.trace_add("write", lambda *_: self.vol_label.config(text=f"{int(self.vol_var.get())}%"))
        ttk.Button(vol_row, text="选mpv…", width=8,
                   command=self._pick_mpv).grid(row=0, column=3, padx=(6, 0))
        dl_btn = ttk.Menubutton(vol_row, text="下载▾", width=8)
        dl_menu = tk.Menu(dl_btn, tearoff=0)
        dl_menu.add_command(label="下载当前歌曲（音频）", command=self._download_song)
        dl_menu.add_command(label="下载当前歌词（.lrc）", command=self._download_lyrics)
        dl_menu.add_command(label="下载歌曲 + 歌词（一起）", command=self._download_both)
        dl_btn["menu"] = dl_menu
        dl_btn.grid(row=0, column=4, padx=(6, 0))

        # 歌词（LRC，随播放时间同步高亮当前句）
        lyrf = ttk.Labelframe(right, text="歌词", padding=4)
        lyrf.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        lyrf.rowconfigure(0, weight=1)
        lyrf.columnconfigure(0, weight=1)
        self.lyr = tk.Text(lyrf, height=7, state="disabled", wrap="word",
                           font=(FONT, 10), foreground="#666",
                           highlightthickness=0, borderwidth=0)
        self.lyr.tag_configure("cur", foreground="#d01818", font=(FONT, 11, "bold"))
        self.lyr.tag_configure("next", foreground="#333")
        self.lyr.tag_configure("muted", foreground="#999")
        lyvs = ttk.Scrollbar(lyrf, orient="vertical", command=self.lyr.yview)
        self.lyr.configure(yscrollcommand=lyvs.set)
        self.lyr.grid(row=0, column=0, sticky="nsew")
        lyvs.grid(row=0, column=1, sticky="ns")
        self._lyric_hint("等待歌曲…")

        # 队列
        qf = ttk.Labelframe(right, text="点歌队列", padding=4)
        qf.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        qf.rowconfigure(0, weight=1)
        qf.columnconfigure(0, weight=1)
        qcols = ("n", "d")
        self.queue_tree = ttk.Treeview(qf, columns=qcols, show="headings", height=6)
        self.queue_tree.heading("n", text="歌曲")
        self.queue_tree.heading("d", text="时长/点歌人")
        self.queue_tree.column("n", width=230, anchor="w")
        self.queue_tree.column("d", width=180, anchor="w")
        qvs = ttk.Scrollbar(qf, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=qvs.set)
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        qvs.grid(row=0, column=1, sticky="ns")

        # 日志
        lf = ttk.Labelframe(right, text="动态/日志", padding=4)
        lf.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
        lf.rowconfigure(0, weight=1)
        lf.columnconfigure(0, weight=1)
        self.log = tk.Text(lf, height=8, state="disabled", wrap="word",
                           font=(FONT, 9), foreground="#333")
        self.log.tag_configure("music", foreground="#b00")
        self.log.tag_configure("warn", foreground="#a60")
        self.log.tag_configure("good", foreground="#0a6")
        self.log.tag_configure("muted", foreground="#777")
        ls = ttk.Scrollbar(lf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=ls.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        ls.grid(row=0, column=1, sticky="ns")
        # “显示聊天”：默认开启；用 ☑️/☐ 文本样式（避免主题默认的打叉样式）
        self.chat_var = tk.BooleanVar(value=True)
        self.chat_btn = tk.Checkbutton(right, text="", variable=self.chat_var,
                                       indicatoron=False, relief="flat", anchor="w",
                                       cursor="hand2", font=(FONT, 9),
                                       bg=self.root.cget("bg"),
                                       activebackground=self.root.cget("bg"),
                                       selectcolor=self.root.cget("bg"),
                                       highlightthickness=0, borderwidth=0)
        self.chat_btn.grid(row=5, column=0, sticky="w", pady=(4, 0))
        self.chat_var.trace_add("write", lambda *_: self._sync_chat_text())
        self._sync_chat_text()

        # 聊天输入行（回车或点“发送”）
        chat_row = ttk.Frame(right)
        chat_row.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        chat_row.columnconfigure(0, weight=1)
        self.chat_input = ttk.Entry(chat_row, font=(FONT, 9))
        self.chat_input.grid(row=0, column=0, sticky="ew")
        self.chat_input.bind("<Return>", lambda e: self._send_chat())
        ttk.Button(chat_row, text="发送", width=6,
                   command=self._send_chat).grid(row=0, column=1, padx=(4, 0))

        # 昵称设置行（连接后自动应用；留空则用服务端默认昵称）
        nick_row = ttk.Frame(right)
        nick_row.grid(row=7, column=0, sticky="ew", pady=(4, 2))
        nick_row.columnconfigure(1, weight=1)
        ttk.Label(nick_row, text="昵称").grid(row=0, column=0, sticky="w")
        self.nick_var = tk.StringVar(value="")
        nick_entry = ttk.Entry(nick_row, textvariable=self.nick_var)
        nick_entry.grid(row=0, column=1, sticky="ew", padx=(4, 4))
        nick_entry.bind("<Return>", lambda e: self._apply_nickname())
        ttk.Button(nick_row, text="设置", width=6,
                   command=self._apply_nickname).grid(row=0, column=2)

        paned.add(left, weight=3)
        paned.add(right, weight=2)

        # 状态栏
        status = ttk.Frame(outer, padding=(2, 4))
        status.grid(row=1, column=0, sticky="ew")
        self.status_var = tk.StringVar(value=f"后端 https://{self.args.host}{MUSIC_API} ｜ 未连接")
        ttk.Label(status, textvariable=self.status_var, foreground="#555").pack(side="left")
        self.mpv_var = tk.StringVar(value="mpv: …")
        ttk.Label(status, textvariable=self.mpv_var, foreground="#888").pack(side="right")
        # 角落：版本号 + 开源协议与致谢入口（点击查看详情）
        about_label = tk.Label(status, text=f"ℹ 关于 · v{self._version} · GPL-3.0",
                               fg="#0a66c2", cursor="hand2",
                               font=(FONT, 8), bg=self.root.cget("bg"))
        about_label.pack(side="right", padx=(8, 2))
        about_label.bind("<Button-1>", lambda e: self._show_about())

        # 每 10 分钟自动刷新一次房间列表（静默，不打断操作/不刷屏）
        self.root.after(10 * 60 * 1000, self._auto_refresh)

    def _sync_chat_text(self):
        """把“显示聊天”复选框渲染成 ☑️/☐ 文本，并同步是否接收聊天事件。"""
        on = bool(self.chat_var.get())
        self.client.show_chat = on
        try:
            self.chat_btn.configure(text=("☑️ 显示聊天" if on else "☐ 显示聊天"),
                                    fg=("#0a6" if on else "#666"))
        except Exception:
            pass

    def _auto_refresh(self):
        """定时静默刷新房间列表，并尽量保留当前选中项。"""
        try:
            sel = self._selected_room()
            self._pending_reselect = str(sel.get("id")) if sel else None
            self.client.refresh_rooms(silent=True)
        except Exception:
            pass
        finally:
            try:
                self.root.after(10 * 60 * 1000, self._auto_refresh)
            except Exception:
                pass

    # ===================================================================== #
    # 动作
    # ===================================================================== #
    def _refresh(self):
        sel = self._selected_room()
        self._pending_reselect = str(sel.get("id")) if sel else None
        self._log("正在获取房间列表…", "muted")
        self.client.refresh_rooms()

    def _apply_filter(self):
        kw = self.kw_var.get().strip().lower()
        self._populate(self.rooms, kw)

    def _populate(self, rooms, keyword: str = ""):
        rows = sort_rooms(rooms)
        if keyword:
            rows = [r for r in rows
                    if keyword in str(r.get("name") or "").lower()
                    or keyword in str(r.get("desc") or "").lower()]
        self._room_by_iid.clear()
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            iid = str(i)
            self._room_by_iid[iid] = r
            lock = "🔒" if r.get("needPwd") else ""
            self.tree.insert("", "end", iid=iid, values=(
                str(r.get("name") or "")[:22],
                r.get("population") or 0,
                lock,
                str(r.get("desc") or "")[:24],
            ))

    def _selected_room(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._room_by_iid.get(sel[0])

    def _enter_selected(self):
        room = self._selected_room()
        if not room:
            self._log("请先在左侧选择一个房间", "warn")
            return
        name = room.get("name") or room.get("id")
        if self.client.room and str(self.client.room.get("id")) == str(room.get("id")):
            self._log(f"已在该房间：{name}", "good")
            return
        pwd = ""
        if room.get("needPwd"):
            pwd = simpledialog.askstring("房间密码", f"房间「{name}」需要密码：",
                                         show="*", parent=self.root) or ""
        self.client.enter_room(str(room.get("id")), pwd)
        self._log(f"正在切换房间：{name} …", "muted")

    def _leave(self):
        self.client.leave_room()
        self._log("已离开房间", "muted")

    def _skip_vote(self):
        """切歌：普通成员为投票切歌（票数达标自动切），管理员直接切歌。"""
        if not self.client.connected:
            self._log("尚未连接房间，无法切歌", "warn")
            return
        self.client.skip_vote()
        self._log("已发送切歌请求（投票切歌）…", "muted")

    def _send_chat(self):
        """把输入框内容发送到房间聊天（服务端会广播回显到日志区）。"""
        text = self.chat_input.get().strip()
        if not text:
            return
        if not self.client.connected:
            self._log("尚未连接房间，无法发送聊天", "warn")
            return
        if self.client.send_chat(text):
            self.chat_input.delete(0, "end")
        else:
            self._log("消息为空，未发送", "warn")

    def _apply_nickname(self):
        """设置房间内昵称（留空则使用服务端默认昵称）。"""
        name = self.nick_var.get().strip()
        if not name:
            self._log("请输入昵称（留空则使用服务端默认昵称）", "warn")
            return
        if not self.client.connected:
            self._log("尚未连接房间，无法设置昵称", "warn")
            return
        self.client.set_nickname(name)
        self._log(f"已发送昵称设置：{name}", "muted")

    # ---------------- 点歌（搜索曲库 / 加入队列） ---------------- #
    def _open_pick_dialog(self):
        """打开点歌面板：搜索各音源曲库，选中后加入房间点歌队列。"""
        if not self.client.connected:
            self._log("尚未连接房间，无法点歌", "warn")
            messagebox.showinfo("还未连接房间",
                                "请先进入一个房间，再使用点歌功能。", parent=self.root)
            return
        win = getattr(self, "_pick_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            return

        win = tk.Toplevel(self.root)
        self._pick_win = win
        win.title("点歌")
        win.transient(self.root)
        win.minsize(560, 400)
        win.geometry("660x480")
        try:
            self.root.update_idletasks()
            win.geometry(f"+{self.root.winfo_rootx() + 140}+{self.root.winfo_rooty() + 80}")
        except Exception:
            pass
        win.protocol("WM_DELETE_WINDOW", self._close_pick_dialog)
        win.bind("<Escape>", lambda e: self._close_pick_dialog())

        # 搜索结果上下文（关闭面板时清空）
        self._pick_songs = {}          # 行 iid -> 歌曲 dict
        self._pick_state = {"keyword": "", "page": 0, "songs": [], "total": 0,
                            "loading": False, "token": 0}

        body = ttk.Frame(win, padding=8)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        # 搜索行：关键词 + 音源 + 搜索 / 热歌榜
        search_row = ttk.Frame(body)
        search_row.grid(row=0, column=0, sticky="ew")
        search_row.columnconfigure(0, weight=1)
        self._pick_kw_var = tk.StringVar()
        kw_entry = ttk.Entry(search_row, textvariable=self._pick_kw_var)
        kw_entry.grid(row=0, column=0, sticky="ew")
        kw_entry.bind("<Return>", lambda e: self._pick_search(reset=True))
        self._pick_src_var = tk.StringVar(value="网易")
        ttk.Combobox(search_row, textvariable=self._pick_src_var, width=6,
                     state="readonly", values=list(SONG_SOURCE_CODES)).grid(
            row=0, column=1, padx=(6, 0))
        self._pick_search_btn = ttk.Button(search_row, text="搜索",
                                           command=lambda: self._pick_search(reset=True))
        self._pick_search_btn.grid(row=0, column=2, padx=(6, 0))
        ttk.Button(search_row, text="热歌榜",
                   command=self._pick_hot).grid(row=0, column=3, padx=(4, 0))

        self._pick_status_var = tk.StringVar(
            value="输入歌名/歌手后点「搜索」；也可以点「热歌榜」看看热门金曲")
        ttk.Label(body, textvariable=self._pick_status_var,
                  foreground="#555").grid(row=1, column=0, sticky="w", pady=(6, 4))

        # 结果列表
        tree_box = ttk.Frame(body)
        tree_box.grid(row=2, column=0, sticky="nsew")
        tree_box.rowconfigure(0, weight=1)
        tree_box.columnconfigure(0, weight=1)
        cols = ("n", "a", "d")
        self._pick_tree = ttk.Treeview(tree_box, columns=cols, show="headings", height=12)
        self._pick_tree.heading("n", text="歌曲")
        self._pick_tree.heading("a", text="歌手 · 专辑")
        self._pick_tree.heading("d", text="时长")
        self._pick_tree.column("n", width=250, anchor="w")
        self._pick_tree.column("a", width=270, anchor="w")
        self._pick_tree.column("d", width=70, anchor="center")
        vs = ttk.Scrollbar(tree_box, orient="vertical", command=self._pick_tree.yview)
        self._pick_tree.configure(yscrollcommand=vs.set)
        self._pick_tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        self._pick_tree.bind("<Double-1>", lambda e: self._pick_send("320k"))
        self._pick_tree.bind("<Return>", lambda e: self._pick_send("320k"))

        # 操作行
        btns = ttk.Frame(body)
        btns.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        btns.columnconfigure(3, weight=1)
        ttk.Button(btns, text="点歌 · 标准",
                   command=lambda: self._pick_send("320k")).grid(row=0, column=0, sticky="w")
        ttk.Button(btns, text="点歌 · 高清",
                   command=lambda: self._pick_send("flac")).grid(row=0, column=1, padx=(6, 0))
        self._pick_more_btn = ttk.Button(btns, text="加载更多", state="disabled",
                                         command=lambda: self._pick_search(reset=False))
        self._pick_more_btn.grid(row=0, column=2, padx=(6, 0))
        ttk.Button(btns, text="关闭", width=8,
                   command=self._close_pick_dialog).grid(row=0, column=4, sticky="e")

        ttk.Label(body, text="双击结果 = 标准点歌；「高清」为 FLAC 音质。"
                             "若房间禁止访客点歌，服务端会推送通知说明。",
                  foreground="#888", font=(FONT, 8)).grid(row=4, column=0, sticky="w", pady=(6, 0))
        kw_entry.focus_set()

    def _close_pick_dialog(self):
        win, self._pick_win = getattr(self, "_pick_win", None), None
        self._pick_state = None
        self._pick_songs = {}
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def _pick_source(self):
        try:
            return source_code(self._pick_src_var.get())
        except Exception:
            return "wy"

    def _pick_search(self, reset=True, keyword=None):
        """发起搜索；reset=False 表示「加载更多」（页码 +1 并追加结果）。"""
        st = getattr(self, "_pick_state", None)
        if st is None or not self.client.connected:
            return
        if reset:
            kw = (self._pick_kw_var.get() if keyword is None else keyword).strip()
            if not kw:
                self._pick_status_var.set("请输入歌名、歌手或关键词")
                return
            self._pick_kw_var.set(kw)
            st.update({"keyword": kw, "page": 0, "songs": [], "total": 0})
        page = st["page"] + 1
        st["page"] = page
        st["loading"] = True
        st["token"] += 1
        token = st["token"]
        if not self.client.search_songs(st["keyword"], self._pick_source(), page):
            st["loading"] = False
            self._pick_status_var.set("搜索关键词为空")
            return
        self._pick_status_var.set(f"正在搜索「{st['keyword']}」（{st['page']}/{self._pick_source()}）…")
        self._pick_more_btn.configure(state="disabled")
        if reset:
            self._render_pick_rows(keep_scroll=False)
        self.root.after(8000, lambda: self._pick_timeout(token))

    def _pick_hot(self):
        """热歌榜：与网页端「热歌」面板一致，用 *热歌榜 作为关键词。"""
        self._pick_search(reset=True, keyword="*热歌榜")

    def _pick_timeout(self, token):
        st = getattr(self, "_pick_state", None)
        if not st or st.get("token") != token or not st.get("loading"):
            return
        st["loading"] = False
        self._pick_status_var.set("搜索响应超时：请重试或换个音源")

    def _on_search_result(self, data):
        """核心层 "search" 事件：把结果渲染进点歌面板。"""
        st = getattr(self, "_pick_state", None)
        win = getattr(self, "_pick_win", None)
        if st is None or win is None or not win.winfo_exists():
            return
        songs = list(data.get("songs") or [])
        st["loading"] = False
        st["token"] += 1                     # 让未触发的超时回调失效
        if st["page"] <= 1:
            st["songs"] = songs
        else:
            st["songs"].extend(songs)
        st["total"] = int(data.get("total") or len(st["songs"]))
        self._render_pick_rows()
        if not st["songs"]:
            self._pick_status_var.set(f"没有找到「{st['keyword']}」，换个关键词或音源试试")
        else:
            self._pick_status_var.set(f"共 {st['total']} 首，已显示 {len(st['songs'])} 首"
                                      f"（音源 {self._pick_src_var.get()}）")

    @staticmethod
    def _song_unavailable(song) -> bool:
        """搜索结果是否不可播（复用核心库判断，命令行版同源）。"""
        return song_unavailable(song)

    @staticmethod
    def _album_label(album) -> str:
        """专辑名：实测后端给的是对象 {"name": ...}，也兼容字符串。"""
        return song_album({"album": album})

    def _render_pick_rows(self, keep_scroll=True):
        st = getattr(self, "_pick_state", None)
        if st is None:
            return
        pos = self._pick_tree.yview()[0] if keep_scroll else 0.0
        self._pick_tree.delete(*self._pick_tree.get_children())
        self._pick_songs.clear()
        for i, song in enumerate(st["songs"]):
            iid = str(i)
            self._pick_songs[iid] = song
            artist = str(song.get("artist") or "未知歌手")
            album = self._album_label(song.get("album"))
            meta = f"{artist} · {album}" if album else artist
            if self._song_unavailable(song):
                meta = "[不可用] " + meta
            self._pick_tree.insert("", "end", iid=iid, values=(
                str(song.get("name") or "未知歌曲")[:34],
                meta[:44],
                human_seconds(song.get("duration")),
            ))
        if st["songs"]:
            self._pick_tree.yview_moveto(pos)
        more = len(st["songs"]) < st["total"]
        self._pick_more_btn.configure(state=("normal" if more else "disabled"))

    def _pick_send(self, quality: str = "320k"):
        """把选中歌曲加入房间点歌队列（quality: 320k 标准 / flac 高清）。"""
        sel = self._pick_tree.selection()
        if not sel:
            self._pick_status_var.set("请先在列表中选择一首歌")
            return
        song = self._pick_songs.get(sel[0])
        if not song:
            return
        if self._song_unavailable(song):
            self._pick_status_var.set("这首在当前音源不可用，换一首试试")
            return
        if not self.client.connected:
            self._pick_status_var.set("尚未连接房间，无法点歌")
            return
        label = "高清(FLAC)" if quality == "flac" else "标准(320k)"
        name = str(song.get("name") or "")
        artist = str(song.get("artist") or "")
        ok = self.client.pick_song(song.get("id"), name,
                                   song.get("source") or self._pick_source(), quality)
        if ok:
            self._log(f"点歌（{label}）：{name} - {artist}", "good")
            self._pick_status_var.set(f"已发送点歌请求（{label}）：{name} - {artist}")
        else:
            self._pick_status_var.set("点歌失败：歌曲 id 无效")

    # ---------------- 分享房间（链接 / 二维码 / 小程序码） ---------------- #
    def _share_room(self):
        """生成当前房间的分享链接与二维码（与网页端「分享房间」等价）。"""
        room = self.client.room
        if not room:
            self._log("尚未进入房间，无法分享", "warn")
            messagebox.showinfo("还未进入房间",
                                "请先进入一个房间，再使用分享功能。", parent=self.root)
            return
        url = room_share_url(room.get("id"), room.get("password") or "")
        self._open_share_dialog(room, url)

    def _open_share_dialog(self, room, url):
        name = room.get("name") or room.get("id")
        win = tk.Toplevel(self.root)
        win.title("分享房间")
        win.transient(self.root)
        win.resizable(False, False)
        try:
            win.grab_set()
        except Exception:
            pass
        try:                                    # 就近于主窗口显示，避免贴着屏幕边缘
            self.root.update_idletasks()
            win.geometry(f"+{self.root.winfo_rootx() + 90}+{self.root.winfo_rooty() + 70}")
        except Exception:
            pass

        body = ttk.Frame(win, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"分享房间：{name}", font=(FONT, 12, "bold")).pack(anchor="w")
        tip = ("朋友用浏览器打开链接即可直达本房间；密码已写入链接，"
               "请只分享给可信的朋友。" if room.get("password") else
               "朋友用浏览器打开链接即可直达本房间，一起实时听歌。")
        ttk.Label(body, text=tip, foreground="#666", justify="left",
                  wraplength=420).pack(anchor="w", pady=(2, 8))

        link_row = ttk.Frame(body)
        link_row.pack(fill="x")
        link_row.columnconfigure(0, weight=1)
        link = ttk.Entry(link_row, state="readonly", width=48)
        link.grid(row=0, column=0, sticky="ew")
        link.configure(state="normal")          # 直接写入文本，避免变量被回收后丢失
        link.insert(0, url)
        link.configure(state="readonly")
        try:
            link.selection_range(0, "end")      # 便于直接 Ctrl+C
        except Exception:
            pass

        # 二维码（与网页端一致：静区 4 个模块，用 Canvas 直接绘制，无需图片库）
        matrix = None
        qr_box = ttk.Labelframe(body, text="扫码进房（手机相机 / 微信扫一扫）", padding=6)
        try:
            matrix = jusic_qr.encode(url)
            self._draw_qr(qr_box, matrix)
            qr_box.pack(pady=(10, 0))
        except Exception as exc:
            ttk.Label(qr_box, text=f"二维码生成失败：{exc}",
                      foreground="#a60", wraplength=320).pack()
            qr_box.pack(pady=(10, 0))

        row1 = ttk.Frame(body)
        row1.pack(fill="x", pady=(10, 0))
        for col in range(3):
            row1.columnconfigure(col, weight=1)
        ttk.Button(row1, text="复制链接",
                   command=lambda: self._copy_share_link(url, win)).grid(
            row=0, column=0, sticky="ew")
        ttk.Button(row1, text="浏览器打开",
                   command=lambda: self._open_share_link(url)).grid(
            row=0, column=1, sticky="ew", padx=4)
        ttk.Button(row1, text="保存二维码",
                   command=lambda: self._save_qr_png(matrix, name, win)).grid(
            row=0, column=2, sticky="ew")

        row2 = ttk.Frame(body)
        row2.pack(fill="x", pady=(6, 0))
        row2.columnconfigure(0, weight=1)
        ttk.Button(row2, text="微信小程序码…",
                   command=lambda: self._fetch_mini_code(room.get("id"), name)).grid(
            row=0, column=0, sticky="ew")
        ttk.Button(row2, text="关闭", width=8,
                   command=win.destroy).grid(row=0, column=1, padx=(4, 0))
        win.bind("<Escape>", lambda e: win.destroy())

    def _draw_qr(self, parent, matrix):
        """用 Canvas 逐模块绘制二维码（深色模块画成小方块）。"""
        n = len(matrix)
        scale = max(2, 210 // (n + 8))          # 目标边长约 210px（与网页端一致）
        side = (n + 8) * scale
        canvas = tk.Canvas(parent, width=side, height=side, bg="white",
                           highlightthickness=0, borderwidth=0)
        canvas.pack()
        offset = 4 * scale                      # 标准静区：4 个模块
        for r, row in enumerate(matrix):
            y0 = offset + r * scale
            for c, value in enumerate(row):
                if value:
                    x0 = offset + c * scale
                    canvas.create_rectangle(x0, y0, x0 + scale, y0 + scale,
                                            fill="#000000", outline="", width=0)
        return canvas

    def _copy_share_link(self, url, win=None):
        parent = win or self.root
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.root.update_idletasks()        # 刷新剪贴板，程序退出后内容仍保留
        except Exception as exc:
            self._log(f"复制链接失败：{exc}", "warn")
            messagebox.showwarning("复制失败", f"请手动复制链接：\n\n{url}", parent=parent)
            return
        self._log("房间链接已复制到剪贴板", "good")
        messagebox.showinfo("已复制", "房间链接已复制到剪贴板，发给朋友即可进房。",
                            parent=parent)

    def _open_share_link(self, url):
        try:
            webbrowser.open(url)
            self._log("已在浏览器中打开分享链接", "muted")
        except Exception as exc:
            self._log(f"打开浏览器失败：{exc}", "warn")

    def _save_qr_png(self, matrix, name, win=None):
        parent = win or self.root
        if not matrix:
            messagebox.showwarning("无法保存", "二维码未生成成功，无法保存。", parent=parent)
            return
        path = filedialog.asksaveasfilename(
            parent=parent, title="保存房间二维码",
            initialfile=sanitize_filename(f"房间二维码-{name}") + ".png",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(jusic_qr.png_bytes(matrix, scale=8, border=4))
            self._log(f"二维码已保存：{os.path.basename(path)}", "good")
        except Exception as exc:
            self._log(f"二维码保存失败：{exc}", "warn")

    def _fetch_mini_code(self, room_id, name):
        """拉取微信小程序码（后台线程，避免阻塞界面），完成后选择保存位置。"""
        if not room_id:
            return
        self._log("正在获取微信小程序码…", "muted")

        def worker():
            try:
                self.evq.put(("minicode", (get_mini_code(self.args.host, room_id), name)))
            except Exception as exc:
                self.evq.put(("minicode-error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=worker, daemon=True, name="jusic-minicode").start()

    def _save_mini_code(self, raw, name):
        text = str(raw or "").strip()
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        try:
            blob = base64.b64decode(text, validate=False)
        except Exception as exc:
            self._log(f"小程序码解析失败：{exc}", "warn")
            return
        if not blob:
            self._log("服务端未返回小程序码", "warn")
            return
        ext = ".jpg" if blob[:2] == b"\xff\xd8" else ".png"
        path = filedialog.asksaveasfilename(
            parent=self.root, title="保存微信小程序码",
            initialfile=sanitize_filename(f"小程序码-{name}") + ext,
            defaultextension=ext,
            filetypes=[("图片文件", "*" + ext), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(blob)
            self._log(f"小程序码已保存：{os.path.basename(path)}", "good")
        except Exception as exc:
            self._log(f"小程序码保存失败：{exc}", "warn")

    # ---------------- 歌词（LRC）显示 ---------------- #
    def _begin_lyrics(self, lrc_text, duration_ms):
        """切到新歌：解析歌词并以本地播放起点计时。"""
        self._lyrics = parse_lyrics(lrc_text)
        self._lyric_t0 = time.monotonic()
        self._lyric_idx = -1
        self._lyric_end = duration_ms or 0
        if self._lyrics:
            self._lyric_draw(max(0, lyric_index(self._lyrics, 0.0)))
            self._schedule_lyric()
        else:
            self._lyric_hint("暂无歌词")

    def _clear_lyrics(self):
        self._lyrics = []
        self._lyric_hint("等待歌曲…")
        if self._lyric_after is not None:
            try:
                self.root.after_cancel(self._lyric_after)
            except Exception:
                pass
            self._lyric_after = None

    def _schedule_lyric(self):
        if self._lyric_after is not None:
            try:
                self.root.after_cancel(self._lyric_after)
            except Exception:
                pass
            self._lyric_after = None
        self._lyric_after = self.root.after(200, self._lyric_tick)

    def _lyric_tick(self):
        self._lyric_after = None
        if not self._lyrics:
            return
        t_ms = (time.monotonic() - self._lyric_t0) * 1000.0
        idx = lyric_index(self._lyrics, t_ms)
        if idx != self._lyric_idx:
            self._lyric_idx = idx
            self._lyric_draw(idx)
        # 结束时停止计时：超过歌曲时长 3s，或歌词结束后 8s
        if self._lyrics:
            last_t = self._lyrics[-1][0]
            over = self._lyric_end > 0 and t_ms > self._lyric_end + 3000
            stale = t_ms > last_t + 8000
        else:
            over = stale = True
        if not over and not stale:
            self._lyric_after = self.root.after(200, self._lyric_tick)

    def _lyric_hint(self, text):
        try:
            self.lyr.configure(state="normal")
            self.lyr.delete("1.0", "end")
            self.lyr.insert("1.0", text, "muted")
            self.lyr.configure(state="disabled")
        except Exception:
            pass

    def _lyric_draw(self, idx):
        """只显示当前句附近几行，当前句高亮并带 ▶。"""
        if not self._lyrics:
            return
        try:
            self.lyr.configure(state="normal")
            self.lyr.delete("1.0", "end")
            lo = max(0, idx - 2)
            hi = min(len(self._lyrics), idx + 6)
            for i in range(lo, hi):
                _, text = self._lyrics[i]
                if i == idx:
                    tag, prefix = "cur", "▶ "
                elif i == idx + 1:
                    tag, prefix = "next", ""
                else:
                    tag, prefix = "muted", ""
                self.lyr.insert("end", prefix + text + "\n", tag)
            self.lyr.configure(state="disabled")
        except Exception:
            pass

    # ---------------- 下载当前歌曲 / 歌词 ---------------- #
    def _song_title(self):
        m = self._current_music or {}
        return sanitize_filename(
            f"{m.get('name') or 'song'} - {m.get('artist') or ''}".strip(" -")) or "song"

    def _download_song(self):
        m = self._current_music
        if not m:
            self._log("当前没有正在播放的歌曲，无法下载", "warn")
            return
        url = m.get("url") or ""
        if not url:
            self._log("当前歌曲没有可用的下载地址", "warn")
            return
        if self._downloading:
            self._log("已有下载任务进行中，请稍候…", "warn")
            return
        ext = guess_audio_ext(url, m.get("source"))
        path = filedialog.asksaveasfilename(
            parent=self.root, title="保存当前歌曲",
            initialfile=self._song_title() + ext, defaultextension=ext,
            filetypes=[("音频文件", "*" + ext), ("所有文件", "*.*")])
        if not path:
            return
        self._downloading = True
        self._log(f"开始下载：{os.path.basename(path)}", "muted")
        threading.Thread(target=self._download_worker, args=(url, path, "歌曲"),
                         daemon=True, name="jusic-download").start()

    def _download_lyrics(self):
        m = self._current_music or {}
        lyric = (m.get("lyric") or "").strip()
        if not lyric:
            self._log("当前歌曲暂无歌词可下载", "warn")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="保存当前歌词",
            initialfile=self._song_title() + ".lrc", defaultextension=".lrc",
            filetypes=[("LRC 歌词", "*.lrc"), ("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(lyric + "\n")
            self._log(f"歌词已保存：{os.path.basename(path)}", "good")
        except Exception as exc:
            self._log(f"歌词保存失败：{exc}", "warn")

    def _download_both(self):
        """音频与歌词一起下载：音频存到用户选择的位置，歌词存为同名 .lrc。"""
        m = self._current_music
        if not m:
            self._log("当前没有正在播放的歌曲，无法下载", "warn")
            return
        url = m.get("url") or ""
        if not url:
            self._log("当前歌曲没有可用的下载地址", "warn")
            return
        if self._downloading:
            self._log("已有下载任务进行中，请稍候…", "warn")
            return
        ext = guess_audio_ext(url, m.get("source"))
        path = filedialog.asksaveasfilename(
            parent=self.root, title="保存歌曲（歌词将保存为同名 .lrc）",
            initialfile=self._song_title() + ext, defaultextension=ext,
            filetypes=[("音频文件", "*" + ext), ("所有文件", "*.*")])
        if not path:
            return
        lyric = (m.get("lyric") or "").strip()
        lyrics = ((os.path.splitext(path)[0] + ".lrc"), lyric) if lyric else None
        self._downloading = True
        note = "歌曲 + 歌词" if lyrics else "歌曲（当前无歌词）"
        self._log(f"开始下载：{os.path.basename(path)}（{note}）", "muted")
        threading.Thread(target=self._download_worker, args=(url, path, "歌曲+歌词", lyrics),
                         daemon=True, name="jusic-download").start()

    def _download_worker(self, url, path, kind, lyrics=None):
        """lyrics 为 (lrc_path, text) 时，音频下载完成后一并写出歌词。"""
        last = [0.0]

        def prog(done, total):
            now = time.monotonic()
            if now - last[0] >= 0.5 or (total and done >= total):
                last[0] = now
                self.evq.put(("dl-progress", (done, total)))

        try:
            done, _total = download_file(url, path, progress=prog)
            lrc_saved = None
            if lyrics and lyrics[0] and lyrics[1]:
                lrc_path, text = lyrics
                try:
                    with open(lrc_path, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(text if text.endswith("\n") else text + "\n")
                    lrc_saved = lrc_path
                except Exception as exc:
                    self.evq.put(("dl-error", f"歌词保存失败：{exc}"))
            self.evq.put(("dl-done", (path, done, lrc_saved)))
        except DownloadCancelled:
            self.evq.put(("dl-error", "下载已取消"))
        except Exception as exc:
            self.evq.put(("dl-error", f"{type(exc).__name__}: {exc}"))
        finally:
            self._downloading = False

    # ---------------- mpv 内核 ---------------- #
    def _update_mpv_status(self):
        path = MpvEngine.find_mpv(self.client.engine.mpv_path)
        if path:
            self.mpv_var.set(f"mpv: {os.path.basename(os.path.dirname(path))}")
        else:
            self.mpv_var.set("mpv: 未找到（播放会失败，可点“选mpv…”）")

    def _pick_mpv(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="选择 mpv.exe（播放内核）",
            filetypes=[("mpv 程序", "mpv.exe"), ("可执行文件", "*.exe")])
        if not path:
            return
        self.client.engine.mpv_path = path
        self._update_mpv_status()
        self._log(f"已设置 mpv：{path}", "good")

    def _warn_mpv_missing(self):
        if MpvEngine.find_mpv(self.client.engine.mpv_path) is None:
            messagebox.showwarning(
                "未找到播放内核 mpv",
                "未找到 mpv.exe，进入房间后将无法出声。\n\n"
                "1) 点右上“选mpv…”手动指定 mpv.exe；或\n"
                "2) 在命令行执行  winget install shinchiro.mpv  后重启本程序。",
                parent=self.root)

    # ---------------- 关于/开源致谢 ---------------- #
    def _app_version(self) -> str:
        try:
            with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as fh:
                return fh.read().strip() or "1.0.0"
        except Exception:
            return "1.0.0"

    def _show_about(self):
        ver = getattr(self, "_version", None) or self._app_version()
        lines = [
            "JusicRoomPlayer " + ver + "（一起听歌吧 · 轻量房间客户端）",
            "",
            "Copyright (C) 2026 The JusicRoomPlayer Authors",
            "本软件以 GNU GPL v3 开源（SPDX: GPL-3.0-only），",
            "完整许可证见项目根目录 LICENSE 文件。",
            "",
            "──────── 基于以下开源项目开发 ────────",
            "▪ 播放内核 mpv（http 音频解码/播放）",
            "  https://github.com/mpv-player/mpv   LGPL-2.1+ / ISC",
            "▪ 房间服务与协议参考 Jusic-Serve-Houses",
            "  https://github.com/JumpAlang/Jusic-Serve-Houses   GPL-3.0",
            "▪ 实时通信库 websockets",
            "  https://github.com/python-websockets/websockets   BSD-3-Clause",
            "▪ 图形界面 Tkinter/Tcl-Tk（随 Python 分发，PSF/Tcl 许可）",
            "▪ 打包 PyInstaller（GPL-2.0+，含 Bootloader 例外）",
            "▪ 第三方许可汇总：THIRD_PARTY_NOTICES（项目根目录）",
            "",
            "仅用于个人学习与合法收听场景；歌曲版权归原权利人所有，",
            "请遵守所用服务的使用条款与版权规定。",
        ]
        win = tk.Toplevel(self.root)
        win.title("关于")
        win.transient(self.root)
        win.grab_set()
        text = tk.Text(win, width=72, height=len(lines) + 1, wrap="word",
                       font=(FONT, 9), relief="flat", padx=10, pady=8)
        text.pack(padx=8, pady=(8, 2))
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(2, 8))

    # ---------------- 系统托盘（最小化驻留） ---------------- #
    def _init_tray(self):
        """创建系统托盘图标；不可用时退化为普通最小化（不影响主功能）。"""
        if TrayIcon is None or not TrayIcon.available():
            return
        try:
            ver = getattr(self, "_version", "") or self._app_version()
            self._tray = TrayIcon(
                tooltip=f"Jusic 房间播放器 v{ver}（双击显示主界面）",
                on_show=lambda: self.evq.put(("tray-show", None)),
                on_quit=lambda: self.evq.put(("tray-quit", None)),
            )
            if not self._tray.start():
                self._tray = None
        except Exception:
            self._tray = None

    def _on_unmap(self, event):
        """窗口被最小化（iconify）时，隐藏到系统托盘。"""
        if event.widget is not self.root or self._tray is None:
            return
        try:
            if self.root.state() == "iconic":
                self.root.after(10, self._hide_to_tray)
        except Exception:
            pass

    def _hide_to_tray(self):
        if self._tray is None or self._in_tray:
            return
        try:
            if self.root.state() != "iconic":
                return
            self._in_tray = True
            self.root.withdraw()          # 收起窗口与任务栏按钮，仅保留托盘图标
        except Exception:
            self._in_tray = False
            return
        self._log("已最小化到系统托盘（双击托盘图标可恢复窗口）", "muted")
        if not getattr(self, "_tray_tip_shown", False):
            self._tray_tip_shown = True
            self._tray.balloon("已最小化到系统托盘",
                               "程序仍在后台播放：双击托盘图标恢复窗口，右键图标可退出程序。")

    def _restore_from_tray(self):
        """从系统托盘恢复主窗口。"""
        if not self._in_tray:
            return
        self._in_tray = False
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass
        self._log("已从系统托盘恢复窗口", "muted")

    def _stop_tray(self):
        tray, self._tray = self._tray, None
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass

    def _on_close(self):
        try:
            # 先同步停 mpv（防止窗口关闭后仍有声音残留）
            self.client.engine.stop()
            self.client.stop()
        except Exception:
            pass
        finally:
            self._stop_tray()
            try:
                self.root.destroy()
            except Exception:
                pass

    # ===================================================================== #
    # 事件桥：后台线程 -> UI 队列 -> after 轮询
    # ===================================================================== #
    def _on_core_event(self, event, data):
        self.evq.put((event, data))

    def _poll(self):
        try:
            while True:
                event, data = self.evq.get_nowait()
                self._dispatch(event, data)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _dispatch(self, event, data):
        if event == "rooms":
            self.rooms = list(data or [])
            self._populate(self.rooms, self.kw_var.get().strip().lower())
            if not self._auto_entered:
                self._auto_entered = True
                target = self.args.house
                if not target and self.rooms:
                    default = next((r for r in self.rooms if str(r.get("id")) == "DEFAULT"),
                                   self.rooms[0])
                    target = str(default.get("id"))
                if target:
                    pwd = self.args.password or ""
                    room = next((r for r in self.rooms if str(r.get("id")) == target), None)
                    if room and room.get("needPwd") and not pwd:
                        pwd = simpledialog.askstring("房间密码", f"房间需要密码：",
                                                     show="*", parent=self.root) or ""
                    self.client.enter_room(target, pwd)
                    self._log(f"自动进入房间：{target}", "muted")
            # 刷新后恢复之前选中的房间（自动/手动刷新都适用）
            if self._pending_reselect:
                rid = str(self._pending_reselect)
                for iid, room in self._room_by_iid.items():
                    if str(room.get("id")) == rid:
                        try:
                            self.tree.selection_set(iid)
                            self.tree.see(iid)
                        except Exception:
                            pass
                        break
                self._pending_reselect = None
        elif event == "connected":
            info = data or {}
            name = info.get("name") if info else ""
            self.room_var.set(f"房间：{name or '—'}")
            self.status_var.set(f"后端 https://{self.args.host}{MUSIC_API} ｜ 已连接 {name}")
            self._clear_lyrics()          # 新房间：先清空上一房间歌词
            # 通道完全就绪后，若已填写昵称则自动应用
            if info.get("ready") and self.nick_var.get().strip():
                self.client.set_nickname(self.nick_var.get().strip())
        elif event == "reconnecting":
            self.status_var.set(f"后端 https://{self.args.host}{MUSIC_API} ｜ 重连中（{data}）")
        elif event == "music":
            m = data or {}
            self._current_music = m
            title = m.get("name") or "—"
            artist = m.get("artist") or ""
            dur = human_seconds(m.get("duration"))
            self.track_var.set(f"{title} - {artist}")
            self.sub_var.set(f"时长 {dur}　来源 {m.get('source') or m.get('platform') or '—'}")
            self._log(f"[♪] {title} - {artist} {dur}", "music")
            # 歌词：LRC 解析 + 按本地起播时间同步滚动
            self._begin_lyrics(m.get("lyric") or "", m.get("duration"))
        elif event == "search":
            self._on_search_result(data or {})
        elif event == "online":
            self.online_var.set(f"在线 {data} 人")
        elif event == "queue":
            self.queue_tree.delete(*self.queue_tree.get_children())
            for i, s in enumerate(data or [], 1):
                txt = f"{i}. {s.get('name') or ''} - {s.get('artist') or ''}"
                sub = f"{human_seconds(s.get('duration'))}　点：{s.get('nickName') or s.get('picker') or '?'}"
                self.queue_tree.insert("", "end", values=(txt[:46], sub[:42]))
        elif event == "chat":
            if self.chat_var.get():
                self._log(f"[聊天] {data.get('name')}: {data.get('text')}", "muted")
        elif event == "notice":
            self._log(f"[通知] {data}", "warn")
        elif event == "announce":
            self._log(f"[公告] {(data or {}).get('content', '')[:240]}", "warn")
        elif event == "dl-progress":
            done, total = data
            if total:
                self.status_var.set(
                    f"下载中… {done / 1048576:.1f}/{total / 1048576:.1f} MB"
                    f"（{done * 100 // total}%）")
            else:
                self.status_var.set(f"下载中… {done / 1048576:.1f} MB")
        elif event == "dl-done":
            path, done, lrc = data
            msg = f"下载完成：{os.path.basename(path)}（{done / 1048576:.1f} MB）"
            if lrc:
                msg += f" + 歌词 {os.path.basename(lrc)}"
            self._log(msg, "good")
            self.status_var.set(msg)
        elif event == "dl-error":
            self._log(f"[下载失败] {data}", "warn")
            self.status_var.set(f"下载失败：{data}")
        elif event == "minicode":
            self._save_mini_code(*data)
        elif event == "minicode-error":
            self._log(f"小程序码获取失败：{data}", "warn")
        elif event == "tray-show":
            self._restore_from_tray()
        elif event == "tray-quit":
            self._on_close()
        elif event == "log":
            self._log(data, "muted")
        elif event == "error":
            self._log(f"[错误] {data}", "warn")
            self.status_var.set(f"后端 https://{self.args.host}{MUSIC_API} ｜ {data}")

    def _log(self, text, tag=None):
        try:
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n", tag)
            self.log.see("end")
            # 限制行数，避免长跑内存增长
            nlines = int(self.log.index("end-1c").split(".")[0])
            if nlines > 400:
                self.log.delete("1.0", f"{nlines - 300}.0")
            self.log.configure(state="disabled")
        except Exception:
            pass


def parse_args(argv):
    p = argparse.ArgumentParser(prog="jusic_gui",
                                description="Jusic 房间播放器图形界面（ttk，mpv 内核）")
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"Jusic 后端域名（默认 {DEFAULT_HOST}）")
    p.add_argument("--house", default="", help="启动后自动进入的房间 ID")
    p.add_argument("--password", default="", help="房间密码")
    p.add_argument("--mpv", default="", help="mpv.exe 绝对路径")
    p.add_argument("--volume", type=int, default=90, help="默认音量 0-100")
    p.add_argument("--console", action="store_true",
                   help="保留控制台运行（默认双击时会自动改用 pythonw 无窗口运行）")
    return p.parse_args(argv)


def _relaunch_without_console(argv):
    """直接双击 .py 会附带黑色控制台窗口，这里改用 pythonw.exe 无窗口重启。
    命令行手动运行时加 --console 可保留控制台。"""
    if os.name != "nt":
        return False
    if "--console" in argv or getattr(sys, "frozen", False):
        return False
    if os.environ.get("JUSIC_GUI_PYW") == "1":
        return False
    exe = os.path.normcase(os.path.abspath(sys.executable))
    if not exe.endswith("python.exe"):
        return False
    pyw = exe[:-len("python.exe")] + "pythonw.exe"
    if not os.path.isfile(pyw):
        return False
    env = dict(os.environ)
    env["JUSIC_GUI_PYW"] = "1"
    try:
        subprocess.Popen([pyw, os.path.abspath(__file__)] + list(argv),
                         cwd=SCRIPT_DIR, env=env)
        return True
    except Exception:
        return False


def _main_impl(raw):
    args = parse_args(raw)
    try:
        root = tk.Tk()
    except Exception as exc:
        _fatal_error("无法创建图形窗口（是否缺少 tkinter？）\n\n" + str(exc))
    gui = JusicGui(root, args)
    gui.client.start()
    gui._update_mpv_status()
    gui.client.refresh_rooms()
    root.after(100, gui._poll)
    # 首次启动后检查 mpv 是否就绪，缺失时给引导提示
    root.after(1200, gui._warn_mpv_missing)
    try:
        root.mainloop()
    finally:
        # mainloop 结束后兜底清理（关闭窗口/异常等都会走到这里）
        gui._stop_tray()
        gui.client.engine.stop()
        gui.client.stop()


def main(argv=None):
    raw = sys.argv[1:] if argv is None else list(argv)
    if _relaunch_without_console(raw):
        return                       # 已用 pythonw 重启，本进程直接退出
    try:
        _main_impl(raw)
    except Exception:
        import traceback
        text = traceback.format_exc()
        # 冻结（exe）环境把错误写到可执行文件所在目录，便于排错
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                   "JusicRoomPlayer-error.log"),
                      "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception:
            pass
        _fatal_error("程序运行出错，已写入日志：JusicRoomPlayer-error.log\n\n" + text[-1200:])


if __name__ == "__main__":
    main()
