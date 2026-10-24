"""Qt worker 迁移保持模块身份、替换接缝及新入口导入边界。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ISOLATE_SETTINGS = r'''
from pathlib import Path
import os
import core.settings_manager as settings
settings.LEGACY_SETTINGS_FILE = str(Path(os.environ["LOCALAPPDATA"]) / "legacy.json")
assert Path(settings.SETTINGS_FILE).is_relative_to(Path(os.environ["LOCALAPPDATA"]))
assert not Path(settings.LEGACY_SETTINGS_FILE).exists()
'''


def _run_probe(script: str, tmp_path: Path, *arguments: str) -> None:
    """每个探针独占模块表与运行数据，不能读到用户设置或真实设备。"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                 "XDG_DATA_HOME", "MOBILEPERF_LOG_DIR", "TMPDIR", "TEMP", "TMP"):
        env[name] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-B", "-c", _ISOLATE_SETTINGS + script, *arguments],
        cwd=_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.integration
@pytest.mark.parametrize("leaf", ["app_manager", "file_explorer"])
@pytest.mark.parametrize("order", ["old-first", "new-first"])
def test_worker_module_import_order_preserves_identity(tmp_path, leaf, order):
    """静态类再导出或新入口抢注册旧 key 会破坏模块/父包属性身份。"""
    _run_probe(r'''
import importlib
import sys
from PySide6.QtCore import QThread

leaf, order = sys.argv[1:]
old_name = "models." + leaf + "_worker"
new_name = "adblab.presentation.workers." + leaf
first_name, second_name = ((old_name, new_name) if order == "old-first"
                           else (new_name, old_name))
first = importlib.import_module(first_name)
if order == "new-first":
    assert "models" not in sys.modules
    assert old_name not in sys.modules
second = importlib.import_module(second_name)
assert first is second
assert sys.modules[old_name] is sys.modules[new_name] is first
assert getattr(sys.modules["models"], leaf + "_worker") is first
assert getattr(sys.modules["adblab.presentation.workers"], leaf) is first
names = (["AppManagerWorker"] if leaf == "app_manager" else [
    "ADBWorker", "DirectoryListWorker", "TextReadWorker", "TextSaveWorker",
    "LocalTextSaveWorker", "TransferWorker",
])
for name in names:
    worker_type = getattr(first, name)
    assert worker_type is getattr(second, name)
    assert worker_type.__module__ == new_name
    assert issubclass(worker_type, QThread)
    if name in {"DirectoryListWorker", "TextReadWorker", "TextSaveWorker",
                "LocalTextSaveWorker"}:
        assert worker_type.__bases__ == (first.ADBWorker,)
    else:
        assert worker_type.__bases__ == (QThread,)
''', tmp_path, leaf, order)


@pytest.mark.integration
@pytest.mark.parametrize("leaf", ["package-only", "app_manager", "file_explorer"])
def test_new_worker_import_does_not_load_model_or_gui_aggregates(tmp_path, leaf):
    """新入口反向依赖旧聚合或包 eager 导出会触发实际导入阻断。"""
    _run_probe(r'''
import importlib
import importlib.abc
import sys

blocked = ("models", "controllers", "gui", "qfluentwidgets")
def forbidden(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in blocked)
assert not any(forbidden(name) for name in sys.modules)
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise AssertionError("forbidden import: " + fullname)
sys.meta_path.insert(0, Blocker())
leaf = sys.argv[1]
package = "adblab.presentation.workers"
importlib.import_module(package if leaf == "package-only" else package + "." + leaf)
assert not any(forbidden(name) for name in sys.modules)
for other in ("app_manager", "file_explorer"):
    if leaf != other:
        assert package + "." + other not in sys.modules
''', tmp_path, leaf)


@pytest.mark.integration
@pytest.mark.parametrize("leaf", ["app_manager", "file_explorer"])
@pytest.mark.parametrize("alias", ["old", "new"])
@pytest.mark.parametrize("timing", ["before-construction", "after-construction"])
def test_old_module_rebinding_reaches_new_worker_execution(tmp_path, leaf, alias, timing):
    """模块快照或构造期缓存会使真实 run 无法使用调用前替换的服务。"""
    _run_probe(r'''
import importlib
import sys
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication

application = QCoreApplication([])
leaf, alias, timing = sys.argv[1:]
new = importlib.import_module("adblab.presentation.workers." + leaf)
old = importlib.import_module("models." + leaf + "_worker")
target = old if alias == "old" else new
calls, received = [], []
def unexpected_external_call(*args, **kwargs):
    raise AssertionError("unreplaced worker dependency must not access a device")
if leaf == "app_manager":
    new.load_app_icons = unexpected_external_call
    def fake_load(device, packages, cancelled, emit):
        calls.append((device, packages, cancelled()))
        emit("com.example.app", b"synthetic-png", "")
    def construct():
        worker = new.AppManagerWorker(
            "synthetic-device", "load_icon_batch", packages=["com.example.app"],
        )
        worker.app_icon_loaded.connect(lambda *args: received.append(args))
        return worker
    def rebind():
        target.load_app_icons = fake_load
else:
    new.CommandRunner = SimpleNamespace(run=unexpected_external_call)
    class FakeRunner:
        @staticmethod
        def run(command, *, timeout, cancelled):
            calls.append((command, timeout, cancelled()))
            return SimpleNamespace(success=True, output="synthetic-output", error="")
    def construct():
        worker = new.ADBWorker("synthetic-device", ["shell", "pwd"], timeout=7)
        worker.result_ready.connect(lambda *args: received.append(args))
        return worker
    def rebind():
        target.CommandRunner = FakeRunner
if timing == "before-construction":
    rebind()
worker = construct()
if timing == "after-construction":
    rebind()
worker.run()
if leaf == "app_manager":
    assert calls == [("synthetic-device", ["com.example.app"], False)]
    assert received == [("com.example.app", b"synthetic-png", "")]
else:
    assert calls == [(["adb", "-s", "synthetic-device", "shell", "pwd"], 7, False)]
    assert received == [("synthetic-output", False)]
assert not worker.isRunning()
''', tmp_path, leaf, alias, timing)
