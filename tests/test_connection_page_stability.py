"""连接方式切换的自然高度、真实绘制位置和展开收起交叉行为。"""

from contextlib import contextmanager
from dataclasses import replace

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, QPoint, Qt
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from gui.i18n import install_translators
from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from gui.widgets.device_connection import DeviceConnectionPanel
from tests.test_device_connection import PairingDouble
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@contextmanager
def _connection(app, width, font_size, language="zh_CN"):
    translators = install_translators(app, language)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    host = QWidget()
    host.resize(width + 24, 1400)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(0)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    pairing = PairingDouble()
    panel = DeviceConnectionPanel(pairing, parent=host, animated=True)
    layout.addWidget(panel)
    body = QPushButton("设备列表", host)
    layout.addWidget(body)
    layout.addStretch(1)
    host.show()
    app.processEvents()
    panel.expand()
    try:
        yield panel, pairing, body
    finally:
        panel.prepare_shutdown()
        pairing.busy = False
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for translator in reversed(translators):
            app.removeTranslator(translator)
            translator.deleteLater()


def _settle(app, panel):
    wait_until(app, lambda: not panel._transition_active and not panel._reflow_pending)
    for _ in range(3):
        app.processEvents()


def _advance(app, panel, fraction):
    animation = panel._reveal_animation
    if animation.state() == QAbstractAnimation.State.Running:
        animation.pause()
    animation.setCurrentTime(round(animation.duration() * fraction))
    for _ in range(3):
        app.processEvents()


def _primary(panel, page):
    return {
        "qr": panel.qr_text_layout.itemAt(0).widget(),
        "manual": panel.pairing_address,
        "address": panel.address_form.address,
    }[page]


class _PagePaintProbe(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.records = []
        self.widgets = {page: _primary(panel, page) for page in panel.PAGES}
        for widget in self.widgets.values():
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            page = self.panel.current_page
            if watched is self.widgets[page]:
                origin = watched.mapTo(self.panel, QPoint())
                self.records.append((
                    page, (origin.x(), origin.y(), watched.width(), watched.height()),
                    self.panel.height(), self.panel._natural_height,
                ))
        return False


@pytest.mark.parametrize(
    "width,font_size,language",
    [(748, 12, "zh_CN"), (748, 22, "zh_CN"), (568, 22, "en_US"), (336, 22, "zh_CN")],
)
def test_cancelled_page_roundtrip_keeps_equal_height_and_first_paint_geometry(
    qt_application, width, font_size, language,
):
    with _connection(qt_application, width, font_size, language) as (panel, pairing, body):
        _settle(qt_application, panel)
        probe = _PagePaintProbe(panel)
        baseline = panel.height()
        results = [("qr", panel.height(), body.y())]
        geometries = {}
        for page in ("manual", "address", "qr", "manual", "address", "qr"):
            probe.records.clear()
            panel.request_page(page)
            if panel._pending_page is not None:
                pairing.finish("Idle", "cancelled")
            _settle(qt_application, panel)
            assert panel.current_page == page
            current = _primary(panel, page)
            current.update()
            qt_application.processEvents()
            paints = [record[1] for record in probe.records if record[0] == page]
            assert paints and len(set(paints)) == 1, (page, probe.records)
            if page in geometries:
                assert paints[-1] == geometries[page], (page, paints[-1], geometries[page])
            geometries[page] = paints[-1]
            results.append((page, panel.height(), body.y()))
        assert all(height == baseline for _, height, _ in results), results


@pytest.mark.parametrize("width,font_size", [(748, 12), (568, 22)])
def test_failed_qr_to_other_pages_has_stable_entry_and_return_geometry(
    qt_application, width, font_size,
):
    with _connection(qt_application, width, font_size) as (panel, pairing, _body):
        _settle(qt_application, panel)
        pairing.finish("Failed", "mdns_unrecognized")
        _settle(qt_application, panel)
        probe = _PagePaintProbe(panel)
        visits = []
        for page in ("manual", "address", "manual", "address"):
            probe.records.clear()
            panel.request_page(page)
            _settle(qt_application, panel)
            _primary(panel, page).update()
            qt_application.processEvents()
            paints = [record[1] for record in probe.records if record[0] == page]
            assert paints and len(set(paints)) == 1, (page, probe.records)
            visits.append((page, panel.height(), paints[-1]))
        assert visits[0] == visits[2] and visits[1] == visits[3], visits


@pytest.mark.parametrize("width,font_size", [(748, 12), (568, 22)])
def test_page_switch_during_reveal_keeps_text_fixed_until_reveal_finishes(
    qt_application, width, font_size,
):
    with _connection(qt_application, width, font_size) as (panel, pairing, _body):
        _advance(qt_application, panel, .25)
        probe = _PagePaintProbe(panel)
        panel.request_page("manual")
        assert panel.current_page == "qr"
        pairing.finish("Idle", "cancelled")
        for fraction in (.4, .6, .8, 1):
            _primary(panel, "manual").update()
            _advance(qt_application, panel, fraction)
        _settle(qt_application, panel)
        paints = [record[1] for record in probe.records if record[0] == "manual"]
        assert paints and len(set(paints)) == 1, probe.records
        assert panel.current_page == "manual" and panel.is_expanded
        assert pairing.calls.count(("qr",)) == 1


def test_collapse_during_pending_page_switch_prevents_late_page_and_animation_restart(
    qt_application,
):
    with _connection(qt_application, 568, 22) as (panel, pairing, _body):
        _advance(qt_application, panel, .4)
        panel.request_page("manual")
        panel.collapse()
        pairing.finish("Idle", "cancelled")
        _advance(qt_application, panel, 1)
        _settle(qt_application, panel)
        assert panel.current_page == "qr" and panel.isHidden() and not panel.is_expanded
        assert panel._pending_page is None and pairing.calls.count(("qr",)) == 1
