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
    python jusic_room_player.py --auto-seconds N # 自动运行 N 秒退出（脚本/自测）

退出: 输入 q 回车（或 Ctrl+C）。
"""

import argparse
import os
import sys
import threading

from jusic_core import (DEFAULT_HOST, MUSIC_API, UI_URL,
                        RoomClient, human_seconds, sort_rooms)

try:
    import websockets  # noqa: F401  (确保依赖存在并给出友好提示)
except ImportError:
    sys.exit("缺少依赖 websockets，请先执行:  python -m pip install -r requirements.txt")

MAX_LIST_ROWS = 18


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
            cprint("命令: 序号=进入房间  l=刷新列表  s 关键字=搜索  "
                   "f=全部房间  m=当前播放/队列  q=退出")
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
