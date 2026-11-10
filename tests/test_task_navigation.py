"""验证任务导航的优先级、短暂成功反馈和可释放计时器。"""

import importlib
import importlib.util

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole


class _PaintProbe(QObject):
    """观察真实绘制区域，验证状态动画不会连带刷新导航正文。"""

    def __init__(self, widget):
        super().__init__(widget)
        self.regions = []
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.regions.append(event.region())
        return False


@pytest.fixture
def navigation(qt_application):
    """仅创建普通 QWidget，避免 macOS 原生无边框窗口边界。"""
    buttons = []

    def create(*, baseline=True):
        assert importlib.util.find_spec("gui.widgets.task_navigation") is not None, (
            "任务导航状态控件尚未实现"
        )
        module = importlib.import_module("gui.widgets.task_navigation")
        button = module.TaskNavigationButton()
        buttons.append(button)
        button.show()
        qt_application.processEvents()
        if baseline:
            button.set_snapshot(module.TaskNavigationSnapshot())
        return button, module.TaskNavigationSnapshot

    yield create
    for button in buttons:
        button.shutdown()
        button.close()
        button.deleteLater()


def test_active_and_unread_priority_discard_superseded_success(navigation):
    button, snapshot = navigation()
    button.set_snapshot(snapshot(success_event_id="success-one"))
    assert tr("已完成") in button.accessibleName()
    button.set_snapshot(snapshot(active_count=2, unread_count=1))
    assert "2" in button.accessibleName()
    assert tr("进行中") in button.accessibleName()
    assert tr("未读异常") in button.accessibleName()
    button.set_snapshot(snapshot(unread_count=1))
    assert tr("未读异常") in button.accessibleName()
    assert tr("进行中") not in button.accessibleName()
    button.set_snapshot(snapshot())
    assert button.accessibleName() == tr("任务中心")


def test_repeated_snapshot_does_not_repaint_navigation(navigation, qt_application):
    button, snapshot = navigation()
    button.setCompacted(False)
    current = snapshot(unread_count=1)
    button.set_snapshot(current)
    qt_application.processEvents()
    probe = _PaintProbe(button)

    button.set_snapshot(current)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.UpdateRequest)
    qt_application.processEvents()

    assert not probe.regions
    assert tr("未读异常") in button.accessibleName()


def test_activity_frame_repaints_icon_without_navigation_text(navigation, qt_application):
    button, snapshot = navigation()
    button.setCompacted(False)
    button.set_snapshot(snapshot(active_count=2, busy_count=1))
    qt_application.processEvents()
    probe = _PaintProbe(button)

    button._advance_animation()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.UpdateRequest)
    qt_application.processEvents()

    assert probe.regions
    assert all(not region.contains(QPoint(80, 18)) for region in probe.regions)
    assert all(region.boundingRect().right() < 40 for region in probe.regions)
    assert "2" in button.accessibleName()


def test_initial_snapshot_and_suppressed_success_never_replay(navigation):
    button, snapshot = navigation()
    button.set_snapshot(snapshot())
    assert button.accessibleName() == tr("任务中心")
    button.set_snapshot(snapshot(active_count=1, success_event_id="other-completion"))
    button.set_snapshot(snapshot(success_event_id="other-completion"))
    assert button.accessibleName() == tr("任务中心")
    button.set_snapshot(snapshot(unread_count=1, success_event_id="warning-completion"))
    button.set_snapshot(snapshot(success_event_id="warning-completion"))
    assert button.accessibleName() == tr("任务中心")


def test_first_snapshot_establishes_baseline_even_with_success_id(navigation):
    button, snapshot = navigation(baseline=False)
    button.set_snapshot(snapshot(success_event_id="history"))
    assert button.accessibleName() == tr("任务中心")
    button.set_snapshot(snapshot(success_event_id="history"))
    assert button.accessibleName() == tr("任务中心")


def test_success_expires_after_three_seconds_without_duplicate_restart(navigation):
    button, snapshot = navigation()
    button.set_snapshot(snapshot(success_event_id="once"))
    QTest.qWait(2750)
    assert tr("已完成") in button.accessibleName()
    button.set_snapshot(snapshot(success_event_id="once"))
    QTest.qWait(450)
    assert button.accessibleName() == tr("任务中心")
    button.set_snapshot(snapshot())
    button.set_snapshot(snapshot(success_event_id="once"))
    assert button.accessibleName() == tr("任务中心")


