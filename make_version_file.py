#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
make_version_file.py —— 生成 PyInstaller 可用的 Windows 版本资源文件
====================================================================
从同目录的 VERSION 读取版本号（如 1.2.3），输出到 build/version_info.txt，
供 build_exe*.bat 通过 PyInstaller --version-file 写入 exe 属性。
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "JusicRoomPlayer"
DESCRIPTION = "Jusic 房间播放器 - 一起听歌吧 轻量客户端（ttk GUI / mpv 内核）"
COMPANY = "The JusicRoomPlayer Authors"
COPYRIGHT = "Copyright (C) 2026 The JusicRoomPlayer Authors"


def read_version():
    path = os.path.join(ROOT, "VERSION")
    with open(path, "r", encoding="utf-8") as fh:
        ver = fh.read().strip()
    parts = [int(x) for x in ver.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return ver, tuple(parts[:4])


def build_info_text(ver, parts):
    vals = ", ".join(str(x) for x in parts)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({vals}),
    prodvers=({vals}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [StringStruct('CompanyName', '{COMPANY}'),
           StringStruct('FileDescription', '{DESCRIPTION}'),
           StringStruct('FileVersion', '{ver}'),
           StringStruct('InternalName', '{APP_NAME}'),
           StringStruct('LegalCopyright', '{COPYRIGHT}'),
           StringStruct('OriginalFilename', '{APP_NAME}.exe'),
           StringStruct('ProductName', '{APP_NAME}'),
           StringStruct('ProductVersion', '{ver}')]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main():
    ver, parts = read_version()
    build_dir = os.path.join(ROOT, "build")
    os.makedirs(build_dir, exist_ok=True)
    out = os.path.join(build_dir, "version_info.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(build_info_text(ver, parts))
    print(ver)          # 供调用方(bat)拿到版本号
    print(out)


if __name__ == "__main__":
    main()
