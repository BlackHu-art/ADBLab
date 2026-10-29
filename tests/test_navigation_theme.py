"""验证主题入口不参与导航，并保留紧凑与展开模式的真实交互。"""

import pytest
from PySide6.QtCore import QAbstractAnimation, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    NavigationDisplayMode,
    NavigationInterface,
    NavigationItemPosition,
)

from core.settings_manager import AppSettings
from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles import theme as theme_module
from gui.widgets.navigation_theme import NavigationThemeToggle
from tests.test_main_window_layout import (
    _FakeScreen,
    _FakeScreenAdapter,
    _MainFrameSettings,
    build_main_frame,
)
from tests.ui_geometry_helpers import wait_until


@pytest.mark.parametrize("initial,target", [("Light", "Dark"), ("Dark", "Light")])
def test_theme_rebuild_uses_target_tokens_without_painting_partial_state(
    qt_application, monkeypatch, initial, target,
):
    """Fluent 重建与应用回调只见目标 token，窗口等完整提交后恢复绘制。"""
    from qfluentwidgets.common import style_sheet

    BaseStyles.switch_theme(initial)
    visible = QWidget()
    disabled = QWidget()
    visible.show()
    disabled.setUpdatesEnabled(False)
    observed = []
    original = style_sheet.updateStyleSheet

    def rebuild(*args, **kwargs):
        observed.append((BaseStyles.resolved_theme(), visible.updatesEnabled()))
        return original(*args, **kwargs)

    monkeypatch.setattr(style_sheet, "updateStyleSheet", rebuild)
    try:
        BaseStyles.switch_theme(target)
        assert observed == [(target, False)]
        assert visible.updatesEnabled()
        assert not disabled.updatesEnabled()
    finally:
        monkeypatch.setattr(style_sheet, "updateStyleSheet", original)
        visible.close()
        disabled.close()
        visible.deleteLater()
        disabled.deleteLater()


