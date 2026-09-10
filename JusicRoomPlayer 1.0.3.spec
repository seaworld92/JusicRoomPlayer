# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['jusic_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Program Files/MPV Player/mpv.exe', '_engine/mpv'), ('D:/BaiduSyncdisk/编程/本地音乐播放器/VERSION', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='JusicRoomPlayer 1.0.3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='build/version_info.txt',
)
