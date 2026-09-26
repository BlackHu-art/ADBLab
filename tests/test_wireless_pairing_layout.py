"""真实控件在多语言、主题和大字体下保持二维码及连接操作可达。"""

import io
import os
from dataclasses import replace
from pathlib import Path

import pytest
import segno
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFontMetricsF
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import SmoothScrollArea

from gui.i18n import install_translators, tr
from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from gui.widgets.device_connection import DeviceConnectionPanel
from tests.test_device_connection import PairingDouble, qr_png
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


@pytest.fixture
def history_panel(qt_application):
    pairing = PairingDouble()
    host = SmoothScrollArea()
    host.setWidgetResizable(True)
    host.resize(960, 800)
    content = QWidget()
    layout = QVBoxLayout(content)
    panel = DeviceConnectionPanel(pairing, parent=content)
    layout.addWidget(panel)
    layout.addStretch()
    host.setWidget(content)
    host.show()
    history = [
        (f"QA phone {index} · 192.0.2.{index}:5555", f"192.0.2.{index}:5555")
        for index in range(1, 11)
    ]
    panel.expand(history)
    panel.request_page("address")
    pairing.finish("Idle", "")
    wait_until(qt_application, lambda: panel.current_page == "address")
    for _ in range(8):
        qt_application.processEvents()
    try:
        yield panel, pairing, history
    finally:
        pairing.busy = False
        panel.close()
        host.close()
        host.deleteLater()


def test_connection_history_displays_each_address_once_on_one_line(history_panel):
    panel, _pairing, history = history_panel
    row = panel.address_form.history_rows[0]
    assert row.isVisible()
    labels = [label for label in row.findChildren(QLabel) if label.isVisible()]
    displayed_text = " ".join([row.text(), *(label.text() for label in labels)])
    assert displayed_text.count(history[0][1]) == 1
    assert "QA phone 1" in displayed_text
    assert "\n" not in displayed_text
    if labels:
        centers = [label.mapTo(row, label.rect().center()).y() for label in labels]
        assert max(centers) - min(centers) <= 1


def test_connection_history_starts_at_top_and_last_row_can_be_filled(
    history_panel, qt_application
):
    panel, pairing, history = history_panel
    form = panel.address_form
    viewport = form.history_scroll.viewport()
    assert form.history_box.mapTo(form, QPoint()).y() <= 1
    assert form.history_box.rect().contains(form.history_scroll.geometry())
    for row in form.history_rows[:4]:
        assert viewport.rect().contains(QRect(row.mapTo(viewport, QPoint()), row.size()))
        assert form.rect().contains(QRect(row.mapTo(form, QPoint()), row.size()))

    bar = form.history_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    qt_application.processEvents()
    last_row = form.history_rows[-1]
    assert viewport.rect().contains(QRect(last_row.mapTo(viewport, QPoint()), last_row.size()))
    submitted = QSignalSpy(panel.connect_requested)
    calls_before = list(pairing.calls)
    QTest.mouseClick(last_row, Qt.MouseButton.LeftButton, pos=last_row.rect().center())
    assert form.address.text() == history[-1][1]
    assert form.address.hasFocus()
    assert submitted.count() == 0
    assert pairing.calls == calls_before
    assert panel.is_expanded


