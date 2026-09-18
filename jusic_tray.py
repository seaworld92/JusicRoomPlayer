#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
Jusic 房间播放器 · 系统托盘组件（Windows）
==========================================
纯 ctypes 直接调用 Win32 API（Shell_NotifyIcon）实现“最小化到系统托盘”，
**不引入任何第三方依赖**（不使用 pystray / Pillow），保持项目“低内存、
零额外依赖”的定位。

能力：
    * 后台线程创建隐藏消息窗口并注册托盘图标（不占用主线程、不阻塞 tkinter）；
    * 左键单击 / 双击图标 → on_show()（恢复主窗口）；
    * 右键图标 → 弹出菜单：“显示主界面 / 退出程序”；
    * balloon() 弹出气泡提示（首次最小化时提示用户程序仍在运行）；
    * 托盘图标由代码逐像素绘制并动态生成 HICON（唱片造型），无需外部 .ico 资源。

非 Windows 平台：TrayIcon.available() 返回 False，调用方应退化为普通最小化。
"""

import ctypes
import math
import os
import struct
import threading

IS_WINDOWS = (os.name == "nt") and hasattr(ctypes, "windll")

# ------------------------------- 常量 ------------------------------- #
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_CONTEXTMENU = 0x007B
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO = 0x00000001

MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
TPM_LEFTALIGN, TPM_RIGHTBUTTON = 0x0000, 0x0002

ERROR_CLASS_ALREADY_EXISTS = 1410

ID_SHOW = 1001
ID_QUIT = 1002

# 图标配色（RGB）
_COLOR_DARK = (0x27, 0x2B, 0x33)
_COLOR_ACCENT = (0xF0, 0x92, 0x24)
_COLOR_HOLE = (0xFA, 0xFA, 0xFA)

# ---------------------------- 图标绘制 ---------------------------- #
def _ring_color(d, r_hole, r_mid, r_out):
    """按到圆心距离返回该采样点的颜色；圆外返回 None。"""
    if d > r_out:
        return None
    if d <= r_hole:
        return _COLOR_HOLE
    if d <= r_mid:
        return _COLOR_ACCENT
    return _COLOR_DARK


def _icon_pixels(size=32, ss=3):
    """超采样绘制“唱片”图标，返回 [(r,g,b,a)] 行优先像素表。"""
    cx = cy = (size - 1) / 2.0
    r_out = size * 0.475
    r_mid = size * 0.305
    r_hole = size * 0.115
    total = ss * ss
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            hit = 0
            sr = sg = sb = 0
            for sy in range(ss):
                for sx in range(ss):
                    px = x + (sx + 0.5) / ss
                    py = y + (sy + 0.5) / ss
                    col = _ring_color(math.hypot(px - cx, py - cy), r_hole, r_mid, r_out)
                    if col is None:
                        continue
                    hit += 1
                    sr += col[0]
                    sg += col[1]
                    sb += col[2]
            if not hit:
                row.append((0, 0, 0, 0))
            else:
                row.append((sr // hit, sg // hit, sb // hit,
                            int(round(255.0 * hit / total))))
        rows.append(row)
    return rows


def icon_image_bytes(size=32):
    """生成 CreateIconFromResourceEx 所需的 ICONIMAGE 数据（BITMAPINFOHEADER+位图）。"""
    rows = _icon_pixels(size)
    xor = bytearray()
    for y in range(size - 1, -1, -1):          # BMP 为自下而上
        for x in range(size):
            r, g, b, a = rows[y][x]
            xor += bytes((b, g, r, a))         # BGRA
    and_row = ((size + 31) // 32) * 4          # 每行按 4 字节对齐
    and_mask = bytes(and_row * size)           # 32bpp 用 alpha，掩码留空
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + bytes(xor) + and_mask


# ============================ Windows 实现 ============================ #
if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _shell32 = ctypes.windll.shell32          # Shell_NotifyIconW 由 shell32 导出

    LRESULT = ctypes.c_ssize_t
    _HANDLE = wintypes.HANDLE
    WPARAM = getattr(wintypes, "WPARAM", ctypes.c_size_t)
    LPARAM = getattr(wintypes, "LPARAM", ctypes.c_ssize_t)
    HWND = getattr(wintypes, "HWND", _HANDLE)
    UINT = wintypes.UINT
    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL
    HICON = getattr(wintypes, "HICON", _HANDLE)
    HINSTANCE = getattr(wintypes, "HINSTANCE", _HANDLE)
    HMENU = getattr(wintypes, "HMENU", _HANDLE)
    HCURSOR = getattr(wintypes, "HCURSOR", _HANDLE)
    HBRUSH = getattr(wintypes, "HBRUSH", _HANDLE)
    LPCWSTR = wintypes.LPCWSTR
    POINT = wintypes.POINT
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", UINT),
            ("style", UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", HINSTANCE),
            ("hIcon", HICON),
            ("hCursor", HCURSOR),
            ("hbrBackground", HBRUSH),
            ("lpszMenuName", LPCWSTR),
            ("lpszClassName", LPCWSTR),
            ("hIconSm", HICON),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", DWORD),
            ("hWnd", HWND),
            ("uID", UINT),
            ("uFlags", UINT),
            ("uCallbackMessage", UINT),
            ("hIcon", HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", DWORD),
            ("dwStateMask", DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", DWORD),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", HWND),
            ("message", UINT),
            ("wParam", WPARAM),
            ("lParam", LPARAM),
            ("time", DWORD),
            ("pt", POINT),
            ("lPrivate", DWORD),
        ]

    def _setup_signatures():
        u, k = _user32, _kernel32
        k.GetModuleHandleW.restype = HINSTANCE
        k.GetModuleHandleW.argtypes = [LPCWSTR]
        k.GetLastError.restype = DWORD

        u.DefWindowProcW.restype = LRESULT
        u.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
        u.RegisterClassExW.restype = ctypes.c_ushort
        u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        u.UnregisterClassW.restype = BOOL
        u.UnregisterClassW.argtypes = [LPCWSTR, HINSTANCE]
        u.CreateWindowExW.restype = HWND
        u.CreateWindowExW.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      HWND, HMENU, HINSTANCE, ctypes.c_void_p]
        u.DestroyWindow.restype = BOOL
        u.DestroyWindow.argtypes = [HWND]
        u.PostQuitMessage.argtypes = [ctypes.c_int]
        u.GetMessageW.restype = ctypes.c_int
        u.GetMessageW.argtypes = [ctypes.POINTER(MSG), HWND, UINT, UINT]
        u.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        u.PostMessageW.restype = BOOL
        u.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]

        u.CreateIconFromResourceEx.restype = HICON
        u.CreateIconFromResourceEx.argtypes = [ctypes.c_void_p, DWORD, BOOL, DWORD,
                                               ctypes.c_int, ctypes.c_int, UINT]
        u.DestroyIcon.argtypes = [HICON]
        u.LoadIconW.restype = HICON
        u.LoadIconW.argtypes = [HINSTANCE, LPCWSTR]

        _shell32.Shell_NotifyIconW.restype = BOOL
        _shell32.Shell_NotifyIconW.argtypes = [DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

        u.CreatePopupMenu.restype = HMENU
        u.AppendMenuW.restype = BOOL
        u.AppendMenuW.argtypes = [HMENU, UINT, ctypes.c_size_t, LPCWSTR]
        u.TrackPopupMenu.restype = BOOL
        u.TrackPopupMenu.argtypes = [HMENU, UINT, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, HWND, ctypes.c_void_p]
        u.DestroyMenu.restype = BOOL
        u.DestroyMenu.argtypes = [HMENU]
        u.SetForegroundWindow.argtypes = [HWND]
        u.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]

    _setup_signatures()

    class TrayIcon:
        """系统托盘图标：后台线程 + 隐藏消息窗口，线程安全。"""

        def __init__(self, tooltip="Jusic 房间播放器", on_show=None, on_quit=None,
                     class_name="JusicRoomPlayerTrayWnd"):
            self.tooltip = tooltip
            self.on_show = on_show
            self.on_quit = on_quit
            self._class_name = class_name
            self._thread = None
            self._ready = threading.Event()
            self._lock = threading.Lock()
            self._nid = None                      # NOTIFYICONDATAW（持有引用防回收）
            self.hwnd = 0
            self._hicon = 0
            self._wndproc_ref = WNDPROC(self._wndproc)

        # ---------------- 对外接口 ---------------- #
        @staticmethod
        def available():
            return bool(IS_WINDOWS)

        def start(self, timeout=3.0):
            """启动托盘线程并等待图标注册完成。成功返回 True。"""
            if self._thread is not None and self._thread.is_alive():
                return True
            self._thread = threading.Thread(target=self._run, name="jusic-tray", daemon=True)
            self._thread.start()
            self._ready.wait(timeout)
            return bool(self.hwnd)

        def stop(self, timeout=3.0):
            """关闭托盘图标并结束消息循环（可从任意线程调用）。"""
            hwnd = self.hwnd
            if hwnd:
                try:
                    _user32.PostMessageW(HWND(hwnd), WM_CLOSE, 0, 0)
                except Exception:
                    pass
            thread = self._thread
            if thread is not None and thread.is_alive():
                thread.join(timeout)
            self._thread = None
            self.hwnd = 0

        def balloon(self, title, text, timeout_ms=5000):
            """弹出气泡提示（托盘图标不存在时静默忽略）。"""
            with self._lock:
                nid = self._nid
                if nid is None:
                    return False
                try:
                    nid.uFlags = NIF_INFO
                    nid.uTimeout = timeout_ms
                    nid.szInfo = str(text)[:255]
                    nid.szInfoTitle = str(title)[:63]
                    nid.dwInfoFlags = NIIF_INFO
                    return bool(_shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))
                except Exception:
                    return False

        # ---------------- 内部实现 ---------------- #
        def _run(self):
            try:
                self._create()
            except Exception:
                self._ready.set()
                return
            self._ready.set()
            msg = MSG()
            try:
                while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
            finally:
                self._cleanup()

        def _create(self):
            hinst = _kernel32.GetModuleHandleW(None)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = 0
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            if not _user32.RegisterClassExW(ctypes.byref(wc)):
                err = _kernel32.GetLastError()
                if err != ERROR_CLASS_ALREADY_EXISTS:
                    raise ctypes.WinError(err)
            hwnd = _user32.CreateWindowExW(0, self._class_name, self._class_name, 0,
                                           0, 0, 0, 0, None, None, hinst, None)
            if not hwnd:
                raise ctypes.WinError()
            self.hwnd = int(hwnd)

            icon = self._make_icon()
            self._hicon = int(icon or 0)
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = HWND(self.hwnd)
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = icon
            nid.szTip = str(self.tooltip)[:127]
            with self._lock:
                self._nid = nid
            if not _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                with self._lock:
                    self._nid = None
                raise ctypes.WinError()

        def _make_icon(self):
            """代码绘制图标并创建 HICON（失败则退回系统默认图标）。"""
            try:
                data = icon_image_bytes(32)
                buf = ctypes.create_string_buffer(data, len(data))
                hicon = _user32.CreateIconFromResourceEx(
                    ctypes.cast(buf, ctypes.c_void_p), len(data), 1, 0x00030000, 0, 0, 0)
                if hicon:
                    return hicon
            except Exception:
                pass
            try:
                return _user32.LoadIconW(None, ctypes.c_wchar_p(32516))  # IDI_APPLICATION
            except Exception:
                return 0

        def _cleanup(self):
            with self._lock:
                nid, self._nid = self._nid, None
            try:
                if nid is not None:
                    _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            except Exception:
                pass
            try:
                if self._hicon:
                    _user32.DestroyIcon(HICON(self._hicon))
            except Exception:
                pass
            self._hicon = 0
            try:
                if self.hwnd:
                    _user32.UnregisterClassW(self._class_name, _kernel32.GetModuleHandleW(None))
            except Exception:
                pass
            self.hwnd = 0

        def _wndproc(self, hwnd, msg, wparam, lparam):
            try:
                if msg == WM_TRAYICON:
                    event = int(lparam) & 0xFFFF
                    if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                        self._fire(self.on_show)
                    elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                        self._show_menu()
                    return 0
                if msg == WM_COMMAND:
                    cid = int(wparam) & 0xFFFF
                    if cid == ID_SHOW:
                        self._fire(self.on_show)
                    elif cid == ID_QUIT:
                        self._fire(self.on_quit)
                    return 0
                if msg == WM_CLOSE:
                    _user32.DestroyWindow(HWND(hwnd))
                    return 0
                if msg == WM_DESTROY:
                    _user32.PostQuitMessage(0)
                    return 0
            except Exception:
                return 0
            try:
                return int(_user32.DefWindowProcW(HWND(hwnd), msg, wparam, lparam))
            except Exception:
                return 0

        def _show_menu(self):
            hwnd = HWND(self.hwnd or 0)
            menu = _user32.CreatePopupMenu()
            if not menu:
                return
            try:
                _user32.AppendMenuW(menu, MF_STRING, ID_SHOW, "显示主界面")
                _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                _user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "退出程序")
                pt = POINT()
                _user32.GetCursorPos(ctypes.byref(pt))
                _user32.SetForegroundWindow(hwnd)
                _user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_LEFTALIGN,
                                       pt.x, pt.y, 0, hwnd, None)
                _user32.PostMessageW(hwnd, WM_NULL, 0, 0)
            except Exception:
                pass
            finally:
                try:
                    _user32.DestroyMenu(menu)
                except Exception:
                    pass

        @staticmethod
        def _fire(callback):
            if callback is None:
                return
            try:
                callback()
            except Exception:
                pass

else:

    class TrayIcon:                     # noqa: F811  （非 Windows 占位实现）
        """非 Windows 平台占位：available() 恒为 False。"""

        def __init__(self, *args, **kwargs):
            raise RuntimeError("系统托盘仅支持 Windows")

        @staticmethod
        def available():
            return False
