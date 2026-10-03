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
* 音量   : 经 mpv 的 IPC 通道（命名管道/unix socket）即时下发，调整立即生效
* 线程模型: RoomClient.start() 后自动在后台线程中运行 asyncio 事件循环，
            所有对外方法均为线程安全；状态通过 listener(evt, data) 回调传出。
"""

import asyncio
import http.client
import inspect
import json
import os
import random
import re
import shutil
import socket
import ssl
import string
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from urllib.parse import quote, urlparse

try:
    import websockets
except ImportError:
    raise SystemExit("缺少依赖 websockets，请先执行:  python -m pip install -r requirements.txt")

# --------------------------------------------------------------------------- #
# 基本设置
# --------------------------------------------------------------------------- #
DEFAULT_HOST = "tx.alang.run"           # Jusic 后端域名
UI_URL = "https://happy.alang.run/modern-ui/"      # 网页 UI（协议同源）
SHARE_UI_URL = UI_URL.rstrip("/")       # 分享链接前缀（与网页端 roomShareUrl 一致）
MUSIC_API = "/api"                      # REST / WS 统一前缀

# 点歌音源（与网页端 SOURCE_CODES 一致：显示名 -> 音源代码）
SONG_SOURCE_CODES = {
    "网易": "wy",
    "QQ": "qq",
    "酷我": "kw",
    "酷狗": "kg",
    "咪咕": "mg",
}
SONG_QUALITIES = {"标准": "320k", "高清": "flac"}   # 网页端两个点歌按钮对应的音质

# 在线成员（HOUSE_USER 帧）里的身份取值；未知取值原样显示
MEMBER_ROLE_LABELS = {
    "default": "普通成员",
    "admin": "房管",
    "root": "超级管理员",
    "picker": "点歌人",
    "voter": "切歌人",
    "black": "已拉黑",
}

# 昵称清洗（与网页端 cleanNickname 一致）：服务端下发的 nickName 形如
# 「昵称(113.117.*.*)」，需要去掉末尾的掩码 IP 才算真正的昵称。
_NICK_IP = r"(?:\d{1,3}|\*)\.(?:\d{1,3}|\*)\.(?:\d{1,3}|\*)\.(?:\d{1,3}|\*)"
_NICK_TAIL_STAR = re.compile(r"(?:\(\*\))+$")
_NICK_TAIL_IP = re.compile(rf"(?:\({_NICK_IP}\))+$")
_NICK_IP_ONLY = re.compile(rf"^{_NICK_IP}$")


def clean_nickname(value) -> str:
    """清洗昵称：去掉末尾的 ``(*)`` 与掩码 IP 后缀（同网页端 cleanNickname）。

    若去掉后为空、或昵称本身就是掩码 IP（该用户没设昵称），返回空串。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    text = _NICK_TAIL_STAR.sub("", text).strip()
    if text.lower() in ("null", "undefined", "anonymous"):
        return ""
    if _NICK_IP_ONLY.match(text):
        return ""
    return _NICK_TAIL_IP.sub("", text).strip()


def member_display_name(member) -> str:
    """成员显示名：昵称优先（去掉掩码 IP），未设昵称时回落到会话 ID（同网页端）。"""
    member = member or {}
    for key in ("nickName", "nickname", "userName", "name"):
        name = clean_nickname(member.get(key))
        if name:
            return name
    return str(member.get("sessionId") or "匿名用户")


def member_role_label(member) -> str:
    """成员身份的中文名（role：default/admin/root/picker/voter/black）。"""
    member = member or {}
    role = str(member.get("role") or "").strip()
    if not role:
        return MEMBER_ROLE_LABELS["default"]
    return MEMBER_ROLE_LABELS.get(role.lower(), role)


def member_joined_text(member) -> str:
    """成员加入时间（joinedAt 为服务端毫秒时间戳），取本地时区。"""
    try:
        ts = float((member or {}).get("joinedAt") or 0) / 1000.0
    except (TypeError, ValueError):
        return "—"
    if ts <= 0:
        return "—"
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(ts))
    except (OSError, ValueError):
        return "—"


