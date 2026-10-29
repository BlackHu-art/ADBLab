"""导航内容在最终几何上过渡，不移动共享材质与业务目标。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    qInstallMessageHandler,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from tests.test_navigation_rendering import theme_probe_frame as theme_probe_frame
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.usefixtures("isolated_settings_client_detection")


@pytest.mark.parametrize("theme_name", ["Light", "Dark"])
@pytest.mark.parametrize("mica", [False, True])
def test_routes_keep_final_geometry_through_shared_content_transition(
    qt_application, theme_probe_frame, theme_name, mica,
):
    frame = theme_probe_frame(theme_name, mica)
    for key in ("appsPage", "appManagerPage", "settingsPage", "logcatPage", "performancePage"):
        frame.navigationInterface.widget(key).click()
        page = frame.stackedWidget.currentWidget()
        animation = frame._page_transition.animation
        assert animation.state() == QAbstractAnimation.State.Paused
        wait_until(qt_application, lambda: animation.state() == QAbstractAnimation.State.Running)
        assert page.pos() == QPoint(0, 0), "页面应从最终位置绘制，不能先露出大块背景"
        assert 300 <= animation.duration() <= 350
        geometry = page.geometry()
        bar_geometry = frame._global_device_bar.geometry()
        samples = []
        for time_ms in (0, 35, 90, animation.duration()):
            animation.setCurrentTime(time_ms)
            qt_application.processEvents()
            assert page.geometry() == geometry
            assert frame._global_device_bar.geometry() == bar_geometry
            image = frame.grab().toImage()
            point = frame.stackedWidget.mapTo(frame, QPoint(frame.stackedWidget.width() // 2, 2))
            ratio = image.devicePixelRatio()
            samples.append(image.pixelColor(round(point.x() * ratio), round(point.y() * ratio)))
        assert samples == [samples[-1]] * len(samples), (key, samples)
        assert frame._content_surface.graphicsEffect() is None
        assert frame._global_device_bar.graphicsEffect() is None
        assert frame._page_transition.effect.opacity() == 1
        assert not frame._page_transition.effect.isEnabled()


def test_same_host_and_rapid_replacement_commit_latest_route(theme_probe_frame, qt_application):
    frame = theme_probe_frame("Dark", False)
    frame.navigationInterface.widget("logcatPage").click()
    page = frame.stackedWidget.currentWidget()
    assert page.pos() == QPoint(0, 0)
    animation = frame._page_transition.animation
    wait_until(qt_application, lambda: animation.state() == QAbstractAnimation.State.Running)
    animation.setCurrentTime(45)
    frame.navigationInterface.widget("performancePage").click()
    assert frame.stackedWidget.currentWidget() is page
    assert animation.state() == QAbstractAnimation.State.Paused
    assert frame._page_transition.effect.opacity() == pytest.approx(0.15)
    assert page.current_route.feature == "performance"
    for key in ("appsPage", "settingsPage", "logcatPage", "performancePage"):
        frame.navigationInterface.widget(key).click()
        assert frame._page_transition.effect.opacity() == pytest.approx(0.15)
        wait_until(qt_application, lambda: animation.state() == QAbstractAnimation.State.Running)
        animation.setCurrentTime(25)
        assert frame.stackedWidget.currentWidget().pos() == QPoint(0, 0)
    assert frame.stackedWidget.currentWidget().current_route.feature == "performance"
    animation.setCurrentTime(animation.duration())
    frame.navigationInterface.widget("performancePage").click()
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert frame._content_surface.updatesEnabled()


@pytest.mark.parametrize("started", [False, True])
def test_theme_change_cancels_fade_without_changing_route(
    theme_probe_frame, qt_application, started,
):
    from gui.styles import BaseStyles

    frame = theme_probe_frame("Dark", True)
    frame.navigationInterface.widget("performancePage").click()
    transition = frame._page_transition
    if started:
        wait_until(
            qt_application,
            lambda: transition.animation.state() == QAbstractAnimation.State.Running,
        )
        transition.animation.setCurrentTime(35)
    assert transition.effect.isEnabled()
    page = frame.stackedWidget.currentWidget()
    route = page.current_route
    BaseStyles.switch_theme("Light")
    QTest.qWait(40)
    assert transition.animation.state() == QAbstractAnimation.State.Stopped
    assert not transition.effect.isEnabled()
    assert transition.effect.opacity() == 1
    assert frame.stackedWidget.currentWidget() is page
    assert page.current_route == route
    assert frame._content_surface.updatesEnabled()


@pytest.mark.parametrize("theme,mica", [
    ("Light", False), ("Dark", False), ("Light", True), ("Dark", True),
])
def test_content_fade_composes_without_painter_errors(
    theme_probe_frame, qt_application, record_property, theme, mica,
):
    frame = theme_probe_frame(theme, mica)
    messages = []
    previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    effects = {}
    try:
        for key in (
            "homePage", "appsPage", "appManagerPage", "filesPage", "settingsPage",
            "systemPage", "logcatPage", "performancePage", "tasksPage",
        ):
            frame.navigationInterface.widget(key).click()
            frame._page_transition.animation.setCurrentTime(40)
            qt_application.processEvents()
            effects[key] = [
                (type(widget).__name__, type(widget.graphicsEffect()).__name__)
                for widget in frame.stackedWidget.findChildren(QWidget)
                if widget.isVisibleTo(frame) and widget.graphicsEffect() is not None
                and widget.graphicsEffect().isEnabled()
            ]
            assert not frame.grab().isNull()
    finally:
        qInstallMessageHandler(previous)
    record_property("visible_child_effects", effects)
    assert not [
        message for message in messages if "QPainter" in message or "paintEngine" in message
    ]


@pytest.fixture
def transition_widgets(qt_application):
    from gui.widgets.page_transition import PageTransition

    surface = QWidget()
    surface.resize(400, 260)
    layout = QVBoxLayout(surface)
    content = QWidget(surface)
    content_layout = QVBoxLayout(content)
    editor = QLineEdit(content)
    content_layout.addWidget(editor)
    layout.addWidget(content)
    transition = PageTransition(surface, content)
    surface.show()
    qt_application.processEvents()
    yield surface, content, editor, transition
    surface.close()
    surface.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_nested_batch_keeps_focus_values_and_restores_updates_on_exception(transition_widgets):
    surface, content, editor, transition = transition_widgets
    editor.setText("保留内容")
    editor.setFocus()
    state = ["old"]
    with transition.batch(lambda: state[0]):
        with transition.batch(lambda: state[0]):
            state[0] = "new"
            assert not surface.updatesEnabled()
        assert not surface.updatesEnabled()
        assert transition.animation.state() == QAbstractAnimation.State.Stopped
    assert surface.updatesEnabled()
    assert editor.hasFocus() and editor.text() == "保留内容"
    assert transition.animation.state() == QAbstractAnimation.State.Paused
    with pytest.raises(ValueError, match="synthetic"):
        with transition.batch(lambda: state[0]):
            state[0] = "failed"
            raise ValueError("synthetic")
    assert surface.updatesEnabled()
    assert not transition.effect.isEnabled()
    assert transition.effect.opacity() == 1
    assert content.isVisible()


@pytest.mark.parametrize("action", ["hide", "resize", "disable", "close", "stop"])
@pytest.mark.parametrize("stage", ["before_paint", "after_paint", "running"])
def test_interrupted_animation_always_restores_final_content(
    transition_widgets, qt_application, action, stage,
):
    surface, content, _editor, transition = transition_widgets
    state = [0]
    with transition.batch(lambda: state[0]):
        state[0] = 1
    if stage == "after_paint":
        content.repaint()
    elif stage == "running":
        wait_until(
            qt_application,
            lambda: transition.animation.state() == QAbstractAnimation.State.Running,
        )
        transition.animation.setCurrentTime(30)
    assert transition.effect.isEnabled()
    assert 0 < transition.effect.opacity() < 1
    if action == "hide":
        surface.hide()
    elif action == "resize":
        content.resize(content.width() - 1, content.height())
    elif action == "disable":
        transition.set_enabled(False)
    elif action == "close":
        surface.close()
    else:
        transition.animation.stop()
    QTest.qWait(40)
    assert transition.animation.state() == QAbstractAnimation.State.Stopped
    assert not transition.effect.isEnabled()
    assert transition.effect.opacity() == 1
    assert surface.updatesEnabled()


def test_destroyed_content_cannot_resume_after_queued_first_paint(transition_widgets):
    surface, content, _editor, transition = transition_widgets
    state = [0]
    with transition.batch(lambda: state[0]):
        state[0] = 1
    content.repaint()
    assert transition.animation.state() == QAbstractAnimation.State.Paused
    destroyed = []
    content.destroyed.connect(lambda: destroyed.append(True))
    content.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed == [True]
    QTest.qWait(40)
    assert transition.animation.state() == QAbstractAnimation.State.Stopped
    assert surface.updatesEnabled()


def test_batch_does_not_enable_externally_disabled_updates(transition_widgets):
    surface, _content, _editor, transition = transition_widgets
    surface.setUpdatesEnabled(False)
    state = [0]
    with transition.batch(lambda: state[0]):
        state[0] = 1
    assert not surface.updatesEnabled()
    assert transition.animation.state() == QAbstractAnimation.State.Stopped
    assert not transition.effect.isEnabled()
    surface.setUpdatesEnabled(True)


def test_style_disabling_animation_commits_route_without_fade(transition_widgets, monkeypatch):
    surface, content, _editor, transition = transition_widgets
    monkeypatch.setattr(content, "style", lambda: SimpleNamespace(styleHint=lambda _hint: 0))
    state = [0]
    with transition.batch(lambda: state[0]):
        state[0] = 1
    assert state == [1]
    assert surface.updatesEnabled()
    assert transition.animation.state() == QAbstractAnimation.State.Stopped
    assert not transition.effect.isEnabled()
    assert transition.effect.opacity() == 1


def test_content_destroyed_inside_batch_does_not_leave_surface_frozen(transition_widgets):
    surface, content, _editor, transition = transition_widgets
    state = [0]
    with transition.batch(lambda: state[0]):
        state[0] = 1
        content.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert surface.updatesEnabled()


def test_slow_first_paint_keeps_full_fade_budget(transition_widgets, qt_application):
    surface, content, _editor, transition = transition_widgets
    samples = []

    class SlowFirstPaint(QObject):
        def eventFilter(self, watched, event):  # noqa: N802
            if event.type() == QEvent.Type.Paint and not samples:
                samples.append((transition.animation.currentTime(), transition.effect.opacity()))
                # 确定性模拟首帧绘制成本，期间不泵事件；不能占用淡入时长。
                QTest.qSleep(120)
            return False

    observer = SlowFirstPaint(content)
    content.installEventFilter(observer)
    state = [0]
    with transition.batch(lambda: state[0]):
        state[0] = 1
    assert surface.updatesEnabled() and state == [1]
    assert transition.animation.state() == QAbstractAnimation.State.Paused
    content.repaint()
    assert samples == [(0, pytest.approx(0.15))]
    assert transition.animation.currentTime() == 0
    assert transition.animation.state() == QAbstractAnimation.State.Paused
    wait_until(
        qt_application, lambda: transition.animation.state() == QAbstractAnimation.State.Running,
    )
    assert transition.animation.currentTime() < 50
    assert transition.effect.opacity() < 0.55
    transition.animation.setCurrentTime(160)
    assert transition.effect.opacity() == pytest.approx(0.7875)
    transition.animation.setCurrentTime(320)
    assert not transition.effect.isEnabled() and transition.effect.opacity() == 1


def test_replacement_restarts_from_low_opacity_and_waits_for_its_own_paint(
    transition_widgets, qt_application,
):
    _surface, content, _editor, transition = transition_widgets
    state = [0]
    with transition.batch(lambda: state[0]):
        state[0] = 1
    wait_until(
        qt_application, lambda: transition.animation.state() == QAbstractAnimation.State.Running,
    )
    transition.animation.setCurrentTime(round(transition.animation.duration() * 0.85))
    assert transition.effect.opacity() > 0.9
    with transition.batch(lambda: state[0]):
        state[0] = 2
    assert transition.effect.opacity() == pytest.approx(0.15)
    content.repaint()  # 首个替换目标已经绘制，但启动回调尚未执行。
    with transition.batch(lambda: state[0]):
        state[0] = 3
    # 暂停更新后泵事件，旧目标的待启动回调不能提前启动最新目标。
    content.setUpdatesEnabled(False)
    QTest.qWait(40)
    assert state == [3]
    assert transition.animation.state() == QAbstractAnimation.State.Paused
    assert transition.animation.currentTime() == 0
    assert transition.effect.opacity() == pytest.approx(0.15)
    content.setUpdatesEnabled(True)
    wait_until(
        qt_application, lambda: transition.animation.state() == QAbstractAnimation.State.Running,
    )
    wait_until(
        qt_application, lambda: transition.animation.state() == QAbstractAnimation.State.Stopped,
    )
    assert not transition.effect.isEnabled() and transition.effect.opacity() == 1