@pytest.mark.parametrize("width", [748, 900])
def test_wide_qr_page_places_actions_after_code_and_keeps_tabs_compact(
    qt_application, monkeypatch, width,
):
    config = replace(BaseStyles.current_font_config(), ui_size=12)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    pairing = PairingDouble()
    panel = DeviceConnectionPanel(pairing)
    painted_icons = []
    draw_icon = panel.refresh_button._drawIcon

    def record_icon(icon, painter, rect, *args):
        painted_icons.append(rect.toRect())
        return draw_icon(icon, painter, rect, *args)

    monkeypatch.setattr(panel.refresh_button, "_drawIcon", record_icon)
    panel.resize(width, 300)
    panel.expand([("QA phone", "192.0.2.1:5555")])
    qr = segno.make_qr("WIFI:T:ADB;S:studio-00000000000000000000;P:XXXXXXXXXXXXXXXXXXXXXXXX;;")
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=6, border=4)
    modules = qr.symbol_size(scale=1, border=4)[0]
    pairing.qr_ready.emit(1, buffer.getvalue(), modules)
    pairing.publish("WaitingForScan", remaining=120)
    try:
        wait_until(qt_application, lambda: ("ack", 1) in pairing.calls)
        for _ in range(8):
            qt_application.processEvents()
        code = QRect(panel.qr_label.mapTo(panel, QPoint()), panel.qr_label.size())
        refresh = QRect(panel.refresh_button.mapTo(panel, QPoint()), panel.refresh_button.size())
        stop = QRect(panel.cancel_button.mapTo(panel, QPoint()), panel.cancel_button.size())
        assert panel.qr_text.mapTo(panel, QPoint(panel.qr_text.width(), 0)).x() <= code.left()
        assert code.right() < refresh.left() < stop.left()
        assert abs(refresh.bottom() - stop.bottom()) <= 1
        alternative = QRect(panel.code_button.mapTo(panel, QPoint()), panel.code_button.size())
        assert abs(alternative.bottom() - refresh.bottom()) <= 1
        assert refresh.bottom() <= code.bottom()
        assert panel.status_label.alignment() & Qt.AlignmentFlag.AlignLeft
        panel.refresh_button.grab()
        icon_left = refresh.left() + painted_icons[-1].left()
        status_left = panel.status_label.mapTo(panel, QPoint()).x()
        assert abs(status_left - icon_left) <= 1
        text_end = status_left + QFontMetricsF(
            panel.status_label.font(), panel.status_label,
        ).horizontalAdvance(panel.status_label.text())
        countdown_left = panel.countdown_label.mapTo(panel, QPoint()).x()
        assert 8 <= countdown_left - text_end <= 12
        assert panel.countdown_label.alignment() & Qt.AlignmentFlag.AlignLeft
        assert panel.height() <= 250
        pixmap = panel.qr_label.pixmap()
        assert pixmap.width() % modules == 0
        assert pixmap.width() / pixmap.devicePixelRatioF() >= 164
        height = panel.height()
        pairing.finish("Idle", "")
        for page in ("manual", "address"):
            panel.request_page(page)
            for _ in range(8):
                qt_application.processEvents()
            assert panel.height() == height
    finally:
        panel.prepare_shutdown()
        panel.close()
        panel.deleteLater()


def test_qr_feedback_uses_full_width_and_retry_restores_compact_actions(qt_application):
    config = replace(BaseStyles.current_font_config(), ui_size=12)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    pairing = PairingDouble()
    panel = DeviceConnectionPanel(pairing)
    panel.resize(900, 300)
    panel.expand([("QA phone", "192.0.2.1:5555")])

    def settle():
        for _ in range(8):
            qt_application.processEvents()

    try:
        pairing.finish("Failed", "mdns_unavailable")
        settle()
        assert panel.status_box.width() == panel.qr_page.width()
        code_bottom = panel.qr_label.mapTo(panel, panel.qr_label.rect().bottomLeft()).y()
        assert panel.status_box.mapTo(panel, QPoint()).y() > code_bottom
        assert panel.status_detail.isVisible()
        assert panel.rect().contains(
            QRect(panel.status_detail.mapTo(panel, QPoint()), panel.status_detail.size())
        )

        pairing.continuation = object()
        pairing.finish("PairedOnly", "connection_timeout")
        panel.connection_address.setText("192.0.2.1:45111")
        settle()
        assert panel.status_box.width() == panel.qr_page.width()
        assert panel.continue_button.isEnabled()
        for widget in (panel.connection_address, panel.continue_button, panel.use_address_button):
            assert panel.rect().contains(QRect(widget.mapTo(panel, QPoint()), widget.size()))

        panel.refresh_button.click()
        settle()
        assert panel.height() <= 250
        code_right = panel.qr_label.mapTo(panel, panel.qr_label.rect().topRight()).x()
        assert panel.refresh_button.mapTo(panel, QPoint()).x() > code_right
        for width in (600, 360, 900):
            panel.resize(width, panel.height())
            settle()
            for widget in (
                panel.qr_label, panel.status_label, panel.refresh_button, panel.cancel_button,
            ):
                assert panel.rect().contains(QRect(widget.mapTo(panel, QPoint()), widget.size()))
        assert panel.height() <= 250
        code_right = panel.qr_label.mapTo(panel, panel.qr_label.rect().topRight()).x()
        assert panel.refresh_button.mapTo(panel, QPoint()).x() > code_right
    finally:
        panel.prepare_shutdown()
        panel.close()
        panel.deleteLater()


