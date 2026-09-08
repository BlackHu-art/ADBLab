"""页面贴边时滚动条与无边框缩放热区的输入回归。"""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import ScrollArea
from shiboken6 import isValid

from gui.widgets.frameless_resize import FramelessResizeController

pytestmark = pytest.mark.ui


def _window_with_scroll(qt_application, monkeypatch, *, late=False, native_hover=False):
    window = QWidget()
    if native_hover and qt_application.platformName() == "windows":
        # 原生悬停依赖桌面命中；仅激活窗口不能越过其他应用的置顶窗口。
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.resize(800, 600)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    stack = QStackedWidget(window)
    layout.addWidget(stack)
    controller = FramelessResizeController(window) if late else None
    if late:
        window.show()
        qt_application.processEvents()
    scroll = ScrollArea()
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
    content = QWidget()
    content.setMinimumSize(1400, 1600)
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    stack.addWidget(scroll)
    stack.addWidget(QWidget())
    if controller is None:
        controller = FramelessResizeController(window)
    window.show()
    qt_application.processEvents()
    native_resize = Mock(return_value=True)
    monkeypatch.setattr(window.windowHandle(), "startSystemResize", native_resize)
    return window, controller, scroll, content, stack, native_resize


def _hit(window, target, point=None):
    location = target.mapTo(window, point or target.rect().center())
    hit = window.childAt(location)
    assert hit is not None
    return hit, hit.mapFrom(window, location)


