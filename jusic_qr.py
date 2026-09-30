#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 The JusicRoomPlayer Authors
"""
jusic_qr：纯 Python 二维码(QR Code)生成，零第三方依赖
======================================================
只为「分享房间」等小场景服务：把链接（字节模式，UTF-8）编码为 QR 矩阵，
再由 GUI 用 tkinter Canvas 绘制，或用 :func:`qr_png_bytes` 导出 PNG。

实现范围（够用即止，避免拖入庞大的通用二维码库）：
* 字节模式（UTF-8），版本 1-10 自动选择
* 纠错等级 L/M/Q/H（官方网页端分享用 H，空间不足时自动降级）
* 8 种掩码按标准 4 条惩罚规则择优
* 输出：``matrix``（0/1 二维列表）/ ``png``（8 位灰度 PNG 字节）

用法::

    from jusic_qr import encode, qr_png_bytes
    matrix = encode("https://happy.alang.run/modern-ui?houseId=DEFAULT")
    open("room.png", "wb").write(qr_png_bytes(matrix, scale=8, border=4))
"""

import zlib

# --------------------------------------------------------------------------- #
# GF(256) 伽罗华域（QR 本原多项式 x^8 + x^4 + x^3 + x^2 + 1 = 0x11D）
# --------------------------------------------------------------------------- #
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(nsym: int):
    """生成多项式 prod(x + α^i)，系数按最高次在前。"""
    gen = [1]
    for i in range(nsym):
        nxt = [0] * (len(gen) + 1)
        for j, coef in enumerate(gen):
            nxt[j] ^= coef
            nxt[j + 1] ^= _mul(coef, _EXP[i])
        gen = nxt
    return gen


def _rs_encode(msg, nsym: int):
    """Reed-Solomon 纠错码字（系统码，返回 nsym 个校验码字）。"""
    gen = _rs_generator(nsym)
    out = list(msg) + [0] * nsym
    for i in range(len(msg)):
        coef = out[i]
        if coef:
            for j in range(1, len(gen)):
                out[i + j] ^= _mul(gen[j], coef)
    return out[len(msg):]


# --------------------------------------------------------------------------- #
# 标准表（版本 1-10）
# --------------------------------------------------------------------------- #
# 纠错等级 -> 格式信息里的 2 bit 编码
_EC_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}
# 容量由大到小；空间不足时按此顺序降级
_EC_FALLBACK = ("L", "M", "Q", "H")

# 版本 -> {等级: (每块纠错码字数, [(块数, 每块数据码字数), ...])}
_BLOCKS = {
    1: {"L": (7, [(1, 19)]), "M": (10, [(1, 16)]),
        "Q": (13, [(1, 13)]), "H": (17, [(1, 9)])},
    2: {"L": (10, [(1, 34)]), "M": (16, [(1, 28)]),
        "Q": (22, [(1, 22)]), "H": (28, [(1, 16)])},
    3: {"L": (15, [(1, 55)]), "M": (26, [(1, 44)]),
        "Q": (18, [(2, 17)]), "H": (22, [(2, 13)])},
    4: {"L": (20, [(1, 80)]), "M": (18, [(2, 32)]),
        "Q": (26, [(2, 24)]), "H": (16, [(4, 9)])},
    5: {"L": (26, [(1, 108)]), "M": (24, [(2, 43)]),
        "Q": (18, [(2, 15), (2, 16)]), "H": (22, [(2, 11), (2, 12)])},
    6: {"L": (18, [(2, 68)]), "M": (16, [(4, 27)]),
        "Q": (24, [(4, 19)]), "H": (28, [(4, 15)])},
    7: {"L": (20, [(2, 78)]), "M": (18, [(4, 31)]),
        "Q": (18, [(2, 14), (4, 15)]), "H": (26, [(4, 13), (1, 14)])},
    8: {"L": (24, [(2, 97)]), "M": (22, [(2, 38), (2, 39)]),
        "Q": (22, [(4, 18), (2, 19)]), "H": (26, [(4, 14), (2, 15)])},
    9: {"L": (30, [(2, 116)]), "M": (22, [(3, 36), (2, 37)]),
        "Q": (20, [(4, 16), (4, 17)]), "H": (24, [(4, 12), (4, 13)])},
    10: {"L": (18, [(2, 68), (2, 69)]), "M": (26, [(4, 43), (1, 44)]),
         "Q": (24, [(6, 19), (2, 20)]), "H": (28, [(6, 15), (2, 16)])},
}

