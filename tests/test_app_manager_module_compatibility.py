"""应用管理归包保留旧路径身份、懒加载与两处独立 worker 替换边界。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PAIRS = (
    ("app_manager", "page"),
    ("app_manager_details", "details"),
    ("app_manager_batch", "batch"),
    ("app_manager_form", "form"),
    ("app_manager_icons", "icons"),
    ("app_manager_views", "views"),
    ("app_manager_rows", "rows"),
    ("app_manager_material", "material"),
)


def _run_import_probe(script, *arguments):
    result = subprocess.run(
        [sys.executable, "-c", script, *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, (
        f"exit={result.returncode}\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.parametrize("old_name,new_name", MODULE_PAIRS)
@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_each_module_import_order_preserves_identity(old_name, new_name, old_first):
    _run_import_probe("""
import importlib
import sys

old_name, new_name, old_first = sys.argv[1:]
old_path = 'gui.dialogs.' + old_name
new_path = 'gui.features.app_manager.' + new_name
first, second = (old_path, new_path) if old_first == 'True' else (new_path, old_path)
first_module = importlib.import_module(first)
second_module = importlib.import_module(second)
assert first_module is second_module
assert sys.modules[old_path] is sys.modules[new_path]
assert getattr(importlib.import_module('gui.dialogs'), old_name) is second_module
assert getattr(importlib.import_module('gui.features.app_manager'), new_name) is second_module
from gui.features.app_manager import AppDetailsPage, AppManagerPage, AppSortProxy
from gui.features.app_manager.page import AppManagerPage as NewPage, AppSortProxy as NewProxy
from gui.features.app_manager.details import AppDetailsPage as NewDetails
from gui.dialogs.app_manager import AppManagerPage as OldPage, AppSortProxy as OldProxy
from gui.dialogs.app_manager_details import AppDetailsPage as OldDetails
assert AppManagerPage is NewPage is OldPage
assert AppSortProxy is NewProxy is OldProxy
assert AppDetailsPage is NewDetails is OldDetails
""", old_name, new_name, str(old_first))


@pytest.mark.parametrize("leaf", ["", "rows", "details"], ids=["package", "rows", "details"])
def test_package_and_collaborator_imports_remain_lazy(leaf):
    _run_import_probe("""
import importlib
import sys

leaf = sys.argv[1]
package = importlib.import_module('gui.features.app_manager')
if leaf:
    importlib.import_module('gui.features.app_manager.' + leaf)
assert 'gui.features.app_manager.page' not in sys.modules
assert not any(name.startswith('gui.dialogs.app_manager') for name in sys.modules)
assert not any(name.startswith(('gui.features.file_explorer', 'gui.features.performance'))
               for name in sys.modules)
try:
    package.unknown_feature_attribute
except AttributeError:
    pass
else:
    raise AssertionError('unknown package attribute must raise AttributeError')
if leaf == 'details':
    from gui.features.app_manager import AppDetailsPage
    assert AppDetailsPage is sys.modules['gui.features.app_manager.details'].AppDetailsPage
    assert 'gui.features.app_manager.page' not in sys.modules
