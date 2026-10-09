"""验证远程页透明动作与开关在鼠标、键盘交互中的绘制和几何稳定性。"""

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from qfluentwidgets import SwitchButton

from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from tests import test_remote_layout
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry

pytestmark = pytest.mark.ui
remote_layout = test_remote_layout.remote_layout

_SWITCHES = (
    "chk_aot", "chk_fullscreen", "chk_record", "chk_noaudio", "chk_showtouches",
    "chk_stayawake", "chk_turnscreenoff", "chk_noplayback",
)


def _geometry(widgets, root):
    return tuple(mapped_rect(widget, root).getRect() for widget in widgets)


class _PaintGeometry(QObject):
    def __init__(self, widgets, root):
        super().__init__(root)
        self.widgets = widgets
        self.root = root
        self.samples = []
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint and watched.isVisible():
            self.samples.append(_geometry(self.widgets, self.root))
        return False


def _pixel(image, x, y):
    scale = image.devicePixelRatio()
    return image.pixelColor(round(x * scale), round(y * scale))


def _assert_no_rectangular_border(button):
    image = button.grab().toImage()
    width, height = button.width(), button.height()
    background = _pixel(image, width // 2, 4)
    for x, y in ((width // 2, 1), (1, height // 2), (width - 2, height // 2)):
        assert _pixel(image, x, y) == background, (button.text(), x, y)
    return image


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_window_switches_keep_native_indicator_through_pointer_and_keyboard_states(
    remote_layout, qt_application, theme,
):
    _panel, remote, _scroll, content, _settings = remote_layout
    BaseStyles.switch_theme(theme)
    for name in ("chk_aot", "chk_fullscreen", "chk_showtouches"):
        switch = getattr(remote, name)
        assert isinstance(switch, SwitchButton)
        switch.setChecked(False)
        switch.indicator.clearFocus()
        QTest.mouseMove(content, QPoint(0, 0))
        wait_for_stable_geometry(qt_application, switch)
        widgets = (switch, switch.indicator, switch.label)
        original_hint, original_geometry = switch.minimumSizeHint(), _geometry(widgets, content)
        idle = switch.indicator.grab().toImage()
        switch.indicator.setFocus(Qt.FocusReason.TabFocusReason)
        assert switch.indicator.hasFocus()
        QTest.keyClick(switch.indicator, Qt.Key.Key_Space)
        assert switch.isChecked()
        QTest.qWait(150)
        assert switch.indicator.grab().toImage() != idle
        QTest.mouseClick(switch.indicator, Qt.MouseButton.LeftButton)
        assert not switch.isChecked()
        QTest.qWait(150)
        assert switch.minimumSizeHint() == original_hint
        assert _geometry(widgets, content) == original_geometry
        switch.setEnabled(False)
        QTest.mouseClick(switch.indicator, Qt.MouseButton.LeftButton)
        assert not switch.isChecked()
        switch.setEnabled(True)


@pytest.mark.parametrize("font_size", (12, 22))
def test_switch_clicks_preserve_every_row_geometry_and_unclipped_text(
    remote_layout, qt_application, font_size,
):
    _panel, remote, _scroll, content, _settings = remote_layout
    test_remote_layout.expand_remote_options(remote, content, qt_application)
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family="Arial", ui_size=font_size,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    QTest.qWait(200)
    switches = tuple(getattr(remote, name) for name in _SWITCHES)
    widgets = tuple(child for switch in switches for child in (
        switch, switch.label, switch.indicator,
    ))
    wait_for_stable_geometry(qt_application, widgets)
    before = _geometry(widgets, content)
    probe = _PaintGeometry(widgets, content)
    for switch in switches:
        checked = switch.isChecked()
        QTest.mouseClick(switch.indicator, Qt.MouseButton.LeftButton)
        assert switch.isChecked() != checked
        QTest.qWait(150)
        assert _geometry(widgets, content) == before
        switch.indicator.setFocus(Qt.FocusReason.TabFocusReason)
        assert switch.indicator.hasFocus()
        QTest.keyClick(switch.indicator, Qt.Key.Key_Space)
        assert switch.isChecked() == checked
        QTest.qWait(150)
        assert _geometry(widgets, content) == before
        assert switch.label.font().pointSize() == font_size
        assert switch.label.width() >= switch.label.fontMetrics().horizontalAdvance(
            switch.label.text(),
        )
        assert switch.label.height() >= switch.label.fontMetrics().height()
        assert switch.indicator.geometry().right() < switch.label.geometry().left()
        assert switch.label.geometry().left() - switch.indicator.geometry().right() <= 16
    assert probe.samples
    assert all(sample == before for sample in probe.samples)
    common = switches[:6]
    for column in (common[::2], common[1::2]):
        assert len({mapped_rect(s.indicator, content).left() for s in column}) == 1


def test_switch_keyboard_focus_has_visible_text_feedback(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    switch = remote.chk_stayawake
    switch.indicator.clearFocus()
    QTest.mouseMove(content, QPoint(0, 0))
    idle = switch.label.grab().toImage()
    switch.indicator.setFocus(Qt.FocusReason.TabFocusReason)
    assert switch.indicator.hasFocus()
    assert switch.label.grab().toImage() != idle


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_remote_actions_show_native_hover_and_focus_without_changing_geometry(
    remote_layout, qt_application, theme,
):
    _panel, remote, _scroll, content, _settings = remote_layout
    BaseStyles.switch_theme(theme)
    remote.set_target_devices(["synthetic-device"])
    for button in (
        remote.btn_start, remote.btn_stop, remote.btn_advanced, remote.btn_more_options,
        *remote._remote_control_buttons,
    ):
        button.setEnabled(True)
        button.clearFocus()
        _scroll.ensureWidgetVisible(button)
        QTest.mouseMove(_scroll.windowHandle(), QPoint(_scroll.width() - 2, 2))
        wait_for_stable_geometry(qt_application, button)
        original_hint = button.minimumSizeHint()
        original_geometry = button.geometry()
        idle = _assert_no_rectangular_border(button)
        # QWidget 的 mouseMove 在离屏后端可能只移动位置而不生成 Enter；窗口事件
        # 路径仍经过 Qt 命中测试，必须由实际按钮接收悬停，不能直接设置 isHover。
        QTest.mouseMove(_scroll.windowHandle(), button.mapTo(_scroll, button.rect().center()))
        QTest.qWait(40)
        assert button.underMouse() and button.isHover, (
            button.text(), mapped_rect(button, _scroll.viewport()),
        )
        hovered = button.grab().toImage()
        assert hovered != idle, f"{button.text()} 悬停应保留原生背景反馈"
        assert _pixel(hovered, button.width() // 2, 4) != _pixel(
            idle, button.width() // 2, 4,
        ), "悬停反馈应包含按钮背景，而不只是文字变色"
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        assert button.minimumSizeHint() == original_hint
        assert button.geometry() == original_geometry
        # 在按钮外释放，验证按压绘制而不触发真实动作或折叠切换。
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=QPoint(-1, -1))
        QTest.mouseMove(_scroll.windowHandle(), QPoint(_scroll.width() - 2, 2))
        button.setFocus(Qt.FocusReason.TabFocusReason)
        assert button.hasFocus()
        focused = button.grab().toImage()
        assert button.minimumSizeHint() == original_hint
        assert button.geometry() == original_geometry
        assert focused != idle, "键盘焦点必须具有可见反馈"
