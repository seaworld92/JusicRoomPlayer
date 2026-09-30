#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
Jusic 轻量房间播放器 · 命令行版（复用 jusic_core）
====================================================
用法:
    python jusic_room_player.py                  # 交互模式（自动进入默认房 DEFAULT）
    python jusic_room_player.py --house ID       # 直接进入指定房间
    python jusic_room_player.py --chat           # 开启聊天/动态流输出
    python jusic_room_player.py --mpv PATH       # 手动指定 mpv.exe 路径
    python jusic_room_player.py --source qq      # 点歌默认音源（wy/qq/kw/kg/mg）
    python jusic_room_player.py --auto-seconds N # 自动运行 N 秒退出（脚本/自测）

交互命令（输入 ? 查看）:
    序号            进入对应房间（配合 l / s / f 使用）
    l / s 关键字 / f  刷新房间列表 / 搜索房间 / 显示全部房间
    m               查看当前播放与点歌队列
    p 关键字        搜索歌曲（点歌用），ph 热歌榜，pn 加载更多
    pick 序号 [flac] 把搜索结果第 N 首加入房间队列（默认 320k，加 flac 为高清）
    src [音源]      查看/切换点歌音源（wy/qq/kw/kg/mg 或 网易/QQ/酷我/酷狗/咪咕）
    q / Ctrl+C      退出
