"""在真实主窗口覆盖全部既有设备入口的绘制位置和切页清理。"""

from dataclasses import replace

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.test_global_device_context import _ClosableSessionPage, frame  # noqa: F401
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui

_SELECTOR_ROUTES = (
    ("devices", "files"), ("devices", "remote"), ("apps", "manager"),
    ("apps", "overview"), ("apps", "media"), ("system", "overview"),
    ("system", "logcat"), ("system", "performance"),
)
_FIELD_NAMES = ("brand_label", "name_label", "version_label", "connection_label")


def _rect_in(widget, ancestor):
    point = widget.mapTo(ancestor, QPoint())
    return point.x(), point.y(), widget.width(), widget.height()


def _settle(window, application):
    bar = window._global_device_bar
    wait_until(application, lambda: (
        bar._selector_animation.state() == QAbstractAnimation.State.Stopped
        and not bar._selector_transition_active
        and window.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
        and window.navigationInterface.panel.expandAni.state() == QAbstractAnimation.State.Stopped
        and window.left_panel._responsive_coordinator.diagnostics.stable
    ))
    QTest.qWait(20)


class _PaintPositions(QObject):
    def __init__(self, window, widgets):
        super().__init__(window)
        self.window = window
        self.positions = {widget: [] for widget in widgets}
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.positions[watched].append(_rect_in(watched, self.window))
        return False

    def detach(self):
        for widget in self.positions:
            widget.removeEventFilter(self)


@pytest.fixture
def page_frame(request, qt_application):
    window = request.getfixturevalue("frame")
    # 只替换需要外部资源的会话工厂，页面路由、布局、选择器和批量面板保持真实实现。
    for section, feature in _SELECTOR_ROUTES:
        host = window._workspace_feature_hosts[section]
        if feature in host._definitions:
            host._definitions[feature] = replace(
                host._definitions[feature], factory=_ClosableSessionPage,
            )
    window._on_devices_updated(["demo-usb", "emulator-5554"])
    for device, metadata in (
        ("demo-usb", {"Brand": "vivo", "Model": "V2458A", "Aversion": "16"}),
        ("emulator-5554", {"Brand": "Redmi", "Model": "23113RKC6C", "Aversion": "15"}),
    ):
        window._on_device_info_updated(device, metadata)
    window.left_panel.set_selected_devices(["demo-usb"])
    window.show()
    _settle(window, qt_application)
    return window


@pytest.mark.parametrize("theme,mica,font_size,width", [
    ("Light", False, 12, 1120), ("Dark", True, 22, 860),
])
def test_all_existing_selectors_keep_text_fixed_in_actual_paints(
    page_frame, qt_application, theme, mica, font_size, width,
):
    """跨路由复用选择器时，每个展开和收起帧只能裁切，不能重排可见字段。"""
    window = page_frame
    # 在真实窗口首显后改变字号和宽度，覆盖导航及最小尺寸协调完成后的实际几何。
    window.resize(width, 900)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    BaseStyles.switch_theme(theme)
    window.setMicaEffectEnabled(mica)
    _settle(window, qt_application)
    original_mica = window.isMicaEffectEnabled()
    bar = window._global_device_bar
    picker_identity = None
    for section, feature in _SELECTOR_ROUTES:
        assert window._open_workspace_feature(section, feature, device_id="demo-usb")
        _settle(window, qt_application)
        assert bar.isVisibleTo(window)
        QTest.mouseClick(bar.targets_button, Qt.MouseButton.LeftButton)
        assert bar._selector_animation.state() == QAbstractAnimation.State.Running
        picker = bar._picker
        if picker_identity is None:
            picker_identity = picker
        assert picker is picker_identity
        first_row = next(iter(picker._rows.values()))
        widgets = [picker.summary_label, picker.clear_button]
        widgets.extend(getattr(first_row, name) for name in _FIELD_NAMES)
        observer = _PaintPositions(window, widgets)
        try:
            for opening in (True, False):
                if not opening:
                    for positions in observer.positions.values():
                        positions.clear()
                    QTest.mouseClick(bar.targets_button, Qt.MouseButton.LeftButton)
                _settle(window, qt_application)
                for widget, positions in observer.positions.items():
                    context = (section, feature, opening, widget.text(), positions)
                    assert len(positions) >= 2, context
                    assert set(positions) == {_rect_in(widget, window)}, context
                    assert widget.font().pointSize() == font_size
                assert not bar.targets_button.property("keyboardFocus")
                assert not picker.content.autoFillBackground()
                assert not picker.scroll_area.viewport().autoFillBackground()
                assert window.isMicaEffectEnabled() == original_mica
        finally:
            observer.detach()
        assert not bar.is_selector_expanded


def test_every_selector_releases_its_transition_when_leaving_the_page(
    page_frame, qt_application,
):
    """切页可以改变正文高度，但不能留下选择区、旧动画帧或未释放的响应式暂停。"""
    window = page_frame
    bar = window._global_device_bar
    destinations = ("home", "devices", "tasks", "settings")
    for index, (section, feature) in enumerate(_SELECTOR_ROUTES):
        assert window._open_workspace_feature(section, feature, device_id="demo-usb")
        _settle(window, qt_application)
        bar.open_picker()
        animation = bar._selector_animation
        animation.pause()
        animation.setCurrentTime(round(animation.duration() * .45))
        assert bar._selector_transition_active
        destination = destinations[index % len(destinations)]
        window._on_nav_requested(destination)
        _settle(window, qt_application)
        assert bar.isHidden()
        assert not bar.is_selector_expanded
        assert not bar._selector_transition_active
        assert not window.left_panel._responsive_coordinator._geometry_transition_active
        assert animation.state() == QAbstractAnimation.State.Stopped
        target = window.stackedWidget.currentWidget()
        animation.setCurrentTime(animation.duration())
        QTest.qWait(30)
        assert window.stackedWidget.currentWidget() is target
        assert bar.isHidden() and not bar.is_selector_expanded
        assert window.left_panel._responsive_coordinator.diagnostics.stable