def source_code(label_or_code: str) -> str:
    """把音源显示名（如「网易」）转成接口用的代码（如 wy）；已是代码则原样返回。"""
    text = str(label_or_code or "").strip()
    return SONG_SOURCE_CODES.get(text, text or "wy")


def song_unavailable(song) -> bool:
    """搜索结果是否不可播（与网页端一致：fl == 0 或 st < 0）。

    实测后端把这两个字段放在 privilege 子对象里（如 {"fl": 1, "st": 1}），
    部分音源也会平铺到顶层，故两处都查。
    """
    def number(value):
        if value is None or str(value).strip() == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    song = song or {}
    boxes = [song]
    if isinstance(song.get("privilege"), dict):
        boxes.append(song["privilege"])
    for box in boxes:
        if number(box.get("fl")) == 0:
            return True
        status = number(box.get("st"))
        if status is not None and status < 0:
            return True
    return False


def song_album(song) -> str:
    """取专辑名：实测 album 是对象 {"name": ...}，也兼容直接给字符串。"""
    album = (song or {}).get("album")
    if isinstance(album, dict):
        return str(album.get("name") or "")
    return str(album or "")

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
# websockets 版本适配（参数名与能力随版本变化，写死会直接连不上）
# --------------------------------------------------------------------------- #
_UA = "JusicRoomPlayer/1.0"
_ws_extras = None


def _loop_supports_proxy() -> bool:
    """底层事件循环的 create_connection 是否支持 proxy 参数。

    websockets 15 在没有原生 proxy 支持的解释器（如 Python 3.13）上会把
    ``proxy=`` 原样透传给 ``loop.create_connection``，从而抛 TypeError。
    """
    try:
        return "proxy" in inspect.signature(
            asyncio.BaseEventLoop.create_connection).parameters
    except (TypeError, ValueError):
        return False


def ws_connect_extras() -> dict:
    """按当前 websockets 版本拼装 connect() 的可选参数。

    * 请求头：websockets >= 14 用 ``additional_headers``，13.x 用 ``user_agent_header``
      （老版本 ``extra_headers`` 会覆盖掉 websockets 自带的 UA，故优先专用参数）；
    * ``proxy=None``（不代理、直连，绕开系统代理干扰）只在底层真正支持时才传，
      否则在旧版 websockets 上会被透传给 loop.create_connection 而失败；
      完全不支持代理的版本（13.x）本来就直连，无需该参数。
    """
    global _ws_extras
    if _ws_extras is not None:
        return dict(_ws_extras)
    try:
        params = inspect.signature(websockets.connect).parameters
    except (TypeError, ValueError):
        params = {}
    extras = {}
    if "additional_headers" in params:
        extras["additional_headers"] = {"User-Agent": _UA}
    elif "user_agent_header" in params:
        extras["user_agent_header"] = _UA
    elif "extra_headers" in params:
        extras["extra_headers"] = {"User-Agent": _UA}
    if "proxy" in params and _loop_supports_proxy():
        extras["proxy"] = None
    _ws_extras = dict(extras)
    return dict(extras)


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
# 房间分享
# --------------------------------------------------------------------------- #
def room_share_url(room_id, password="") -> str:
    """房间分享链接（与网页端 roomShareUrl() 完全一致）。

    形如 https://happy.alang.run/modern-ui?houseId=xxx&housePwd=yyy
    对方用浏览器打开即可直达该房间（密码房会把密码一并带上）。
    """
    return (f"{SHARE_UI_URL}?houseId={quote(str(room_id or ''), safe='')}"
            f"&housePwd={quote(str(password or ''), safe='')}")


def get_mini_code(host: str, room_id) -> str:
    """POST /api/house/getMiniCode -> 微信小程序码（base64 图片字符串）。"""
    code, text = api_post(host, MUSIC_API + "/house/getMiniCode",
                          {"id": str(room_id or "")}, timeout=20)
    if code != 200:
        raise RuntimeError(f"小程序码请求失败 HTTP {code}")
    obj = json.loads(text)
    if str(obj.get("code")) != "20000":
        raise RuntimeError(obj.get("message") or "小程序码接口返回异常")
    data = obj.get("data")
    if isinstance(data, dict):                     # 兼容 {img/base64: ...} 形式
        data = data.get("img") or data.get("base64") or data.get("url") or ""
    return data or ""


