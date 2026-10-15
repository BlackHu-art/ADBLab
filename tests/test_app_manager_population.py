"""大列表分批交付期间，事件循环、最新筛选和会话生命周期仍有效。"""

from time import monotonic

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QStyleOptionViewItem

from gui.dialogs.app_manager import AppManagerPage
from gui.styles import BaseStyles
from tests.test_app_manager_metadata import MetadataWorker

pytestmark = pytest.mark.ui


def _wait(app, predicate):
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        app.processEvents()
    assert predicate()


def _apps(count, prefix="example.app"):
    return [(f"App {index:05}", f"{prefix}{index:05}", "Enabled", "User")
            for index in range(count)]


def test_app_population_keeps_busy_until_rows_finish_and_preserves_selection(
    qt_application, monkeypatch,
):
    page = AppManagerPage(device_ip="batch-device")
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    try:
        page.selected_packages.add("example.app01599")
        page._active_load_request = 1
        page._load_in_progress = True
        page._set_load_state("loading", "loading")
        page._populate(_apps(1600), request_id=1)
        page._on_load_worker_finished(1)
        observed = []
        QTimer.singleShot(0, lambda: observed.append(page._load_in_progress))
        assert page._load_in_progress and page.load_state == "loading"
        page._toggle_view()
        page.search_input.setText("01599")
        _wait(qt_application, lambda: not page._load_in_progress)
        assert observed == [True]
        assert page.load_state == "ready"
        assert page.model.rowCount() == page.icon_list.topLevelItemCount() == 1600
        assert page.selected_packages == {"example.app01599"}
        assert page._detail_icon_by_pkg["example.app01599"].isSelected()
        assert page.proxy.rowCount() == 1
        assert [page.icon_list.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole)
                for row in range(1600) if not page.icon_list.topLevelItem(row).isHidden()
                ] == ["example.app01599"]
    finally:
        page.close()


def test_app_population_pauses_off_page_and_resumes_same_snapshot(qt_application, monkeypatch):
    page = AppManagerPage(device_ip="batch-device")
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    page._activated_once = True
    page._populate(_apps(1600))
    try:
        page.deactivate()
        initial = page.model.rowCount()
        assert initial < 1600
        for _ in range(8):
            qt_application.processEvents()
        assert page.model.rowCount() == initial
        page.activate()
        _wait(qt_application, lambda: page.model.rowCount() == 1600)
    finally:
        page.close()


@pytest.mark.parametrize("change", ["replace", "close"])
def test_app_population_drops_old_batches(qt_application, monkeypatch, change):
    page = AppManagerPage(device_ip="batch-device")
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    try:
        page._active_load_request = 1
        page._populate(_apps(1600), request_id=1)
        assert page.model.rowCount() < 1600
        if change == "replace":
            page._active_load_request = 2
            page._populate(_apps(1, "new.app"), request_id=2)
        else:
            page.request_dispose()
        count = page.model.rowCount()
        for _ in range(8):
            qt_application.processEvents()
        assert page.model.rowCount() == count
        if change == "replace":
            assert page.model.item(0, 2).text() == "new.app00000"
            assert page.icon_list.topLevelItemCount() == 1
    finally:
        page.close()


def test_app_population_geometry_uses_view_font_without_visiting_every_icon(
    qt_application, monkeypatch,
):
    page = AppManagerPage(device_ip="batch-device")
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    try:
        page._populate(_apps(600))
        _wait(qt_application, lambda: not page._views_controller.populating)
        visited = []
        original = page.icon_list.topLevelItem

        def record_item(row):
            visited.append(row)
            return original(row)

        monkeypatch.setattr(page.icon_list, "topLevelItem", record_item)
        monkeypatch.setattr(BaseStyles, "font_for_role", lambda *args, **kwargs: QFont("Arial", 20))
        page._form_controller._update_view_geometry()
        option = QStyleOptionViewItem()
        index = page.icon_list.model().index(599, 1)
        page.icon_list.itemDelegate().initStyleOption(option, index)
        assert option.font.pointSize() == 20
        assert len(visited) < 10
    finally:
        page.close()


def test_app_population_owns_snapshot_until_all_rows_are_delivered(qt_application, monkeypatch):
    page = AppManagerPage(device_ip="batch-device")
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    try:
        snapshot = _apps(600)
        page._populate(snapshot)
        snapshot.clear()
        _wait(qt_application, lambda: not page._views_controller.populating)
        assert page.model.rowCount() == page.icon_list.topLevelItemCount() == 600
        assert page.model.item(599, 2).text() == "example.app00599"
    finally:
        page.close()


def test_app_population_merges_refreshes_until_gui_delivery_finishes(qt_application, monkeypatch):
    workers = []

    def create_worker(*args, **kwargs):
        worker = MetadataWorker(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerWorker", create_worker)
    page = AppManagerPage(device_ip="batch-device")
    monkeypatch.setattr(page, "_schedule_visible_detail_load", lambda *args, **kwargs: None)
    try:
        page.activate()
        first_request = page._active_load_request
        workers[0].user_context_loaded.emit(0)
        workers[0].apps_loaded.emit(_apps(1600))
        workers[0].finish()
        qt_application.processEvents()
        assert page._load_in_progress
        assert page.load_state == "loading"
        page.retry_load()
        page.retry_load()
        assert len(workers) == 1
        _wait(qt_application, lambda: len(workers) == 2)
        assert page.model.rowCount() == 1600
        assert workers[1].operation == "load_apps"
        workers[1].user_context_loaded.emit(0)
        workers[1].apps_loaded.emit(_apps(1, "new.app"))
        workers[1].finish()
        _wait(qt_application, lambda: not page._load_in_progress)
        page._populate(_apps(1600), request_id=first_request)
        assert page.model.rowCount() == page.icon_list.topLevelItemCount() == 1
        assert page.model.item(0, 2).text() == "new.app00000"
        assert page.load_state == "ready"
    finally:
        page.request_dispose()
        for worker in workers:
            if worker.isRunning():
                worker.finish()
        qt_application.processEvents()
        page.close()
