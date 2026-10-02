#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
mem_bench.py —— 内存占用基准测试（Windows）
================================================================================
用途
    实测本项目各个前端在「运行中（已进房、正在播放）」时的内存占用，
    用于回归对比（例如评估 ttkbootstrap 主题界面是否值得多花那几 MB）。

测量口径
    * 进程内存取 Windows 工作集（Working Set，任务管理器“内存”列同口径），
      同时给出提交大小（Commit）与句柄数；
    * 每个前端单独串行启动（互不干扰），先等界面建好采样，再等进入房间、
      播放稳定后采样，最后 taskkill /F /T 连子进程（mpv）一起收干净；
    * 启动一律加 ``--console`` 并设 ``JUSIC_GUI_PYW=1``，避免程序自动改用
      pythonw 重启导致测到两个进程；
    * mpv 是独立进程，单独用 ``tasklist`` 抓取，便于给出“播放器 + 内核”总量；
    * ``--imports-only`` 只测库导入的固定开销（定位差距来源，不启动界面）。

用法
    python tools/mem_bench.py                  # 经典界面 + 主题界面（各 ~55s）
    python tools/mem_bench.py --cli            # 再额外测命令行版
    python tools/mem_bench.py --only theme     # 只测某一个前端
    python tools/mem_bench.py --seconds 30     # 缩短每项采样时长（默认 55s）
    python tools/mem_bench.py --imports-only   # 只测库导入开销
    python tools/mem_bench.py --json out.json  # 结果另存 JSON

注意
    * 仅 Windows 可用（依赖 psapi / tasklist / taskkill）；
    * 测量期间会真的弹出界面窗口并播放声音，属于正常现象；
    * 参考数据（2026-10-02，本机 python 3.13 + mpv 0.41）：
        命令行版    python ≈ 37 MB + mpv ≈ 53 MB ≈  90 MB
        经典界面    python ≈ 66 MB + mpv ≈ 57 MB ≈ 123 MB
        主题界面    python ≈ 76 MB + mpv ≈ 57 MB ≈ 134 MB
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WINDOWS = os.name == "nt"

# --------------------------------------------------------------------------- #
# 进程内存读取
# --------------------------------------------------------------------------- #


class _PMC(ctypes.Structure):
    """PROCESS_MEMORY_COUNTERS"""

    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


def process_mem(pid):
    """返回 {'ws','peak','commit','handles'}（MB），进程不在则 None。"""
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return None
    try:
        counters = _PMC()
        counters.cb = ctypes.sizeof(counters)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb):
            return None
        handles = -1
        count = wt.DWORD()
        try:
            if ctypes.windll.kernel32.GetProcessHandleCount(handle, ctypes.byref(count)):
                handles = count.value
        except Exception:
            pass
        return {
            "ws": round(counters.WorkingSetSize / 1048576, 1),
            "peak": round(counters.PeakWorkingSetSize / 1048576, 1),
            "commit": round(counters.PagefileUsage / 1048576, 1),
            "handles": handles,
        }
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def mpv_processes():
    """当前所有 mpv.exe 的 (pid, 工作集 MB)。"""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mpv.exe", "/FO", "CSV", "/NH"],
                         capture_output=True)
    text = out.stdout.decode("gbk", "replace")
    rows = []
    for line in text.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 5 and cols[0].lower().startswith("mpv"):
            used = cols[4].replace(",", "").replace("K", "").strip()
            try:
                rows.append((cols[1], round(int(used) / 1024, 1)))
            except ValueError:
                pass
    return rows


# --------------------------------------------------------------------------- #
# 启动 / 清理
# --------------------------------------------------------------------------- #


def spawn(script, extra_args):
    env = dict(os.environ)
    env["JUSIC_GUI_PYW"] = "1"        # 禁止自动改用 pythonw 重启
    return subprocess.Popen([sys.executable, os.path.join(ROOT, script), *extra_args],
                            cwd=ROOT, env=env)


def kill_tree(pid, keep=False):
    if keep:
        return
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    time.sleep(1.0)


# --------------------------------------------------------------------------- #
# 被测目标
# --------------------------------------------------------------------------- #

TARGETS = {
    "cli": {
        "label": "命令行版 jusic_room_player.py",
        "script": "jusic_room_player.py",
        "args": lambda s, a: ["--auto-seconds", str(s + 20)],
    },
    "classic": {
        "label": "经典界面 jusic_gui.py",
        "script": "jusic_gui.py",
        "args": lambda s, a: ["--console"],
    },
    "theme": {
        "label": "主题界面 jusic_gui_bootstrap.py",
        "script": "jusic_gui_bootstrap.py",
        "args": lambda s, a: ["--console"] + (["--theme", a.theme] if a.theme else []),
    },
}
DEFAULT_ORDER = ["classic", "theme"]


