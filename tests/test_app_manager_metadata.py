"""应用名称优先补全、增量缓存与刷新取消的页面回归。"""

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from gui.dialogs.app_manager import AppManagerPage
from tests.test_app_manager_icons import png
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class MetadataWorker(QObject):
    apps_loaded = Signal(list)
    app_metadata_loaded = Signal(dict)
    app_detail_batch = Signal(str, str, str, str)
    app_icon_loaded = Signal(str, bytes, str)
    log_message = Signal(str)
    finished = Signal()

    def __init__(self, device, operation, **kwargs):
        super().__init__()
        self.operation = operation
        self.packages = kwargs.get("packages", [])
        self.expected_fingerprints = kwargs.get("expected_fingerprints")
        self.running = False
        self.aborted = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def abort(self):
        self.aborted = True

    def finish(self):
        self.running = False
        self.finished.emit()


@pytest.fixture
def metadata_page(qt_application, monkeypatch):
    workers = []

    def create(*args, **kwargs):
        worker = MetadataWorker(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerWorker", create)
    page = AppManagerPage(device_ip="test-device")
    page._active = True
    page._activated_once = True
    page.resize(860, 620)
    page.show()
    yield page, workers
    page.request_dispose()
    for worker in workers:
        if worker in page._workers and worker.isRunning():
            worker.finish()
    qt_application.processEvents()
    page.close()


def apps(count=1):
    return [(f"App {index:03}", f"example.app{index}", "Enabled", "User")
            for index in range(count)]


def metadata(worker, *, fingerprints=None):
    for package in worker.packages:
        worker.app_metadata_loaded.emit({
            "package": package,
            "label": f"真实名称 {package}",
            "version": "1.0 (1)",
            "installed": "2026-09-25",
            "fingerprint": (fingerprints or {}).get(package, "user0:1:100:zh"),
        })
    worker.finish()


def images(worker):
    for package in worker.packages:
        worker.app_icon_loaded.emit(package, png(), "")
    worker.finish()


def refresh(page, workers, snapshot):
    page._load_apps()
    worker = workers[-1]
    assert worker.operation == "load_apps"
    worker.apps_loaded.emit(snapshot)
    worker.finish()


def test_visible_names_finish_before_icons_then_background_metadata(metadata_page, qt_application):
    page, workers = metadata_page
    page._populate(apps(80))
    wait_until(qt_application, lambda: bool(workers))
    assert workers[0].operation == "load_metadata_batch"
    first = workers[0]
    assert 0 < len(first.packages) < 80
    metadata(first)
    wait_until(qt_application, lambda: len(workers) == 2)
    assert workers[1].operation == "load_icon_batch"
    for package in workers[1].packages:
        assert page._detail_icon_by_pkg[package].text(1) == f"真实名称 {package}"
    images(workers[1])
    wait_until(qt_application, lambda: len(workers) == 3)
    assert workers[2].operation == "load_metadata_batch"
    assert set(workers[2].packages).isdisjoint(first.packages)
    assert sum(worker.running for worker in workers) == 1


def test_icon_query_carries_verified_metadata_identity(metadata_page, qt_application):
    page, workers = metadata_page
    page._populate(apps())
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: len(workers) == 2)
    assert workers[1].expected_fingerprints == {"example.app0": "user0:1:100:zh"}


def test_refresh_reuses_only_icons_with_unchanged_fingerprint(metadata_page, qt_application):
    page, workers = metadata_page
    page._populate(apps(2))
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: len(workers) == 2)
    images(workers[1])
    wait_until(qt_application, lambda: page._icons_controller._worker is None)
    refresh(page, workers, apps(2))
    wait_until(qt_application, lambda: len(workers) == 4)
    assert page._detail_icon_by_pkg["example.app0"].text(1) == "真实名称 example.app0"
    assert page._detail_icon_by_pkg["example.app0"].icon(0).pixmap(48, 48).toImage().pixelColor(
        24, 24
    ) != QColor("#e61b72")
    metadata(workers[3], fingerprints={"example.app1": "user0:2:200:zh"})
    wait_until(qt_application, lambda: len(workers) == 5)
    assert workers[4].operation == "load_icon_batch"
    assert workers[4].packages == ["example.app1"]
    assert page._detail_icon_by_pkg["example.app0"].icon(0).pixmap(48, 48).toImage().pixelColor(
        24, 24
    ) == QColor("#e61b72")


