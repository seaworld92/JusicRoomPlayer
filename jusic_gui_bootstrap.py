#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
Jusic 房间播放器 · 主题界面版（ttkbootstrap）
==============================================
在 jusic_gui.py（经典 ttk 界面）之外，提供一个**多主题、可随时切换**的新界面。

设计要点
--------
* **业务逻辑 100% 复用**：房间列表、REST/WSS 协议、点歌、点赞、歌词同步、
  下载、系统托盘等全部继承自 ``jusic_gui.JusicGui``，本文件只替换“皮肤与布局”，
  因此不会出现两份逻辑各自漂移的问题（改核心只需改 jusic_core.py）；
* **主题**：ttkbootstrap 2.x 自带 15 套风格 × 明/暗两套 = **30 种主题**，
  界面里可用「风格下拉框 + 深色开关 + 全部主题菜单」任意切换，
  也可用 Ctrl+T 一键明暗对调；主题会记住，下次启动自动恢复；
* **深色主题适配**：歌词/日志文本框、次要文字、以及父类对话框里硬编码的
  浅色文字，都会随主题重新着色，暗色下同样清晰。

运行
----
双击 ``jusic_gui_bootstrap.pyw``（或 ``python jusic_gui_bootstrap.py``）即可：

    python jusic_gui_bootstrap.py                    # 打开界面（自动用 pythonw 免控制台）
    python jusic_gui_bootstrap.py --console          # 保留控制台（调试）
    python jusic_gui_bootstrap.py --theme dracula-dark   # 指定启动主题
    python jusic_gui_bootstrap.py --host 你的域名 --volume 60

依赖：``websockets``（实时通道）+ ``ttkbootstrap``（主题界面）
    python -m pip install -r requirements.txt
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import tkinter as tk
import warnings

# ---- 双击/打包(冻结)启动支持（与 jusic_gui.py 同一套约定） ----
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = BASE_DIR
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
if not getattr(sys, "frozen", False):
    try:
        os.chdir(SCRIPT_DIR)
    except OSError:
        pass

# 业务逻辑与工具函数全部来自既有前端（导入会做依赖自检并弹出友好错误框）
from jusic_gui import FONT, JusicGui, _fatal_error            # noqa: E402
from jusic_core import DEFAULT_HOST, MUSIC_API, human_seconds  # noqa: E402

try:
    import ttkbootstrap as ttb
except (ImportError, SystemExit) as exc:                       # pragma: no cover
    _fatal_error("缺少主题界面依赖 ttkbootstrap，请先执行：\n\n"
                 "    python -m pip install -r requirements.txt\n\n"
                 f"详细信息：{exc}")

DEFAULT_THEME = "bootstrap-light"        # 找不到配置/参数时的兜底主题
MUTED_LIGHT = "#6c757d"                  # 浅色主题下的“次要文字”颜色
MUTED_DARK = "#9aa0a5"                   # 深色主题下的“次要文字”颜色
_GEOMETRY_RE = re.compile(r"^\d+x\d+([+-]\d+[+-]\d+)?$")

# 基类对话框里用了一批硬编码的浅色文字颜色，深色主题下会看不清；
# 这里按语义映射到当前主题的对应颜色（见 BootstrapGui._retint_dialog）。
_FG_MAP = {
    "#333": "fg", "#555": "muted", "#666": "muted", "#777": "muted",
    "#888": "muted", "#999": "muted", "#0a6": "success", "#06a": "info",
    "#a60": "warning", "#b00": "danger", "#d01818": "danger", "#0a66c2": "info",
}


# ===================================================================== #
# 设置持久化（记住上次用的主题和窗口大小）
# ===================================================================== #
def _settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "JusicRoomPlayer", "ui.json")


def _load_settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    path = _settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _theme_families(names) -> list:
    """提取“同时具备明/暗两套”的风格名（如 dracula），用于风格下拉框。"""
    modes = {}
    for name in names:
        for suffix in ("-light", "-dark"):
            if name.endswith(suffix):
                modes.setdefault(name[:-len(suffix)], set()).add(suffix[1:])
    return sorted(family for family, ms in modes.items() if ms == {"light", "dark"})


