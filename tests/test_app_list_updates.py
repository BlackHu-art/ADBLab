"""应用单项选择只同步变化项，缓存淘汰同时释放行图标。"""

import pytest
from PySide6.QtCore import Qt

from gui.dialogs.app_manager import AppManagerPage
from tests.test_app_manager_icons import png

pytestmark = pytest.mark.ui


@pytest.fixture
def app_page(qt_application):
    page = AppManagerPage(device_ip="")
    page._populate([(f"App {i}", f"example.app{i}", "Enabled", "User") for i in range(200)])
    yield page
    page.close()


def _count_item_reads(page, monkeypatch):
    calls = []
    original = page.model.item
    top_level = page.icon_list.topLevelItem

    def item(*args):
        calls.append("table")
        return original(*args)

    def icon(*args):
        calls.append("icons")
        return top_level(*args)

    monkeypatch.setattr(page.model, "item", item)
    monkeypatch.setattr(page.icon_list, "topLevelItem", icon)
    return calls, original


def test_single_checkbox_updates_matching_icon_without_scanning_both_lists(app_page, monkeypatch):
    calls, original = _count_item_reads(app_page, monkeypatch)
    original(17, 0).setCheckState(Qt.CheckState.Checked)
    assert app_page.selected_packages == {"example.app17"}
    assert app_page._detail_icon_by_pkg["example.app17"].isSelected()
    assert len(calls) <= 4
    assert "icons" not in calls


def test_icon_selection_delta_preserves_hidden_selection(app_page, monkeypatch):
    first = app_page._detail_icon_by_pkg["example.app0"]
    last = app_page._detail_icon_by_pkg["example.app199"]
    first.setSelected(True)
    app_page.search_input.setText("example.app199")
    assert first.isHidden() and first.isSelected()
    calls, original = _count_item_reads(app_page, monkeypatch)
    last.setSelected(True)
    assert app_page.selected_packages == {"example.app0", "example.app199"}
    assert original(199, 0).checkState() == Qt.CheckState.Checked
    last.setSelected(False)
    assert app_page.selected_packages == {"example.app0"}
    assert original(199, 0).checkState() == Qt.CheckState.Unchecked
    assert len(calls) <= 6
    assert "icons" not in calls


def test_eviction_restores_placeholder_and_only_cached_rows_keep_real_icons(app_page, monkeypatch):
    from PySide6.QtCore import QObject

    controller = app_page._icons_controller
    controller.CACHE_LIMIT = 2
    worker = QObject()
    worker.setProperty("iconEpoch", controller._epoch)
    controller._worker = worker
    monkeypatch.setattr(controller, "sender", lambda: worker)
    first = app_page._detail_icon_by_pkg["example.app0"]
    placeholder = first.icon(0).cacheKey()
    try:
        for package in ("example.app0", "example.app1", "example.app2"):
            controller._pending = {package}
            controller._receive(package, png(), "")
        assert first.icon(0).cacheKey() == placeholder
        assert set(controller.cache) == {"example.app1", "example.app2"}
        for package in controller.cache:
            assert app_page._detail_icon_by_pkg[package].icon(0).cacheKey() == (
                controller.cache[package].cacheKey()
            )
    finally:
        controller._worker = None
        controller._pending.clear()
