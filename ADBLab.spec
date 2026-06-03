# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ADBLab — ensures resource files are bundled."""

from pathlib import Path

ROOT = Path(SPECPATH)
WEB_DASHBOARD_ASSETS = ROOT / 'gui' / 'performance_web' / 'assets'

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        ('resources', 'resources'),
        ('icon.ico', '.'),
        ('scrcpy-win64-v3.3.1', 'scrcpy-win64-v3.3.1'),
        (str(WEB_DASHBOARD_ASSETS), 'gui/performance_web/assets'),
    ],
    hiddenimports=[
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'email',
        'http',
        'xmlrpc',
        'pydoc',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ADBLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Windows GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
