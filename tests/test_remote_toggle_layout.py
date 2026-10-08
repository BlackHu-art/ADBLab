"""验证远程页透明动作与开关在鼠标、键盘交互中的绘制和几何稳定性。"""

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from qfluentwidgets import themeColor

from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from tests import test_remote_layout
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry

pytestmark = pytest.mark.ui
remote_layout = test_remote_layout.remote_layout

_TOGGLES = ("chk_aot", "chk_fullscreen", "chk_showtouches")
_SWITCHES = (
    "chk_record", "chk_noaudio", "chk_stayawake", "chk_turnscreenoff",
    "chk_noplayback",
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
def test_window_toggles_keep_only_bottom_accent_through_pointer_and_keyboard_states(
    remote_layout, qt_application, theme,
):
    _panel, remote, _scroll, content, _settings = remote_layout
    BaseStyles.switch_theme(theme)
    for name in _TOGGLES:
        button = getattr(remote, name)
        button.setChecked(False)
        button.clearFocus()
        QTest.mouseMove(content, QPoint(0, 0))
        wait_for_stable_geometry(qt_application, button)
        original_hint = button.minimumSizeHint()
        _assert_no_rectangular_border(button)
        button.setFocus(Qt.FocusReason.TabFocusReason)
        assert button.hasFocus()
        _assert_no_rectangular_border(button)
        assert button.minimumSizeHint() == original_hint
        QTest.keyClick(button, Qt.Key.Key_Space)
        assert button.isChecked()
        QTest.mouseMove(button, button.rect().center())
        image = _assert_no_rectangular_border(button)
        assert _pixel(image, button.width() // 2, button.height() - 1).name() == themeColor().name()
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        _assert_no_rectangular_border(button)
        assert button.minimumSizeHint() == original_hint
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        assert not button.isChecked()
        button.setEnabled(False)
        _assert_no_rectangular_border(button)
        button.setEnabled(True)


@pytest.mark.parametrize("font_size", (12, 22))
def test_switch_clicks_preserve_every_row_geometry_and_unclipped_text(
    remote_layout, qt_application, font_size,
):
    _panel, remote, _scroll, content, _settings = remote_layout
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
    for column in (switches[::2], switches[1::2]):
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


def test_remote_action_focus_keeps_transparent_frame_and_content_metrics(
    remote_layout, qt_application,
):
    _panel, remote, _scroll, content, _settings = remote_layout
    remote.set_target_devices(["synthetic-device"])
    for button in (remote.btn_start, remote.btn_stop, *remote._remote_control_buttons):
        button.setEnabled(True)
        button.clearFocus()
        QTest.mouseMove(content, QPoint(0, 0))
        wait_for_stable_geometry(qt_application, button)
        original_hint = button.minimumSizeHint()
        idle = _assert_no_rectangular_border(button)
        button.setFocus(Qt.FocusReason.TabFocusReason)
        assert button.hasFocus()
        focused = _assert_no_rectangular_border(button)
        assert button.minimumSizeHint() == original_hint
        assert focused != idle, "键盘焦点必须具有可见反馈"
