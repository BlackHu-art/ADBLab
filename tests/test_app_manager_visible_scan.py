"""可见应用补全只检查视口附近的行，排序和隐藏不改变包名身份。"""

from collections import Counter
from time import monotonic

import pytest
from PySide6.QtCore import Qt

from gui.dialogs.app_manager import AppManagerPage
from tests.test_app_manager_metadata import MetadataWorker
from tests.ui_geometry_helpers import wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.fixture
def manager(qt_application, monkeypatch):
    workers = []

    def create_worker(*args, **kwargs):
        worker = MetadataWorker(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr("gui.dialogs.app_manager.AppManagerWorker", create_worker)
    page = AppManagerPage(device_ip="test-device")
    page._active = False
    page._activated_once = True
    page.resize(860, 620)
    page._populate([
        (f"App {index:03}", f"example.app{index:03}", "Enabled", "User")
        for index in range(600)
    ])
    # 大列表让出事件循环后再验证视口扫描，不能依赖同步建完第 533 行。
    deadline = monotonic() + 5
    while page._views_controller.populating and monotonic() < deadline:
        qt_application.processEvents()
    assert page.model.rowCount() == page.icon_list.topLevelItemCount() == 600
    assert not page._views_controller.populating
    page.show()
    yield page, workers
    page.request_dispose()
    for worker in workers:
        if worker in page._workers and worker.isRunning():
            worker.finish()
    qt_application.processEvents()
    page.close()


def _position_view(page, qt_application, *, icon_mode, filtered):
    # 经过真实切换入口，避免测试绕开选择同步或代理排序。
    page.model.item(533, 0).setCheckState(Qt.CheckState.Checked)
    if page._view_mode != icon_mode:
        page.view_toggle.click()
    view = page.icon_list if icon_mode else page.tree
    if filtered:
        page.search_input.setText("example.app5")
        page._filter()
    if icon_mode:
        view.sortItems(2, Qt.SortOrder.DescendingOrder)
    else:
        view.sortByColumn(2, Qt.SortOrder.DescendingOrder)
    if not filtered:
        for row in range(view.model().rowCount()):
            if row % 3 == 0:
                view.setRowHidden(row, view.rootIndex(), True)
    # 横滚后首个可见列不再是保存包名角色的第零列。
    view.setColumnWidth(2, 1100)
    wait_for_stable_geometry(qt_application, view)
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum() * 3 // 4)
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
    wait_for_stable_geometry(qt_application, view)
    assert view.verticalScrollBar().value() > 0
    assert view.horizontalScrollBar().value() > 0
    assert page.selected_packages == {"example.app533"}
    return view


def _visible_packages(page, view):
    # 独立的全表几何 oracle 只用于测试；生产访问次数从它完成后开始计数。
    viewport = view.viewport().rect()
    column = view.header().logicalIndexAt(viewport.center().x())
    assert column >= 0
    rows = []
    for row in range(view.model().rowCount()):
        index = view.model().index(row, column, view.rootIndex())
        rect = view.visualRect(index)
        if rect.isValid() and viewport.intersects(rect):
            package = (
                view.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole)
                if view is page.icon_list else page.proxy.index(row, 2).data()
            )
            rows.append((rect.top(), package))
    return [package for _top, package in sorted(rows)]


def _count_view_queries(view, monkeypatch):
    counts = Counter()

    def instrument(target, name):
        original = getattr(target, name)

        def measured(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(target, name, measured)

    for name in ("visualRect", "indexAt", "indexBelow"):
        instrument(view, name)
    for name in ("visualItemRect", "topLevelItem"):
        if hasattr(view, name):
            instrument(view, name)
    instrument(view.model(), "index")
    return counts


@pytest.mark.parametrize("icon_mode", [False, True], ids=["table", "icons"])
@pytest.mark.parametrize("filtered", [False, True], ids=["sorted-hidden", "filtered"])
def test_visible_detail_scan_is_bounded_by_viewport(
    manager, qt_application, monkeypatch, icon_mode, filtered,
):
    page, _workers = manager
    view = _position_view(page, qt_application, icon_mode=icon_mode, filtered=filtered)
    visible = _visible_packages(page, view)
    assert 2 < len(visible) < 30
    page._loaded_detail_packages.add(visible[0])
    page._failed_detail_packages.add(visible[-1])
    counts = _count_view_queries(view, monkeypatch)
    packages = page._visible_detail_packages()
    assert packages == visible[1:-1]
    assert sum(counts.values()) <= 7 * len(visible) + 8, counts
    assert page.selected_packages == {"example.app533"}


def test_icon_scan_only_requests_visible_packages_without_scanning_all_rows(
    manager, qt_application, monkeypatch,
):
    page, workers = manager
    view = _position_view(page, qt_application, icon_mode=True, filtered=False)
    visible = _visible_packages(page, view)
    page._loaded_detail_packages.update(visible)
    counts = _count_view_queries(view, monkeypatch)
    page._active = True
    page._icons_controller._load_visible()
    assert len(workers) == 1
    assert workers[0].operation == "load_icon_batch"
    assert workers[0].packages == visible[:page._icons_controller.BATCH_SIZE]
    assert sum(counts.values()) <= 14 * len(visible) + 16, counts


@pytest.mark.parametrize("icon_mode", [False, True], ids=["table", "icons"])
def test_metadata_requests_keep_visible_identity_after_view_switch(
    manager, qt_application, icon_mode,
):
    page, workers = manager
    view = _position_view(page, qt_application, icon_mode=icon_mode, filtered=True)
    visible = _visible_packages(page, view)
    page._active = True
    page._load_visible_details()
    assert len(workers) == 1
    assert workers[0].operation == "load_metadata_batch"
    assert workers[0].packages == visible
    assert page.selected_packages == {"example.app533"}