def test_refresh_cancels_old_metadata_and_waits_for_actual_finish(metadata_page, qt_application):
    page, workers = metadata_page
    page._populate(apps())
    wait_until(qt_application, lambda: len(workers) == 1)
    old = workers[0]
    refresh(page, workers, apps())
    qt_application.processEvents()
    assert old.aborted
    page._load_visible_details()
    page._icons_controller._load_visible()
    assert len(workers) == 2
    old.app_metadata_loaded.emit({"package": "example.app0", "label": "过期名称",
                                  "version": "9", "installed": "", "fingerprint": "old"})
    old.finish()
    wait_until(qt_application, lambda: len(workers) == 3)
    assert workers[2].operation == "load_metadata_batch"
    assert page.model.item(0, 1).text() == "App 000"
    assert page._detail_worker_running


@pytest.mark.parametrize("fallback", [False, True])
def test_unverified_refresh_does_not_reuse_cached_icon(metadata_page, qt_application, fallback):
    page, workers = metadata_page
    page._populate(apps())
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: len(workers) == 2)
    images(workers[1])
    wait_until(qt_application, lambda: page._icons_controller._worker is None)
    refresh(page, workers, apps())
    wait_until(qt_application, lambda: len(workers) == 4)
    if fallback:
        workers[3].app_detail_batch.emit("example.app0", "兼容名称", "1.0", "")
    workers[3].finish()
    wait_until(qt_application, lambda: len(workers) == 5)
    assert workers[4].operation == "load_icon_batch"
    assert workers[4].packages == ["example.app0"]
    assert page._detail_icon_by_pkg["example.app0"].icon(0).pixmap(48, 48).toImage().pixelColor(
        24, 24
    ) != QColor("#e61b72")
    if not fallback:
        assert "部分" in page.status_bar.text()
        assert page.model.item(0, 1).text() == "真实名称 example.app0"
        assert not page._has_unloaded_details()


def test_scroll_cancels_obsolete_icon_batch_without_starting_parallel_work(
    metadata_page, qt_application,
):
    page, workers = metadata_page
    page._populate(apps(80))
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: len(workers) == 2)
    old = workers[1]
    page.icon_list.scrollToItem(page._detail_icon_by_pkg["example.app79"])
    wait_until(qt_application, lambda: old.aborted)
    page._load_visible_details()
    assert len(workers) == 2
    old.finish()
    wait_until(qt_application, lambda: len(workers) == 3)
    assert workers[2].operation == "load_metadata_batch"
    assert "example.app79" in workers[2].packages
    assert page._icons_controller.failures == set()


def test_scroll_requeues_cancelled_background_metadata_and_rejects_late_results(
    metadata_page, qt_application,
):
    page, workers = metadata_page
    page._populate(apps(80))
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: len(workers) == 2)
    images(workers[1])
    wait_until(qt_application, lambda: len(workers) == 3)
    old = workers[2]
    old_packages = list(old.packages)
    page.icon_list.scrollToItem(page._detail_icon_by_pkg["example.app79"])
    wait_until(qt_application, lambda: old.aborted)
    assert len(workers) == 3
    old.app_metadata_loaded.emit({"package": old_packages[0], "label": "取消后的名称",
                                  "version": "9", "installed": "", "fingerprint": "old"})
    old.finish()
    wait_until(qt_application, lambda: len(workers) == 4)
    current = workers[3]
    assert "example.app79" in current.packages
    assert set(old_packages).isdisjoint(page._failed_detail_packages)
    assert old_packages[0] not in page._detail_cache
    assert old_packages[0] in page._next_unloaded_detail_packages()
    page._on_detail_worker_finished(old_packages, page._active_load_request, old)
    assert page._detail_worker_running and current.running