@pytest.mark.parametrize(
    "language,width,font_size",
    [
        ("zh_CN", 748, 12), ("zh_CN", 600, 22), ("en_US", 900, 12),
        ("en_US", 600, 22), ("zh_HK", 360, 22),
    ],
)
def test_qr_action_positions_stay_fixed_through_refresh_and_countdown(
    qt_application, monkeypatch, language, width, font_size,
):
    translators = install_translators(qt_application, language)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    pairing = PairingDouble()
    panel = DeviceConnectionPanel(pairing)
    panel.resize(width, 300)
    panel.expand([("QA phone", "192.0.2.1:5555")])
    painted_icons = []
    draw_icon = panel.refresh_button._drawIcon

    def record_icon(icon, painter, rect, *args):
        painted_icons.append(rect.toRect())
        return draw_icon(icon, painter, rect, *args)

    monkeypatch.setattr(panel.refresh_button, "_drawIcon", record_icon)

    def actions():
        panel.refresh_button.grab()
        return (
            QRect(panel.refresh_slot.mapTo(panel, QPoint()), panel.refresh_slot.size()),
            QRect(panel.cancel_button.mapTo(panel, QPoint()), panel.cancel_button.size()),
            panel.refresh_button.mapTo(panel, painted_icons[-1].topLeft()),
        )

    try:
        for _ in range(8):
            qt_application.processEvents()
        initial_actions = actions()
        initial_height = panel.height()

        def assert_stable():
            for _ in range(8):
                qt_application.processEvents()
                assert actions() == initial_actions
                assert panel.height() == initial_height
                icon_left = panel.refresh_button.mapTo(panel, painted_icons[-1].topLeft()).x()
                status_left = panel.status_label.mapTo(panel, QPoint()).x()
                assert abs(status_left - icon_left) <= 1

        for request_id in (1, 2):
            pairing.qr_ready.emit(request_id, qr_png(), 29)
            wait_until(qt_application, lambda: ("ack", request_id) in pairing.calls)
            for remaining in (120, 119, 60, 59, 9, 1):
                pairing.publish("WaitingForScan", remaining=remaining)
                assert_stable()
            if request_id == 1:
                QTest.mouseClick(panel.refresh_button, Qt.MouseButton.LeftButton)
                assert pairing.calls[-1] == ("cancel",)
                assert not panel.refresh_button.isEnabled()
                assert_stable()
                pairing.finish("Idle", "cancelled")
                assert pairing.calls[-1] == ("qr",)
                assert_stable()
        pairing.finish("Failed", "scan_timeout")
        assert_stable()
        assert panel.cancel_button.isHidden()
        assert panel.refresh_button.isEnabled()
    finally:
        panel.prepare_shutdown()
        panel.close()
        panel.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()


@pytest.mark.parametrize("expiry_source", ["countdown", "worker"])
@pytest.mark.parametrize(
    "language,width,font_size",
    [("zh_CN", 900, 12), ("en_US", 900, 12), ("en_US", 600, 22), ("zh_HK", 360, 22)],
)
def test_expired_qr_keeps_layout_and_waits_for_explicit_regeneration(
    qt_application, expiry_source, language, width, font_size,
):
    translators = install_translators(qt_application, language)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    pairing = PairingDouble()
    panel = DeviceConnectionPanel(pairing)
    panel.resize(width, 300)
    panel.expand([("QA phone", "192.0.2.1:5555")])
    pairing.qr_ready.emit(1, qr_png(), 29)
    pairing.publish("WaitingForScan", remaining=120)

    def settle():
        for _ in range(8):
            qt_application.processEvents()

    try:
        wait_until(qt_application, lambda: ("ack", 1) in pairing.calls)
        settle()
        initial_height = panel.height()
        code_rect = panel.qr_label.geometry()
        refresh_origin = panel.refresh_button.mapTo(panel, QPoint())
        if expiry_source == "countdown":
            panel._scan_deadline = 0
            panel._tick()
        else:
            pairing.finish("Failed", "scan_timeout")
        settle()
        assert panel.qr_label.accessibleName() == tr("二维码已过期")
        assert panel.qr_placeholder.isVisible()
        assert panel.qr_label.rect().contains(panel.qr_placeholder.geometry())
        assert panel.qr_label.pixmap().isNull()
        assert not panel._countdown.isActive()
        assert panel.countdown_label.isHidden()
        assert panel.cancel_button.isHidden()
        assert panel.refresh_button.text() == tr("重新生成")
        assert panel.status_label.text() == tr("等待重新生成")
        assert panel.status_detail.isHidden()
        assert panel.height() == initial_height
        assert panel.qr_label.geometry() == code_rect
        if width == 900:
            assert panel.refresh_button.mapTo(panel, QPoint()).y() == refresh_origin.y()
        assert pairing.calls.count(("qr",)) == 1

        pairing.qr_ready.emit(1, qr_png(), 29)
        settle()
        assert panel.qr_label.pixmap().isNull()
        panel.refresh_button.click()
        if expiry_source == "countdown":
            assert pairing.calls.count(("qr",)) == 1
            assert not panel.refresh_button.isEnabled()
            panel.refresh_button.click()
            pairing.finish("Idle", "cancelled")
        settle()
        assert pairing.calls.count(("qr",)) == 2
        pairing.qr_ready.emit(2, qr_png(), 29)
        pairing.publish("WaitingForScan", remaining=120)
        wait_until(qt_application, lambda: ("ack", 2) in pairing.calls)
        settle()
        assert not panel.qr_label.pixmap().isNull()
        assert panel.qr_label.accessibleName() == tr("无线调试配对二维码")
        assert panel.qr_placeholder.isHidden()
        assert panel.height() == initial_height
    finally:
        panel.prepare_shutdown()
        panel.close()
        panel.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()


