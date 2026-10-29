"""用真实主窗与字体通知观察 Intent 高级参数显隐的中间绘制。"""

from dataclasses import replace

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.test_global_device_context import frame  # noqa: F401
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def _geometry_in(widget, owner):
    point = widget.mapTo(owner, QPoint())
    return point.x(), point.y(), widget.width(), widget.height()


class _PaintGeometry(QObject):
    def __init__(self, owner, widgets):
        super().__init__(owner)
        self.owner = owner
        self.frames = {widget: [] for widget in widgets}
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.frames[watched].append(_geometry_in(watched, self.owner))
        return False


@pytest.mark.parametrize("font_size,width", [(12, 1120), (22, 860)])
def test_intent_advanced_keeps_leading_fields_fixed_in_mainframe_paints(
    request, qt_application, font_size, width,
):
    window = request.getfixturevalue("frame")
    window.show()
    assert window._open_workspace_feature("system", "overview")
    coordinator = window.left_panel._responsive_coordinator
    wait_until(qt_application, lambda: (
        window._page_transition.animation.state() == QAbstractAnimation.State.Stopped
        and coordinator.diagnostics.stable
    ))
    window.resize(width, 900)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    panel = window.left_panel.system_panel
    form = panel.intent_controls
    form.data_uri.setText("demo://stable/draft")
    form.flags.setText("0x10000000")
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    card = next(
        card for card in panel._system_section_groups
        if card.headerLabel.text() == "广播与 Intent"
    )
    scroll = window._workspace_feature_hosts["system"].overview.body
    scroll.ensureWidgetVisible(form.advanced_toggle, 0, 80)
    QTest.qWait(40)
    wait_until(qt_application, lambda: coordinator.diagnostics.stable)
    widgets = [form.activity_mode, panel.activity_spec, panel.btn_start_activity]
    before = {widget: _geometry_in(widget, card) for widget in widgets}
    assert all(widget.font().pointSize() == font_size for widget in widgets)
    assert all(widget.isVisibleTo(window) for widget in widgets)
    observer = _PaintGeometry(card, widgets)
    for expanded in (True, False, True, False):
        for positions in observer.frames.values():
            positions.clear()
        QTest.mouseClick(form.advanced_toggle, Qt.MouseButton.LeftButton)
        QTest.qWait(60)
        wait_until(qt_application, lambda: (
            coordinator.diagnostics.stable
            and form.advanced_reveal.animation.state() == QAbstractAnimation.State.Stopped
        ))
        assert form.advanced.isVisibleTo(card) is expanded
        assert form.data_uri.text() == "demo://stable/draft"
        assert form.flags.text() == "0x10000000"
        for widget, positions in observer.frames.items():
            context = (expanded, widget, before[widget], positions)
            assert positions, context
            assert set(positions) == {before[widget]}, context
            assert _geometry_in(widget, card) == before[widget]