@pytest.mark.parametrize("orientation", [Qt.Orientation.Vertical, Qt.Orientation.Horizontal])
@pytest.mark.parametrize("late", [False, True], ids=["existing-page", "late-page"])
def test_edge_scrollbar_handle_receives_real_hit_and_drag(
    qt_application, monkeypatch, orientation, late
):
    window, _, scroll, _, _, native_resize = _window_with_scroll(
        qt_application, monkeypatch, late=late
    )
    bar = (
        scroll.scrollDelagate.vScrollBar
        if orientation == Qt.Orientation.Vertical
        else scroll.scrollDelagate.hScrollBar
    )
    assert bar.isVisible() and bar.maximum() > 0
    hit, point = _hit(window, bar.handle)
    assert hit is bar.handle
    before = bar.value()
    delta = QPoint(0, 80) if orientation == Qt.Orientation.Vertical else QPoint(80, 0)
    QTest.mousePress(hit, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(hit, point + delta)
    QTest.mouseRelease(hit, Qt.MouseButton.LeftButton, pos=point + delta)
    assert bar.value() > before
    native_resize.assert_not_called()


@pytest.mark.parametrize("orientation", [Qt.Orientation.Vertical, Qt.Orientation.Horizontal])
def test_scrollbar_full_track_and_arrow_keep_input(qt_application, monkeypatch, orientation):
    window, _, scroll, _, _, native_resize = _window_with_scroll(qt_application, monkeypatch)
    if orientation == Qt.Orientation.Vertical:
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    else:
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    qt_application.processEvents()
    bar = (
        scroll.scrollDelagate.vScrollBar
        if orientation == Qt.Orientation.Vertical
        else scroll.scrollDelagate.hScrollBar
    )
    bar.groove.setOpacity(1)
    arrow = bar.groove.downButton
    hit, point = _hit(window, arrow)
    assert hit is arrow
    before = bar.value()
    QTest.mouseClick(hit, Qt.MouseButton.LeftButton, pos=point)
    bar.ani.setCurrentTime(bar.ani.duration())
    assert bar.value() > before
    offsets = (
        (0, bar.width() - 1)
        if orientation == Qt.Orientation.Vertical
        else (0, bar.height() - 1)
    )
    for offset in offsets:
        position = (
            QPoint(offset, bar.height() // 2)
            if orientation == Qt.Orientation.Vertical
            else QPoint(bar.width() // 2, offset)
        )
        hit, _ = _hit(window, bar, position)
        assert hit is bar or bar.isAncestorOf(hit)
    native_resize.assert_not_called()


def test_scrollbar_visibility_route_and_resize_refresh_hit_masks(qt_application, monkeypatch):
    window, controller, scroll, content, stack, _ = _window_with_scroll(qt_application, monkeypatch)
    bar = scroll.scrollDelagate.vScrollBar
    hit, _ = _hit(window, bar.handle)
    assert hit is bar.handle
    point = QPoint(window.width() - 6, window.height() // 2)
    stack.setCurrentIndex(1)
    qt_application.processEvents()
    assert window.childAt(point) is controller._zones["right"]
    stack.setCurrentIndex(0)
    qt_application.processEvents()
    hit, _ = _hit(window, bar.handle)
    assert hit is bar.handle
    content.setMinimumSize(0, 0)
    content.resize(scroll.viewport().size())
    qt_application.processEvents()
    assert not bar.isVisible()
    assert window.childAt(point) is controller._zones["right"]
    content.setMinimumSize(1400, 1600)
    window.resize(920, 700)
    controller.update_geometry()
    qt_application.processEvents()
    hit, _ = _hit(window, bar.handle)
    assert hit is bar.handle
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    qt_application.processEvents()
    assert window.childAt(QPoint(window.width() - 6, 300)) is controller._zones["right"]


def test_scrollbar_hover_expands_from_actual_track_hit(qt_application, monkeypatch):
    window, _, scroll, _, _, native_resize = _window_with_scroll(
        qt_application, monkeypatch, native_hover=True,
    )
    bar = scroll.scrollDelagate.vScrollBar
    assert QTest.qWaitForWindowExposed(window)
    QTest.mouseMove(window, QPoint(400, 300))
    hit, point = _hit(window, bar, QPoint(bar.width() - 2, bar.height() // 2))
    assert hit is bar or bar.isAncestorOf(hit)
    if qt_application.platformName() == "windows":
        assert QApplication.widgetAt(hit.mapToGlobal(point)) is hit
    QTest.mouseMove(hit, point)
    elapsed = QElapsedTimer()
    elapsed.start()
    while bar.handle.width() <= 3 and elapsed.elapsed() < 800:
        QTest.qWait(20)
    assert bar.handle.width() > 3
    assert bar.groove.opacity > 0
    native_resize.assert_not_called()


def test_moving_scroll_area_inward_restores_uncovered_resize_edge(qt_application, monkeypatch):
    window, controller, scroll, _, stack, _ = _window_with_scroll(qt_application, monkeypatch)
    stack.setContentsMargins(0, 0, 20, 0)
    qt_application.processEvents()
    assert window.childAt(QPoint(794, 300)) is controller._zones["right"]
    hit, _ = _hit(window, scroll.scrollDelagate.vScrollBar.handle)
    assert hit is scroll.scrollDelagate.vScrollBar.handle
    stack.setContentsMargins(0, 0, 0, 0)
    qt_application.processEvents()
    hit, _ = _hit(window, scroll.scrollDelagate.vScrollBar.handle)
    assert hit is scroll.scrollDelagate.vScrollBar.handle


def test_outer_edge_and_corner_still_start_native_resize(qt_application, monkeypatch):
    window, controller, _, _, _, native_resize = _window_with_scroll(qt_application, monkeypatch)
    for point, edge in (
        (QPoint(799, 300), Qt.Edge.RightEdge),
        (QPoint(400, 599), Qt.Edge.BottomEdge),
        (QPoint(799, 599), Qt.Edge.RightEdge | Qt.Edge.BottomEdge),
        (QPoint(0, 0), Qt.Edge.LeftEdge | Qt.Edge.TopEdge),
    ):
        hit = window.childAt(point)
        assert hit in controller.zones
        QTest.mouseClick(hit, Qt.MouseButton.LeftButton, pos=hit.mapFrom(window, point))
        native_resize.assert_called_with(edge)


@pytest.mark.parametrize("state", [Qt.WindowState.WindowMaximized, Qt.WindowState.WindowFullScreen])
def test_non_normal_window_has_no_resize_hits(qt_application, monkeypatch, state):
    window, controller, scroll, _, _, native_resize = _window_with_scroll(
        qt_application, monkeypatch
    )
    window.setWindowState(state)
    qt_application.processEvents()
    controller.update_geometry()
    assert all(zone.isHidden() for zone in controller.zones)
    hit, point = _hit(window, scroll.scrollDelagate.vScrollBar.handle)
    assert hit is scroll.scrollDelagate.vScrollBar.handle
    QTest.mouseClick(hit, Qt.MouseButton.LeftButton, pos=point)
    native_resize.assert_not_called()


@pytest.mark.parametrize("hide_first", [False, True], ids=["visible-page", "hidden-page"])
def test_removed_scroll_page_and_window_release_without_late_callbacks(
    qt_application, monkeypatch, hide_first
):
    window, controller, scroll, _, stack, _ = _window_with_scroll(qt_application, monkeypatch)
    if hide_first:
        stack.setCurrentIndex(1)
    stack.removeWidget(scroll)
    scroll.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    assert not isValid(scroll)
    assert window.childAt(QPoint(794, 300)) is controller._zones["right"]
    zones = controller.zones
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    assert not isValid(window)
    assert not isValid(controller)
    assert all(not isValid(zone) for zone in zones)


def test_deleting_visible_scroll_ancestor_restores_resize_hit(qt_application, monkeypatch):
    window = QWidget()
    window.resize(800, 600)
    container = QWidget(window)
    container.setGeometry(0, 0, 800, 400)
    scroll = ScrollArea(container)
    scroll.setGeometry(0, 0, 800, 600)
    scroll.setStyleSheet("QScrollArea { border: none; }")
    content = QWidget()
    content.setMinimumHeight(1600)
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    controller = FramelessResizeController(window)
    window.show()
    qt_application.processEvents()
    bar = scroll.scrollDelagate.vScrollBar
    point = QPoint(794, 200)
    hit = window.childAt(point)
    assert hit is bar or bar.isAncestorOf(hit)
    native_resize = Mock(return_value=True)
    monkeypatch.setattr(window.windowHandle(), "startSystemResize", native_resize)

    container.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()

    assert not isValid(container) and not isValid(bar)
    hit = window.childAt(point)
    assert hit is controller._zones["right"]
    QTest.mouseClick(hit, Qt.MouseButton.LeftButton, pos=hit.mapFrom(window, point))
    native_resize.assert_called_once_with(Qt.Edge.RightEdge)


def test_window_deletion_cancels_pending_scroll_mask_refresh(qt_application, monkeypatch):
    window, controller, scroll, _, stack, _ = _window_with_scroll(qt_application, monkeypatch)
    zones = controller.zones
    stack.deleteLater()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_application.processEvents()
    assert not isValid(scroll)
    assert not isValid(controller) and not isValid(window)
    assert all(not isValid(zone) for zone in zones)
