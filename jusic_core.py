#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
jusic_core：Jusic 房间播放器共享核心库
========================================
命令行版(jusic_room_player.py)与 GUI 版(jusic_gui.py)共用的无界面客户端核心：

* REST   : 房间列表 (POST /api/house/search)
* WSS    : 直连后端 SockJS WebSocket，纯监听即可获得 MUSIC/PICK/ONLINE/CHAT 等推送
* 播放   : 把 MUSIC 中的真实播放地址交给 mpv 进程（极轻量播放内核）
* 线程模型: RoomClient.start() 后自动在后台线程中运行 asyncio 事件循环，
            所有对外方法均为线程安全；状态通过 listener(evt, data) 回调传出。
"""

import asyncio
import http.client
import json
import os
import random
import re
import shutil
import ssl
import string
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlparse

try:
    import websockets
except ImportError:
    raise SystemExit("缺少依赖 websockets，请先执行:  python -m pip install -r requirements.txt")

# --------------------------------------------------------------------------- #
# 基本设置
# --------------------------------------------------------------------------- #
DEFAULT_HOST = "tx.alang.run"           # Jusic 后端域名
UI_URL = "https://happy.alang.run/modern-ui/"      # 网页 UI（协议同源）
MUSIC_API = "/api"                      # REST / WS 统一前缀

MAX_ROOM_RETRY = 6                      # 断线最大自动重连次数
RECONNECT_WAIT = 5                      # 重连基础等待（秒，指数退避）


def human_seconds(ms) -> str:
    if not ms:
        return "--:--"
    sec = int(ms) // 1000
    return f"{sec // 60:02d}:{sec % 60:02d}"


# --------------------------------------------------------------------------- #
# LRC 歌词解析与检索
# --------------------------------------------------------------------------- #
_LRC_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lyrics(lrc_text):
    """把 LRC 文本解析为按时间排序的 [(start_ms, text), ...]。

    兼容标准 LRC 的 [mm:ss.xx] / [mm:ss:xxx]，也兼容多个时间标签占一行、
    以及 [ar:...] 等元信息行（自动忽略）。
    """
    lyrics = []
    if not lrc_text:
        return lyrics
    for line in lrc_text.splitlines():
        tags = list(_LRC_TAG.finditer(line))
        if not tags:
            continue
        text = _LRC_TAG.sub("", line).strip()
        if not text:
            continue
        for tag in tags:
            minutes = int(tag.group(1))
            seconds = int(tag.group(2))
            frac = tag.group(3)
            ms = (minutes * 60 + seconds) * 1000
            if frac:
                if len(frac) == 2:          # [mm:ss.xx] 百分秒
                    ms += int(frac) * 10
                elif len(frac) == 1:        # [mm:ss.x]
                    ms += int(frac) * 100
                else:                       # [mm:ss:xxx] 毫秒
                    ms += int(frac)
            lyrics.append((ms, text))
    lyrics.sort(key=lambda item: item[0])
    return lyrics


def lyric_index(lyrics, t_ms: float):
    """返回 t_ms 时刻应高亮的歌词下标；t 在首句之前返回 -1，之后返回最后一句。"""
    lo, hi = 0, len(lyrics)
    while lo < hi:
        mid = (lo + hi) // 2
        if lyrics[mid][0] <= t_ms:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


# --------------------------------------------------------------------------- #
# 下载工具（保存当前歌曲 / 歌词）
# --------------------------------------------------------------------------- #
class DownloadCancelled(Exception):
    pass


_INVALID_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def sanitize_filename(name, fallback="song"):
    """把歌曲名/歌手清洗成合法的 Windows 文件名（不含扩展名）。"""
    text = _INVALID_FILENAME.sub("_", str(name or "")).strip(" .")
    text = re.sub(r"\s+", " ", text)
    return text[:120] or fallback


_AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"}


def guess_audio_ext(url, source=""):
    """从下载地址推断音频扩展名，失败则按音源/默认给 .mp3。"""
    try:
        ext = os.path.splitext(urlparse(url).path)[1].lower()
    except Exception:
        ext = ""
    if ext in _AUDIO_EXTS:
        return ext
    return {"qq": ".m4a", "mg": ".mp3"}.get(source or "", ".mp3")


def download_file(url, dest, progress=None, timeout=30, chunk_size=64 * 1024,
                  stop_event=None, user_agent="Mozilla/5.0"):
    """流式下载 url 到 dest。

    progress(done_bytes, total_bytes) 会周期性回调（total 未知时为 0）；
    stop_event 为 threading.Event，置位后抛出 DownloadCancelled。
    返回 (已下载字节数, 总字节数)。
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    done = 0
    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except Exception:
                total = 0
            with open(tmp, "wb") as fh:
                while True:
                    if stop_event is not None and stop_event.is_set():
                        raise DownloadCancelled("用户取消下载")
                    buf = resp.read(chunk_size)
                    if not buf:
                        break
                    fh.write(buf)
                    done += len(buf)
                    if progress is not None:
                        try:
                            progress(done, total)
                        except Exception:
                            pass
        os.replace(tmp, dest)
        return done, total
    except BaseException:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


