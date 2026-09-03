#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
make_zip.py —— 把 dist 下的绿色目录版文件夹压缩成同版本 ZIP
====================================================================
读取同目录 VERSION；将 dist\\JusicRoomPlayerPortable_<版本> 压缩为
dist\\JusicRoomPlayerPortable_<版本>.zip（ZIP 顶层即版本文件夹）。
由 build_exe_dir.bat 在 PyInstaller 打包后调用。
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    ver = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip() or "0.0.0"
    dist = os.path.join(ROOT, "dist")
    folder = os.path.join(dist, f"JusicRoomPlayerPortable_{ver}")
    if not os.path.isdir(folder):
        sys.exit(f"找不到目录: {folder}")

    target = os.path.join(dist, f"JusicRoomPlayerPortable_{ver}")
    zip_path = target + ".zip"
    if os.path.isfile(zip_path):
        os.remove(zip_path)

    # base_dir=版本文件夹，使解压后顶层就是该文件夹，不含 dist 前缀
    made = shutil.make_archive(target, "zip", root_dir=dist,
                               base_dir=f"JusicRoomPlayerPortable_{ver}")
    size = os.path.getsize(made) / 1048576
    print(f"ZIP OK: {made} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