from gui.features.app_manager import AppManagerPage
assert AppManagerPage is sys.modules['gui.features.app_manager.page'].AppManagerPage
""", leaf)


@pytest.mark.ui
def test_old_page_proxy_patch_is_used_by_form(qt_application, monkeypatch):
    from gui.dialogs import app_manager as old_page
    from gui.features.app_manager import AppManagerPage

    class RecordingProxy(old_page.AppSortProxy):
        pass

    monkeypatch.setattr(old_page, "AppSortProxy", RecordingProxy)
    page = AppManagerPage(device_ip="compat-device")
    try:
        assert isinstance(page.proxy, RecordingProxy)
        page._populate([("Example", "org.example.compat", "Enabled", "User")])
        page.search_input.setText("org.example.compat")
        assert page.proxy.rowCount() == 1
    finally:
        page.close()


@pytest.fixture
def patched_page(qt_application, monkeypatch):
    from gui.features.app_manager import AppManagerPage
    from tests.test_app_manager_user_context import UserWorker

    page_workers, detail_workers = [], []

    def page_factory(*args, **kwargs):
        worker = UserWorker(*args, **kwargs)
        page_workers.append(worker)
        return worker

    def detail_factory(*args, **kwargs):
        worker = UserWorker(*args, **kwargs)
        detail_workers.append(worker)
        return worker

    page = AppManagerPage(device_ip="compat-device")
    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerWorker", page_factory)
    monkeypatch.setattr("gui.dialogs.app_manager_details.AppManagerWorker", detail_factory)
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    yield page, page_workers, detail_workers
    page.request_dispose()
    for worker in page._all_workers():
        if worker.isRunning():
            worker.finish()
    qt_application.processEvents()
    page.close()


@pytest.mark.ui
def test_old_page_worker_patch_reaches_collaborators(patched_page, qt_application, monkeypatch):
    from tests.test_app_manager_user_context import PACKAGE, snapshot
    from tests.ui_geometry_helpers import wait_until

    page, workers, detail_workers = patched_page
    snapshot(page, workers, qt_application, 10)
    assert workers[0].device_ip == "compat-device"
    assert workers[0].kwargs.get("user_id") is None
    assert page._android_user_ready
    page._active = True
    monkeypatch.setattr(page, "_visible_detail_packages", lambda: [PACKAGE])
    page._load_visible_details()
    metadata = workers[-1]
    assert metadata.operation == "load_metadata_batch"
    assert metadata.kwargs == {"packages": [PACKAGE], "user_id": 10}
    metadata.finish()
    wait_until(qt_application, lambda: not page._detail_worker_running)

    page._launch(PACKAGE)
    launch = workers[-1]
    assert launch.operation == "launch_app"
    assert launch.kwargs == {"package_name": PACKAGE, "user_id": 10}
    launch.finish()
    wait_until(qt_application, lambda: not page._batch_workers)

    page._loaded_detail_packages.add(PACKAGE)
    monkeypatch.setattr(page, "_visible_detail_packages", lambda: [])
    monkeypatch.setattr(page._icons_controller, "_visible_packages", lambda: [PACKAGE])
    page._icons_controller._load_visible()
    icon = workers[-1]
    assert icon.operation == "load_icon_batch"
    assert icon.kwargs == {"packages": [PACKAGE], "expected_fingerprints": {}, "user_id": 10}
    assert icon.property("iconEpoch") == page._icons_controller._epoch
    assert all(worker.device_ip == "compat-device" for worker in workers)
    assert detail_workers == []


@pytest.mark.ui
def test_details_worker_patch_remains_independent(patched_page, qt_application):
    from gui.features.app_manager import AppDetailsPage
    from tests.test_app_manager_user_context import PACKAGE, snapshot

    page, workers, detail_workers = patched_page
    snapshot(page, workers, qt_application, 10)
    detail = page.details_page
    assert isinstance(detail, AppDetailsPage)
    received = []
    generation = detail._load_generation
    worker = detail._rw(
        "app_snapshot", _generation=generation, package_name=PACKAGE,
        app_details_loaded=received.append,
    )
    assert detail_workers == [worker]
    assert len(workers) == 1
    assert worker.parent() is detail
    assert worker.kwargs == {"package_name": PACKAGE, "user_id": 10}
    worker.user_context_loaded.emit(10)
    worker.app_details_loaded.emit({"Package": PACKAGE})
    qt_application.processEvents()
    assert detail._pending_android_user_id == 10
    assert received == [{"Package": PACKAGE}]
    detail.set_android_user(11)
    worker.user_context_loaded.emit(10)
    worker.app_details_loaded.emit({"Package": "org.example.stale"})
    qt_application.processEvents()
    assert detail._load_generation > generation
    assert detail._android_user_id == 11
    assert received == [{"Package": PACKAGE}]
