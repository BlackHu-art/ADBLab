"""文件功能包迁移保持导入身份、懒加载及旧 worker 替换行为。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PAIRS = (
    ("file_explorer", "page"),
    ("file_explorer_image", "image"),
    ("file_explorer_list", "list"),
    ("file_explorer_ops", "ops"),
    ("file_explorer_transfers", "transfers"),
    ("file_explorer_view", "view"),
    ("file_explorer_preview_tasks", "preview_tasks"),
)


def _run_import_probe(script, *args):
    result = subprocess.run(
        [sys.executable, "-c", script, *args],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, (
        f"exit={result.returncode}\n{result.stdout}{result.stderr}"
    )


@pytest.mark.parametrize("old_name,new_name", MODULE_PAIRS)
@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_each_module_import_order_preserves_identity(old_name, new_name, old_first):
    _run_import_probe(
        """
import importlib
import sys

old_name, new_name, old_first = sys.argv[1:]
old_path = 'gui.dialogs.' + old_name
new_path = 'gui.features.file_explorer.' + new_name
first, second = (old_path, new_path) if old_first == 'True' else (new_path, old_path)
first_module = importlib.import_module(first)
second_module = importlib.import_module(second)
assert first_module is second_module
assert sys.modules[old_path] is sys.modules[new_path]
assert getattr(importlib.import_module('gui.dialogs'), old_name) is second_module
assert getattr(importlib.import_module('gui.features.file_explorer'), new_name) is second_module
from gui.features.file_explorer import FileExplorerPage
from gui.dialogs.file_explorer import FileExplorerPage as OldPage
from gui.features.file_explorer.page import FileExplorerPage as NewPage
assert FileExplorerPage is OldPage is NewPage
""",
        old_name, new_name, str(old_first),
    )


@pytest.mark.parametrize("leaf", ["", "preview_tasks"], ids=["package-only", "leaf-first"])
def test_package_and_preview_tasks_load_without_page(leaf):
    _run_import_probe(
        """
import importlib
import sys

package = importlib.import_module('gui.features.file_explorer')
leaf = sys.argv[1]
if leaf:
    importlib.import_module('gui.features.file_explorer.' + leaf)
assert 'gui.features.file_explorer.page' not in sys.modules
assert not any(name.startswith('gui.dialogs.file_explorer') for name in sys.modules)
for prefix in ('gui.features.app_manager', 'gui.features.performance',
               'gui.dialogs.app_manager', 'gui.dialogs.performance_launcher'):
    assert not any(name.startswith(prefix) for name in sys.modules)
try:
    package.unknown_feature_attribute
except AttributeError:
    pass
else:
    raise AssertionError('unknown package attribute must raise AttributeError')
from gui.features.file_explorer import FileExplorerPage
page = importlib.import_module('gui.features.file_explorer.page')
assert FileExplorerPage is page.FileExplorerPage
""",
        leaf,
    )


@pytest.mark.ui
def test_old_page_worker_patch_is_used_by_commands(qt_application, monkeypatch):
    from gui.features.file_explorer import FileExplorerPage
    from models.file_explorer_worker import ADBWorker, TransferWorker

    class HeldADBWorker(ADBWorker):
        def start(self):
            raise AssertionError("command factory must not start ADB")

    class HeldTransferWorker(TransferWorker):
        def start(self):
            raise AssertionError("command factory must not start transfer")

    monkeypatch.setattr("gui.dialogs.file_explorer.ADBWorker", HeldADBWorker)
    monkeypatch.setattr("gui.dialogs.file_explorer.TransferWorker", HeldTransferWorker)
    page = FileExplorerPage(device_ip="synthetic-device")
    try:
        adb = page._run_adb("shell", "pwd", timeout=17, _device_ip="synthetic-origin")
        transfer = page._run_transfer(
            "push", "source.txt", "/target.txt", _device_ip="synthetic-origin",
        )
        assert isinstance(adb, HeldADBWorker)
        assert isinstance(transfer, HeldTransferWorker)
        assert adb.args == ["shell", "pwd"]
        assert adb.timeout == 17
        assert transfer.args == ["push", "source.txt", "/target.txt"]
        for worker in (adb, transfer):
            assert worker.device_ip == "synthetic-origin"
            assert worker in page._workers
            assert worker.parent() is page
            assert not worker.isRunning()
    finally:
        page.close()
        page.deleteLater()
        qt_application.processEvents()


@pytest.mark.ui
def test_old_list_worker_patch_is_used_by_refresh(qt_application, monkeypatch):
    from gui.features.file_explorer import FileExplorerPage
    from models.file_explorer_worker import DirectoryListWorker

    class HeldDirectoryListWorker(DirectoryListWorker):
        def start(self):
            self.start_requested = True

    monkeypatch.setattr(
        "gui.dialogs.file_explorer_list.DirectoryListWorker", HeldDirectoryListWorker,
    )
    page = FileExplorerPage(device_ip="synthetic-device")
    try:
        page.root_cb.setChecked(True)
        page._refresh(requested_path="/data/local/tmp")
        worker = page._active_refresh_worker
        assert isinstance(worker, HeldDirectoryListWorker)
        assert worker.start_requested
        assert worker.device_ip == "synthetic-device"
        assert worker.path == "/data/local/tmp"
        assert worker.use_root is True
        assert worker.property("refreshRequestId") == 1
        assert worker.property("requestedPath") == "/data/local/tmp"
        assert page._active_refresh == (1, "/data/local/tmp")
        assert worker in page._workers
        assert worker.parent() is page
        assert not worker.isRunning()
    finally:
        page.close()
        page.deleteLater()
        qt_application.processEvents()