def measure_target(key, args):
    spec = TARGETS[key]
    seconds = args.seconds
    early_ws = 9                                  # 界面已建好的早期采样点
    late_ws = max(seconds - 9, early_ws + 12)      # 进房播放稳定后的采样点
    print(f"\n=== {spec['label']} ===", flush=True)

    proc = spawn(spec["script"], spec["args"](seconds, args))
    record = {"target": key, "label": spec["label"], "script": spec["script"],
              "pid": proc.pid, "samples": []}
    try:
        time.sleep(early_ws)
        for i in range(3):
            sample(proc.pid, early_ws + i * 3, record["samples"])
            time.sleep(3)
        if late_ws > early_ws + 6:
            time.sleep(late_ws - (early_ws + 6))
        for i in range(3):
            sample(proc.pid, late_ws + i * 3, record["samples"])
            time.sleep(3)
        record["alive"] = proc.poll() is None
        record["mpv"] = mpv_processes()
        print(f"   mpv: {record['mpv'] or '（无）'}   alive={record['alive']}", flush=True)
    finally:
        kill_tree(proc.pid, keep=args.keep)

    late = [s for s in record["samples"] if s["tag"] >= late_ws]
    record["python_ws"] = median([s["ws"] for s in late]) if late else None
    record["python_commit"] = median([s["commit"] for s in late]) if late else None
    return record


def sample(pid, tag, store):
    mem = process_mem(pid)
    if not mem:
        print(f"   +{tag:3d}s  进程已退出", flush=True)
        return
    store.append({"tag": tag, **mem})
    print(f"   +{tag:3d}s  work-set {mem['ws']:6.1f} MB   "
          f"commit {mem['commit']:6.1f} MB   handles {mem['handles']}", flush=True)


def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return round((values[mid - 1] + values[mid]) / 2, 1)


# --------------------------------------------------------------------------- #
# 库导入开销
# --------------------------------------------------------------------------- #

IMPORT_CASES = [
    ("python 空进程基线", "import time; time.sleep({s})"),
    ("+ tkinter", "import time, tkinter; time.sleep({s})"),
    ("+ tkinter + ttkbootstrap", "import time, tkinter, ttkbootstrap; time.sleep({s})"),
    ("+ ttkbootstrap 创建 Window",
     "import time, ttkbootstrap as ttb; w = ttb.Window(); w.update(); time.sleep({s})"),
]


def measure_imports(seconds, keep=False):
    print("\n=== 库导入开销（定位主题界面差距来源）===", flush=True)
    rows = []
    for label, code in IMPORT_CASES:
        proc = subprocess.Popen([sys.executable, "-c", code.format(s=seconds)],
                                cwd=ROOT)
        time.sleep(max(seconds - 3, 3))
        mem = process_mem(proc.pid)
        if mem:
            print(f"   {label:<28s} work-set {mem['ws']:6.1f} MB   "
                  f"commit {mem['commit']:6.1f} MB", flush=True)
            rows.append({"case": label, "ws": mem["ws"], "commit": mem["commit"]})
        kill_tree(proc.pid, keep=keep)
    return rows


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #


def report(records):
    print("\n" + "=" * 78)
    print("内存基准汇总（工作集口径，播放稳定态）")
    print("=" * 78)
    print(f"{'前端':<38s}{'python':>10s}{'提交':>10s}{'mpv':>9s}{'合计':>11s}")
    print("-" * 78)
    for rec in records:
        py = rec.get("python_ws")
        commit = rec.get("python_commit")
        mpv = rec.get("mpv") or []
        mpv_mb = median([m for _, m in mpv]) if mpv else None
        total = round(py + mpv_mb, 1) if (py and mpv_mb) else None
        print(f"{rec['label']:<38s}"
              f"{(f'{py:.1f} MB' if py else '?'):>10s}"
              f"{(f'{commit:.1f} MB' if commit else '?'):>10s}"
              f"{(f'{mpv_mb:.1f} MB' if mpv_mb else '（无）'):>9s}"
              f"{(f'{total:.1f} MB' if total else '?'):>11s}")
    print("-" * 78)
    print("说明：mpv 为独立进程，两个界面共用同一 mpv 内核，占用基本相同；")
    print("      若某前端 mpv 为空，可能是刚切歌（旧进程已退、新进程未起）。")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mem_bench",
        description="Jusic 房间播放器内存基准测试（Windows）")
    parser.add_argument("--only", nargs="*", choices=list(TARGETS),
                        help=f"只测指定前端（默认 {' '.join(DEFAULT_ORDER)}；可选 {', '.join(TARGETS)}）")
    parser.add_argument("--cli", action="store_true", help="把命令行版也纳入测量")
    parser.add_argument("--seconds", type=int, default=55,
                        help="每项稳定态采样目标时长（秒，默认 55）")
    parser.add_argument("--theme", default="litera",
                        help="主题界面版使用的主题（默认 litera）")
    parser.add_argument("--imports-only", action="store_true",
                        help="只测库导入开销，不启动界面")
    parser.add_argument("--no-imports", action="store_true",
                        help="跳过库导入开销部分")
    parser.add_argument("--json", dest="json_path", default="",
                        help="把结果另存为 JSON 文件")
    parser.add_argument("--keep", action="store_true",
                        help="测完不杀进程（调试用，记得自己清理窗口与 mpv）")
    args = parser.parse_args(argv)

    if not IS_WINDOWS:
        sys.exit("mem_bench.py 仅支持 Windows（依赖 psapi / tasklist / taskkill）")

    if args.only:
        order = [t for t in TARGETS if t in args.only]
    else:
        order = list(DEFAULT_ORDER)
        if args.cli:
            order.append("cli")

    result = {"seconds": args.seconds, "theme": args.theme, "targets": [], "imports": []}

    if not args.imports_only:
        for key in order:
            result["targets"].append(measure_target(key, args))
        report(result["targets"])

    if not args.no_imports:
        result["imports"] = measure_imports(min(args.seconds, 12), keep=args.keep)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        print(f"\n结果已写入: {os.path.abspath(args.json_path)}")


if __name__ == "__main__":
    main()