# --------------------------------------------------------------------------- #
# TLS：目标服务器会拒绝部分 TLS1.3 客户端的握手，固定 TLS1.2；
# 默认校验证书，构造失败时自动降级为不校验。
# --------------------------------------------------------------------------- #
def make_ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


_ssl_ctx = None


def ssl_context() -> ssl.SSLContext:
    global _ssl_ctx
    if _ssl_ctx is not None:
        return _ssl_ctx
    try:
        _ssl_ctx = make_ssl_context(True)
    except Exception:
        _ssl_ctx = make_ssl_context(False)
    return _ssl_ctx


# --------------------------------------------------------------------------- #
# 轻量 REST 客户端（标准库 http.client，不引入 requests）
# --------------------------------------------------------------------------- #
def api_post(host: str, path: str, payload=None, timeout: int = 12):
    body = json.dumps(payload or {}, ensure_ascii=False)
    conn = http.client.HTTPSConnection(host, 443, context=ssl_context(), timeout=timeout)
    try:
        conn.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "AccessToken": "token",           # 与网页端一致，匿名即可
                "User-Agent": "JusicRoomPlayer/1.0",
                "Origin": UI_URL,
            },
        )
        resp = conn.getresponse()
        data = resp.read().decode("utf-8", "replace")
        return resp.status, data
    finally:
        conn.close()


def get_rooms(host: str):
    """POST /api/house/search -> list[room]"""
    code, text = api_post(host, MUSIC_API + "/house/search", {})
    if code != 200:
        raise RuntimeError(f"房间列表请求失败 HTTP {code}")
    obj = json.loads(text)
    if str(obj.get("code")) != "20000":
        raise RuntimeError(obj.get("message") or "房间列表接口返回异常")
    return obj.get("data") or []


# --------------------------------------------------------------------------- #
# 帧解析：后端通过 SockJS 推来“类 STOMP”自定义文本帧
# --------------------------------------------------------------------------- #
EVENT_TYPES = {
    "NOTICE", "ONLINE", "CHAT", "PICK", "MUSIC", "SETTING_NAME", "AUTH",
    "AUTH_ROOT", "AUTH_ADMIN", "SEARCH", "SEARCH_PICTURE", "VOLUMN",
    "GOODMODEL", "SEARCH_HOUSE", "ENTER_HOUSE", "ENTER_HOUSE_START",
    "ADD_HOUSE", "ADD_HOUSE_START", "SEARCH_SONGLIST", "SEARCH_USER",
    "ANNOUNCEMENT", "HOUSE_USER", "CIRCLEMODEL", "LISTMODEL",
}


