"""应用图标的后台加载、视图缓存和会话生命周期回归。"""

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy

from gui.dialogs.app_manager import AppManagerPage
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until


class IconWorker(QObject):
    app_icon_loaded = Signal(str, bytes, str)
    finished = Signal()

    def __init__(self, device, operation, **kwargs):
        super().__init__()
        self.device = device
        self.operation = operation
        self.packages = kwargs["packages"]
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


def png(color="#e61b72"):
    image = QImage(96, 96, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(data)


@pytest.fixture
def page(qt_application, monkeypatch):
    workers = []

    def worker_factory(*args, **kwargs):
        worker = IconWorker(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerWorker", worker_factory)
    window = AppManagerPage(device_ip="demo-device")
    monkeypatch.setattr(window, "_schedule_visible_detail_load", lambda *a, **kw: None)
    window._active = True
    window._activated_once = True
    window.resize(860, 720)
    window.show()
    yield window, workers
    window.request_dispose()
    for worker in list(workers):
        if worker in window._workers and worker.isRunning():
            worker.finish()
    qt_application.processEvents()
    window.close()


def populate(window, count=1, prefix="example.app"):
    window._populate([(f"应用 {i}", f"{prefix}{i}", "Enabled", "User") for i in range(count)])


def test_icon_view_fetches_real_image_and_keeps_selection_and_cache(page, qt_application):
    window, workers = page
    populate(window)
    item = window.icon_list.item(0)
    package = item.data(Qt.ItemDataRole.UserRole)
    window.model.item(0, 0).setCheckState(Qt.CheckState.Checked)
    window.view_toggle.click()
    wait_until(qt_application, lambda: bool(workers), timeout_ms=1000)
    worker = workers[0]
    assert worker.operation == "load_icon_batch"
    assert worker.device == "demo-device"
    assert worker.packages == [package]
    worker.app_icon_loaded.emit(package, png(), "")
    worker.finish()
    wait_until(qt_application, lambda: item.icon().pixmap(48, 48).toImage().pixelColor(24, 24)
               == QColor("#e61b72"))
    assert window.selected_packages == {package}
    for _ in range(2):
        window.view_toggle.click()
    wait_for_stable_geometry(qt_application, window.icon_list)
    assert item.isSelected()
    assert len(workers) == 1


def test_icon_requests_follow_viewport_and_filter_instead_of_loading_all_apps(page, qt_application):
    window, workers = page
    populate(window, 120)
    window.view_toggle.click()
    wait_until(qt_application, lambda: bool(workers))
    first = workers[0]
    visible = {
        window.icon_list.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(window.icon_list.count())
        if window.icon_list.viewport().rect().intersects(
            window.icon_list.visualItemRect(window.icon_list.item(i))
        )
    }
    assert set(first.packages) <= visible
    assert 0 < len(first.packages) <= 12 < window.icon_list.count()
    window.search_input.setText("example.app119")
    for package in first.packages:
        first.app_icon_loaded.emit(package, png(), "")
    first.finish()
    wait_until(qt_application, lambda: len(workers) == 2)
    assert workers[1].packages == ["example.app119"]


def test_refresh_discards_old_icon_results_and_requests_new_generation(page, qt_application):
    window, workers = page
    populate(window)
    window.view_toggle.click()
    wait_until(qt_application, lambda: bool(workers))
    old = workers[0]
    populate(window)
    assert old.aborted
    old.app_icon_loaded.emit("example.app0", png(), "")
    old.finish()
    wait_until(qt_application, lambda: len(workers) == 2)
    item = window.icon_list.item(0)
    assert item.icon().pixmap(48, 48).toImage().pixelColor(24, 24) != QColor("#e61b72")
    workers[1].app_icon_loaded.emit("example.app0", png("#36a960"), "")
    wait_until(qt_application, lambda: item.icon().pixmap(48, 48).toImage().pixelColor(24, 24)
               == QColor("#36a960"))


def test_failed_icon_keeps_placeholder_and_refresh_allows_retry(page, qt_application):
    window, workers = page
    populate(window)
    window.view_toggle.click()
    wait_until(qt_application, lambda: bool(workers))
    item = window.icon_list.item(0)
    original = item.icon().cacheKey()
    workers[0].app_icon_loaded.emit("example.app0", b"broken image", "")
    workers[0].finish()
    wait_until(qt_application, lambda: "重试" in item.toolTip())
    assert item.icon().cacheKey() == original
    populate(window)
    wait_until(qt_application, lambda: len(workers) == 2)


def test_offline_pauses_requests_and_reconnect_retries_unfinished_icons(page, qt_application):
    window, workers = page
    populate(window)
    window.view_toggle.click()
    wait_until(qt_application, lambda: bool(workers))
    worker = workers[0]
    window.set_device_connected(False)
    assert worker.aborted
    worker.finish()
    qt_application.processEvents()
    assert len(workers) == 1
    window.set_device_connected(True)
    wait_until(qt_application, lambda: len(workers) == 2)


def test_closing_waits_for_icon_worker_and_rejects_late_image(page, qt_application):
    window, workers = page
    populate(window)
    window.view_toggle.click()
    wait_until(qt_application, lambda: bool(workers))
    item = window.icon_list.item(0)
    original = item.icon().cacheKey()
    ready = QSignalSpy(window.dispose_ready)
    assert not window.request_dispose()
    worker = workers[0]
    assert worker.aborted
    worker.app_icon_loaded.emit("example.app0", png(), "")
    worker.finish()
    wait_until(qt_application, lambda: ready.count() == 1)
    assert item.icon().cacheKey() == original