"""

import argparse
import os
import sys
import threading

from jusic_core import (DEFAULT_HOST, MUSIC_API, SONG_SOURCE_CODES, UI_URL,
                        RoomClient, human_seconds, song_album,
                        song_unavailable, sort_rooms, source_code)

try:
    import websockets  # noqa: F401  (确保依赖存在并给出友好提示)
except ImportError:
    sys.exit("缺少依赖 websockets，请先执行:  python -m pip install -r requirements.txt")

MAX_LIST_ROWS = 18
SEARCH_WAIT = 12          # 等待点歌搜索结果的秒数（超时给提示）
SOURCE_LABELS = list(SONG_SOURCE_CODES.items())     # [(显示名, 音源代码), ...]
QUALITY_HIGH = ("flac", "high", "h", "高清")
QUALITY_STD = ("320k", "320", "std", "s", "标准")


def cprint(text: str = "", end: str = "\n"):
    try:
        sys.stdout.write(text + end)
        sys.stdout.flush()
    except Exception:
        pass


class ConsoleUI:
    def __init__(self, args):
        self.args = args
        self.all_rooms = []
        self.rows = []                 # 当前展示（排序/过滤后的快照）
        self.exited = False
        self.rooms_loaded = threading.Event()

        # 点歌状态
        self.source = source_code(getattr(args, "source", "wy"))
        if self.source not in {code for _, code in SOURCE_LABELS}:
            self.source = "wy"
        self.song_keyword = ""
        self.song_rows = []            # 已累积的搜索结果（pick 序号 用它的下标）
        self.song_page = 0
        self.song_total = 0
        self._search_ev = None         # 同步等待搜索结果用
        self._search_data = None

        self.client = RoomClient(
            host=args.host, volume=args.volume, mpv_path=args.mpv,
            show_chat=args.chat, listener=self._on_event,
        )

    # ---------------- 事件 -> 打印 ---------------- #
    def _on_event(self, event, data):
        if event == "rooms":
            self.all_rooms = list(data or [])
            self.rows = sort_rooms(self.all_rooms)
            self.show_rooms()
            self.rooms_loaded.set()
        elif event == "music":
            m = data or {}
            cprint(f"[♪] {m.get('name')} - {m.get('artist')}  "
                   f"{human_seconds(m.get('duration'))}")
        elif event == "queue":
            pass                            # 已由 log 摘要提示
        elif event == "search":
            self._search_data = data or {}
            ev = self._search_ev
            if ev is not None:
                ev.set()                    # 唤醒正在等结果的搜索命令
        elif event == "online":
            pass
        elif event == "chat":
            cprint(f"[聊天] {data.get('name')}: {data.get('text')}")
        elif event == "notice":
            cprint(f"[通知] {data}")
        elif event == "announce":
            cprint(f"[公告] {(data or {}).get('content', '')[:200]}")
        elif event == "error":
            cprint(f"[错误] {data}")
        elif event == "log":
            cprint(f"  · {data}")
        elif event == "reconnecting":
            cprint(f"[连接] {data}")
        elif event == "disconnected":
            cprint("[连接] 已断开")
        elif event == "stopped":
            pass

    # ---------------- 展示 ---------------- #
    def show_rooms(self, rows=None, page_all=False):
        rows = self.rows if rows is None else rows
        if not rows:
            cprint("（当前没有匹配的房间）")
            return
        limit = len(rows) if page_all else MAX_LIST_ROWS
        cprint(f"{'序号':<6}{'房间':<30}{'在线':>5}  简介")
        for idx, r in enumerate(rows[:limit], 1):
            pwd = "锁" if r.get("needPwd") else "·"
            cprint(f"{idx:<6}{str(r.get('name') or '')[:29]:<30}"
                   f"{r.get('population') or 0:>5}  {pwd}  {str(r.get('desc') or '')[:24]}")
        if len(rows) > limit:
            cprint(f"… 还有 {len(rows) - limit} 个房间（输入 f 显示全部）")

    def show_now(self):
        c = self.client
        if c.room:
            cprint(f"[当前房间] {c.room.get('name')}  (在线 {c.online})")
        if c.current:
            m = c.current
            cprint(f"[正在播放] {m.get('name')} - {m.get('artist')}  "
                   f"{human_seconds(m.get('duration'))}")
        else:
            cprint("[正在播放] （暂无歌曲，房间可能在放歌间隙）")
        if c.queue:
            cprint(f"[点歌队列] {len(c.queue)} 首：")
            for i, s in enumerate(c.queue[:5], 1):
                cprint(f"   {i}. {s.get('name')} - {s.get('artist')} "
                       f"(点: {s.get('nickName') or s.get('picker') or '?'})")
        else:
            cprint("[点歌队列] 空")

    # ---------------- 点歌（搜索曲库 / 加入队列） ---------------- #
    def source_label(self):
        return next((label for label, code in SOURCE_LABELS if code == self.source),
                    self.source)

    def show_songs(self, offset=0):
        """列出点歌搜索结果；offset 之前的行视为已打印过（加载更多时只看新增）。"""
        for i, song in enumerate(self.song_rows):
            if i < offset:
                continue
            name = str(song.get("name") or "未知歌曲")
            artist = str(song.get("artist") or "未知歌手")
            album = song_album(song)
            meta = f"{artist} · {album}" if album else artist
            flag = "[不可用] " if song_unavailable(song) else ""
            cprint(f"{i + 1:>3}. {flag}{name} - {meta}  "
                   f"({human_seconds(song.get('duration'))})")

    def cmd_source(self, token=""):
        """查看/切换点歌音源：src、src QQ、src 2。"""
        token = (token or "").strip()
        if not token:
            cprint(f"[点歌] 当前音源：{self.source_label()}（{self.source}）")
            for i, (label, code) in enumerate(SOURCE_LABELS, 1):
                mark = "  ←当前" if code == self.source else ""
                cprint(f"   {i}. {label}({code}){mark}")
            cprint("   切换示例：src QQ   或   src 2")
            return
        chosen = None
        if token.isdigit() and 1 <= int(token) <= len(SOURCE_LABELS):
            chosen = SOURCE_LABELS[int(token) - 1][1]
        else:
            code = source_code(token)
            if any(code == c for _, c in SOURCE_LABELS):
                chosen = code
        if not chosen:
            cprint(f"[点歌] 未知音源：{token}（输入 src 查看可用音源）")
            return
        self.source = chosen
        cprint(f"[点歌] 音源已切换为 {self.source_label()}（{chosen}）")

    def cmd_search_songs(self, keyword, reset=True):
        """搜索歌曲并同步等待结果（reset=False 表示 pn 加载下一页）。"""
        if not self.client.connected:
            cprint("[点歌] 尚未连接到房间，无法搜索")
            return
        keyword = (keyword or "").strip()
        if not keyword:
            cprint("[点歌] 请给出关键词，例如：p 晴天")
            return
        if reset:
            self.song_keyword = keyword
            self.song_rows = []
            self.song_page = 0
            self.song_total = 0
        page = self.song_page + 1
        label = self.source_label()
        cprint(f"[点歌] 搜索「{keyword}」（{label}，第 {page} 页）…")

        ev = threading.Event()
        self._search_data, self._search_ev = None, ev
        if not self.client.search_songs(keyword, self.source, page):
            self._search_ev = None
            cprint("[点歌] 搜索关键词为空")
            return
        if not ev.wait(timeout=SEARCH_WAIT):
            self._search_ev = None
            cprint(f"[点歌] 搜索超时（{SEARCH_WAIT}s）：请重试或换个音源（src）")
            return
        data = self._search_data or {}
        self._search_ev = None

        songs = list(data.get("songs") or [])
        self.song_page = page
        self.song_total = int(data.get("total") or 0)
        start = len(self.song_rows)
        self.song_rows.extend(songs)
        if not self.song_rows:
            cprint(f"[点歌] 没有找到「{keyword}」，换个关键词或音源（src）试试")
            return
        cprint(f"[点歌] 共 {self.song_total} 首，已列出 {len(self.song_rows)} 首：")
        self.show_songs(offset=start)
        hint = "pick 序号 点歌（要高清就加 flac，如 pick 2 flac）"
        if len(self.song_rows) < self.song_total:
            hint += "；pn 加载更多"
        cprint(f"   提示：{hint}")

    def cmd_pick(self, token):
        """pick 序号 [flac]：把搜索结果里的某首加入房间点歌队列。"""
        parts = (token or "").split()
        if not parts:
            cprint("[点歌] 用法：pick 序号 [flac]（先用 p 关键词 搜索）")
            return
        quality = "320k"
        if len(parts) > 1:
            flag = parts[1].lower()
            if flag in QUALITY_HIGH:
                quality = "flac"
            elif flag not in QUALITY_STD:
                cprint(f"[点歌] 未知音质：{parts[1]}（可用 320k/标准 或 flac/高清）")
                return
        try:
            idx = int(parts[0])
        except ValueError:
            cprint(f"[点歌] 序号应为数字：{parts[0]}")
            return
        if not 1 <= idx <= len(self.song_rows):
            cprint(f"[点歌] 序号超出范围：当前搜索结果共 {len(self.song_rows)} 首"
                   f"（先用 p 关键词 搜索）")
            return
        if not self.client.connected:
            cprint("[点歌] 尚未连接到房间，无法点歌")
            return
        song = self.song_rows[idx - 1]
        if song_unavailable(song):
            cprint("[点歌] 这首在当前音源不可用，换一首或换音源（src）")
            return
        label = "高清(FLAC)" if quality == "flac" else "标准(320k)"
        name = str(song.get("name") or "")
        artist = str(song.get("artist") or "")
        if self.client.pick_song(song.get("id"), name, self.source, quality):
            cprint(f"[点歌] 已发送（{label}）：{name} - {artist}")
            cprint("   （服务端确认后会打印「[通知] 点歌成功」并刷新队列）")
        else:
            cprint("[点歌] 点歌失败：歌曲 id 无效")

    # ---------------- 命令 ---------------- #
    def _resolve_index(self, token):
        try:
            idx = int(token)
        except ValueError:
            return -1
        if 1 <= idx <= len(self.rows):
            return idx - 1
        return -1

    def handle(self, line: str):
        line = line.strip()
        if not line:
            return
        low = line.lower()
        if low in ("q", "quit", "exit"):
            self.exited = True
            return
        if low in ("?", "h", "help"):
            cprint("房间: 序号=进入房间  l=刷新列表  s 关键字=搜索房间  "
                   "f=全部房间  m=当前播放/队列")
            cprint("点歌: p 关键字=搜索歌曲  pick 序号 [flac]=点歌  pn=加载更多  "
                   "ph=热歌榜  src [音源]=查看/切换音源")
            cprint("其它: q=退出（Ctrl+C 同样退出）")
            return
        if low == "l":
            self.client.refresh_rooms()
            return
        if low == "m":
            self.show_now()
            return
        if low == "f":
            self.show_rooms(rows=sort_rooms(self.all_rooms), page_all=True)
            return
        if low.startswith("s "):
            kw = line[2:].strip().lower()
            rows = [r for r in sort_rooms(self.all_rooms)
                    if kw in str(r.get("name") or "").lower()
                    or kw in str(r.get("desc") or "").lower()]
            self.rows = rows
            self.show_rooms()
            return
        # ---- 点歌 ----
        if low.startswith("p "):
            self.cmd_search_songs(line[2:].strip(), reset=True)
            return
        if low == "pn":
            if not self.song_keyword:
                cprint("[点歌] 还没搜索过：先用 p 关键词 搜索")
                return
            self.cmd_search_songs(self.song_keyword, reset=False)
            return
        if low == "ph":
            self.cmd_search_songs("*热歌榜", reset=True)
            return
        if low == "pick" or low.startswith("pick "):
            self.cmd_pick(line[4:])
            return
        if line == "点" or line.startswith("点 "):
            self.cmd_pick(line[1:])
            return
        if low == "src" or line == "音源":
            self.cmd_source()
            return
        if low.startswith("src "):
            self.cmd_source(line[4:])
            return
        if line.startswith("音源 "):
            self.cmd_source(line[3:])
            return
        idx = self._resolve_index(line)
        if idx >= 0:
            room = self.rows[idx]
            name = room.get("name") or room.get("id")
            c = self.client
            if c.room and str(c.room.get("id")) == str(room.get("id")) and c.connected:
                cprint(f"[已在该房间] {name}")
                return
            password = ""
            if room.get("needPwd"):
                try:
                    password = input(f"房间「{name}」需要密码: ").strip()
                except EOFError:
                    return
            cprint(f"[操作] 切换到房间：{name}")
            self.client.enter_room(str(room.get("id")), password)
            return
        cprint(f"未知命令：{line}（输入 ? 查看帮助）")

    # ---------------- 主循环 ---------------- #
    def run(self):
        cprint("=" * 60)
        cprint(" Jusic 轻量房间播放器（命令行） · mpv 内核低内存方案")
        cprint(f" 后端: https://{self.host()}{MUSIC_API}   网页UI: {UI_URL}")
        cprint(f" 点歌音源: {self.source_label()}（{self.source}），切换用 src 命令")
        cprint(" 输入 ? 查看命令，q 退出")
        cprint("=" * 60)
        self.client.start()
        self.client.refresh_rooms()

        # 等待首屏房间列表
        if not self.rooms_loaded.wait(timeout=30):
            cprint("[加载] 房间列表获取超时")
        target_id = self.args.house
        if target_id:
            self.client.enter_room(target_id, self.args.password or "")
        elif self.all_rooms:
            default = next((r for r in self.all_rooms if str(r.get("id")) == "DEFAULT"),
                           self.all_rooms[0])
            self.client.enter_room(str(default.get("id")), self.args.password or "")

        # 自动（无人值守）模式
        if self.args.auto_seconds:
            import time
            cprint(f"[auto] 运行 {self.args.auto_seconds}s 后自动退出…")
            time.sleep(self.args.auto_seconds)
            self.exited = True

        while not self.exited:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                cprint()
                break
            self.handle(line)

        self.client.stop()
        cprint("已退出。")

    def host(self):
        return self.args.host


def parse_args(argv):
    p = argparse.ArgumentParser(prog="jusic_room_player",
                                description="轻量『一起听歌吧』房间播放器（mpv 内核，低内存）")
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"Jusic 后端域名（默认 {DEFAULT_HOST}）")
    p.add_argument("--house", default="", help="直接进入的房间 ID")
    p.add_argument("--password", default="", help="房间密码")
    p.add_argument("--mpv", default="", help="mpv.exe 绝对路径")
    p.add_argument("--chat", action="store_true", help="在控制台显示房间聊天流")
    p.add_argument("--volume", type=int, default=90, help="播放音量 0-100")
    p.add_argument("--source", default="wy",
                   help="点歌默认音源：wy/qq/kw/kg/mg（也可写 网易/QQ/酷我/酷狗/咪咕）")
    p.add_argument("--auto-seconds", type=float, default=0,
                   help="自动运行指定秒数后退出（便于脚本/自测）")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            if stream and hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass
    ui = ConsoleUI(args)
    try:
        ui.run()
    except KeyboardInterrupt:
        pass
    finally:
        ui.client.stop()


if __name__ == "__main__":
    main()