# 每个版本的总码字数（用于自检：数据 + 纠错 应与之相等）
_TOTAL_CW = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134,
             6: 172, 7: 196, 8: 242, 9: 292, 10: 346}

# 校正图形中心坐标
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
          6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46],
          10: [6, 28, 50]}

# 版本信息（18 bit，BCH(18,6)），仅版本 7 起需要
_VERSION_INFO = {7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3}

_FORMAT_GEN = 0b10100110111        # 格式信息生成多项式 x^10+x^8+x^5+x^4+x^2+x+1
_FORMAT_XOR = 0b101010000010010    # 固定掩码 0x5412

MAX_VERSION = 10


def _char_count_bits(version: int) -> int:
    """字节模式的字符计数位宽：版本 1-9 为 8 bit，10-26 为 16 bit。"""
    return 8 if version < 10 else 16


def _data_codewords(version: int, ec: str) -> int:
    return sum(cnt * ln for cnt, ln in _BLOCKS[version][ec][1])


def _ec_block_count(version: int, ec: str) -> int:
    return sum(cnt for cnt, _ in _BLOCKS[version][ec][1])


def _choose(version: int, ec: str, nbytes: int):
    cap = _data_codewords(version, ec) * 8
    need = 4 + _char_count_bits(version) + 8 * nbytes
    return need <= cap


# --------------------------------------------------------------------------- #
# 数据编码
# --------------------------------------------------------------------------- #
def _payload_bits(payload: bytes, version: int, ec: str):
    """字节模式位流：模式指示符 + 字符计数 + 数据 + 结束符 + 补齐 + 填充码字。"""
    cap_bits = _data_codewords(version, ec) * 8
    bits = []

    def put(value, width):
        for i in range(width - 1, -1, -1):
            bits.append((value >> i) & 1)

    put(0b0100, 4)                       # 字节模式
    put(len(payload), _char_count_bits(version))
    for byte in payload:
        put(byte, 8)
    for _ in range(min(4, cap_bits - len(bits))):   # 结束符（最多 4 个 0）
        bits.append(0)
    while len(bits) % 8:                            # 补齐到字节边界
        bits.append(0)

    cws = [int("".join(str(b) for b in bits[i:i + 8]), 2)
           for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)                              # 标准填充码字
    i = 0
    while len(cws) < cap_bits // 8:
        cws.append(pad[i & 1])
        i += 1
    return cws


def _codeword_stream(data_cws, version: int, ec: str):
    """分块 → 逐块 RS 纠错 → 按标准交错输出码字序列。"""
    ec_len, groups = _BLOCKS[version][ec]
    data_blocks = []
    idx = 0
    for cnt, dlen in groups:
        for _ in range(cnt):
            data_blocks.append(data_cws[idx:idx + dlen])
            idx += dlen
    ec_blocks = [_rs_encode(blk, ec_len) for blk in data_blocks]

    out = []
    for i in range(max(len(b) for b in data_blocks)):
        for blk in data_blocks:
            if i < len(blk):
                out.append(blk[i])
    for i in range(ec_len):
        for blk in ec_blocks:
            out.append(blk[i])
    return out