# ===================================================================== #
# 主界面
# ===================================================================== #
class BootstrapGui(JusicGui):
    """ttkbootstrap 主题界面：布局与皮肤替换，全部功能继承自 JusicGui。"""

    def __init__(self, root, args):
        # 这几个属性要在 super().__init__()（内部会调用 _build_ui）之前就位
        self._settings = _load_settings()
        self._requested_theme = str(getattr(args, "theme", "") or "").strip()
        self._muted_widgets = []         # 跟随明暗主题变色的“次要文字”控件
        self._tinted = {}                # 已按当前主题处理过的对话框
        self._tint_keys = {}             # 对话框控件 -> 语义色名（供主题来回切换）
        super().__init__(root, args)     # 内部完成 _build_ui / 托盘 / 关闭协议
        self._apply_theme(self._initial_theme(), save=False, quiet=True)
        self._tick_ui()

    # ================================================================= #
    # UI 搭建
    # ================================================================= #
    def _build_ui(self):
        root = self.root
        self._version = self._app_version()
        root.title(f"Jusic 房间播放器 v{self._version} · 主题界面（低内存 · mpv 内核）")
        geometry = str(self._settings.get("geometry") or "").strip()
        root.geometry(geometry if _GEOMETRY_RE.match(geometry) else "1080x760")
        root.minsize(900, 600)
        # 最小化 → 隐藏到系统托盘（逻辑在父类 _on_unmap）
        root.bind("<Unmap>", self._on_unmap)
        root.bind("<Control-t>", lambda e: self._toggle_theme())
        root.bind("<Control-T>", lambda e: self._toggle_theme())
        root.bind("<F2>", lambda e: self._toggle_theme())

        self.style = getattr(root, "style", None) or ttb.Style()
        self._theme_names = list(self.style.theme_names())
        self._families = _theme_families(self._theme_names)
        self._theme_name = self._current_theme()
        self._theme_var = tk.StringVar(value=self._theme_name)

        shell = ttb.Frame(root, padding=0)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        self._build_header(shell)
        ttb.Separator(shell, bootstyle="secondary").grid(row=1, column=0, sticky="ew")

        body = ttb.Panedwindow(shell, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew", padx=12, pady=(8, 4))

        left = self._build_rooms_pane(body)
        right = self._build_player_pane(body)
        body.add(left, weight=3)
        body.add(right, weight=5)
        self._paned = body
        # 左侧房间列表默认给足宽度（否则「简介」列会被挤出可视区）。
        # 注意：**不能在窗口还没完成布局时设 sashpos**——那时 paned 尺寸还是 1x1，
        # Tk 会把分栏位置截成 0，左栏被压成 0 宽，房间列表会整个看不见；
        # 所以这里等真实的 <Map>/<Configure> 到了、宽度正常后再设一次。
        self._sash_done = False
        body.bind("<Map>", self._maybe_set_sash)
        body.bind("<Configure>", self._maybe_set_sash)

        self._build_status_bar(shell)

        # 每 10 分钟自动刷新一次房间列表（静默，不打断操作/不刷屏）
        self.root.after(10 * 60 * 1000, self._auto_refresh)

    def _maybe_set_sash(self, event=None):
        """布局完成后把左右分栏设为约 36% : 64%（只设一次，之后随用户拖动）。"""
        if getattr(self, "_sash_done", True):
            return
        try:
            width = self._paned.winfo_width()
            if not self._paned.winfo_ismapped() or width <= 100:
                return                       # 还没真正布局，等下一次事件
            pos = max(300, int(width * 0.36))
            pos = min(pos, max(240, int(width * 0.60)))   # 窗口很窄时别占太满
            self._paned.sashpos(0, pos)
            self._sash_done = True
        except Exception:
            pass

    # ---------------- 顶部：标题 + 房间状态 + 主题切换 ---------------- #
    def _build_header(self, shell):
        head = ttb.Frame(shell, padding=(12, 10, 12, 6))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)

        brand = ttb.Frame(head)
        brand.grid(row=0, column=0, rowspan=2, sticky="w")
        ttb.Label(brand, text="♪ Jusic 房间播放器", font=(FONT, 17, "bold"),
                  bootstyle="primary").pack(side="left")
        ttb.Label(brand, text=f"  v{self._version} · 低内存 · mpv 内核",
                  font=(FONT, 9)).pack(side="left", pady=(7, 0))

        # 房间在线状态（ttkbootstrap 的彩色徽标）
        self.room_var = tk.StringVar(value="未进入房间")
        self.online_var = tk.StringVar(value="—")
        ttb.Label(head, textvariable=self.room_var, bootstyle="success",
                  font=(FONT, 10, "bold")).grid(row=0, column=1, sticky="e")
        ttb.Label(head, textvariable=self.online_var, bootstyle="info",
                  font=(FONT, 10)).grid(row=0, column=2, sticky="e", padx=(8, 0))

        # 主题切换：风格下拉框 + 深色开关 + 全部主题菜单
        theme_row = ttb.Frame(head)
        theme_row.grid(row=1, column=1, columnspan=2, sticky="e", pady=(8, 0))
        self._muted(theme_row, text="主题", font=(FONT, 9)).pack(side="left")
        self._family_var = tk.StringVar(value=self._family_of(self._theme_name))
        self._family_box = ttb.Combobox(theme_row, textvariable=self._family_var,
                                        values=self._families, state="readonly",
                                        width=13, bootstyle="primary")
        self._family_box.pack(side="left", padx=(6, 6))
        self._family_box.bind("<<ComboboxSelected>>", lambda e: self._on_family_selected())
        self._dark_var = tk.BooleanVar(value=(self.style.theme_mode == "dark"))
        ttb.Checkbutton(theme_row, text="深色", variable=self._dark_var,
                        bootstyle="round-toggle",
                        command=self._on_dark_toggle).pack(side="left")
        self._theme_btn = ttb.Menubutton(theme_row, text="全部主题 ▾",
                                         bootstyle="secondary-outline")
        self._theme_btn.pack(side="left", padx=(8, 0))
        self._build_theme_menu()

    def _build_theme_menu(self):
        """「全部主题」下拉菜单：浅色 / 深色 两组，另有明暗对调与随机主题。"""
        menu = ttb.Menu(self._theme_btn, tearoff=0)
        light_menu = ttb.Menu(menu, tearoff=0)
        dark_menu = ttb.Menu(menu, tearoff=0)
        for name in self._theme_names:
            target = dark_menu if name.endswith("-dark") else light_menu
            target.add_radiobutton(label=self._family_of(name),
                                   variable=self._theme_var, value=name,
                                   command=lambda n=name: self._apply_theme(n))
        menu.add_cascade(label="浅色主题", menu=light_menu)
        menu.add_cascade(label="深色主题", menu=dark_menu)
        menu.add_separator()
        menu.add_command(label="明暗一键切换（Ctrl+T）", command=self._toggle_theme)
        menu.add_command(label="随机换一个主题", command=self._random_theme)
        self._theme_btn.configure(menu=menu)

    # ---------------- 左：房间列表 ---------------- #
    def _build_rooms_pane(self, parent):
        # width=380：给分栏一个“请求宽度”，即使分栏位置没被调整，左栏也不会太窄
        left = ttb.Labelframe(parent, text=" 房间列表 · 双击进入 ",
                              padding=8, width=380, bootstyle="primary")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        search_row = ttb.Frame(left)
        search_row.grid(row=0, column=0, sticky="ew")
        search_row.columnconfigure(0, weight=1)
        self.kw_var = tk.StringVar()
        kw_entry = ttb.Entry(search_row, textvariable=self.kw_var, bootstyle="primary")
        kw_entry.grid(row=0, column=0, sticky="ew")
        kw_entry.bind("<Return>", lambda e: self._apply_filter())
        ttb.Button(search_row, text="过滤", width=4, bootstyle="info-outline",
                   command=self._apply_filter).grid(row=0, column=1, padx=(6, 0))
        ttb.Button(search_row, text="刷新", width=4, bootstyle="info-outline",
                   command=self._refresh).grid(row=0, column=2, padx=(6, 0))

        # 房间数量/提示：列表为空时也能一眼看出是“加载中/没取到”而不是界面坏了
        self._rooms_hint_var = tk.StringVar(value="正在获取房间列表…")
        self._muted(left, textvariable=self._rooms_hint_var, font=(FONT, 8)).grid(
            row=1, column=0, sticky="w", pady=(6, 4))

        tree_box = ttb.Frame(left)
        tree_box.grid(row=2, column=0, sticky="nsew")
        tree_box.rowconfigure(0, weight=1)
        tree_box.columnconfigure(0, weight=1)
        cols = ("name", "pop", "lock", "desc")
        self.tree = ttb.Treeview(tree_box, columns=cols, show="headings",
                                 height=18, bootstyle="primary")
        for key, text, width, anchor in (
                ("name", "房间", 150, "w"), ("pop", "在线", 52, "center"),
                ("lock", "锁", 30, "center"), ("desc", "简介", 100, "w")):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor)
        vs = ttb.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda e: self._enter_selected())
        self.tree.bind("<Return>", lambda e: self._enter_selected())

        btn_row = ttb.Frame(left)
        btn_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        btn_row.columnconfigure(0, weight=1)
        ttb.Button(btn_row, text="进入选中房间", bootstyle="success",
                   command=self._enter_selected).grid(row=0, column=0, sticky="ew")
        ttb.Button(btn_row, text="离开房间", bootstyle="danger-outline",
                   command=self._leave).grid(row=0, column=1, padx=(6, 0))
        return left

    # ---------------- 右：当前播放 + 歌词/队列/日志 ---------------- #
    def _build_player_pane(self, parent):
        right = ttb.Frame(parent)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_now_playing(right)

        nb = ttb.Notebook(right, bootstyle="primary")
        nb.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        nb.add(self._build_lyric_page(nb), text="  ♪ 歌词  ")
        nb.add(self._build_queue_page(nb), text="  🎵 点歌队列  ")
        nb.add(self._build_log_page(nb), text="  📋 动态日志  ")
        self._notebook = nb
        return right

    def _build_now_playing(self, parent):
        info = ttb.Labelframe(parent, text=" 当前播放 ", padding=10, bootstyle="primary")
        info.grid(row=0, column=0, sticky="ew")
        info.columnconfigure(0, weight=1)

        self.track_var = tk.StringVar(value="—")
        ttb.Label(info, textvariable=self.track_var, font=(FONT, 15, "bold"),
                  bootstyle="primary").grid(row=0, column=0, sticky="w")
        self.sub_var = tk.StringVar(value="等待房间歌曲推送…")
        self._muted(info, textvariable=self.sub_var, font=(FONT, 9)).grid(
            row=1, column=0, sticky="w", pady=(2, 8))

        # 播放进度（按本地起播时间估算，和歌词同一时钟）
        prog_row = ttb.Frame(info)
        prog_row.grid(row=2, column=0, sticky="ew")
        prog_row.columnconfigure(0, weight=1)
        self.progress = ttb.Progressbar(prog_row, bootstyle="info-striped",
                                        maximum=100, value=0)
        self.progress.grid(row=0, column=0, sticky="ew")
        self._time_var = tk.StringVar(value="--:-- / --:--")
        self._muted(prog_row, textvariable=self._time_var, font=(FONT, 9),
                    width=14, anchor="e").grid(row=0, column=1, padx=(8, 0))

        act = ttb.Frame(info)
        act.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        act.columnconfigure(2, weight=1)
        ttb.Button(act, text="切歌（投票）", bootstyle="warning",
                   command=self._skip_vote).grid(row=0, column=0, sticky="w")
        ttb.Button(act, text="点歌…", bootstyle="primary",
                   command=self._open_pick_dialog).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttb.Button(act, text="分享房间…", bootstyle="info-outline",
                   command=self._share_room).grid(row=0, column=2, sticky="e")
        self._muted(act, text="普通成员投票，票数达标自动切歌", font=(FONT, 8)).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        vol_row = ttb.Frame(info)
        vol_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        vol_row.columnconfigure(1, weight=1)
        self._muted(vol_row, text="音量", font=(FONT, 9)).grid(row=0, column=0, sticky="w")
        self.vol_var = tk.DoubleVar(value=self.args.volume)
        ttb.Scale(vol_row, from_=0, to=100, variable=self.vol_var, bootstyle="primary",
                  command=lambda v: self.client.set_volume(int(float(v)))).grid(
            row=0, column=1, sticky="ew", padx=8)
        self.vol_label = self._muted(vol_row, text=f"{int(self.args.volume)}%",
                                     font=(FONT, 9), width=5, anchor="e")
        self.vol_label.grid(row=0, column=2, sticky="e")
        self.vol_var.trace_add(
            "write", lambda *_: self.vol_label.config(text=f"{int(self.vol_var.get())}%"))
        ttb.Button(vol_row, text="选mpv…", width=8, bootstyle="secondary-outline",
                   command=self._pick_mpv).grid(row=0, column=3, padx=(6, 0))
        self._dl_btn = ttb.Menubutton(vol_row, text="下载▾", width=8,
                                      bootstyle="secondary-outline")
        self._dl_btn.grid(row=0, column=4, padx=(6, 0))
        dl_menu = ttb.Menu(self._dl_btn, tearoff=0)
        dl_menu.add_command(label="下载当前歌曲（音频）", command=self._download_song)
        dl_menu.add_command(label="下载当前歌词（.lrc）", command=self._download_lyrics)
        dl_menu.add_command(label="下载歌曲 + 歌词（一起）", command=self._download_both)
        self._dl_btn.configure(menu=dl_menu)
        return info

    def _build_lyric_page(self, parent):
        page = ttb.Frame(parent, padding=8)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        # ttb.Text 会随主题自动换底色/字色；以下标签色在主题切换时由本类重设
        self.lyr = ttb.Text(page, height=10, state="disabled", wrap="word",
                            font=(FONT, 11), relief="flat", padx=10, pady=8,
                            highlightthickness=0, borderwidth=0)
        lyvs = ttb.Scrollbar(page, orient="vertical", command=self.lyr.yview)
        self.lyr.configure(yscrollcommand=lyvs.set)
        self.lyr.grid(row=0, column=0, sticky="nsew")
        lyvs.grid(row=0, column=1, sticky="ns")
        self._lyric_hint("等待歌曲…")
        return page

    def _build_queue_page(self, parent):
        page = ttb.Frame(parent, padding=8)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        qcols = ("n", "d", "liked")
        self.queue_tree = ttb.Treeview(page, columns=qcols, show="headings",
                                       height=9, bootstyle="info")
        for key, text, width, anchor in (("n", "歌曲", 230, "w"),
                                         ("d", "时长/点歌人", 170, "w"),
                                         ("liked", "点赞", 60, "center")):
            self.queue_tree.heading(key, text=text)
            self.queue_tree.column(key, width=width, anchor=anchor)
        qvs = ttb.Scrollbar(page, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=qvs.set)
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        qvs.grid(row=0, column=1, sticky="ns")
        bar = ttb.Frame(page)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttb.Button(bar, text="👍 点赞选中歌曲", bootstyle="success-outline",
                   command=self._like_selected_queue).pack(side="left")
        self._muted(bar, text="服务端只接受自己点的歌点赞；房间开启“点赞排序”时顺序会变",
                    font=(FONT, 8)).pack(side="left", padx=(8, 0))
        return page

    def _build_log_page(self, parent):
        page = ttb.Frame(parent, padding=8)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        self.log = ttb.Text(page, height=9, state="disabled", wrap="word",
                            font=(FONT, 9), relief="flat", padx=8, pady=6,
                            highlightthickness=0, borderwidth=0)
        ls = ttb.Scrollbar(page, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=ls.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        ls.grid(row=0, column=1, sticky="ns")

        opt = ttb.Frame(page)
        opt.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.chat_var = tk.BooleanVar(value=True)
        self.chat_btn = ttb.Checkbutton(opt, text="显示聊天", variable=self.chat_var,
                                        bootstyle="round-toggle")
        self.chat_btn.pack(side="left")
        self._muted(opt, text="在日志里显示房间聊天流", font=(FONT, 8)).pack(
            side="left", padx=(8, 0))
        self.chat_var.trace_add("write", lambda *_: self._sync_chat_text())

        chat_row = ttb.Frame(page)
        chat_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        chat_row.columnconfigure(0, weight=1)
        self.chat_input = ttb.Entry(chat_row, bootstyle="primary")
        self.chat_input.grid(row=0, column=0, sticky="ew")
        self.chat_input.bind("<Return>", lambda e: self._send_chat())
        ttb.Button(chat_row, text="发送", width=6, bootstyle="primary",
                   command=self._send_chat).grid(row=0, column=1, padx=(6, 0))

        nick_row = ttb.Frame(page)
        nick_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        nick_row.columnconfigure(1, weight=1)
        self._muted(nick_row, text="昵称", font=(FONT, 9)).grid(row=0, column=0, sticky="w")
        self.nick_var = tk.StringVar(value="")
        nick = ttb.Entry(nick_row, textvariable=self.nick_var, bootstyle="primary")
        nick.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        nick.bind("<Return>", lambda e: self._apply_nickname())
        ttb.Button(nick_row, text="设置", width=6, bootstyle="info-outline",
                   command=self._apply_nickname).grid(row=0, column=2)
        self._sync_chat_text()
        return page

    # ---------------- 底部状态栏 ---------------- #
    def _build_status_bar(self, shell):
        bar = ttb.Frame(shell, padding=(12, 0, 12, 10))
        bar.grid(row=3, column=0, sticky="ew")
        self.status_var = tk.StringVar(
            value=f"后端 https://{self.args.host}{MUSIC_API} ｜ 未连接")
        ttb.Label(bar, textvariable=self.status_var, font=(FONT, 9)).pack(side="left")
        self.mpv_var = tk.StringVar(value="mpv: …")
        self._muted(bar, textvariable=self.mpv_var, font=(FONT, 9)).pack(side="right")
        self._theme_status = tk.StringVar(value="")
        self._muted(bar, textvariable=self._theme_status, font=(FONT, 9)).pack(
            side="right", padx=(0, 12))
        # 角落：版本号 + 开源协议与致谢入口
        about = ttb.Label(bar, text=f"ℹ 关于 · v{self._version} · GPL-3.0",
                          font=(FONT, 8), bootstyle="info", cursor="hand2")
        about.pack(side="right", padx=(8, 12))
        about.bind("<Button-1>", lambda e: self._show_about())

    def _muted(self, parent, **kwargs):
        """创建“次要文字”标签：颜色随明暗主题自动调整。"""
        label = ttb.Label(parent, **kwargs)
        self._muted_widgets.append(label)
        return label

    # ================================================================= #
    # 主题切换
    # ================================================================= #
    def _current_theme(self) -> str:
        theme = getattr(self.style, "theme", None)
        name = getattr(theme, "name", None)          # 2.x：Style.theme 是 Theme 对象
        if name:
            return str(name)
        try:
            return str(self.style.theme_use() or "")
        except Exception:
            return ""

    def _family_of(self, theme_name: str) -> str:
        for suffix in ("-light", "-dark"):
            if theme_name.endswith(suffix):
                return theme_name[:-len(suffix)]
        return theme_name or (self._families[0] if self._families else "")

    def _pick_theme(self, family: str, mode: str) -> str:
        """风格 + 明暗 → 主题名（不存在时退化为风格名/当前主题）。"""
        for candidate in (f"{family}-{mode}", family):
            if candidate in self._theme_names:
                return candidate
        return ""

    def _initial_theme(self) -> str:
        name = self._requested_theme or str(self._settings.get("theme") or "")
        name = name.strip()
        return name if name in self._theme_names else self._current_theme()

    def _apply_theme(self, name, save=True, quiet=False) -> bool:
        """切到指定主题，并同步控件颜色、菜单勾选与配置持久化。"""
        if not name or name not in self._theme_names:
            self._sync_theme_controls()               # 还原控件显示，避免与真实主题不符
            return False
        if name != self._current_theme():
            try:
                with warnings.catch_warnings():       # 旧版主题名会发弃用警告，这里静音
                    warnings.simplefilter("ignore")
                    self.style.theme_use(name)
            except Exception as exc:
                if not quiet:
                    self._log(f"主题切换失败：{exc}", "warn")
                return False
        self._theme_name = name
        self._sync_theme_controls()
        self._restyle_custom_widgets()
        self._tinted.clear()                          # 已打开的对话框需要按新主题重着色
        if save:
            self._settings["theme"] = name
            _save_settings(self._settings)
        if not quiet:
            self._log(f"已切换主题：{name}", "muted")
        return True

    def _sync_theme_controls(self):
        try:
            self._theme_var.set(self._theme_name)
            self._family_var.set(self._family_of(self._theme_name))
            self._dark_var.set(self.style.theme_mode == "dark")
            self._theme_status.set(f"主题 {self._theme_name}")
        except Exception:
            pass

    def _on_family_selected(self):
        mode = "dark" if self._dark_var.get() else "light"
        self._apply_theme(self._pick_theme(self._family_var.get().strip(), mode))

    def _on_dark_toggle(self):
        mode = "dark" if self._dark_var.get() else "light"
        self._apply_theme(self._pick_theme(self._family_of(self._theme_name), mode))

    def _toggle_theme(self):
        """明暗一键对调（Ctrl+T / F2）。"""
        mode = "light" if self.style.theme_mode == "dark" else "dark"
        self._apply_theme(self._pick_theme(self._family_of(self._theme_name), mode))

    def _random_theme(self):
        if self._theme_names:
            self._apply_theme(random.choice(self._theme_names))

    def _muted_color(self) -> str:
        return MUTED_DARK if self.style.theme_mode == "dark" else MUTED_LIGHT

    def _restyle_custom_widgets(self):
        """把不受 ttk 主题影响的部件（次要文字、文本标签色、对话框底色）重新着色。"""
        colors = self.style.colors
        muted = self._muted_color()
        # 普通 tk 窗口/控件（父类的分享、点歌、关于等对话框）读取选项库取色
        for pattern, value in (("*Background", colors.bg), ("*Foreground", colors.fg),
                               ("*Text*Background", colors.inputbg),
                               ("*Text*Foreground", colors.inputfg),
                               ("*Menu*Background", colors.bg),
                               ("*Menu*Foreground", colors.fg)):
            try:
                self.root.option_add(pattern, value)
            except Exception:
                pass
        for label in list(getattr(self, "_muted_widgets", [])):
            try:
                label.configure(foreground=muted)
            except Exception:
                pass
        self._restyle_text(self.log, {"music": colors.danger, "warn": colors.warning,
                                      "good": colors.success, "muted": muted})
        self._restyle_text(self.lyr, {"cur": colors.primary, "next": colors.fg,
                                      "muted": muted}, bold_tag="cur")

    def _restyle_text(self, widget, tag_colors, bold_tag=None):
        colors = self.style.colors
        try:
            widget.configure(background=colors.inputbg, foreground=colors.inputfg,
                             insertbackground=colors.inputfg,
                             selectbackground=colors.selectbg,
                             selectforeground=colors.selectfg)
        except Exception:
            pass
        for tag, color in tag_colors.items():
            try:
                if tag == bold_tag:
                    widget.tag_configure(tag, foreground=color, font=(FONT, 13, "bold"))
                else:
                    widget.tag_configure(tag, foreground=color)
            except Exception:
                pass

    # ---------------- 父类对话框的深色适配 ---------------- #
    def _retint_dialogs(self):
        """给父类新开的对话框（点歌/分享/关于）换掉硬编码的浅色文字。"""
        theme = self._theme_name
        fresh = {}
        for win in list(self.root.winfo_children()):
            if not isinstance(win, tk.Toplevel):
                continue
            key = str(win)
            fresh[key] = theme
            if self._tinted.get(key) != theme:
                self._retint_dialog(win)
        self._tinted = fresh

    def _retint_dialog(self, win):
        """把对话框里硬编码的文字颜色换成当前主题色。

        第一次见到某个控件时按 `_FG_MAP` 识别其“语义色”，并记在 `_tint_keys`
        里；之后主题再变化时直接按记下的语义色重新取值，因此深浅来回切换都能
        保持正确（否则第二次拿到的已是主题色，就认不出来了）。
        """
        colors = self.style.colors
        table = {"muted": self._muted_color(), "fg": colors.fg, "info": colors.info,
                 "success": colors.success, "warning": colors.warning,
                 "danger": colors.danger}
        found = {}
        stack = [win]
        while stack:
            widget = stack.pop()
            try:
                stack.extend(widget.winfo_children())
            except Exception:
                pass
            name = str(widget)
            try:
                current = str(widget.cget("foreground") or "").strip().lower()
            except Exception:
                current = ""
            key = self._tint_keys.get(name) or _FG_MAP.get(current)
            if key:
                found[name] = key
                try:
                    widget.configure(foreground=table[key])
                except Exception:
                    pass
            if isinstance(widget, tk.Text):        # 关于窗口等文本控件的标签色
                try:
                    for tag in widget.tag_names():
                        tag_key = name + "#" + str(tag)
                        key = (self._tint_keys.get(tag_key)
                               or _FG_MAP.get(str(widget.tag_cget(tag, "foreground")
                                                  or "").strip().lower()))
                        if key:
                            found[tag_key] = key
                            widget.tag_configure(tag, foreground=table[key])
                except Exception:
                    pass
        # 用本次扫描结果替换该窗口的旧记录（同时丢弃已销毁窗口的记录）
        prefix = str(win)
        self._tint_keys = {k: v for k, v in self._tint_keys.items()
                           if not (k == prefix or k.startswith(prefix + "."))}
        self._tint_keys.update(found)

    # ================================================================= #
    # 其它覆写
    # ================================================================= #
    def _refresh(self):
        """刷新房间列表：先在面板上给出可见反馈，再走父类的刷新逻辑。"""
        try:
            self._rooms_hint_var.set("正在获取房间列表…")
        except Exception:
            pass
        super()._refresh()

    def _populate(self, rooms, keyword=""):
        """父类渲染房间表格后，顺带更新「房间数量 / 为空原因」提示。"""
        super()._populate(rooms, keyword)
        try:
            shown = len(self.tree.get_children())
            if not rooms:
                self._rooms_hint_var.set("未获取到房间：请检查网络后点「刷新」重试")
            elif shown == 0:
                self._rooms_hint_var.set(
                    f"没有匹配「{keyword}」的房间（共 {len(rooms)} 个）")
            elif keyword:
                self._rooms_hint_var.set(f"筛选出 {shown} / {len(rooms)} 个房间")
            else:
                self._rooms_hint_var.set(f"共 {shown} 个房间 · 双击进入")
        except Exception:
            pass

    def _sync_chat_text(self):
        """「显示聊天」开关：ttkbootstrap 的开关自带状态显示，只需同步给核心层。"""
        try:
            self.client.show_chat = bool(self.chat_var.get())
        except Exception:
            pass

    def _tick_ui(self):
        """每 0.5s 刷新播放进度条/时长，并顺带给新开的对话框换深色配色。"""
        try:
            music = self._current_music or {}
            duration = int(music.get("duration") or 0)
            if duration > 0:
                elapsed = (time.monotonic() - self._lyric_t0) * 1000.0 if self._lyric_t0 else 0.0
                elapsed = max(0.0, min(elapsed, float(duration)))
                self.progress.configure(value=elapsed * 100.0 / duration)
                now = human_seconds(int(elapsed))
            else:
                self.progress.configure(value=0)
                now = "--:--"
            self._time_var.set(f"{now} / {human_seconds(duration)}")
        except Exception:
            pass
        try:
            self._retint_dialogs()
        except Exception:
            pass
        try:
            self.root.after(500, self._tick_ui)
        except Exception:
            pass                # 窗口已销毁时停止刷新

    def _show_about(self):
        """关于窗口：在父类致谢基础上补充主题界面所用的开源组件。"""
        version = getattr(self, "_version", None) or self._app_version()
        lines = [
            "JusicRoomPlayer " + version + "（一起听歌吧 · 轻量房间客户端）",
            "界面：ttkbootstrap 主题界面（15 套风格 × 明/暗 = 30 种主题）",
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
            "▪ 主题界面 ttkbootstrap（Bootstrap 风格 Tk 主题库）",
            "  https://github.com/israel-dryer/ttkbootstrap   MIT",
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
        text = tk.Text(win, width=74, height=len(lines) + 1, wrap="word",
                       font=(FONT, 9), relief="flat", padx=10, pady=8)
        text.pack(padx=8, pady=(8, 2))
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        ttb.Button(win, text="关闭", bootstyle="primary",
                   command=win.destroy).pack(pady=(2, 8))

    def _on_close(self):
        try:
            self._settings["theme"] = self._theme_name
            geometry = self.root.winfo_geometry()
            if _GEOMETRY_RE.match(geometry):
                self._settings["geometry"] = geometry
            _save_settings(self._settings)
        except Exception:
            pass
        super()._on_close()


# ===================================================================== #
# 启动
# ===================================================================== #
def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="jusic_gui_bootstrap",
        description="Jusic 房间播放器 · ttkbootstrap 主题界面（mpv 内核）")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"Jusic 后端域名（默认 {DEFAULT_HOST}）")
    parser.add_argument("--house", default="", help="启动后自动进入的房间 ID")
    parser.add_argument("--password", default="", help="房间密码")
    parser.add_argument("--mpv", default="", help="mpv.exe 绝对路径")
    parser.add_argument("--volume", type=int, default=90, help="默认音量 0-100")
    parser.add_argument("--theme", default="",
                        help="启动主题，如 dracula-dark / nord-light（默认用上次记住的主题）")
    parser.add_argument("--console", action="store_true",
                        help="保留控制台运行（默认双击时会自动改用 pythonw 无窗口运行）")
    return parser.parse_args(argv)