def test_theme_rebuild_failure_restores_window_updates(qt_application, monkeypatch):
    """样式重建失败不能把窗口永久留在停止重绘状态。"""
    from qfluentwidgets.common import style_sheet
    from shiboken6.Shiboken import delete

    BaseStyles.switch_theme("Light")
    host = QWidget()
    host.show()
    doomed = QWidget()
    doomed.show()
    seen = []
    original = style_sheet.updateStyleSheet

    def fail(*_args, **_kwargs):
        seen.append(host.updatesEnabled())
        delete(doomed)
        raise RuntimeError("synthetic style failure")

    monkeypatch.setattr(style_sheet, "updateStyleSheet", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic style failure"):
            BaseStyles.switch_theme("Dark")
        assert seen == [False]
        assert host.updatesEnabled()
    finally:
        monkeypatch.setattr(style_sheet, "updateStyleSheet", original)
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("compacted", [True, False])
def test_theme_focus_keeps_fluent_background_without_outer_outline(qt_application, compacted):
    """明暗切换和键盘焦点都不为主题入口增加外围黑白框。"""
    BaseStyles.switch_theme("Light")
    host = QWidget()
    widget = NavigationThemeToggle(host)
    widget.setCompacted(compacted)
    layout = QVBoxLayout(host)
    layout.addWidget(widget)
    widget.clicked.connect(BaseStyles.toggle_theme)
    BaseStyles.theme_changed.connect(widget.sync_theme)
    target = widget if compacted else widget.switch.indicator
    try:
        host.show()
        host.activateWindow()
        target.setFocus(Qt.FocusReason.TabFocusReason)
        wait_until(qt_application, target.hasFocus)
        for theme in ("Dark", "Light"):
            QTest.mouseClick(target, Qt.MouseButton.LeftButton)
            qt_application.processEvents()
            assert BaseStyles.resolved_theme() == theme
            assert target.hasFocus()
            focused = widget.grab().toImage()
            target.clearFocus()
            qt_application.processEvents()
            unfocused = widget.grab().toImage()
            scale = focused.devicePixelRatio()
            edge_x = round(scale)
            edge_y = round(widget.height() * scale / 2)
            assert focused.pixelColor(edge_x, edge_y) == unfocused.pixelColor(edge_x, edge_y)
            target.setFocus(Qt.FocusReason.TabFocusReason)
            wait_until(qt_application, target.hasFocus)
    finally:
        host.close()


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_compact_theme_action_supports_keyboard_and_mouse(qt_application, key):
    widget = NavigationThemeToggle()
    widget.show()
    calls = QSignalSpy(widget.clicked)

    QTest.keyClick(widget, key)
    assert calls.count() == 1
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert calls.count() == 2
    QTest.mouseClick(widget, Qt.MouseButton.RightButton)
    assert calls.count() == 2
    assert widget.switch.isHidden()
    assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert not widget.isSelectable


@pytest.mark.parametrize("resolved", ["Light", "Dark"])
def test_system_theme_sync_is_silent_and_toggle_uses_resolved_theme(
    qt_application, monkeypatch, resolved,
):
    monkeypatch.setattr(theme_module, "_current_theme", resolved)
    monkeypatch.setattr(theme_module, "_theme_mode", "System")
    widget = NavigationThemeToggle()
    calls = QSignalSpy(widget.clicked)
    widget.clicked.connect(BaseStyles.toggle_theme)

    widget.sync_theme()
    widget.sync_theme()
    assert calls.count() == 0
    assert BaseStyles.current_theme() == "System"
    assert widget.switch.isChecked() == (resolved == "Dark")
    target = "Light" if resolved == "Dark" else "Dark"
    target_label = tr("浅色") if target == "Light" else tr("深色")
    assert widget.accessibleName() == tr("切换到{theme}主题").format(theme=target_label)
    assert widget.toolTip() == widget.accessibleName()

    widget.show()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert calls.count() == 1
    assert BaseStyles.current_theme() == target
    widget.sync_theme()
    assert calls.count() == 1
    assert widget.switch.isChecked() == (target == "Dark")


def test_theme_switch_skips_redundant_accent_and_same_mode(
    qt_application, monkeypatch,
):
    from qfluentwidgets import Theme

    calls = []
    state = {"actual": "Light"}

    def fake_set_theme(theme, save=False, lazy=False):
        calls.append(("theme", theme, lazy))
        state["actual"] = "Dark" if theme == Theme.DARK else "Light"

    monkeypatch.setattr("qfluentwidgets.setTheme", fake_set_theme)
    monkeypatch.setattr(
        "qfluentwidgets.setThemeColor",
        lambda color, save=False, lazy=False: calls.append(("color", color)),
    )
    monkeypatch.setattr(theme_module, "_resolve_qfluentwidgets_theme", lambda: state["actual"])
    monkeypatch.setattr(theme_module, "_qfw_accent_applied", None)
    monkeypatch.setattr(theme_module, "_theme_mode", "Light")
    monkeypatch.setattr(theme_module, "_current_theme", "Light")

    BaseStyles.switch_theme("Dark")
    assert calls[0] == ("theme", Theme.DARK, False)
    assert calls[1][0] == "color"

    calls.clear()
    BaseStyles.switch_theme("Light")
    assert calls == [("theme", Theme.LIGHT, False)]

    calls.clear()
    BaseStyles.switch_theme("Light")
    assert calls == []

    calls.clear()
    BaseStyles.set_accent_color(BaseStyles.accent_color())
    assert calls == []


def test_switch_theme_repairs_stale_qfluentwidgets_state(qt_application, monkeypatch):
    from qfluentwidgets import Theme

    calls = []
    state = {"actual": "Dark"}
    monkeypatch.setattr(
        "qfluentwidgets.setTheme",
        lambda theme, save=False, lazy=False: (
            calls.append(theme),
            state.__setitem__("actual", "Dark" if theme == Theme.DARK else "Light"),
        ),
    )
    monkeypatch.setattr(theme_module, "_resolve_qfluentwidgets_theme", lambda: state["actual"])
    monkeypatch.setattr(theme_module, "_desired_qfluentwidgets_theme", lambda mode=None: "Light")
    monkeypatch.setattr(theme_module, "_qfw_accent_applied", BaseStyles.accent_color())
    monkeypatch.setattr(theme_module, "_theme_mode", "System")
    monkeypatch.setattr(theme_module, "_current_theme", "Light")

    BaseStyles.switch_theme("System")

    assert calls == [Theme.LIGHT]
    assert BaseStyles.resolved_theme() == "Light"


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_expanded_theme_switch_uses_native_checkable_control(qt_application, key):
    BaseStyles.switch_theme("Light")
    widget = NavigationThemeToggle()
    widget.setCompacted(False)
    widget.show()
    calls = QSignalSpy(widget.clicked)
    widget.clicked.connect(BaseStyles.toggle_theme)
    BaseStyles.theme_changed.connect(widget.sync_theme)

    QTest.mouseClick(widget.switch.indicator, Qt.MouseButton.LeftButton)
    assert BaseStyles.current_theme() == "Dark"
    assert widget.switch.isChecked()
    assert calls.count() == 1
    QTest.keyClick(widget.switch.indicator, key)
    assert BaseStyles.current_theme() == "Light"
    assert not widget.switch.isChecked()
    assert calls.count() == 2
    assert widget.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert widget.switch.indicator.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert widget.switch.indicator.isCheckable()
    assert widget.switch.indicator.accessibleName() == tr("深色")


@pytest.mark.parametrize("compacted", [True, False])
def test_theme_action_remains_a_single_tab_stop_without_outer_outline(qt_application, compacted):
    """移除外围框后仍可经 Tab 到达唯一主题入口，并用 Space 激活一次。"""
    host = QWidget()
    layout = QVBoxLayout(host)
    before = QPushButton("Before", host)
    theme = NavigationThemeToggle(host)
    theme.setCompacted(compacted)
    after = QPushButton("After", host)
    for widget in (before, theme, after):
        layout.addWidget(widget)
    calls = QSignalSpy(theme.clicked)
    target = theme if compacted else theme.switch.indicator
    try:
        host.show()
        host.activateWindow()
        before.setFocus(Qt.FocusReason.TabFocusReason)
        wait_until(qt_application, before.hasFocus)
        QTest.keyClick(before, Qt.Key.Key_Tab)
        assert target.hasFocus()
        QTest.keyClick(target, Qt.Key.Key_Space)
        assert calls.count() == 1
        QTest.keyClick(target, Qt.Key.Key_Tab)
        assert after.hasFocus()
        assert calls.count() == 1
    finally:
        host.close()


@pytest.mark.parametrize("font_size", [12, 18])
def test_expanded_theme_control_keeps_switch_and_text_separate(
    qt_application, font_size,
):
    widget = NavigationThemeToggle()
    widget.EXPAND_WIDTH = 210
    font = QFont(widget.font())
    font.setPointSize(font_size)
    widget.setFont(font)
    widget.setCompacted(False)
    widget.show()
    qt_application.processEvents()

    assert widget.switch.isVisibleTo(widget)
    assert widget.rect().contains(widget.switch.geometry())
    assert 44 + widget.fontMetrics().horizontalAdvance(widget.text()) < widget.switch.x() - 12
    assert widget.switch.height() <= widget.height()
    widget.setCompacted(True)
    assert widget.switch.isHidden()
    assert widget.width() == 40
    assert widget.focusProxy() is None
    widget.setCompacted(False)
    assert widget.rect().contains(widget.switch.geometry())


def test_theme_navigation_item_is_above_settings_without_changing_selection(qt_application):
    navigation = NavigationInterface()
    navigation.addItem("home", FluentIcon.HOME, "Home")
    widget = NavigationThemeToggle()
    navigation.addWidget("theme", widget, position=NavigationItemPosition.BOTTOM)
    settings = navigation.addItem(
        "settings", FluentIcon.SETTING, "Settings", position=NavigationItemPosition.BOTTOM,
    )
    navigation.setCurrentItem("home")
    navigation.show()
    qt_application.processEvents()
    panel = navigation.panel
    selected = panel.currentItem()
    calls = QSignalSpy(widget.clicked)

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert calls.count() == 1
    assert panel.currentItem() is selected
    assert selected.isSelected
    assert not widget.isSelected
    assert panel.bottomLayout.indexOf(widget) < panel.bottomLayout.indexOf(settings)


def test_main_window_theme_switch_preserves_route_session_and_persists_choice(
    qt_application, monkeypatch,
):
    settings = _MainFrameSettings()
    settings.values.update(window_width=1280, window_height=840, mica_enabled=False)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    BaseStyles.switch_theme("Light")
    frame = build_main_frame(
        settings=settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("theme-test", QSize(1920, 1080))),
    )
    try:
        frame.show()
        frame._open_workspace_feature("apps", "media")
        panel = frame.navigationInterface.panel
        widget = frame._theme_navigation_widget
        wait_until(
            qt_application,
            lambda: panel.displayMode == NavigationDisplayMode.EXPAND
            and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
        )
        location = frame._current_navigation_location
        history = list(frame._navigation_history)
        selected = panel.currentItem()
        host = frame._workspace_feature_hosts["apps"]
        session = host.stack.currentWidget()

        for theme in ("Dark", "Light"):
            if theme == "Light":
                frame._toggle_navigation_panel()
                wait_until(
                    qt_application,
                    lambda: panel.displayMode == NavigationDisplayMode.COMPACT
                    and panel.expandAni.state() == QAbstractAnimation.State.Stopped,
                )
                target = widget
            else:
                target = widget.switch.indicator
                assert widget.switch.isVisibleTo(frame)
            writes = len([write for write in settings.writes if "theme" in write])
            QTest.mouseClick(target, Qt.MouseButton.LeftButton)

            assert BaseStyles.resolved_theme() == theme
            assert settings.values["theme"] == theme
            assert len([write for write in settings.writes if "theme" in write]) == writes + 1
            assert widget.switch.isChecked() == (theme == "Dark")
            assert frame._settings_page.theme_card.combo_box.currentText() == (
                frame._settings_page.THEME_LABELS[theme]
            )
            assert frame._current_navigation_location == location
            assert frame._navigation_history == history
            assert panel.currentItem() is selected
            assert host.stack.currentWidget() is session
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