# --------------------------------------------------------------------------- #
# 矩阵构造
# --------------------------------------------------------------------------- #
def _mask_fn(row: int, col: int, mask: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _format_bits(ec: str, mask: int) -> int:
    data = (_EC_BITS[ec] << 3) | mask
    rem = data << 10
    for i in range(4, -1, -1):
        if rem & (1 << (i + 10)):
            rem ^= _FORMAT_GEN << i
    return ((data << 10) | rem) ^ _FORMAT_XOR


def _setup_finder(m, res, size, top, left):
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = top + r, left + c
            if not (0 <= rr < size and 0 <= cc < size):
                continue
            res[rr][cc] = True
            if not (0 <= r <= 6 and 0 <= c <= 6):       # 分隔符（浅色）
                m[rr][cc] = 0
                continue
            border = r in (0, 6) or c in (0, 6)
            core = 2 <= r <= 4 and 2 <= c <= 4
            m[rr][cc] = 1 if (border or core) else 0


def _layout(version: int):
    """生成带功能图形的空白矩阵与“已占用”标记表。"""
    size = version * 4 + 17
    m = [[0] * size for _ in range(size)]
    res = [[False] * size for _ in range(size)]

    _setup_finder(m, res, size, 0, 0)
    _setup_finder(m, res, size, 0, size - 7)
    _setup_finder(m, res, size, size - 7, 0)

    for i in range(8, size - 8):                        # 定位时序图形
        bit = 1 if i % 2 == 0 else 0
        if not res[6][i]:
            m[6][i], res[6][i] = bit, True
        if not res[i][6]:
            m[i][6], res[i][6] = bit, True

    pos = _ALIGN[version]                                # 校正图形
    for r in pos:
        for c in pos:
            if (r, c) in ((6, 6), (6, pos[-1]), (pos[-1], 6)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    rr, cc = r + dr, c + dc
                    res[rr][cc] = True
                    m[rr][cc] = 1 if (abs(dr) == 2 or abs(dc) == 2
                                      or (dr == 0 and dc == 0)) else 0

    m[size - 8][8] = 1                                   # 固定的深色模块
    res[size - 8][8] = True

    for i in range(9):                                   # 格式信息预留区
        res[8][i] = True
        res[i][8] = True
    for i in range(8):
        res[8][size - 1 - i] = True
        res[size - 1 - i][8] = True

    if version >= 7:                                     # 版本信息预留区
        for i in range(6):
            for j in range(3):
                res[i][size - 11 + j] = True
                res[size - 11 + j][i] = True
    return m, res, size


def _place_data(m, res, size, bits):
    """自右下角起，两列一组之字形填充数据位。"""
    idx, total = 0, len(bits)
    col, upward = size - 1, True
    while col > 0:
        if col == 6:                                     # 跳过垂直时序列
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if res[row][c]:
                    continue
                m[row][c] = bits[idx] if idx < total else 0
                idx += 1
        upward = not upward
        col -= 2


def _draw_format(m, size, ec, mask):
    """格式信息（15 bit）的两处副本，bit0 为最低位。

    副本一环绕左上角定位图形；副本二为右上横排 + 左下竖排（注意两处
    的位序是镜像关系，(size-8, 8) 是固定深色模块，不可被格式位覆盖）。
    """
    bits = _format_bits(ec, mask)
    get = lambda i: (bits >> i) & 1                    # noqa: E731

    for i in range(6):                                  # 副本一：左侧竖排
        m[i][8] = get(i)
    m[7][8] = get(6)
    m[8][8] = get(7)
    m[8][7] = get(8)
    for i in range(9, 15):                              # 副本一：上方横排
        m[8][14 - i] = get(i)

    for i in range(8):                                  # 副本二：右上横排
        m[8][size - 1 - i] = get(i)
    for i in range(8, 15):                              # 副本二：左下竖排
        m[size - 15 + i][8] = get(i)


def _draw_version(m, size, version):
    bits = _VERSION_INFO[version]
    for i in range(18):
        bit = (bits >> i) & 1
        r, c = divmod(i, 3)
        m[size - 11 + c][r] = bit                       # 左下 3x6
        m[r][size - 11 + c] = bit                       # 右上 6x3


def _n3_line(line) -> int:
    """规则 3：深浅比 1:1:3:1:1 且前后（或贴边）有 4 个浅色模块，每次 40 分。"""
    text = "".join("1" if v else "0" for v in line)
    n = len(text)
    score = 0
    idx = text.find("1011101")
    while idx != -1:
        offset = idx + 7
        before = text[max(idx - 4, 0):idx]
        after = text[offset:offset + 4]
        if "1" not in before or "1" not in after:
            score += 40
        else:
            offset = idx + 4                             # 浅色不足，从下一个可能位置续找
        idx = text.find("1011101", offset)
    return score


def _penalty(m) -> int:
    """标准 4 条掩码惩罚规则（ISO/IEC 18004 7.8.3），分值越低越好。"""
    n = len(m)
    score = 0
    lines = [list(row) for row in m]
    lines += [[m[r][c] for r in range(n)] for c in range(n)]

    for line in lines:
        run = 1
        for i in range(1, n):                            # 规则 1：同色连续 5 个起
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
        score += _n3_line(line)                          # 规则 3

    for r in range(n - 1):                               # 规则 2：2x2 同色块
        for c in range(n - 1):
            v = m[r][c]
            if v == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3

    dark = sum(sum(row) for row in m)                     # 规则 4：深浅比例失衡
    percent = dark * 100.0 / (n * n)
    score += int(abs(percent - 50) / 5) * 10
    return score


def _build(version: int, ec: str, payload: bytes):
    data_cws = _payload_bits(payload, version, ec)
    stream = _codeword_stream(data_cws, version, ec)
    bits = [int(b) for cw in stream for b in format(cw, "08b")]

    best = None
    for mask in range(8):
        m, res, size = _layout(version)
        _place_data(m, res, size, bits)
        for r in range(size):                            # 掩码只作用于数据区
            for c in range(size):
                if not res[r][c] and _mask_fn(r, c, mask):
                    m[r][c] ^= 1
        _draw_format(m, size, ec, mask)
        if version >= 7:
            _draw_version(m, size, version)
        score = _penalty(m)
        if best is None or score < best[0]:
            best = (score, m)
    return best[1]


# --------------------------------------------------------------------------- #
# 对外接口
# --------------------------------------------------------------------------- #
def encode(text: str, ec: str = "H", max_version: int = MAX_VERSION):
    """把文本编码为 QR 矩阵（0/1 二维列表，True/1 = 深色模块）。

    ec 为期望的纠错等级（官方网页端分享使用 "H"）；空间不足时自动降级。
    内容超出可容纳范围时抛 ValueError。
    """
    payload = text.encode("utf-8")
    order = [ec] + [lv for lv in _EC_FALLBACK if lv != ec]
    for level in order:
        for version in range(1, max_version + 1):
            if _choose(version, level, len(payload)):
                return _build(version, level, payload)
    raise ValueError(f"内容过长，超出二维码（版本 1-{max_version}）容量：{len(payload)} 字节")


def png_bytes(matrix, scale: int = 8, border: int = 4) -> bytes:
    """把矩阵导出为 8 位灰度 PNG（深色=0，浅色=255），border 为静区模块数。"""
    n = len(matrix)
    scale = max(1, int(scale))
    side = (n + 2 * border) * scale
    rows = []
    for y in range(side):
        my = y // scale - border
        line = bytearray([0])                            # 每行滤波类型 0
        for x in range(side):
            mx = x // scale - border
            dark = 0 <= mx < n and 0 <= my < n and matrix[my][mx]
            line.append(0 if dark else 255)
        rows.append(bytes(line))
    raw = b"".join(rows)

    def chunk(tag, data):
        return (len(data).to_bytes(4, "big") + tag + data
                + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big"))

    ihdr = (side.to_bytes(4, "big") + side.to_bytes(4, "big")
            + bytes((8, 0, 0, 0, 0)))                    # 8bit 灰度、无隔行
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def self_check() -> None:
    """自检：所有版本/等级的码字数必须等于标准总码字数。"""
    for version, levels in _BLOCKS.items():
        for ec, (ec_len, groups) in levels.items():
            total = sum(cnt * ln for cnt, ln in groups) + ec_len * _ec_block_count(version, ec)
            if total != _TOTAL_CW[version]:
                raise AssertionError(f"版本 {version} 等级 {ec} 码字数 {total} != {_TOTAL_CW[version]}")


if __name__ == "__main__":
    self_check()
    demo = encode("https://happy.alang.run/modern-ui?houseId=DEFAULT&housePwd=")
    print(f"自检通过；示例矩阵 {len(demo)}x{len(demo)}")