def _relaunch_without_console(argv) -> bool:
    """直接双击 .py 会附带黑色控制台窗口，这里改用 pythonw.exe 无窗口重启。"""
    if os.name != "nt" or getattr(sys, "frozen", False):
        return False
    if "--console" in argv or os.environ.get("JUSIC_GUI_PYW") == "1":
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
        # 注意：必须用本文件（__file__）作为入口，否则会重启成经典界面
        subprocess.Popen([pyw, os.path.abspath(__file__)] + list(argv),
                         cwd=SCRIPT_DIR, env=env)
        return True
    except Exception:
        return False


def _offline_theme_names():
    """不创建 Style 单例就能拿到的主题名集合。

    注意：ttkbootstrap 2.x 的 Style 一旦创建就绑定到当时的根窗口，之后再新建
    Window 会直接报 “single application root window”；所以启动前校验 --theme
    与配置里的主题名时，只能读数据模块（ttkbootstrap.themes），不能碰 Style。
    """
    names = set()
    try:
        from ttkbootstrap.themes import builtin
        for theme in builtin.CURATED_THEMES:          # 2.0 目录：15 风格 × 明/暗
            family = str(getattr(theme, "name", "") or "")
            if family:
                names.update({family + "-light", family + "-dark"})
    except Exception:
        pass
    try:
        from ttkbootstrap.themes.legacy import STANDARD_THEMES
        names.update(STANDARD_THEMES)                 # 旧版主题名（兼容 --theme darkly）
    except Exception:
        pass
    return names


def _main_impl(raw):
    args = parse_args(raw)
    known = _offline_theme_names()
    offered = [str(getattr(args, "theme", "") or ""),
               str(_load_settings().get("theme") or "")]
    theme = next((c.strip() for c in offered
                  if c.strip() and (not known or c.strip() in known)), DEFAULT_THEME)
    try:
        root = ttb.Window(title="Jusic 房间播放器（主题界面）", themename=theme)
    except Exception as exc:
        _fatal_error("无法创建图形窗口（是否缺少 tkinter / ttkbootstrap？）\n\n" + str(exc))
    gui = BootstrapGui(root, args)
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
                                   "JusicRoomPlayer-theme-error.log"),
                      "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception:
            pass
        _fatal_error("程序运行出错，已写入日志：JusicRoomPlayer-theme-error.log\n\n"
                     + text[-1200:])


if __name__ == "__main__":
    main()