def parse_frame(text):
    if not isinstance(text, str):
        return None
    if text.startswith("a"):
        try:
            text = json.loads(text[1:])[0]
        except Exception:
            return None
    if text in ("o", "h"):
        return None
    nl = text.find("\n")
    if nl <= 0:
        return None
    mtype = text[:nl]
    if mtype not in EVENT_TYPES:
        return None
    sep = text.find("\n\n")
    if sep < 0:
        return None
    try:
        body = json.loads(text[sep + 2:])
    except Exception:
        return None
    return mtype, body


def stomp_frame(command, headers=None, body=""):
    """构造 STOMP 帧文本（以 NUL 结尾）。"""
    lines = [command]
    for key, value in (headers or {}).items():
        lines.append(f"{key}:{value}")
    return "\n".join(lines) + "\n\n" + body + "\x00"


# --------------------------------------------------------------------------- #
# mpv 播放引擎
# --------------------------------------------------------------------------- #
class MpvEngine:
    """每首新歌启动一个纯音频 mpv 进程，播完自动退出；内存占用小。"""

    def __init__(self, volume: int = 90, mpv_path: str = ""):
        self._proc = None
        self._lock = threading.Lock()
        self.volume = max(0, min(100, int(volume)))
        self.mpv_path = mpv_path

    @staticmethod
    def find_mpv(explicit=""):
        candidates = []
        if explicit:
            candidates.append(explicit)
        env = os.environ.get("JUSIC_MPV")
        if env:
            candidates.append(env)
        found = shutil.which("mpv")
        if found:
            candidates.append(found)
        candidates += [
            r"C:\Program Files\MPV Player\mpv.exe",
            r"C:\Program Files (x86)\MPV Player\mpv.exe",
        ]
        try:
            wg = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                              "Microsoft", "WinGet", "Packages")
            if os.path.isdir(wg):
                for root, dirs, files in os.walk(wg):
                    if "mpv.exe" in files:
                        candidates.append(os.path.join(root, "mpv.exe"))
                    if root.count(os.sep) - wg.count(os.sep) > 2:
                        dirs[:] = []
        except Exception:
            pass
        for cand in candidates:
            if cand and os.path.isfile(cand):
                return cand
        return None

    def stop(self):
        with self._lock:
            self._stop_locked()

    def _stop_locked(self):
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._proc = None

    def play(self, url: str):
        """播放新地址（自动停止上一首）。找不到 mpv 时抛 RuntimeError。"""
        if not url:
            return False
        with self._lock:
            self._stop_locked()
            exe = MpvEngine.find_mpv(self.mpv_path)
            if not exe:
                raise RuntimeError(
                    "找不到 mpv.exe。请先安装 mpv（winget install shinchiro.mpv）或"
                    "在设置里指定 mpv 路径。"
                )
            args = [
                exe,
                "--no-config", "--no-video", "--force-window=no",
                "--audio-display=no", "--vo=null", "--no-terminal",
                "--really-quiet", "--msg-level=all=error",
                "--user-agent=Mozilla/5.0",
                "--demuxer-max-bytes=8MiB",        # 限制内存缓存
                "--demuxer-max-back-bytes=1MiB",
                f"--volume={self.volume}",
                url,
            ]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                self._proc = subprocess.Popen(
                    args, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
                return True
            except Exception as exc:
                self._proc = None
                raise RuntimeError(f"mpv 启动失败: {exc}")

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


# --------------------------------------------------------------------------- #
# RoomClient：事件化的房间客户端（后台线程 asyncio 循环）
# --------------------------------------------------------------------------- #
class RoomClient:
    """
    事件回调: listener(event, data)
      rooms       -> list[room]
      connected   -> dict {id,name}
      disconnected-> str 原因
      reconnecting-> str 提示
      music       -> dict MUSIC(含 url/name/artist/lyric/duration/pictureUrl)
      queue       -> list[MUSIC]
      online      -> int
      chat        -> dict  (仅 show_chat=True 时)
      notice      -> str
      announce    -> dict
      log         -> str  普通状态文本
      error       -> str  错误文本
      stopped     -> None
    """

    def __init__(self, host: str = DEFAULT_HOST, volume: int = 90,
                 mpv_path: str = "", listener=None, show_chat: bool = False):
        self.host = host
        self.show_chat = show_chat
        self._listener = listener
        self.engine = MpvEngine(volume=volume, mpv_path=mpv_path)

        # 状态（可从外部线程读取）
        self.rooms = []
        self.room = None          # 当前房间 dict
        self.current = None       # 当前 MUSIC
        self.queue = []
        self.online = 0
        self.connected = False

        self._thread = None
        self._loop = None
        self._cmd_q = None
        self._ready = threading.Event()
        self._ws = None                   # 当前 WebSocket（仅事件循环线程访问）
        self._pending_cmds = []           # 连接建立前缓存的待发指令
        self._session_task = None
        self._leave_room = False
        self._playing_id = None
        self._lock = threading.Lock()
        self._started = threading.Event()

    # ---------------- 线程安全请求 ---------------- #
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, daemon=True,
                                        name="jusic-roomclient")
        self._thread.start()
        self._ready.wait(timeout=10)

    def stop(self, join: bool = True):
        # 先在调用方线程同步终止 mpv，避免任何线程时序导致“关窗后仍在播放”
        self.engine.stop()
        if self._loop and self._cmd_q is not None:
            self._submit(("stop",))
            if join and self._thread:
                self._thread.join(timeout=5)

    def refresh_rooms(self, silent: bool = False):
        """silent=True 时不输出“正在获取房间列表…”等日志（用于定时自动刷新）。"""
        self._submit(("refresh", silent))

    def enter_room(self, room_id: str, password: str = ""):
        self._submit(("enter", str(room_id), password or ""))

    def leave_room(self):
        self._submit(("leave",))

    def command(self, destination: str, body: str = ""):
        """向房间发送 STOMP SEND 指令（线程安全，异步执行）。"""
        self._submit(("command", destination, body or ""))

    def skip_vote(self):
        """切歌：/music/skip/vote（普通成员为投票切歌，管理员将直接切歌）。"""
        self.command("/music/skip/vote")

    def send_chat(self, text: str):
        """发送房间聊天消息：SEND /chat {content, sendTime}。"""
        text = (text or "").strip()
        if not text:
            return False
        body = json.dumps({"content": text, "sendTime": int(time.time() * 1000)},
                          ensure_ascii=False)
        self.command("/chat", body)
        return True

    def set_nickname(self, name: str):
        """设置房间内昵称：SEND /setting/name {name, sendTime}。"""
        name = (name or "").strip()
        if not name:
            return False
        body = json.dumps({"name": name, "sendTime": int(time.time() * 1000)},
                          ensure_ascii=False)
        self.command("/setting/name", body)
        return True

    def set_volume(self, value: int):
        self.engine.volume = max(0, min(100, int(value)))

    def _submit(self, item):
        if self._loop and self._cmd_q is not None:
            try:
                self._loop.call_soon_threadsafe(self._cmd_q.put_nowait, item)
            except Exception:
                pass

    # ---------------- 事件发射 ---------------- #
    def _emit(self, event, data=None):
        cb = self._listener
        if cb is None:
            return
        try:
            cb(event, data)
        except Exception:
            pass

    def _log(self, text):
        self._emit("log", text)

    # ---------------- 后台 asyncio 线程 ---------------- #
    def _thread_main(self):
        asyncio.run(self._amain())

    async def _amain(self):
        self._loop = asyncio.get_running_loop()
        self._cmd_q = asyncio.Queue()
        self._ready.set()
        while True:
            cmd = await self._cmd_q.get()
            kind = cmd[0]
            if kind == "refresh":
                await self._do_refresh(cmd[1] if len(cmd) > 1 else False)
            elif kind == "enter":
                await self._do_enter(cmd[1], cmd[2])
            elif kind == "command":
                await self._do_command(cmd[1], cmd[2] if len(cmd) > 2 else "")
            elif kind == "leave":
                await self._do_leave()
            elif kind == "stop":
                break
        await self._do_leave()
        self.engine.stop()
        self._emit("stopped")

    async def _do_refresh(self, silent: bool = False):
        if not silent:
            self._log("正在获取房间列表…")
        try:
            loop = asyncio.get_running_loop()
            rooms = await loop.run_in_executor(None, get_rooms, self.host)
            with self._lock:
                self.rooms = rooms
            self._emit("rooms", rooms)
            if not silent:
                self._log(f"共 {len(rooms)} 个房间")
        except Exception as exc:
            self._emit("error", f"获取房间列表失败: {exc}")

    async def _do_command(self, destination, body=""):
        """发送 STOMP SEND 指令；连接尚未建立时先缓存，连上后自动补发。"""
        if self._ws is None:
            with self._lock:
                self._pending_cmds.append((destination, body))
            return
        await self._send_now(destination, body)

    async def _send_now(self, destination, body=""):
        """立即发送 STOMP SEND 指令。

        注意：SockJS 的 WebSocket transport 要求客户端把 STOMP 帧放进
        JSON 数组里发送（如 ["SEND\\n...\\x00"]），直接发明文会被服务端
        以 c[1011] 关闭连接。
        """
        ws = self._ws
        if ws is None:
            with self._lock:
                self._pending_cmds.append((destination, body))
            return
        try:
            text = body or ""
            data = text.encode("utf-8")
            frame = stomp_frame("SEND", {
                "destination": destination,
                "content-type": "application/json;charset=utf-8",
                "content-length": str(len(data)),
            }, text)
            await ws.send(json.dumps([frame]))
            self._emit("command-sent", {"destination": destination})
        except Exception as exc:
            self._emit("error", f"发送指令失败: {exc}")

    async def _do_enter(self, room_id, password):
        if self._session_task and not self._session_task.done():
            self._leave_room = True
            self._session_task.cancel()
            try:
                await self._session_task
            except BaseException:
                pass
            self._session_task = None
        self._leave_room = False
        self.engine.stop()
        with self._lock:
            self.current = None
            self.queue = []
            self.online = 0
            self.connected = False
            name = room_id
            if room_id in {r.get("id") for r in self.rooms}:
                name = next((r.get("name") or room_id) for r in self.rooms if r.get("id") == room_id)
            self.room = {"id": room_id, "name": name, "password": password}
        self._emit("connected", dict(self.room))
        self._log(f"正在进入房间：{name} …")
        self._session_task = asyncio.ensure_future(self._session_loop(room_id, password))

    async def _do_leave(self):
        if self._session_task and not self._session_task.done():
            self._leave_room = True
            self._session_task.cancel()
            try:
                await self._session_task
            except BaseException:
                pass
            self._session_task = None
        self.engine.stop()
        self._leave_room = False
        with self._lock:
            self.current = None
            self.queue = []
            self.online = 0
            self.connected = False
            self.room = None

    async def _session_loop(self, room_id, password):
        retry = 0
        while not self._leave_room:
            sess = "".join(random.choices(string.ascii_letters + string.digits, k=8))
            q = f"houseId={room_id}&housePwd={password or ''}&connectType=enter"
            url = f"wss://{self.host}{MUSIC_API}/server/000/{sess}/websocket?{q}"
            try:
                async with websockets.connect(
                    url,
                    ssl=ssl_context(),
                    proxy=None,                     # 直连，绕开本机系统代理干扰
                    origin=UI_URL,
                    additional_headers={"User-Agent": "JusicRoomPlayer/1.0"},
                    open_timeout=15,
                    ping_interval=30,
                    ping_timeout=12,
                ) as ws:
                    retry = 0
                    self._ws = ws
                    try:
                        # 发送 STOMP CONNECT 以便后续能发送指令（投票切歌等）。
                        # SockJS websocket 要求把帧放进 JSON 数组发送。
                        try:
                            await ws.send(json.dumps([stomp_frame(
                                "CONNECT",
                                {"accept-version": "1.1,1.0", "heart-beat": "0,0"})]))
                        except Exception:
                            pass
                        with self._lock:
                            self.connected = True
                            pending, self._pending_cmds = self._pending_cmds, []
                        for dest, payload in pending:      # 补发连接前缓存的指令
                            await self._send_now(dest, payload)
                        ready_payload = dict(self.room) if self.room else {}
                        ready_payload["ready"] = True
                        self._emit("connected", ready_payload)
                        self._log(f"已进入房间：{self.room.get('name') if self.room else room_id}")
                        while not self._leave_room:
                            msg = await ws.recv()
                            if isinstance(msg, bytes):
                                msg = msg.decode("utf-8", "replace")
                            self._handle_frame(parse_frame(msg))
                    finally:
                        self._ws = None
                if not self._leave_room:
                    self._log("连接已断开")
                break
            except asyncio.CancelledError:
                raise
            except websockets.ConnectionClosed as exc:
                self._log(f"连接通道关闭 ({exc.code})")
            except Exception as exc:
                text = str(exc)
                if "403" in text or "handshake" in text.lower() or "rejected" in text.lower():
                    self._emit("error", "进入房间失败（密码错误或房间不存在）")
                    with self._lock:
                        self.connected = False
                    return
                self._log(f"连接异常: {type(exc).__name__}: {text[:120]}")
            if self._leave_room:
                break
            with self._lock:
                self.connected = False
            retry += 1
            if retry > MAX_ROOM_RETRY:
                self._emit("error", "多次重连失败，请刷新列表或重进房间")
                self.engine.stop()
                return
            wait = RECONNECT_WAIT * (2 ** (retry - 1))
            self._emit("reconnecting", f"{wait}s 后自动重连…")
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                raise

    # ---------------- 帧处理 ---------------- #
    def _handle_frame(self, parsed):
        if not parsed:
            return
        mtype, body = parsed
        data = body.get("data")
        code_ok = str(body.get("code")) == "20000"

        if mtype == "MUSIC" and isinstance(data, dict):
            music = data
            with self._lock:
                self.current = music
            mid = str(music.get("id") or "")
            url = music.get("url") or ""
            if url and code_ok:
                if self._playing_id == mid:
                    return
                self._playing_id = mid
                try:
                    self.engine.play(url)
                except Exception as exc:
                    self._emit("error", str(exc))
            self._emit("music", music)
            self._log_queue_line()

        elif mtype == "PICK":
            if isinstance(data, list):
                with self._lock:
                    self.queue = data
                self._emit("queue", data)
                self._log_queue_line(first_only=True)

        elif mtype == "ONLINE":
            with self._lock:
                self.online = int((data or {}).get("count") if isinstance(data, dict) else data or 0)
            self._emit("online", self.online)

        elif mtype == "ANNOUNCEMENT":
            if code_ok and isinstance(data, dict):
                ann = (data.get("content") or "").strip()
                if ann:
                    self._emit("announce", {"content": ann, "nickName": data.get("nickName")})

        elif mtype == "NOTICE":
            if code_ok and body.get("message"):
                self._emit("notice", body.get("message"))

        elif mtype == "CHAT" and self.show_chat and isinstance(data, dict):
            name = data.get("name") or data.get("nickName") or "?"
            content = str(data.get("content") or data.get("text") or "").strip()
            if content:
                self._emit("chat", {"name": name, "text": content})

    def _log_queue_line(self, first_only: bool = False):
        q = self.queue
        if not q:
            return
        first = q[0]
        self._log(f"点歌队列：下一首 {first.get('name')} - {first.get('artist')}"
                  f"（共 {len(q)} 首待播）")


# --------------------------------------------------------------------------- #
# 便捷排序（与网页端一致：有人 > 免密 > 人数）
# --------------------------------------------------------------------------- #
def sort_rooms(rooms):
    return sorted(
        rooms,
        key=lambda r: (
            0 if (r.get("population") or 0) > 0 else 1,
            0 if not r.get("needPwd") else 1,
            -(r.get("population") or 0),
        ),
    )
