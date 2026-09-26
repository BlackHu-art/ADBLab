"""连接窗口的按需启动、资源屏障、秘密生命周期和键盘行为。"""

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, Signal
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from gui.widgets.device_connection import DeviceConnectionPanel
from services.adb_pairing import PairingProgress
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


def test_inline_panel_is_lazy_and_collapse_prevents_late_restart(qt_application):
    pairing = PairingDouble()
    host = QWidget()
    layout = QVBoxLayout(host)
    panel = DeviceConnectionPanel(pairing, parent=host)
    layout.addWidget(panel)
    host.show()
    qt_application.processEvents()
    assert not isinstance(panel, QDialog)
    assert not panel.is_expanded and panel.isHidden() and panel.height() == 0
    assert pairing.calls == []
    changes = QSignalSpy(panel.expanded_changed)
    panel.expand()
    assert panel.is_expanded and panel.current_page == "qr"
    assert pairing.calls.count(("qr",)) == 1
    panel.pairing_code.setText("123456")
    pairing.qr_ready.emit(1, qr_png(), 29)
    panel.refresh_qr()
    panel.collapse()
    assert panel.isHidden() and panel.height() == 0
    assert panel.pairing_code.text() == "" and panel.qr_label.pixmap().isNull()
    panel.expand()
    assert panel.is_expanded and not panel.navigation.isEnabled()
    pairing.finish()
    qt_application.processEvents()
    assert pairing.calls.count(("qr",)) == 1
    assert ("ack", 1) not in pairing.calls
    assert panel.navigation.isEnabled()
    panel.refresh_qr()
    assert pairing.calls.count(("qr",)) == 2
    assert [changes.at(i)[0] for i in range(changes.count())] == [True, False, True]
    panel.collapse()
    pairing.busy = False
    host.close()


def test_leaving_ancestor_clears_secrets_and_does_not_resume_on_return(qt_application):
    pairing = PairingDouble()
    host = QWidget()
    layout = QVBoxLayout(host)
    panel = DeviceConnectionPanel(pairing, parent=host)
    layout.addWidget(panel)
    host.show()
    assert not isinstance(panel, QDialog)
    panel.expand()
    panel.pairing_code.setText("123456")
    host.hide()
    assert not panel.is_expanded and panel.height() == 0
    assert panel.pairing_code.text() == "" and pairing.calls[-1] == ("cancel",)
    pairing.qr_ready.emit(1, qr_png(), 29)
    pairing.finish()
    host.show()
    qt_application.processEvents()
    assert not panel.isVisible() and pairing.calls.count(("qr",)) == 1
    assert ("ack", 1) not in pairing.calls
    host.close()


def test_reopen_projects_cleanup_failure_and_retry_without_starting(dialog):
    panel, pairing = dialog
    panel.refresh_qr()
    panel.collapse()
    pairing.publish("CleanupFailed", "cleanup_failed")
    before = pairing.calls.count(("qr",))
    panel.expand()
    assert "尚未结束" in panel.status_label.text()
    assert panel.retry_stop_button.isVisible()
    assert not panel.refresh_button.isEnabled()
    panel.retry_stop_button.click()
    assert pairing.calls[-1] == ("retry_stop",)
    assert pairing.calls.count(("qr",)) == before


def test_late_qr_is_rejected_after_reopening_while_stopping(dialog, qt_application):
    panel, pairing = dialog
    panel.refresh_qr()
    panel.collapse()
    panel.expand()
    pairing.qr_ready.emit(9, qr_png(), 29)
    qt_application.processEvents()
    assert panel.qr_label.pixmap().isNull()
    assert ("ack", 9) not in pairing.calls


def test_hidden_manual_submission_cannot_start_work(dialog):
    panel, pairing = dialog
    panel.request_page("manual")
    panel.collapse()
    before = list(pairing.calls)
    panel.pairing_address.setText("192.0.2.1:37123")
    panel.pairing_code.setText("123456")
    panel._submit_code()
    assert pairing.calls == before


class PairingDouble(QObject):
    progress = Signal(object)
    qr_ready = Signal(int, bytes, int)
    outcome_ready = Signal(object)
    busy_changed = Signal(bool)
    idle = Signal()
    continuation_changed = Signal()

    def __init__(self):
        super().__init__()
        self.busy = False
        self.state = "Idle"
        self.reason = ""
        self.continuation = None
        self.calls = []

    def publish(self, state, reason="", remaining=0):
        self.state, self.reason = state, reason
        self.progress.emit(PairingProgress(1, state, reason, remaining))

    def start_qr(self):
        self.calls.append(("qr",))
        self.busy = True
        self.publish("Checking")
        return True

    def start_code(self, endpoint, code):
        self.calls.append(("code", endpoint, code))
        self.busy = True
        self.publish("Pairing")
        return True

    def continue_connection(self, endpoint):
        self.calls.append(("continue", endpoint))
        self.busy = True
        self.publish("WaitingForConnection")
        return True

    def acknowledge_qr(self, request_id):
        self.calls.append(("ack", request_id))

    def cancel(self):
        self.calls.append(("cancel",))
        self.continuation = None
        self.continuation_changed.emit()
        self.publish("Stopping" if self.busy else "Idle", "cancelled")

    def finish(self, state="Idle", reason="cancelled"):
        self.busy = False
        self.publish(state, reason)
        self.busy_changed.emit(False)
        self.idle.emit()

    def retry_stop(self):
        self.calls.append(("retry_stop",))


