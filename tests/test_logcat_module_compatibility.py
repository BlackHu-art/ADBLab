"""Logcat 目录迁移保持模块身份、导入顺序和旧路径替换契约。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PAIRS = (
    ("live_logcat", "page"),
    ("live_logcat_form", "form"),
    ("live_logcat_lifecycle", "lifecycle"),
    ("live_logcat_stream", "stream"),
    ("live_logcat_worker", "worker"),
    ("live_logcat_controls", "controls"),
    ("live_logcat_highlighter", "highlighter"),
    ("live_logcat_material", "material"),
)


@pytest.mark.parametrize("old_name,new_name", MODULE_PAIRS)
@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_each_module_import_order_preserves_identity(old_name, new_name, old_first):
    script = """
import importlib
import sys

old_name, new_name, old_first = sys.argv[1:]
old_path = 'gui.dialogs.' + old_name
new_path = 'gui.features.logcat.' + new_name
first, second = (old_path, new_path) if old_first == 'True' else (new_path, old_path)
first_module = importlib.import_module(first)
if new_name == 'worker':
    assert 'gui.features.logcat.page' not in sys.modules
    assert 'gui.dialogs.live_logcat' not in sys.modules
second_module = importlib.import_module(second)
assert first_module is second_module
assert sys.modules[old_path] is sys.modules[new_path]
assert getattr(importlib.import_module('gui.dialogs'), old_name) is second_module
assert getattr(importlib.import_module('gui.features.logcat'), new_name) is second_module
from gui.features.logcat import LiveLogcatPage
from gui.dialogs.live_logcat import CurrentPackageWorker, LiveLogcatPage as OldPage
from gui.features.logcat.page import LiveLogcatPage as NewPage
from gui.features.logcat.worker import CurrentPackageWorker as NewPackageWorker
assert LiveLogcatPage is OldPage is NewPage
assert CurrentPackageWorker is NewPackageWorker
"""
    result = subprocess.run(
        [sys.executable, "-c", script, old_name, new_name, str(old_first)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.ui
def test_old_stream_package_worker_patch_is_used_by_query(qt_application, monkeypatch):
    from gui.features.logcat import LiveLogcatPage
    from gui.features.logcat.worker import CurrentPackageWorker

    class HeldPackageWorker(CurrentPackageWorker):
        def start(self):
            self.start_requested = True

    monkeypatch.setattr(
        "gui.dialogs.live_logcat_stream.CurrentPackageWorker", HeldPackageWorker,
    )
    page = LiveLogcatPage(device_ip="synthetic-device")
    try:
        page._fetch_current_pkg()
        assert isinstance(page._pkg_worker, HeldPackageWorker)
        assert page._pkg_worker.start_requested
        assert not page.btn_get_pkg.isEnabled()
        assert page.status_bar.compactText() == "查询应用"
    finally:
        if page._pkg_worker is not None:
            page._release_pkg_worker(page._pkg_worker)
        page.close()
        page.deleteLater()
        qt_application.processEvents()


@pytest.mark.ui
def test_old_page_logcat_worker_patch_is_used_by_start(qt_application, monkeypatch):
    from gui.features.logcat import LiveLogcatPage
    from gui.features.logcat.worker import LogcatWorker

    class HeldLogcatWorker(LogcatWorker):
        def start(self):
            self.start_requested = True

    monkeypatch.setattr("gui.dialogs.live_logcat.LogcatWorker", HeldLogcatWorker)
    page = LiveLogcatPage(device_ip="synthetic-device")
    try:
        page._start()
        assert isinstance(page.worker, HeldLogcatWorker)
        assert page.worker.start_requested
        assert not page.start_action.isEnabled()
        assert page.stop_action.isEnabled()
        assert page.status_bar.compactText() == "启动中"
    finally:
        if page.worker is not None:
            page._release_logcat_worker(page.worker)
        page.close()
        page.deleteLater()
        qt_application.processEvents()
