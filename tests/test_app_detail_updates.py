"""批量详情交付合并筛选，同时保留标签搜索和两个视图的可观察结果。"""

import pytest

from gui.dialogs.app_manager import AppManagerPage

pytestmark = pytest.mark.ui


def test_detail_burst_coalesces_filter_and_updates_matching_rows(qt_application, monkeypatch):
    page = AppManagerPage(device_ip="detail-test")
    try:
        page._populate([(f"App {i}", f"com.example.app{i}", "Enabled", "User")
                        for i in range(120)])
        page.search_input.setText("renamed")
        assert page.proxy.rowCount() == 0
        calls = []
        original = page._filter

        def filter_and_record():
            calls.append(True)
            original()

        monkeypatch.setattr(page, "_filter", filter_and_record)
        for index in range(30):
            page._on_detail(f"com.example.app{index}", f"Renamed {index}", "1.0", "today")
        qt_application.processEvents()
        assert page.proxy.rowCount() == 30
        visible = [page.icon_list.topLevelItem(i).text(1) for i in range(120)
                   if not page.icon_list.topLevelItem(i).isHidden()]
        assert set(visible) == {f"Renamed {i}" for i in range(30)}
        assert len(calls) <= 1
    finally:
        page.close()


def test_unchanged_filter_does_not_rescan_table(qt_application, monkeypatch):
    page = AppManagerPage(device_ip="detail-test")
    try:
        page._populate([(f"App {i}", f"com.example.app{i}", "Enabled", "User")
                        for i in range(120)])
        page.proxy.rowCount()
        calls = []
        original = page.proxy.filterAcceptsRow

        def accepts(row, parent):
            calls.append(row)
            return original(row, parent)

        monkeypatch.setattr(page.proxy, "filterAcceptsRow", accepts)
        page.proxy.set_filters("", "All")
        assert page.proxy.rowCount() == 120
        assert calls == []
    finally:
        page.close()


def test_closing_page_rejects_pending_detail_filter(qt_application, monkeypatch):
    page = AppManagerPage(device_ip="detail-test")
    page._populate([("App", "com.example.app", "Enabled", "User")])
    page._on_detail("com.example.app", "Renamed", "1.0", "today")
    calls = []
    monkeypatch.setattr(page, "_filter", lambda: calls.append(True))
    page.request_dispose("test")
    qt_application.processEvents()
    assert calls == []
    page.close()
