# -*- mode: python ; coding: utf-8 -*-
"""使用公共资源白名单构建 Windows 窗口模式的 onedir 应用。"""

from pathlib import Path
import subprocess
import sys
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)
sys.path.insert(0, str(ROOT))

from scripts.packaging_manifest import SUBMODULE_PACKAGES, resource_datas

subprocess.run([sys.executable, str(ROOT / 'scripts/prepare_runtime_tools.py')], check=True)
subprocess.run([sys.executable, str(ROOT / 'scripts/build_scrcpy_adb_bridge.py')], check=True)

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=resource_datas(),
    hiddenimports=[
        module for package in SUBMODULE_PACKAGES for module in collect_submodules(package)
    ],
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
    console=False,  # Windows 窗口应用不附带控制台。
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
