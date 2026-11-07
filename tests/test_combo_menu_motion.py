"""下拉菜单的首帧、滑动指示条与取消边界保留原有选择语义。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ComboBox
from qfluentwidgets.components.widgets import acrylic_label
from shiboken6 import isValid

from gui.styles import BaseStyles
from gui.styles.combo_menu import configure_combo_menu
from gui.widgets.combo_menu_motion import ComboMenuMotion
from gui.widgets.frame_animation import FrameAnimation
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class _Host(QWidget):
    def __init__(self, mica):
        super().__init__()
        self.mica = mica

    def isMicaEffectEnabled(self):
        return self.mica


@pytest.fixture
def make_combo(qt_application, monkeypatch):
    owned = []

    def capture(brush, rect):
        image = QPixmap(max(1, rect.width()), max(1, rect.height()))
        image.fill(QColor("#245884"))
        brush.setImage(image)

    monkeypatch.setattr(acrylic_label.AcrylicBrush, "grabImage", capture)

    def create(*, mica=False, count=8, current_index=0):
        host = _Host(mica)
        owned.append(host)
        field = configure_combo_menu(ComboBox(host))
        field.addItems([f"Option {index}" for index in range(count)])
        field.setCurrentIndex(current_index)
        field.setMaxVisibleItems(5)
        layout = QVBoxLayout(host)
        layout.addWidget(field)
        host.resize(320, 80)
        host.show()
        qt_application.processEvents()
        field._showComboMenu()
        return host, field, field.dropMenu

    yield create
    for host in owned:
        if isValid(host):
            host.close()
            host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _finish_popup(app, menu):
    animation = menu.aniManager.ani
    wait_until(app, lambda: animation.state() != QAbstractAnimation.State.Paused)
    animation.setCurrentTime(animation.duration())


@pytest.mark.parametrize("mica", [False, True])
def test_popup_has_visible_intermediate_frame_and_finishes_at_native_endpoint(
    qt_application, make_combo, mica,
):
    _, field, menu = make_combo(mica=mica)
    animation = menu.aniManager.ani
    assert isinstance(animation, FrameAnimation)
    assert animation.state() == QAbstractAnimation.State.Paused
    start, end = animation.startValue(), animation.endValue()
    assert start != end and menu.pos() == start
    animation.setCurrentTime(animation.duration() // 3)
    assert min(start.y(), end.y()) < menu.y() < max(start.y(), end.y())
    assert not menu.mask().isEmpty()
    animation.setCurrentTime(animation.duration())
    assert menu.pos() == end
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert field.currentIndex() == 0


def test_keyboard_candidate_slides_blue_marker_without_committing_choice(
    qt_application, make_combo,
):
    _, field, menu = make_combo()
    _finish_popup(qt_application, menu)
    marker = menu.view.viewport().findChild(QWidget, "adblabComboIndicator")
    assert marker is not None and marker.isVisible()
    changed = QSignalSpy(field.currentIndexChanged)
    start = marker.geometry()
    QTest.keyClick(menu.view, Qt.Key.Key_Down)
    motion = menu.findChild(FrameAnimation, "adblabComboIndicatorAnimation")
    assert motion is not None and motion.state() == QAbstractAnimation.State.Running
    motion.pause()
    motion.setCurrentTime(motion.duration() // 2)
    target = menu.view.visualItemRect(menu.view.currentItem()).top() + 11
    assert start.top() < marker.y() < target
    motion.setCurrentTime(motion.duration())
    assert marker.y() == target
    assert field.currentIndex() == 0 and changed.count() == 0


def test_leaving_hover_without_selected_option_clears_candidate_marker(
    qt_application, make_combo,
):
    _, field, menu = make_combo(current_index=-1)
    _finish_popup(qt_application, menu)
    wait_until(qt_application, lambda: menu.windowHandle().isExposed())
    assert not menu.view.currentIndex().isValid()
    motion = menu.findChild(ComboMenuMotion)
    marker = motion.indicator
    entered = QSignalSpy(menu.view.itemEntered)
    changed = QSignalSpy(field.currentIndexChanged)
    QTest.mouseMove(menu.windowHandle(), QPoint(-20, -20))
    point = menu.view.visualItemRect(menu.view.item(2)).center()
    QTest.mouseMove(menu.windowHandle(), menu.view.viewport().mapTo(menu, point))
    wait_until(qt_application, lambda: entered.count() > 0)
    assert marker.isVisible()
    QTest.mouseMove(menu.windowHandle(), QPoint(-20, -20))
    wait_until(qt_application, marker.isHidden)
    assert motion.indicator_animation.state() == QAbstractAnimation.State.Stopped
    assert field.currentIndex() == -1 and changed.count() == 0


def test_rapid_hover_retargets_from_visible_marker_without_selecting(qt_application, make_combo):
    _, field, menu = make_combo()
    _finish_popup(qt_application, menu)
    wait_until(qt_application, lambda: menu.windowHandle().isExposed())
    QTest.mouseMove(menu.windowHandle(), QPoint(-20, -20))
    motion = menu.findChild(ComboMenuMotion)
    marker = motion.indicator
    changed = QSignalSpy(field.currentIndexChanged)
    activated = QSignalSpy(field.activated)
    entered = []
    entered_signal = QSignalSpy(menu.view.itemEntered)

    def pause_entered_candidate(item):
        animation = motion.indicator_animation
        entered.append((menu.view.row(item), animation.state()))
        animation.pause()

    menu.view.itemEntered.connect(pause_entered_candidate)
    for row in (1, 3, 1):
        before = marker.geometry()
        delivered = len(entered)
        point = menu.view.visualItemRect(menu.view.item(row)).center()
        QTest.mouseMove(menu.windowHandle(), menu.view.viewport().mapTo(menu, point))
        if len(entered) == delivered:
            assert entered_signal.wait(1000), "真实指针移动必须进入目标菜单行"
        assert entered[-1][0] == row
        assert entered[-1][1] == QAbstractAnimation.State.Running
        assert marker.geometry() == before
        animation = motion.indicator_animation
        assert animation.state() == QAbstractAnimation.State.Paused
        animation.setCurrentTime(animation.duration() // 2)
        target = menu.view.visualItemRect(menu.view.item(row)).top() + 11
        assert min(before.y(), target) < marker.y() < max(before.y(), target)
    animation.setCurrentTime(animation.duration())
    assert marker.y() == target
    assert field.currentIndex() == 0
    assert changed.count() == activated.count() == 0


@pytest.mark.parametrize("reason", ["close", "hide", "host-hide", "minimize"])
def test_close_or_hide_cancels_pending_first_frame_and_candidate_clock(
    qt_application, make_combo, reason,
):
    host, _, menu = make_combo()
    motion = menu.findChild(ComboMenuMotion)
    assert motion.popup_animation.state() == QAbstractAnimation.State.Paused
    QTest.keyClick(menu.view, Qt.Key.Key_Down)
    assert motion.indicator_animation.state() == QAbstractAnimation.State.Running
    if reason == "close":
        menu.close()
    elif reason == "hide":
        menu.hide()
    elif reason == "host-hide":
        host.hide()
    else:
        host.showMinimized()
    assert motion.popup_animation.state() == QAbstractAnimation.State.Stopped
    assert motion.indicator_animation.state() == QAbstractAnimation.State.Stopped
    assert not motion._resume_timer.isActive()
    assert not motion.popup_animation._timer.isActive()
    assert not motion.indicator_animation._timer.isActive()


@pytest.mark.parametrize("reason", ["flag", "style"])
def test_disabled_motion_commits_endpoint_and_keeps_option_action(
    qt_application, make_combo, monkeypatch, reason,
):
    _, field, menu = make_combo()
    if reason == "style":
        monkeypatch.setattr(field, "style", lambda: SimpleNamespace(styleHint=lambda _hint: 0))
    menu.exec(field.mapToGlobal(QPoint(0, field.height())), ani=reason != "flag")
    animation = menu.aniManager.ani
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert menu.pos() == animation.endValue()
    assert menu.mask().isEmpty()
    item = menu.view.item(1)
    QTest.mouseClick(
        menu.view.viewport(), Qt.MouseButton.LeftButton,
        pos=menu.view.visualItemRect(item).center(),
    )
    assert field.currentIndex() == 1


def test_scrolling_candidate_tracks_content_and_theme_repaints_marker(
    qt_application, make_combo,
):
    _, field, menu = make_combo(count=40)
    _finish_popup(qt_application, menu)
    motion = menu.findChild(ComboMenuMotion)
    QTest.mouseMove(menu, QPoint(-20, -20))
    menu.view.setCurrentRow(15)
    motion.indicator_animation.setCurrentTime(motion.indicator_animation.duration())
    bar = menu.view.verticalScrollBar()
    bar.setValue(bar.value() + 25)
    assert motion.indicator.y() == menu.view.visualItemRect(menu.view.currentItem()).top() + 11
    assert motion.indicator_animation.state() == QAbstractAnimation.State.Stopped
    colors = []
    for theme in ("Light", "Dark", "Light"):
        BaseStyles.switch_theme(theme)
        colors.append(motion.indicator.grab().toImage().pixelColor(1, 7))
    assert colors[0] == colors[2]
    assert colors[0] != colors[1]
    assert field.currentIndex() == 0
