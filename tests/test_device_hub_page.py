"""验证设备工作台的缓存投影、逐台操作与响应式布局。"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import PushButton
from shiboken6 import isValid

from gui.pages.device_hub import DeviceHubPage
from gui.styles import BaseStyles
from tests.ui_geometry_helpers import wait_for_stable_geometry


def _show_page(qt_application, width=960):
    window = QWidget()
    layout = QVBoxLayout(window)
    page = DeviceHubPage(window)
    layout.addWidget(page)
    page.set_device_metadata([
        {"ip": "demo-usb-a", "Brand": "示例", "Model": "测试手机 A", "Aversion": "14"},
        {"ip": "192.0.2.15:5555", "Brand": "示例", "Model": "测试平板 B", "Aversion": "13"},
    ])
    page.set_device_context(["demo-usb-a"], ["demo-usb-a", "192.0.2.15:5555"], "ready")
    window.resize(width, 900)
    window.show()
    qt_application.processEvents()
    return window, page


def _settle_cards(qt_application, page):
    widgets = [page]
    for card in page.device_cards:
        widgets.extend((
            card, card.action_container, card.files_button, card.remote_button, card.apps_button,
        ))
    wait_for_stable_geometry(qt_application, widgets)


def _rich_metadata():
    return [
        {"ip": "demo-usb-a", "Brand": "示例", "Model": "测试手机 A", "Aversion": "14",
         "SDK Version": "34", "Resolution": "1080 × 2400", "Density": "420 dpi",
         "Total Memory": "8.0 GiB", "Available Memory": "3.2 GiB",
         "Storage Total": "128 GiB", "Storage Available": "64 GiB",
         "Battery Level": "84%", "Battery Status": "充电中",
         "CPU Architecture": "arm64-v8a", "Hardware": "qcom"},
        {"ip": "192.0.2.15:5555", "Brand": "示例", "Model": "测试平板 B", "Aversion": "13",
         "SDK Version": "33", "Resolution": "1600 × 2560", "Density": "320 dpi",
         "Total Memory": "6.0 GiB", "Available Memory": "2.1 GiB",
         "Storage Total": "64 GiB", "Storage Available": "21 GiB",
         "Battery Level": "62%", "Battery Status": "使用电池",
         "CPU Architecture": "arm64-v8a", "Hardware": "mt-demo"},
    ]


def test_normalized_device_metrics_have_named_summary_fields_and_hidden_details(qt_application):
    _window, page = _show_page(qt_application)
    metadata = _rich_metadata()
    page.set_device_metadata(metadata)
    _settle_cards(qt_application, page)
    for card, record in zip(page.device_cards, metadata):
        assert card.summary_fields["system"].caption.text() == "系统"
        assert card.summary_fields["screen"].caption.text() == "屏幕"
        assert card.summary_fields["memory"].caption.text() == "内存"
        assert card.screen_label.text() == record["Resolution"]
        assert card.memory_label.text() == record["Total Memory"]
        assert record["Battery Level"] in card.battery_label.text()
        assert record["Battery Status"] in card.battery_label.text()
        assert all(field.isVisible() for field in card.summary_fields.values())
        assert not card.details_container.isVisible()
        assert not card.identifier.isVisible()
        assert not any(field.isVisible() for field in card.detail_fields.values())


def test_details_expand_without_selection_and_survive_metadata_and_state_updates(qt_application):
    _window, page = _show_page(qt_application)
    metadata = _rich_metadata()
    page.set_device_metadata(metadata)
    card = page.device_cards[1]
    requests = QSignalSpy(page.selection_requested)
    QTest.mouseClick(card.details_button, Qt.MouseButton.LeftButton)
    _settle_cards(qt_application, page)
    assert requests.count() == 0 and not card.selection.isChecked()
    assert card.details_container.isVisible() and card.identifier.isVisible()
    for key, field in card.detail_fields.items():
        assert field.isVisible() and field.value.text() == metadata[1][key]
    metadata[1]["Storage Available"] = "20 GiB"
    page.set_device_metadata(metadata)
    page.set_device_context([], [c.device_id for c in page.device_cards], "scanning")
    assert page.device_cards[1] is card
    assert card.details_button.isChecked() and card.details_container.isVisible()
    assert card.detail_fields["Storage Available"].value.text() == "20 GiB"
    QTest.mouseClick(card.details_button, Qt.MouseButton.LeftButton)
    assert not card.details_container.isVisible()
    assert requests.count() == 0


def test_missing_metrics_remove_fields_while_zero_battery_is_preserved(qt_application):
    _window, page = _show_page(qt_application)
    page.set_device_metadata(_rich_metadata())
    card = page.device_cards[0]
    card.details_button.click()
    page.set_device_metadata([
        {"ip": card.device_id, "Aversion": "14", "Resolution": "Unknown",
         "Density": "N/A", "Total Memory": "-", "Battery Level": "0%"},
    ])
    _settle_cards(qt_application, page)
    assert card.battery_label.text() == "电量 0%" and card.battery_label.isVisible()
    assert card.summary_fields["screen"].isHidden()
    assert card.summary_fields["memory"].isHidden()
    assert all(field.isHidden() for field in card.detail_fields.values())
    assert card.details_container.isVisible() and card.identifier.isVisible()
    assert page.device_cards[1].battery_label.isHidden()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("font_size, width", [(12, 1000), (22, 380)])
def test_expanded_parameter_columns_fit_narrow_windows_and_large_fonts(
    qt_application, monkeypatch, theme, font_size, width
):
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    BaseStyles.switch_theme(theme)
    window, page = _show_page(qt_application, width)
    page.set_device_metadata(_rich_metadata())
    card = page.device_cards[0]
    card.details_button.click()
    _settle_cards(qt_application, page)
    assert window.width() == width
    fields = [*card.summary_fields.values(), *card.detail_fields.values(), card.identifier_field]
    bounds = []
    for field in fields:
        assert field.isVisible()
        rect = QRect(field.mapTo(card, QPoint()), field.size())
        assert card.rect().contains(rect)
        assert all(not rect.intersects(other) for other in bounds)
        bounds.append(rect)
        assert field.value.height() >= field.value.heightForWidth(field.value.width())
        assert field.caption.height() >= field.caption.fontMetrics().height()
    summary_positions = {
        field.mapTo(card, QPoint()).x() for field in card.summary_fields.values()
    }
    assert len(summary_positions) == (3 if width == 1000 else 1)
    for button in (*card._buttons, card.details_button):
        assert card.rect().contains(QRect(button.mapTo(card, QPoint()), button.size()))


def test_cached_metadata_enriches_only_discovered_devices(qt_application):
    _window, page = _show_page(qt_application)
    first = page.device_cards[0]
    assert first.name_label.text() == "示例 测试手机 A"
    assert "Android 14" in first.details_label.text()
    assert "USB" in first.status_label.text()
    assert "无线" in page.device_cards[1].status_label.text()
    assert first.identifier.toolTip() == "demo-usb-a"
    assert "demo-usb-a" in first.identifier.accessibleDescription()
    page.set_device_metadata([{"ip": "not-connected", "Model": "历史设备"}])
    assert [card.device_id for card in page.device_cards] == ["demo-usb-a", "192.0.2.15:5555"]
    assert "历史设备" not in page.summary.text()


def test_selection_round_trip_preserves_cards_and_emits_once(qt_application):
    _window, page = _show_page(qt_application)
    cards = page.device_cards
    requests = QSignalSpy(page.selection_requested)
    page.selection_requested.connect(
        lambda selected: page.set_device_context(
            selected, ["demo-usb-a", "192.0.2.15:5555"], "ready"
        )
    )
    cards[1].selection.setFocus()
    QTest.keyClick(cards[1].selection, Qt.Key.Key_Space)
    assert requests.count() == 1
    assert requests.at(0)[0] == ["demo-usb-a", "192.0.2.15:5555"]
    assert page.device_cards == cards
    assert all(card.selection.isChecked() for card in cards)
    assert "2 台已选为操作目标" in page.summary.text()
    cards[0].selection.click()
    assert requests.count() == 2
    assert requests.at(1)[0] == ["192.0.2.15:5555"]


@pytest.mark.parametrize(
    "target_name", ["card", "identity", "name_label", "details_label", "identifier", "icon"]
)
def test_double_click_device_text_or_background_toggles_once_without_replacing_row(
    qt_application, target_name
):
    _window, page = _show_page(qt_application)
    cards = page.device_cards
    card = cards[1]
    if target_name == "identifier":
        card.details_button.click()
        _settle_cards(qt_application, page)
    requests = QSignalSpy(page.selection_requested)
    page.selection_requested.connect(
        lambda selected: page.set_device_context(selected, [c.device_id for c in cards], "ready")
    )
    target = card if target_name == "card" else getattr(card, target_name)
    point = QPoint(card.width() // 2, 2) if target_name == "card" else target.rect().center()
    QTest.mouseDClick(target, Qt.MouseButton.LeftButton, pos=point)
    assert requests.count() == 1
    assert card.selection.isChecked()
    assert page.device_cards == cards
    QTest.mouseDClick(target, Qt.MouseButton.LeftButton, pos=point)
    assert requests.count() == 2
    assert not card.selection.isChecked()


@pytest.mark.parametrize(
    "button_name", ["files_button", "remote_button", "apps_button", "details_button"]
)
@pytest.mark.parametrize("selected", [False, True])
def test_device_action_double_click_does_not_toggle_batch_target(
    qt_application, button_name, selected
):
    _window, page = _show_page(qt_application)
    card = page.device_cards[1]
    page.set_device_context(
        [card.device_id] if selected else [], [c.device_id for c in page.device_cards], "ready"
    )
    requests = QSignalSpy(page.selection_requested)
    button = getattr(card, button_name)
    QTest.mouseDClick(button, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    assert requests.count() == 0
    assert card.selection.isChecked() == selected
    button.setEnabled(False)
    QTest.mouseDClick(button, Qt.MouseButton.LeftButton)
    assert requests.count() == 0


@pytest.mark.parametrize("state", ["ready", "scanning", "unavailable"])
@pytest.mark.parametrize("button_name", ["files_button", "remote_button", "apps_button"])
def test_cancelled_selection_blocks_disabled_click_and_stale_action_signal(
    qt_application, state, button_name
):
    _window, page = _show_page(qt_application)
    card = page.device_cards[0]
    page.set_device_context([], [c.device_id for c in page.device_cards], state)
    actions = QSignalSpy(page.device_action_requested)
    button = getattr(card, button_name)
    assert not button.isEnabled()
    button.click()
    card.action_requested.emit("devices", "files", card.device_id)
    assert actions.count() == 0
    assert card.details_button.isEnabled()


@pytest.mark.parametrize("state", ["scanning", "unavailable"])
def test_selected_device_cannot_submit_a_stale_action_during_scan_or_error(qt_application, state):
    _window, page = _show_page(qt_application)
    card = page.device_cards[0]
    page.set_device_context([card.device_id], [c.device_id for c in page.device_cards], state)
    actions = QSignalSpy(page.device_action_requested)
    card.action_requested.emit("apps", "manager", card.device_id)
    assert actions.count() == 0


def test_checkbox_single_click_and_double_click_removal_keep_sender_alive(qt_application):
    _window, page = _show_page(qt_application)
    card = page.device_cards[1]
    requests = QSignalSpy(page.selection_requested)
    destroyed = QSignalSpy(card.destroyed)
    QTest.mouseClick(
        card.selection, Qt.MouseButton.LeftButton, pos=QPoint(10, card.selection.height() // 2)
    )
    assert requests.count() == 1
    assert requests.at(0)[0] == ["demo-usb-a", card.device_id]
    page.set_device_context([], ["demo-usb-a", card.device_id], "ready")
    page.selection_requested.connect(
        lambda _selected: page.set_device_context([], ["demo-usb-a"], "ready")
    )
    QTest.mouseDClick(card.name_label, Qt.MouseButton.LeftButton)
    assert requests.count() == 2
    assert destroyed.count() == 0 and isValid(card)
    assert card.isHidden() and "离线" in card.status_label.text()
    assert not card.selection.isEnabled() and not card.files_button.isEnabled()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1 and not isValid(card)


def test_optional_cached_configuration_is_shown_without_inventing_missing_fields(qt_application):
    _window, page = _show_page(qt_application)
    page.set_device_metadata([
        {"ip": "demo-usb-a", "Brand": "示例", "Model": "测试手机", "Aversion": "14",
         "SDK Version": "34", "CPU Architecture": "arm64-v8a", "Hardware": "qcom",
         "Serial Number": "must-not-appear", "IMEI": "must-not-appear"},
        {"ip": "192.0.2.15:5555", "Brand": "Unknown", "Model": "N/A", "Aversion": "-",
         "SDK Version": "unknown", "CPU Architecture": "", "Hardware": "detecting"},
    ])
    first, second = page.device_cards
    assert "API 34" in first.details_label.text()
    assert "arm64-v8a" in first.properties_label.text()
    assert "qcom" in first.detail_fields["Hardware"].value.text()
    assert not first.properties_label.isVisible()
    first.details_button.click()
    assert first.properties_label.isVisible()
    assert "已选" in first.status_label.text() and "在线" in first.status_label.text()
    assert "已选" not in second.status_label.text()
    assert second.detail_fields["CPU Architecture"].isHidden()
    assert "API" not in second.details_label.text()
    assert "must-not-appear" not in " ".join(
        label.text() for label in (first.name_label, first.details_label, first.properties_label)
    )


@pytest.mark.parametrize("state, caption", [("scanning", "扫描中"), ("unavailable", "待确认")])
def test_each_cached_device_row_reports_uncertain_connection_and_blocks_selection(
    qt_application, state, caption
):
    _window, page = _show_page(qt_application)
    cards = page.device_cards
    requests = QSignalSpy(page.selection_requested)
    page.set_device_context([cards[0].device_id], [c.device_id for c in cards], state)
    for card in cards:
        assert caption in card.status_label.text()
        assert "在线" not in card.status_label.text()
        assert not card.selection.isEnabled()
        assert not card.files_button.isEnabled()
        QTest.mouseDClick(card.name_label, Qt.MouseButton.LeftButton)
    assert requests.count() == 0


@pytest.mark.parametrize(
    ("button_name", "section", "feature"),
    [("files_button", "devices", "files"), ("remote_button", "devices", "remote"),
     ("apps_button", "apps", "manager")],
)
def test_device_actions_keep_batch_selection_and_target_one_device(
    qt_application, button_name, section, feature
):
    _window, page = _show_page(qt_application)
    actions = QSignalSpy(page.device_action_requested)
    selection = QSignalSpy(page.selection_requested)
    card = page.device_cards[1]
    page.set_device_context(
        ["demo-usb-a", card.device_id], ["demo-usb-a", card.device_id], "ready"
    )
    getattr(card, button_name).click()
    assert actions.count() == 1
    assert actions.at(0) == [section, feature, "192.0.2.15:5555"]
    assert selection.count() == 0
    assert page.device_cards[0].selection.isChecked()
    assert card.selection.isChecked()


def test_unavailable_snapshot_stays_visible_without_new_device_actions(qt_application):
    _window, page = _show_page(qt_application)
    card = page.device_cards[0]
    actions = QSignalSpy(page.device_action_requested)
    page.set_device_context(["demo-usb-a"], ["demo-usb-a", "192.0.2.15:5555"], "unavailable")
    assert page.device_cards[0] is card
    assert "待确认" in page.summary.text()
    assert not card.files_button.isEnabled()
    card.files_button.click()
    assert actions.count() == 0
    page.set_device_context(["demo-usb-a"], ["demo-usb-a", "192.0.2.15:5555"], "ready")
    assert card.files_button.isEnabled()


def test_removed_card_is_deferred_and_cannot_open_disconnected_device(qt_application):
    _window, page = _show_page(qt_application)
    removed = page.device_cards[0]
    actions = QSignalSpy(page.device_action_requested)
    page.set_device_context([], ["192.0.2.15:5555"], "ready")
    assert isValid(removed)
    assert removed.isHidden()
    removed.files_button.click()
    removed.action_requested.emit("devices", "files", removed.device_id)
    assert actions.count() == 0
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(removed)


@pytest.mark.parametrize("state", ["empty", "scanning", "unavailable"])
def test_empty_states_offer_connection_without_placeholder_devices(qt_application, state):
    page = DeviceHubPage()
    page.set_device_context([], [], state)
    page.show()
    qt_application.processEvents()
    assert page.device_cards == ()
    assert page.empty_card.isVisible()
    assert not page.cards_container.isVisible()
    assert [button for button in page.findChildren(PushButton) if button.isVisible()] == [
        page.connect_button
    ]
    assert page.connect_button.isEnabled() == (state != "scanning")
    assert page.refresh_button.isVisible()
    assert page.refresh_button.isEnabled() == (state != "scanning")
    request = QSignalSpy(page.connect_requested)
    page.connect_button.click()
    assert request.count() == (state != "scanning")


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("width", [380, 1000])
def test_device_cards_fit_actual_fonts_and_preserve_keyboard_actions(
    qt_application, monkeypatch, theme, font_size, width
):
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or font_size)),
    )
    BaseStyles.switch_theme(theme)
    window, page = _show_page(qt_application, width)
    page.set_device_metadata([
        {"ip": "demo-usb-a", "Model": "用于演示的长名称 Android 测试设备", "Aversion": "14"},
    ])
    _settle_cards(qt_application, page)
    assert window.width() == width
    assert page.width() <= width
    toolbar_bounds = []
    for control in (page.summary, page.connect_button, page.refresh_button):
        bounds = QRect(control.mapTo(page.toolbar, QPoint()), control.size())
        assert page.toolbar.rect().contains(bounds)
        assert control.height() >= control.fontMetrics().height()
        toolbar_bounds.append(bounds)
    assert not toolbar_bounds[0].intersects(toolbar_bounds[1])
    assert not toolbar_bounds[1].intersects(toolbar_bounds[2])
    for card in page.device_cards:
        assert card.geometry().right() < page.width()
        assert card.name_label.font().pointSize() == font_size
        assert card.identifier.font().pointSize() == font_size
        assert card.selection.focusPolicy() != Qt.FocusPolicy.NoFocus
        buttons = (card.files_button, card.remote_button, card.apps_button)
        for button in buttons:
            assert button.isVisible()
            assert button.height() >= button.sizeHint().height()
            assert button.width() >= button.sizeHint().width()
            assert button.geometry().right() < card.action_container.width()
            assert button.geometry().bottom() < card.action_container.height()
            assert button.focusPolicy() != Qt.FocusPolicy.NoFocus
            assert button.toolTip()
        for index, button in enumerate(buttons):
            assert not any(
                button.geometry().intersects(other.geometry()) for other in buttons[index + 1:]
            )
    first, second = page.device_cards
    assert first.geometry().bottom() < second.geometry().top()
    if width == 1000:
        assert first.files_button.y() == first.remote_button.y() == first.apps_button.y()


def test_metadata_text_remains_plain_and_long_identifier_is_accessible(qt_application):
    page = DeviceHubPage()
    device_id = "demo-" + "synthetic-identifier-" * 5
    page.set_device_metadata([{"ip": device_id, "Model": "<b>字面设备名称</b>"}])
    page.set_device_context([], [device_id], "ready")
    page.resize(380, 500)
    page.show()
    qt_application.processEvents()
    card = page.device_cards[0]
    assert card.name_label.textFormat() == Qt.TextFormat.PlainText
    assert card.name_label.text() == "<b>字面设备名称</b>"
    assert card.identifier.toolTip() == device_id
    assert card.identifier.accessibleDescription() == device_id
    assert len(card.identifier.text()) < len(device_id)


@pytest.mark.parametrize("selected", [[], ["demo-usb-a"], ["demo-usb-a", "192.0.2.15:5555"]])
def test_device_actions_have_one_entry_per_card_without_a_duplicate_footer(
    qt_application, selected,
):
    _window, page = _show_page(qt_application)
    page.set_device_context(selected, ["demo-usb-a", "192.0.2.15:5555"], "ready")
    _settle_cards(qt_application, page)
    actions = {
        button
        for card in page.device_cards
        for button in (card.files_button, card.remote_button, card.apps_button)
    }
    assert {
        button for button in page.findChildren(PushButton) if button.isVisible()
    } == actions | {page.connect_button} | {card.details_button for card in page.device_cards}
    for card in page.device_cards:
        assert card.apps_button.text() == "应用管理"
        assert card.files_button.isEnabled() == (card.device_id in selected)
    assert f"{len(selected)} 台已选为操作目标" in page.summary.text()


def test_owner_destruction_releases_cards_before_late_style_signals(qt_application):
    window, page = _show_page(qt_application)
    cards = page.device_cards
    destroyed = QSignalSpy(page.destroyed)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed.count() == 1
    assert not isValid(page)
    assert all(not isValid(card) for card in cards)
    BaseStyles.ui_font_changed.emit(BaseStyles.current_font_config())
    BaseStyles.theme_changed.emit(BaseStyles.current_theme)
    qt_application.processEvents()


def test_font_resize_round_trip_reflows_existing_controls(qt_application, monkeypatch):
    size = 12
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or current[0])),
    )
    current = [size]
    _window, page = _show_page(qt_application, 620)
    card = page.device_cards[0]
    baseline = card.height()
    current[0] = 22
    BaseStyles.ui_font_changed.emit(BaseStyles.current_font_config())
    _settle_cards(qt_application, page)
    assert page.device_cards[0] is card
    assert card.name_label.font().pointSize() == 22
    assert card.height() > baseline
    current[0] = 12
    BaseStyles.ui_font_changed.emit(BaseStyles.current_font_config())
    _settle_cards(qt_application, page)
    assert card.height() == baseline


def test_existing_rows_shrink_after_font_change_without_expanding_window(
    qt_application, monkeypatch
):
    window, page = _show_page(qt_application, 1050)
    page.set_device_metadata([
        {"ip": "demo-usb-a", "Brand": "示例", "Model": "测试手机 A", "Aversion": "14",
         "SDK Version": "34", "CPU Architecture": "arm64-v8a", "Hardware": "qcom"},
    ])
    monkeypatch.setattr(
        BaseStyles, "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Microsoft YaHei", size or 22)),
    )
    page._apply_fonts()
    window.resize(380, 1100)
    _settle_cards(qt_application, page)
    assert window.width() == 380
    assert page.toolbar.height() <= page.summary.height() + page.connect_button.height() + 12
    for card in page.device_cards:
        assert card.width() <= page.width()
        labels = [card.name_label, card.status_label, card.details_label, card.properties_label]
        visible_labels = [label for label in labels if label.isVisible()]
        for label in visible_labels:
            assert label.height() >= label.heightForWidth(label.width())
        for first, second in zip(visible_labels, visible_labels[1:]):
            first_bounds = QRect(first.mapTo(card, QPoint()), first.size())
            second_bounds = QRect(second.mapTo(card, QPoint()), second.size())
            assert not first_bounds.intersects(second_bounds)
