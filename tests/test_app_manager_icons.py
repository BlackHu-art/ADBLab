"""应用图标的后台加载、视图缓存和会话生命周期回归。"""

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy

from gui.dialogs.app_manager import AppManagerPage
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until


class IconWorker(QObject):
    app_icon_loaded = Signal(str, bytes, str)
    app_detail_batch = Signal(str, str, str, str)
    app_metadata_loaded = Signal(dict)
    log_message = Signal(str)
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


def populate(window, count=1, prefix="example.app", *, metadata_ready=True):
    window._populate([(f"应用 {i}", f"{prefix}{i}", "Enabled", "User") for i in range(count)])
    if metadata_ready:
        for index in range(count):
            window._on_metadata({
                "package": f"{prefix}{index}", "label": f"应用 {index}",
                "version": "1.0", "installed": "", "fingerprint": "user0:1:100:zh",
            })


def test_icon_view_fetches_real_image_and_keeps_selection_and_cache(page, qt_application):
    window, workers = page
    assert window.stack.currentWidget() is window.icon_list
    assert window.icon_list.isVisible()
    populate(window)
    item = window.icon_list.topLevelItem(0)
    package = item.data(0, Qt.ItemDataRole.UserRole)
    window.model.item(0, 0).setCheckState(Qt.CheckState.Checked)
    wait_until(qt_application, lambda: bool(workers), timeout_ms=1000)
    worker = workers[0]
    assert worker.operation == "load_icon_batch"
    assert worker.device == "demo-device"
    assert worker.packages == [package]
    worker.app_icon_loaded.emit(package, png(), "")
    worker.finish()
    wait_until(qt_application, lambda: item.icon(0).pixmap(48, 48).toImage().pixelColor(24, 24)
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
    wait_until(qt_application, lambda: bool(workers))
    first = workers[0]
    visible = {
        window.icon_list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
        for i in range(window.icon_list.topLevelItemCount())
        if window.icon_list.viewport().rect().intersects(
            window.icon_list.visualItemRect(window.icon_list.topLevelItem(i))
        )
    }
    assert set(first.packages) <= visible
    assert 0 < len(first.packages) <= 12 < window.icon_list.topLevelItemCount()
    window.search_input.setText("example.app119")
    for package in first.packages:
        first.app_icon_loaded.emit(package, png(), "")
    first.finish()
    wait_until(qt_application, lambda: len(workers) == 2)
    assert workers[1].packages == ["example.app119"]


def test_continuous_scroll_starts_icons_for_latest_viewport(page, qt_application, monkeypatch):
    window, workers = page
    monkeypatch.setattr(
        window, "_schedule_visible_detail_load",
        AppManagerPage._schedule_visible_detail_load.__get__(window),
    )
    populate(window, 120)
    qt_application.processEvents()
    scrollbar = window.icon_list.verticalScrollBar()
    assert scrollbar.maximum() > 1
    tail_packages = set()
    for offset in (1, 0):
        scrollbar.setValue(scrollbar.maximum() - offset)
        tail_packages.update(
            item.data(0, Qt.ItemDataRole.UserRole)
            for index in range(window.icon_list.topLevelItemCount())
            if (item := window.icon_list.topLevelItem(index)) is not None
            and window.icon_list.viewport().rect().intersects(window.icon_list.visualItemRect(item))
        )
    scroll_timer = QTimer(window)
    scroll_timer.setInterval(20)
    scroll_timer.timeout.connect(
        lambda: scrollbar.setValue(
            scrollbar.maximum() - (scrollbar.value() == scrollbar.maximum())
        )
    )
    scroll_timer.start()
    try:
        wait_until(qt_application, lambda: bool(workers), timeout_ms=1000)
        assert scroll_timer.isActive()
        assert [worker.operation for worker in workers] == ["load_icon_batch"]
        assert workers[0].packages
        assert set(workers[0].packages) <= tail_packages
    finally:
        scroll_timer.stop()


def test_refresh_discards_old_icon_results_and_requests_new_generation(page, qt_application):
    window, workers = page
    populate(window)
    wait_until(qt_application, lambda: bool(workers))
    old = workers[0]
    populate(window)
    assert old.aborted
    old.app_icon_loaded.emit("example.app0", png(), "")
    old.finish()
    wait_until(qt_application, lambda: len(workers) == 2)
    item = window.icon_list.topLevelItem(0)
    assert item.icon(0).pixmap(48, 48).toImage().pixelColor(24, 24) != QColor("#e61b72")
    workers[1].app_icon_loaded.emit("example.app0", png("#36a960"), "")
    wait_until(qt_application, lambda: item.icon(0).pixmap(48, 48).toImage().pixelColor(24, 24)
               == QColor("#36a960"))


def test_failed_icon_keeps_placeholder_and_refresh_allows_retry(page, qt_application):
    window, workers = page
    populate(window)
    wait_until(qt_application, lambda: bool(workers))
    item = window.icon_list.topLevelItem(0)
    original = item.icon(0).cacheKey()
    workers[0].app_icon_loaded.emit("example.app0", b"broken image", "")
    workers[0].finish()
    wait_until(qt_application, lambda: "重试" in item.toolTip(0))
    assert item.icon(0).cacheKey() == original
    populate(window)
    wait_until(qt_application, lambda: len(workers) == 2)


def test_offline_pauses_requests_and_reconnect_retries_unfinished_icons(page, qt_application):
    window, workers = page
    populate(window)
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
    wait_until(qt_application, lambda: bool(workers))
    item = window.icon_list.topLevelItem(0)
    original = item.icon(0).cacheKey()
    ready = QSignalSpy(window.dispose_ready)
    assert not window.request_dispose()
    worker = workers[0]
    assert worker.aborted
    worker.app_icon_loaded.emit("example.app0", png(), "")
    worker.finish()
    wait_until(qt_application, lambda: ready.count() == 1)
    assert item.icon(0).cacheKey() == original


def test_visible_icons_finish_before_background_metadata_queries(page, qt_application):
    window, workers = page
    populate(window, 80, metadata_ready=False)
    qt_application.processEvents()
    for package in window._visible_detail_packages():
        window._on_metadata({
            "package": package, "label": package, "version": "1.0", "installed": "",
            "fingerprint": "user0:1:100:zh",
        })
    wait_until(qt_application, lambda: bool(workers))
    window._load_visible_details()
    assert [worker.operation for worker in workers] == ["load_icon_batch"]
    for package in workers[0].packages:
        workers[0].app_icon_loaded.emit(package, png(), "")
    workers[0].finish()
    wait_until(qt_application, lambda: window._icons_controller._worker is None)
    window._load_visible_details()
    assert [worker.operation for worker in workers] == ["load_icon_batch", "load_metadata_batch"]


def test_icon_view_detail_queries_follow_scrolled_viewport(page, qt_application):
    window, _workers = page
    populate(window, 120, metadata_ready=False)
    wait_for_stable_geometry(qt_application, window.icon_list)
    window.icon_list.scrollToItem(window.icon_list.topLevelItem(119))
    wait_for_stable_geometry(qt_application, window.icon_list)
    visible = {
        item.data(0, Qt.ItemDataRole.UserRole)
        for index in range(window.icon_list.topLevelItemCount())
        if (item := window.icon_list.topLevelItem(index)) is not None
        and window.icon_list.viewport().rect().intersects(window.icon_list.visualItemRect(item))
    }
    packages = window._visible_detail_packages()
    assert packages and set(packages) <= visible


@pytest.mark.parametrize(("error", "reason"), [
    ("应用图标组件缺失", "应用图标组件缺失"),
    ("应用图标组件传输失败", "应用图标组件传输失败"),
    ("应用或设备配置已变化，请刷新应用列表", "应用或设备配置已变化，请刷新应用列表"),
    ("设备用户已切换，请刷新应用列表", "设备用户已切换，请刷新应用列表"),
    ("设备不支持读取应用图标", "设备不支持读取应用图标"),
    ("应用图标渲染失败", "应用图标渲染失败"),
    ("应用图标超过大小限制", "应用图标超过大小限制"),
    ("当前用户未安装此应用", "当前用户未安装此应用"),
    ("应用图标临时文件清理失败", "清理失败"),
    ("设备图标响应无效", "应用图标数据无效"),
    ("应用缓存身份无效，请刷新应用列表", "应用图标数据无效"),
    ("包名格式无效", "包名无效"),
    ("adb: private-device /private/local/path 192.0.2.23", "查询失败"),
    ("", "应用图标数据无效"),
])
def test_failed_icon_exposes_only_safe_reason_in_tooltip_and_accessibility(
    page, qt_application, error, reason,
):
    window, workers = page
    populate(window)
    wait_until(qt_application, lambda: bool(workers))
    worker = workers[0]
    worker.app_icon_loaded.emit("example.app0", b"invalid-png", error)
    worker.finish()
    wait_until(qt_application, lambda: window._icons_controller._worker is None)
    item = window._detail_icon_by_pkg["example.app0"]
    # 名称补全也会重建提示，失败原因应保留一次，并保持完整包名可读。
    window._on_detail("example.app0", "新名称", "2.0", "")
    for _ in range(2):
        window._icons_controller.decorate("example.app0")
    for column in range(4):
        for text in (item.toolTip(column),
                     item.data(column, Qt.ItemDataRole.AccessibleDescriptionRole)):
            assert reason in text
            assert text.count(reason) == 1
            assert "example.app0" in text and "刷新重试" in text
            assert "private-device" not in text and "/private/" not in text
            assert "192.0.2.23" not in text
    window._icons_controller._load_visible()
    assert len(workers) == 1


@pytest.mark.parametrize("reset", ["refresh", "uninstall", "close"])
def test_refresh_uninstall_and_close_clear_icon_failure_descriptions(page, qt_application, reset):
    window, workers = page
    populate(window)
    wait_until(qt_application, lambda: bool(workers))
    worker = workers[0]
    reason = "应用图标组件缺失"
    worker.app_icon_loaded.emit("example.app0", b"", reason)
    worker.finish()
    wait_until(qt_application, lambda: window._icons_controller._worker is None)
    item = window._detail_icon_by_pkg["example.app0"]
    assert reason in item.toolTip(0)
    if reset == "refresh":
        window._icons_controller.reset(preserve_cache=True)
    elif reset == "uninstall":
        window._icons_controller.retain_packages(set())
    else:
        window.request_dispose()
    assert not window._icons_controller.failures
    for column in range(4):
        assert reason not in item.toolTip(column)
        assert "图标未读取" not in item.toolTip(column)
        assert reason not in item.data(column, Qt.ItemDataRole.AccessibleDescriptionRole)


@pytest.mark.parametrize("closing", [False, True])
def test_late_icon_failure_cannot_reappear_after_refresh_or_close(page, qt_application, closing):
    window, workers = page
    populate(window)
    wait_until(qt_application, lambda: bool(workers))
    worker = workers[0]
    item = window._detail_icon_by_pkg["example.app0"]
    if closing:
        window.request_dispose()
    else:
        window._icons_controller.reset(preserve_cache=True)
    worker.app_icon_loaded.emit("example.app0", b"", "应用图标组件缺失")
    worker.finish()
    wait_until(qt_application, lambda: window._icons_controller._worker is None)
    assert not window._icons_controller.failures
    assert "图标未读取" not in item.toolTip(0)
    assert "组件缺失" not in item.data(0, Qt.ItemDataRole.AccessibleDescriptionRole)
