# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ADBLab — ensures resource files are bundled."""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        ('resources/icons', 'resources/icons'),
        ('resources/app_settings.json', 'resources'),
        ('resources/connected_devices.yaml', 'resources'),
        ('resources/chkbugreport-0.5-215.jar', 'resources'),
        ('resources/ZFB.jpg', 'resources'),
        ('THIRD_PARTY_NOTICES.md', 'licenses'),
        ('mobileperf/LICENSE', 'licenses/mobileperf'),
        ('mobileperf/extlib/xlsxwriter/LICENSE.txt', 'licenses/xlsxwriter'),
        ('icon.ico', '.'),
        ('scrcpy-win64', 'scrcpy-win64'),
    ],
    hiddenimports=collect_submodules('mobileperf') + collect_submodules('qfluentwidgets'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
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
    [],
    exclude_binaries=True,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ADBLab',
)