@pytest.fixture
def dialog(qt_application):
    pairing = PairingDouble()
    window = DeviceConnectionPanel(pairing, [("测试设备", "192.0.2.1:5555")])
    window.resize(760, 500)
    window.expand([("测试设备", "192.0.2.1:5555")])
    pairing.finish("Idle", "")
    qt_application.processEvents()
    yield window, pairing
    pairing.busy = False
    window.close()
    qt_application.processEvents()


def qr_png():
    image = QImage(58, 58, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def test_valid_address_submits_once_and_collapses(dialog, qt_application):
    window, pairing = dialog
    window.request_page("address")
    assert window.current_page == "address"
    submitted = QSignalSpy(window.connect_requested)
    window.address_form.address.setText("invalid")
    window.address_form._connect()
    assert window.isVisible() and submitted.count() == 0
    window.address_form.address.setText("192.0.2.1:5555")
    window.address_form._connect()
    window.address_form._connect()
    assert submitted.count() == 1
    assert not window.isVisible()


def test_history_and_manual_secret_survive_only_as_intended(dialog):
    window, pairing = dialog
    window.request_page("address")
    submitted = QSignalSpy(window.connect_requested)
    window.address_form.history_rows[0].click()
    assert submitted.count() == 0
    window.request_page("manual")
    window.pairing_address.setText("192.0.2.1:37123")
    window.pairing_code.setText("012345")
    assert window.pair_button.isEnabled()
    window.pair_button.click()
    assert pairing.calls[-1] == ("code", "192.0.2.1:37123", "012345")
    assert window.pairing_code.text() == ""
    pairing.finish("Failed", "pair_failed")
    assert window.pairing_address.text() == "192.0.2.1:37123"
    window.request_page("address")
    assert window.address_form.address.text() == "192.0.2.1:5555"


def test_qr_requires_visible_image_ack_and_clears_at_pairing(dialog, qt_application):
    window, pairing = dialog
    window.refresh_qr()
    assert pairing.calls[-1] == ("qr",)
    assert window.qr_label.pixmap().isNull()
    pairing.qr_ready.emit(1, qr_png(), 29)
    wait_until(qt_application, lambda: ("ack", 1) in pairing.calls)
    assert not window.qr_label.pixmap().isNull()
    assert window.qr_label.pixmap().width() % 29 == 0
    pairing.publish("WaitingForScan", remaining=120)
    assert window._countdown.isActive()
    pairing.publish("Pairing")
    assert window.qr_label.pixmap().isNull()
    assert not window._countdown.isActive()
    assert not window.refresh_button.isEnabled()
    pairing.publish("WaitingForConnection")
    assert "已配对" in window.status_label.text()
    assert "设备已连接" != window.status_label.text()


def test_refresh_waits_for_idle_and_close_overrides_pending_refresh(dialog, qt_application):
    window, pairing = dialog
    window.request_page("qr")
    window.refresh_qr()
    window.refresh_qr()
    assert pairing.calls.count(("qr",)) == 2
    assert not window.navigation.isEnabled()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isVisible()
    pairing.finish()
    qt_application.processEvents()
    assert not window.isVisible()
    assert pairing.calls.count(("qr",)) == 2


def test_stop_keeps_action_visible_until_cleanup_then_shows_stopped_placeholder(
    dialog, qt_application,
):
    panel, pairing = dialog
    panel.refresh_qr()
    pairing.qr_ready.emit(1, qr_png(), 29)
    wait_until(qt_application, lambda: ("ack", 1) in pairing.calls)
    pairing.publish("WaitingForScan", remaining=120)
    panel.cancel_button.click()
    qt_application.processEvents()
    assert panel.qr_label.pixmap().isNull()
    assert not panel._countdown.isActive()
    assert panel.cancel_button.isVisible()
    assert not panel.cancel_button.isEnabled()
    assert not panel.refresh_button.isEnabled()
    assert "正在停止" in panel.status_label.text()
    calls = list(pairing.calls)
    panel.cancel_button.click()
    assert pairing.calls == calls

    pairing.finish("Idle", "cancelled")
    qt_application.processEvents()
    assert panel.qr_placeholder.isVisible()
    assert panel.qr_label.accessibleName() == "已停止"
    assert panel.cancel_button.isVisible()
    assert not panel.cancel_button.isEnabled()
    assert panel.refresh_button.isEnabled()
    assert pairing.calls.count(("qr",)) == 2
    panel.refresh_button.click()
    assert pairing.calls.count(("qr",)) == 3
    assert panel.qr_placeholder.isHidden()
    assert panel.cancel_button.isEnabled()


def test_switch_waits_for_resources_and_cleanup_failure_keeps_window(dialog):
    window, pairing = dialog
    window.refresh_qr()
    window.request_page("manual")
    pairing.publish("CleanupFailed", "cleanup_failed")
    assert window.current_page == "qr"
    assert not window.navigation.isEnabled()
    assert window.retry_stop_button.isVisible()
    window.retry_stop_button.click()
    assert pairing.calls[-1] == ("retry_stop",)
    pairing.finish()
    assert window.current_page == "manual"
    assert window.navigation.isEnabled()


def test_pairing_code_link_uses_keyboard_and_waits_without_opening_url(dialog, monkeypatch):
    window, pairing = dialog
    opened_urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened_urls.append(url))
    window.refresh_qr()
    window.code_button.setFocus()
    assert window.code_button.hasFocus()
    QTest.keyClick(window.code_button, Qt.Key.Key_Space)
    assert pairing.calls[-1] == ("cancel",)
    assert window.current_page == "qr"
    assert not window.code_button.isEnabled()
    pairing.finish()
    assert window.current_page == "manual"
    assert window.pairing_address.hasFocus()
    assert opened_urls == []