def test_new_success_replaces_old_deadline_and_old_id_is_ignored(navigation):
    button, snapshot = navigation()
    button.set_snapshot(snapshot(success_event_id="first"))
    QTest.qWait(2750)
    button.set_snapshot(snapshot(success_event_id="second"))
    QTest.qWait(450)
    assert tr("已完成") in button.accessibleName()
    button.set_snapshot(snapshot(active_count=1))
    button.set_snapshot(snapshot(success_event_id="first"))
    assert button.accessibleName() == tr("任务中心")
    button.set_snapshot(snapshot(success_event_id="third"))
    assert tr("已完成") in button.accessibleName()


def test_hiding_discards_success_and_resumes_only_current_activity(navigation, qt_application):
    button, snapshot = navigation()
    button.set_snapshot(snapshot(success_event_id="before-hide"))
    button.hide()
    assert not any(timer.isActive() for timer in button.findChildren(QTimer))
    button.show()
    qt_application.processEvents()
    assert button.accessibleName() == tr("任务中心")
    button.hide()
    button.set_snapshot(snapshot(success_event_id="while-hidden"))
    button.show()
    assert button.accessibleName() == tr("任务中心")
    button.set_snapshot(snapshot(active_count=3))
    assert any(timer.isActive() for timer in button.findChildren(QTimer))
    button.hide()
    assert not any(timer.isActive() for timer in button.findChildren(QTimer))
    button.show()
    qt_application.processEvents()
    assert tr("进行中") in button.accessibleName()
    assert "3" in button.accessibleName()
    assert any(timer.isActive() for timer in button.findChildren(QTimer))


def test_shutdown_and_close_stop_timers_and_reject_late_snapshots(navigation):
    button, snapshot = navigation()
    button.set_snapshot(snapshot(active_count=4))
    button.shutdown()
    previous = button.accessibleName()
    button.set_snapshot(snapshot(unread_count=2, success_event_id="late"))
    button.shutdown()
    assert button.accessibleName() == previous
    assert not any(timer.isActive() for timer in button.findChildren(QTimer))
    button.show()
    assert not any(timer.isActive() for timer in button.findChildren(QTimer))


def test_close_without_shutdown_stops_animation(navigation):
    button, snapshot = navigation()
    button.set_snapshot(snapshot(active_count=1))
    button.close()
    assert not any(timer.isActive() for timer in button.findChildren(QTimer))


def test_activity_icon_follows_custom_accent_and_real_frames_advance(navigation):
    button, snapshot = navigation()
    previous_accent = BaseStyles.accent_color()
    try:
        BaseStyles.set_accent_color("#AD218A")
        button.set_snapshot(snapshot(active_count=2))
        first = button.grab().toImage()
        target = QColor("#AD218A")
        assert sum(
            first.pixelColor(x, y).name() == target.name()
            for x in range(first.width())
            for y in range(first.height())
        ) > 10
        QTest.qWait(120)
        second = button.grab().toImage()
        assert first != second
    finally:
        BaseStyles.set_accent_color(previous_accent)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("compacted", [True, False])
def test_real_paint_keeps_selection_text_and_status_in_both_navigation_modes(
    navigation, theme, compacted,
):
    button, snapshot = navigation()
    BaseStyles.switch_theme(theme)
    button.setCompacted(compacted)
    button.setSelected(True)
    button.set_snapshot(snapshot(active_count=123, unread_count=2))
    assert button.isSelected
    assert button.isSelectable
    assert button.font() == BaseStyles.font_for_role(FontRole.UI)
    assert button.text() == tr("任务中心")
    assert "123" in button.accessibleName()
    image = button.grab().toImage()
    assert not image.isNull()
    scale = image.devicePixelRatio()
    # 环和数字需要实际出现在图标区域，不能只更新可访问名称。
    colored = sum(
        image.pixelColor(x, y).saturation() > 100
        for x in range(round(8 * scale), round(33 * scale))
        for y in range(round(5 * scale), round(31 * scale))
    )
    assert colored > 10


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_task_navigation_keyboard_activation_is_single_and_mouse_is_left_only(navigation, key):
    button, _snapshot = navigation()
    activated = QSignalSpy(button.clicked)
    QTest.keyClick(button, key)
    assert activated.count() == 1
    QTest.mouseClick(button, Qt.MouseButton.RightButton)
    assert activated.count() == 1
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert activated.count() == 2