@pytest.mark.parametrize(
    "width,language,font_size",
    [
        (800, "zh_CN", 12),
        (600, "zh_CN", 12),
        (440, "zh_CN", 12),
        (800, "en_US", 22),
        (600, "en_US", 22),
        (440, "zh_HK", 22),
    ],
)
def test_inline_tabs_share_natural_height_and_reflow_fields(
    qt_application,
    width,
    language,
    font_size,
):
    translators = install_translators(qt_application, language)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    pairing = PairingDouble()
    host = SmoothScrollArea()
    host.setWidgetResizable(True)
    host.resize(width + 26, 800)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(12, 12, 12, 12)
    panel = DeviceConnectionPanel(pairing, parent=content)
    layout.addWidget(panel)
    layout.addStretch()
    host.setWidget(content)
    host.show()
    panel.expand([("First phone", "192.0.2.1:5555"), ("Second phone", "192.0.2.2:5555")])

    def settle():
        for _ in range(8):
            qt_application.processEvents()

    try:
        pairing.qr_ready.emit(1, qr_png(), 29)
        pairing.publish("WaitingForScan", remaining=120)
        settle()
        assert panel.width() == width
        content_width = panel.stack.currentWidget().width()
        qr_height = panel.height()
        if content_width > 440:
            assert panel.qr_label.mapTo(panel, QPoint()).x() > panel.qr_text.x()
        else:
            assert (
                panel.qr_label.mapTo(panel, QPoint()).y() < panel.qr_text.mapTo(panel, QPoint()).y()
            )
        panel.request_page("manual")
        pairing.finish("Idle", "")
        settle()
        assert panel.height() == qr_height
        if content_width > 580 and font_size == 12:
            assert (
                abs(
                    panel.pairing_address.mapTo(panel, QPoint()).y()
                    - panel.pairing_code.mapTo(panel, QPoint()).y()
                )
                <= 1
            )
            assert (
                abs(
                    panel.pair_button.mapTo(panel, QPoint()).y()
                    - panel.pairing_code.mapTo(panel, QPoint()).y()
                )
                <= 1
            )
        elif content_width > 440 and font_size == 12:
            assert (
                abs(
                    panel.pairing_address.mapTo(panel, QPoint()).y()
                    - panel.pairing_code.mapTo(panel, QPoint()).y()
                ) <= 1
            )
            assert (
                panel.pair_button.mapTo(panel, QPoint()).y()
                > panel.pairing_code.mapTo(panel, QPoint()).y()
            )
        if content_width <= 440:
            assert (
                panel.pairing_code.mapTo(panel, QPoint()).y()
                > panel.pairing_address.mapTo(panel, QPoint()).y()
            )
        panel.request_page("address")
        settle()
        assert panel.height() == qr_height
        if content_width > 580:
            assert panel.address_form.history_box.x() > panel.address_form.address.x()
        else:
            assert (
                panel.address_form.history_box.mapTo(panel, QPoint()).y()
                > panel.address_form.address.mapTo(panel, QPoint()).y()
            )
        if width == 800 and font_size == 12:
            assert qr_height < 350
        panel.request_page("qr")
        pairing.qr_ready.emit(2, qr_png(), 29)
        pairing.publish("WaitingForScan", remaining=120)
        settle()
        assert panel.height() == qr_height
    finally:
        panel.collapse()
        host.close()
        host.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()