def test_paired_only_never_copies_pair_port_and_needs_continuation(dialog):
    window, pairing = dialog
    window.request_page("manual")
    window.pairing_address.setText("192.0.2.1:37123")
    pairing.finish("PairedOnly", "connection_timeout")
    assert window.continuation_box.isVisible()
    assert window.connection_address.text() == ""
    window.connection_address.setText("192.0.2.1:45111")
    assert not window.continue_button.isEnabled()
    pairing.continuation = object()
    pairing.continuation_changed.emit()
    assert window.continue_button.isEnabled()
    window.continue_button.click()
    assert pairing.calls[-1] == ("continue", "192.0.2.1:45111")
    assert not window.connection_address.isEnabled()


def test_keyboard_only_active_form_and_cancel_trust_notice(dialog):
    window, pairing = dialog
    window.request_page("address")
    QTest.keyClick(window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    assert window.current_page == "qr"
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert pairing.calls.count(("qr",)) == 2
    pairing.publish("Pairing")
    window.cancel_current()
    pairing.finish()
    assert "手机可能已保存配对记录" in window.status_detail.text()


@pytest.mark.parametrize("code", ["１２３４５６", "12345", "1234567", "12 456"])
def test_manual_code_rejects_non_ascii_or_wrong_length(dialog, code):
    window, _ = dialog
    window.request_page("manual")
    window.pairing_address.setText("192.0.2.1:37123")
    window.pairing_code.setText(code)
    assert not window.pair_button.isEnabled()


def test_qr_failure_does_not_ask_for_a_code_in_a_form_that_is_not_shown(dialog):
    window, pairing = dialog
    window.request_page("qr")
    pairing.finish("Failed", "pair_failed")
    assert window.status_detail.text() == "连接未完成，请检查无线调试与网络后重试。"
    assert window.refresh_button.isEnabled()
    assert window.code_button.isEnabled()


def test_manual_and_continuation_submit_by_return_without_hidden_form(dialog, qt_application):
    window, pairing = dialog
    window.request_page("manual")
    window.pairing_address.setText("192.0.2.1:37123")
    window.pairing_code.setText("001234")
    QTest.keyClick(window.pairing_code, Qt.Key.Key_Return)
    assert pairing.calls[-1] == ("code", "192.0.2.1:37123", "001234")
    pairing.finish("Failed", "pair_failed")
    assert window.pairing_code.hasFocus()
    pairing.continuation = object()
    pairing.finish("PairedOnly", "connection_timeout")
    qt_application.processEvents()
    window.connection_address.setText("192.0.2.1:42222")
    QTest.keyClick(window.connection_address, Qt.Key.Key_Return)
    assert pairing.calls[-1] == ("continue", "192.0.2.1:42222")
    assert sum(call[0] == "code" for call in pairing.calls) == 1


def test_shutdown_stops_visuals_and_does_not_create_an_owner_stop(dialog):
    window, pairing = dialog
    window.request_page("qr")
    before = list(pairing.calls)
    window.prepare_shutdown()
    assert not window._countdown.isActive()
    assert window.qr_label.pixmap().isNull()
    window.close()
    assert pairing.calls == before
