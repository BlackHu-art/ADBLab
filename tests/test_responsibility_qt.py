"""Qt 职责入口必须独立加载真实实现，避免退役包或界面聚合回流。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_LEAVES = [
    ("core.tasks.qt_supervisor", ["QtTaskSupervisor"]),
    ("gui.adapters.adb_runtime", ["QtAdbRuntime"]),
    ("gui.adapters.adb_pairing", [
        "_context", "_PairingWorker", "_PairingResources", "QtAdbPairing",
    ]),
    ("gui.adapters.apk_file_picker", ["QtApkFilePicker"]),
    ("gui.adapters.app_update", ["QtAppUpdate"]),
    ("gui.adapters.device_connection_lifecycle", [
        "_WindowWirelessHistoryGuard", "QtDeviceConnectionLifecycle",
    ]),
    ("gui.workers.device_discovery", ["_ScannedDevices", "_ScanDiscoveryState", "_ScanThread"]),
    ("gui.workers.app_manager", ["AppManagerWorker"]),
    ("gui.workers.file_explorer", [
        "ADBWorker", "DirectoryListWorker", "TextReadWorker", "TextSaveWorker",
        "LocalTextSaveWorker", "TransferWorker",
    ]),
]


def _probe(tmp_path: Path, script: str, *arguments: str) -> None:
    """隔离设置和模块表，禁止导入过程启动真实外部进程。"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                 "XDG_DATA_HOME", "MOBILEPERF_LOG_DIR", "TMPDIR", "TEMP", "TMP"):
        env[name] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, *arguments],
        cwd=_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30,
    )
    assert result.returncode == 0, f"exit={result.returncode}\n{result.stdout}{result.stderr}"


@pytest.mark.integration
@pytest.mark.parametrize(("module_name", "definitions"), _LEAVES)
def test_qt_leaf_owns_definitions_without_retired_or_gui_aggregate_imports(
    tmp_path, module_name, definitions,
):
    """错误再导出、旧依赖或包根聚合会使真实导入和定义归属检查失败。"""
    _probe(tmp_path, r'''
import importlib
import importlib.abc
from pathlib import Path
import subprocess
import sys

module_name, *definitions = sys.argv[1:]
allowed_gui = {"gui", "gui.adapters", "gui.workers", module_name}
blocked = ("adblab", "models", "controllers", "qfluentwidgets")
def forbidden(name):
    if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked):
        return True
    return name.startswith("gui.") and name not in allowed_gui
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise AssertionError("forbidden import: " + fullname)
sys.meta_path.insert(0, Blocker())
def no_process(*args, **kwargs):
    raise AssertionError("import must not start a process")
subprocess.Popen.__init__ = no_process
module = importlib.import_module(module_name)
assert Path(module.__file__).resolve() == Path(*module_name.split(".")).with_suffix(".py").resolve()
for name in definitions:
    assert getattr(module, name).__module__ == module_name
assert not any(forbidden(name) for name in sys.modules)
''', module_name, *definitions)


@pytest.mark.integration
@pytest.mark.parametrize("package", ["gui.adapters", "gui.workers"])
def test_qt_package_roots_do_not_eagerly_import_leaves_or_qt(tmp_path, package):
    """包根一旦主动聚合，纯目录发现就会触发不必要的 Qt/业务加载。"""
    _probe(tmp_path, r'''
import importlib
import importlib.abc
import sys

package = sys.argv[1]
allowed = {"gui", package}
blocked = ("PySide6", "shiboken6", "adblab", "core", "services", "models",
           "controllers", "qfluentwidgets")
def forbidden(name):
    return (any(name == prefix or name.startswith(prefix + ".") for prefix in blocked)
            or (name.startswith("gui.") and name not in allowed))
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise AssertionError("forbidden import: " + fullname)
sys.meta_path.insert(0, Blocker())
importlib.import_module(package)
assert not any(forbidden(name) for name in sys.modules)
''', package)