@pytest.mark.parametrize(
    "language,theme,font_size,width,height",
    [
        ("zh_CN", "light", 12, 800, 680),
        ("zh_CN", "dark", 22, 360, 680),
        ("zh_HK", "dark", 12, 800, 680),
        ("zh_HK", "light", 22, 360, 680),
        ("en_US", "light", 12, 800, 680),
        ("en_US", "dark", 22, 360, 680),
        ("en_US", "light", 12, 360, 400),
    ],
)
def test_pairing_forms_and_qr_remain_reachable(
    qt_application,
    language,
    theme,
    font_size,
    width,
    height,
):
    translators = install_translators(qt_application, language)
    config = replace(BaseStyles.current_font_config(), ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    BaseStyles.switch_theme(theme.title())
    pairing = PairingDouble()
    host = SmoothScrollArea()
    host.setWidgetResizable(True)
    host.resize(width, height)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(12, 12, 12, 12)
    window = DeviceConnectionPanel(pairing, parent=content)
    layout.addWidget(window)
    layout.addStretch()
    host.setWidget(content)
    host.show()
    window.expand([("QA device", "192.0.2.1:5555")])

    def settle():
        for _ in range(8):
            qt_application.processEvents()

    def reachable(widget):
        settle()
        viewport = window.scroll_area.viewport()
        bar = window.scroll_area.verticalScrollBar()
        offset = widget.mapTo(viewport, QPoint(0, 0)).y()
        bar.setValue(bar.value() + offset - max(0, (viewport.height() - widget.height()) // 2))
        settle()
        origin = widget.mapTo(viewport, QPoint(0, 0))
        assert origin.x() >= 0
        assert origin.x() + widget.width() <= viewport.width()
        assert origin.y() >= 0
        assert origin.y() + widget.height() <= viewport.height()
        assert widget.height() >= widget.fontMetrics().height()

    def snapshot(page):
        destination = os.environ.get("ADBLAB_QA_OUTPUT")
        if destination:
            # 截图等待导航指示条的短动画完成；测试断言仍以实际几何为准。
            QTest.qWait(250)
            directory = Path(destination)
            directory.mkdir(parents=True, exist_ok=True)
            filename = f"{language}-{theme}-{font_size}-{width}-{height}-{page}.png"
            assert host.grab().save(str(directory / filename))

    try:
        settle()
        assert window.width() <= width

        qr = segno.make_qr("WIFI:T:ADB;S:studio-00000000000000000000;P:XXXXXXXXXXXXXXXXXXXXXXXX;;")
        buffer = io.BytesIO()
        qr.save(buffer, kind="png", scale=6, border=4)
        modules = qr.symbol_size(scale=1, border=4)[0]
        pairing.qr_ready.emit(1, buffer.getvalue(), modules)
        wait_until(qt_application, lambda: ("ack", 1) in pairing.calls)
        pairing.publish("WaitingForScan", remaining=120)
        settle()
        pixmap = window.qr_label.pixmap()
        assert pixmap.width() % modules == 0
        assert pixmap.width() == pixmap.height()
        assert pixmap.toImage().pixelColor(0, 0).name() == "#ffffff"
        # 显示确认发生时就必须可扫码，不能靠测试随后滚动掩盖过早启动倒计时。
        viewport = window.scroll_area.viewport()
        qr_top = window.qr_label.mapTo(viewport, QPoint(0, 0))
        qr_side = pixmap.width() / pixmap.devicePixelRatioF()
        image_top = qr_top.y() + (window.qr_label.height() - qr_side) / 2
        assert image_top >= 0
        assert image_top + qr_side <= viewport.height()
        snapshot("qr")
        pairing.finish("Failed", "scan_timeout")
        window.request_page("address")
        reachable(window.address_form.address)
        snapshot("address")
        window.request_page("manual")
        settle()
        reachable(window.pairing_address)
        reachable(window.pairing_code)
        snapshot("manual")
        pairing.continuation = object()
        pairing.finish("PairedOnly", "connection_timeout")
        window.connection_address.setText("192.0.2.1:45111")
        settle()
        assert window.continue_button.isEnabled()
        reachable(window.continue_button)
        snapshot("paired-only")
        assert not [
            widget
            for widget in window.findChildren(QWidget)
            if widget.isVisible()
            and widget.window() is host
            and widget.mapTo(window, QPoint(0, 0)).x() + widget.width() > window.width()
        ]
    finally:
        pairing.busy = False
        window.close()
        host.close()
        host.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()
