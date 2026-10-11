"""主窗口内切换连接方式应保持设备列表和首次绘制的表单位置。"""

from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.test_connection_expansion_integration import connection_frame as connection_frame
from tests.test_global_device_context import frame  # noqa: F401
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def _rect_in(widget, ancestor):
    point = widget.mapTo(ancestor, QPoint())
    return point.x(), point.y(), widget.width(), widget.height()


class _FormPaints(QObject):
    def __init__(self, panel, hub):
        super().__init__(panel)
        self.hub = hub
        self.widgets = {
            "qr": panel.qr_text_layout.itemAt(0).widget(),
            "manual": panel.pairing_address,
            "address": panel.address_form.address,
        }
        self.frames = {page: [] for page in self.widgets}
        for widget in self.widgets.values():
            widget.installEventFilter(self)

    def eventFilter(self, widget, event):
        if event.type() == QEvent.Type.Paint:
            for page, target in self.widgets.items():
                if widget is target:
                    self.frames[page].append(_rect_in(widget, self.hub))
                    break
        return False


def _settle(window, application):
    panel = window._connection_panel
    wait_until(application, lambda: (
        not panel._transition_active and not panel._reflow_pending
        and window.left_panel._responsive_coordinator.diagnostics.stable
    ))
    QTest.qWait(30)


@pytest.mark.parametrize("width,font_size,theme", [
    (1120, 12, "Light"), (860, 12, "Dark"), (860, 22, "Light"),
])
def test_real_tab_clicks_keep_form_height_and_device_list_position(
    connection_frame, qt_application, width, font_size, theme,
):
    window = connection_frame
    BaseStyles.switch_theme(theme)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    window.resize(width, 900)
    wait_until(qt_application, lambda: window.left_panel._responsive_coordinator.diagnostics.stable)
    QTest.qWait(30)
    assert window.width() == width
    hub = window._device_hub
    hub.connect_button.click()
    panel = window._connection_panel
    pairing = window._adb_pairing
    _settle(window, qt_application)
    baseline = (panel.height(), hub.cards_container.y(), _rect_in(panel.navigation, hub))
    painted = _FormPaints(panel, hub)
    visits = []
    for page in ("manual", "address", "qr", "manual", "address", "qr"):
        painted.frames[page].clear()
        item = panel.navigation.pivot.widget(f"connection:{page}")
        assert item.isVisibleTo(window) and item.isEnabled()
        QTest.mouseClick(item, Qt.MouseButton.LeftButton)
        if panel._pending_page is not None:
            assert not panel.navigation.isEnabled()
            pairing.finish("Idle", "cancelled")
        _settle(window, qt_application)
        assert panel.current_page == page
        assert panel.navigation._current_key == page
        primary = painted.widgets[page]
        primary.update()
        qt_application.processEvents()
        frames = painted.frames[page]
        assert frames and set(frames) == {_rect_in(primary, hub)}, (page, frames)
        actual = (panel.height(), hub.cards_container.y(), _rect_in(panel.navigation, hub))
        visits.append((page, actual))
    assert all(actual == baseline for _, actual in visits), (baseline, visits)
    hub.connect_button.click()
    _settle(window, qt_application)
    assert panel.isHidden() and panel.height() == 0
    assert not window._connection_transition_active