def test_scroll_prioritizes_icons_when_new_viewport_metadata_is_already_loaded(
    metadata_page, qt_application,
):
    page, workers = metadata_page
    page._populate(apps(80))
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: len(workers) == 2)
    images(workers[1])
    wait_until(qt_application, lambda: len(workers) == 3)
    old = workers[2]
    for index in range(60, 80):
        package = f"example.app{index}"
        page._on_metadata({"package": package, "label": f"真实名称 {package}",
                           "version": "1", "installed": "", "fingerprint": "user0:1"})
    page.icon_list.scrollToItem(page._detail_icon_by_pkg["example.app79"])
    wait_until(qt_application, lambda: old.aborted)
    assert len(workers) == 3
    old.finish()
    wait_until(qt_application, lambda: len(workers) == 4)
    assert workers[3].operation == "load_icon_batch"
    assert "example.app79" in workers[3].packages


def test_name_search_reveals_new_metadata_and_selection_survives_refresh(
    metadata_page, qt_application,
):
    page, workers = metadata_page
    page._populate(apps(2))
    page._detail_icon_by_pkg["example.app0"].setSelected(True)
    page.search_input.setText("真实名称")
    assert page.proxy.rowCount() == 0
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: page.proxy.rowCount() == 2
               and not page._detail_icon_by_pkg["example.app0"].isHidden())
    refresh(page, workers, apps(2))
    wait_until(qt_application, lambda: page.load_state == "ready")
    assert page.selected_packages == {"example.app0"}
    assert page._detail_icon_by_pkg["example.app0"].isSelected()
    assert page.proxy.rowCount() == 2


def test_failed_refresh_preserves_old_text_but_does_not_resume_unverified_icon_io(
    metadata_page, qt_application,
):
    page, workers = metadata_page
    page._populate(apps(80))
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: len(workers) == 2)
    images(workers[1])
    wait_until(qt_application, lambda: len(workers) == 3)
    old = workers[2]
    page._load_apps()
    failed_refresh = workers[3]
    failed_refresh.log_message.emit("Error: test device unavailable")
    failed_refresh.finish()
    old.finish()
    wait_until(qt_application, lambda: page.load_state == "error"
               and not page._detail_worker_running)
    page._load_visible_details()
    page._icons_controller._load_visible()
    assert len(workers) == 4
    assert page._pending_detail_packages == set()
    assert page._loaded_detail_packages == set()
    assert page._detail_icon_by_pkg["example.app0"].text(1) == "真实名称 example.app0"
    assert "Error" in page.status_bar.text()
    refresh(page, workers, apps(80))
    wait_until(qt_application, lambda: len(workers) == 6)
    assert workers[5].operation == "load_metadata_batch"
    assert "example.app0" in workers[5].packages


def test_switch_to_table_cancels_icons_and_waits_before_loading_visible_names(
    metadata_page, qt_application,
):
    page, workers = metadata_page
    page._populate(apps(80))
    wait_until(qt_application, lambda: len(workers) == 1)
    metadata(workers[0])
    wait_until(qt_application, lambda: len(workers) == 2)
    old = workers[1]
    page.view_toggle.click()
    assert not page._view_mode
    assert page._visible_detail_packages()
    assert old.aborted
    page._load_visible_details()
    assert len(workers) == 2
    old.finish()
    wait_until(qt_application, lambda: len(workers) == 3)
    assert workers[2].operation == "load_metadata_batch"
    assert set(workers[2].packages).isdisjoint(workers[0].packages)
    assert sum(worker.running for worker in workers) == 1
    assert page._icons_controller.failures == set()