# --------------------------------------------------------------------------- #
# 帧解析：后端通过 SockJS 推来“类 STOMP”自定义文本帧
# --------------------------------------------------------------------------- #
EVENT_TYPES = {
    "NOTICE", "ONLINE", "CHAT", "PICK", "MUSIC", "SETTING_NAME", "AUTH",
    "AUTH_ROOT", "AUTH_ADMIN", "SEARCH", "SEARCH_PICTURE", "VOLUMN",
    "GOODMODEL", "SEARCH_HOUSE", "ENTER_HOUSE", "ENTER_HOUSE_START",
    "ADD_HOUSE", "ADD_HOUSE_START", "SEARCH_SONGLIST", "SEARCH_USER",
    "ANNOUNCEMENT", "HOUSE_USER", "CIRCLEMODEL", "LISTMODEL", "ROOM_STATE",
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
    """每首新歌启动一个纯音频 mpv 进程，播完自动退出；内存占用小。

    音量通过 mpv 的 IPC 通道下发（Windows 命名管道 / 其它平台 unix socket），
    调整音量立即生效，不必等下一首。
    """

    def __init__(self, volume: int = 90, mpv_path: str = ""):
        self._proc = None
        self._lock = threading.Lock()
        self.volume = max(0, min(100, int(volume)))
        self.mpv_path = mpv_path
        # ---- 音量即时下发（IPC）---- #
        self._ipc_seq = 0                        # 每首新歌 +1，生成互不冲突的 IPC 地址
        self._ipc_path = ""                      # 当前 mpv 的 IPC 地址（"" = 无）
        self._ipc_start_volume = self.volume     # 当前 mpv 启动时使用的音量
        self._ipc_wake = threading.Event()
        # 独立守护线程异步推送音量：即使 IPC 异常也不会卡住界面线程
        self._ipc_thread = threading.Thread(target=self._pump_loop, daemon=True,
                                            name="jusic-mpv-volume")
        self._ipc_thread.start()

    def set_volume(self, value: int) -> int:
        """设置音量：立即作用于正在播放的 mpv，并记住供后续新歌使用。

        实际下发在后台线程里完成（可能滞后几十毫秒），因此本方法永不阻塞。
        """
        self.volume = max(0, min(100, int(value)))
        self._ipc_wake.set()
        return self.volume

    # ---------------- mpv IPC：音量下发 ---------------- #
    @staticmethod
    def _ipc_address(seq: int) -> str:
        """本次播放使用的 IPC 地址（地址唯一，避免与残留/旧进程串线）。"""
        if os.name == "nt":
            return r"\\.\pipe\jusic-mpv-%d-%d" % (os.getpid(), seq)
        return os.path.join(tempfile.gettempdir(),
                            "jusic-mpv-%d-%d.sock" % (os.getpid(), seq))

    @staticmethod
    def _ipc_connect(path: str):
        """连接 mpv 的 IPC，返回可 write/read/close 的对象。"""
        if os.name == "nt":
            return open(path, "r+b", buffering=0)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(path)
        return sock.makefile("rwb", buffering=0)

    def _ipc_push(self, path: str, volume: int) -> bool:
        """把音量下发给 path 对应的 mpv，返回是否成功。

        连接 → 写命令 → 读回执 → 关闭：mpv 每次只接受一个客户端连接，用完即关；
        同一连接上并发读写会让 Windows 命名管道的写入永久阻塞，故保持单线程使用。
        """
        payload = json.dumps({"command": ["set_property", "volume", int(volume)]})
        payload = payload.encode("utf-8") + b"\n"
        try:
            conn = MpvEngine._ipc_connect(path)
        except Exception:
            return False
        try:
            conn.write(payload)
            conn.read(len(payload) + 128)     # 读掉回执，避免 mpv 输出侧堆积
            return True
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _pump_loop(self):
        """守护线程：把 self.volume 的变化异步下发给正在播放的 mpv。"""
        gen, applied, misses = 0, None, 0
        while True:
            path = self._ipc_path
            if self._ipc_seq != gen:                     # 换曲：新 mpv 已按启动音量起播
                gen, misses = self._ipc_seq, 0
                applied = self._ipc_start_volume
            want = self.volume
            if path and want != applied and misses < 40 and self.running():
                time.sleep(0.02)                         # 合并拖动产生的中间值
                want = self.volume
                if self._ipc_push(path, want):
                    applied = want
                else:                                    # 管道可能尚未就绪，稍后重试
                    misses += 1
                    self._ipc_wake.wait(0.05)
            else:
                self._ipc_wake.wait(0.3)
            self._ipc_wake.clear()

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
        ipc = self._ipc_path
        self._ipc_path = ""
        if ipc and os.name != "nt":
            try:
                os.remove(ipc)            # POSIX：清掉 unix socket 文件
            except OSError:
                pass
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
            self._ipc_seq += 1
            ipc = MpvEngine._ipc_address(self._ipc_seq)
            volume = self.volume                 # 启动音量：即刻快照，供后续对比
            args = [
                exe,
                "--no-config", "--no-video", "--force-window=no",
                "--audio-display=no", "--vo=null", "--no-terminal",
                "--really-quiet", "--msg-level=all=error",
                "--user-agent=Mozilla/5.0",
                "--demuxer-max-bytes=8MiB",        # 限制内存缓存
                "--demuxer-max-back-bytes=1MiB",
                f"--input-ipc-server={ipc}",       # 音量即时调用的通道
                f"--volume={volume}",
                url,
            ]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                self._proc = subprocess.Popen(
                    args, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
                self._ipc_path = ipc
                self._ipc_start_volume = volume
                self._ipc_wake.set()               # 让音量线程接手最新音量
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
      search      -> dict {songs: list, total: int, page: int}  点歌搜索结果
      members     -> list[member]  在线成员（/house/houseuser 的应答）
      good-mode   -> bool  房间「点赞排序」是否开启
      online      -> int
      chat        -> dict  (仅 show_chat=True 时)
      notice      -> str  (服务端提示；**含非 20000 码的失败提示**，如点歌被拒/权限不足)
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
        self.members = []         # 最近一次查询到的在线成员（list[dict]）
        self.online = 0
        self.connected = False
        # 本次 WSS 连接的会话 ID（就是连接 URL 里的随机段，服务端也按它标识我们；
        # 用于在成员列表里认出「本人」，实测 HOUSE_USER 里的 sessionId 与之一致）
        self.session_id = ""
        # 点歌搜索的最近一次请求上下文（结果帧里不带关键词，用于界面回填）
        self.search_keyword = ""
        self.search_source = "wy"
        self.search_page = 1
        self.search_total = 0
        self.good_mode = False        # 房间是否开启「点赞排序」

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

    def list_members(self):
        """查询在线成员：SEND /house/houseuser {}（网页端「在线成员」面板同款）。

        服务端回 HOUSE_USER 帧（data 为成员数组），经 listener 的 "members" 事件传出；
        成员字段：houseId / sessionId / name / nickName / remoteAddress / role / joinedAt。
        纯只读查询，不改变房间状态；进房后网页端也会自动查一次。
        """
        self.command("/house/houseuser", "{}")
        return True

    # ---------------- 点歌 ---------------- #
    def search_songs(self, keyword: str, source: str = "wy", page: int = 1,
                     page_size: int = 20):
        """点歌搜索：SEND /music/search {name, source, pageIndex, pageSize, sendTime}。

        结果异步经 listener 的 "search" 事件返回：{songs, total, page, ok}。
        关键词留空返回 False；「*热歌榜」这类星号关键词与网页端一致，可直接使用。
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return False
        self.search_keyword = keyword
        self.search_source = source_code(source)
        self.search_page = max(1, int(page))
        body = json.dumps({
            "name": keyword,
            "source": self.search_source,
            "pageIndex": self.search_page,
            "pageSize": max(1, int(page_size)),
            "sendTime": int(time.time() * 1000),
        }, ensure_ascii=False)
        self.command("/music/search", body)
        return True

    def pick_song(self, song_id, name: str = "", source: str = "wy",
                  quality: str = "320k"):
        """点歌（加入房间队列）：SEND /music/pick {name, id, source, quality, sendTime}。

        quality 用 "320k"（标准）或 "flac"（高清），与网页端两个点歌按钮一致；
        song_id 须为搜索返回的原始 id（后端按字符串匹配点歌归属）。
        """
        if song_id is None or not str(song_id).strip():
            return False
        body = json.dumps({
            "name": (name or "").strip() or str(song_id),
            "id": song_id,
            "source": source_code(source),
            "quality": quality or "320k",
            "sendTime": int(time.time() * 1000),
        }, ensure_ascii=False)
        self.command("/music/pick", body)
        return True

    def good_song(self, song_id):
        """点赞歌曲：SEND /music/good/<id>（网页端播放栏「点赞」与队列点赞同款）。

        点赞本身不改本地状态；房间若开启「点赞排序」，服务端会据此调整播放顺序
        并推送新的 PICK 帧。同一首歌重复点赞由界面侧自行去重。
        """
        if song_id is None or not str(song_id).strip():
            return False
        self.command(f"/music/good/{quote(str(song_id), safe='')}", "{}")
        return True

    def set_volume(self, value: int):
        """调整音量：正在播放时立即生效（mpv IPC），并记忆供后续新歌使用。"""
        return self.engine.set_volume(value)

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
            self.members = []
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
            self.members = []
            self.online = 0
            self.connected = False
            self.room = None
        self.session_id = ""

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
                    origin=UI_URL,
                    open_timeout=15,
                    ping_interval=30,
                    ping_timeout=12,
                    **ws_connect_extras(),          # 版本/代理适配，见该函数说明
                ) as ws:
                    retry = 0
                    self._ws = ws
                    self.session_id = sess          # 供成员列表识别「本人」
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

        elif mtype == "SEARCH":
            # 点歌搜索结果：body.data = {data: [songs], totalSize: N}
            songs, total = [], 0
            if isinstance(data, dict):
                raw = data.get("data")
                songs = raw if isinstance(raw, list) else []
                try:
                    total = int(data.get("totalSize"))
                except (TypeError, ValueError):
                    total = len(songs)
            elif isinstance(data, list):
                songs = data
                total = len(songs)
            self.search_total = total
            self._emit("search", {"songs": songs, "total": total,
                                  "page": self.search_page, "ok": code_ok})

        elif mtype == "HOUSE_USER":
            # 在线成员列表（/house/houseuser 的应答）：data 为成员数组。
            # 与网页端一致：非数组（含失败）一律视为空列表；有成员时用其数量校正在线人数。
            members, raw = [], data
            if isinstance(raw, dict):                 # 兼容 {data/list/users: [...]} 包装
                for key in ("data", "list", "users", "members"):
                    if isinstance(raw.get(key), list):
                        raw = raw[key]
                        break
            if isinstance(raw, list):
                members = [m for m in raw if isinstance(m, dict)]
            with self._lock:
                self.members = members
                if members:
                    self.online = len(members)
            self._emit("members", members)

        elif mtype == "GOODMODEL":
            # 房间「点赞排序」开关：data 为 GOOD 表示已开启（与网页端判定一致）
            if isinstance(data, bool):
                enabled = data
            else:
                enabled = str(data).strip().upper() == "GOOD"
            self.good_mode = enabled
            self._emit("good-mode", enabled)

        elif mtype == "ROOM_STATE" and isinstance(data, dict):
            # 房间状态（部分后端版本在进房时推送，含 goodModel）
            mode = data.get("goodModel")
            if isinstance(mode, bool) and mode != self.good_mode:
                self.good_mode = mode
                self._emit("good-mode", mode)

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
            # 与网页端一致：**不能只看 code**。网页端对 notice-message 不做任何 code 判断，
            # 而点歌被拒/权限不足/进房等待等失败提示都是用非 20000 的 NOTICE 下发的
            # （实测该后端回 code=40000 + message「进入房间满10分钟后才能点歌…」），
            # 只认 code 会把失败提示全部丢掉，界面就表现为“点了没反应、没有任何提示”。
            text = body.get("message")
            if not text and isinstance(data, str):
                text = data                     # 个别后端把提示放在字符串 data 里
            text = str(text or "").strip()
            if text:
                self._emit("notice", text)

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
