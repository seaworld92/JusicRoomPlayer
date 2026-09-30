#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
jusic_gui.pyw：无控制台双击启动器（等价于直接运行 jusic_gui.py）
=================================================================
Windows 下双击 .py 会弹黑色控制台窗口，而双击 .pyw 不会。
本文件只做一件事：把 jusic_gui 主程序跑起来，逻辑全部在 jusic_gui.py，
因此不会再出现两份界面代码不同步的问题。

命令行参数同样支持，例如：
    pythonw jusic_gui.pyw --host 你的域名 --volume 60
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jusic_gui import main      # noqa: E402

if __name__ == "__main__":
    main()
