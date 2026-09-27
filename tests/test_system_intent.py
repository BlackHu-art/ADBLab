"""验证 Intent 表单的请求快照、输入边界和内嵌交互。"""

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtTest import QSignalSpy

from tests.test_system_panel_categories import _build_system_panel

pytestmark = pytest.mark.ui


@pytest.fixture
def intent_panel(qt_application):
    panel, widget = _build_system_panel()
    panel.connect_signals()
    panel.panel.selected_devices = ["demo-a", "demo-b"]
    panel.update_action_states()
    yield panel, widget
    widget.close()
    widget.deleteLater()


def test_custom_scheme_is_valid_but_invalid_uri_is_not_submitted(intent_panel):
    panel, _widget = intent_panel
    requested = QSignalSpy(panel.signals.open_deep_link_requested)
    panel.deep_link_uri.setText("adblab-demo://screen/detail?id=42")
    assert panel.btn_deep_link.isEnabled()
    panel.btn_deep_link.click()
    assert requested.count() == 1
    assert requested.at(0) == [["demo-a", "demo-b"], "adblab-demo://screen/detail?id=42"]
    panel.deep_link_uri.setText("missing-scheme")
    panel.btn_deep_link.clicked.emit()
    assert not panel.btn_deep_link.isEnabled()
    assert requested.count() == 1


def test_explicit_activity_form_freezes_targets_and_advanced_fields(intent_panel):
    panel, _widget = intent_panel
    form = panel.intent_controls
    requested = QSignalSpy(panel.signals.execute_intent_requested)
    form.activity_mode.setCurrentIndex(1)
    panel.activity_spec.setText("android.intent.action.VIEW")
    form.data_uri.setText("adblab-demo://screen/detail")
    form.mime_type.setText("text/plain")
    form.flags.setText("0x10000000")
    form.wait.setChecked(True)
    panel.btn_start_activity.click()
    assert requested.count() == 1
    targets, request = requested.at(0)
    panel.panel.selected_devices[:] = ["demo-c"]
    panel.activity_spec.setText("android.settings.SETTINGS")
    assert targets == ["demo-a", "demo-b"]
    assert request.kind == "activity"
    assert request.action == "android.intent.action.VIEW"
    assert request.data_uri == "adblab-demo://screen/detail"
    assert request.mime_type == "text/plain"
    assert int(request.flags, 0) == 0x10000000
    assert request.wait is True


def test_activity_uri_mode_never_sends_uri_as_component(intent_panel):
    panel, _widget = intent_panel
    requested = QSignalSpy(panel.signals.execute_intent_requested)
    panel.intent_controls.activity_mode.setCurrentIndex(2)
    panel.activity_spec.setText("https://example.com/path")
    panel.btn_start_activity.click()
    assert requested.count() == 1
    request = requested.at(0)[1]
    assert request.component == ""
    assert request.data_uri == "https://example.com/path"


def test_invalid_flags_and_missing_targets_do_not_dispatch(intent_panel):
    panel, _widget = intent_panel
    requested = QSignalSpy(panel.signals.execute_intent_requested)
    panel.activity_spec.setText("com.example/.Main")
    panel.intent_controls.flags.setText("1; reboot")
    panel.btn_start_activity.clicked.emit()
    assert not panel.btn_start_activity.isEnabled()
    assert requested.count() == 0
    panel.intent_controls.flags.clear()
    panel.panel.selected_devices = []
    panel.update_action_states()
    panel.btn_start_activity.clicked.emit()
    assert requested.count() == 0


@pytest.mark.parametrize("mode", [0, 1])
def test_optional_uri_does_not_bypass_required_explicit_mode(intent_panel, mode):
    panel, _widget = intent_panel
    requested = QSignalSpy(panel.signals.execute_intent_requested)
    panel.intent_controls.activity_mode.setCurrentIndex(mode)
    panel.activity_spec.clear()
    panel.intent_controls.data_uri.setText("demo://screen/detail")
    panel.btn_start_activity.clicked.emit()
    assert not panel.btn_start_activity.isEnabled()
    assert requested.count() == 0


def test_broadcast_typed_extras_validate_before_submission(intent_panel):
    panel, _widget = intent_panel
    requested = QSignalSpy(panel.signals.execute_intent_requested)
    panel.broadcast_action.setText("com.example.DEBUG")
    row = panel.intent_controls.add_extra_row()
    row.key.setText("attempts")
    row.value_type.setCurrentIndex(2)
    row.value.setText("not-a-number")
    panel.btn_broadcast.clicked.emit()
    assert not panel.btn_broadcast.isEnabled()
    assert requested.count() == 0
    row.value.setText("3")
    panel.btn_broadcast.click()
    assert requested.count() == 1
    request = requested.at(0)[1]
    assert request.kind == "broadcast"
    assert request.extras[0].key == "attempts"
    assert request.extras[0].value_type == "int"
    assert request.extras[0].value == "3"
    row.remove.click()
    assert not panel.intent_controls.extra_rows
    assert panel.btn_broadcast.isEnabled()


def test_advanced_fields_are_inline_and_collapsed_by_default(intent_panel, qt_application):
    panel, widget = intent_panel
    widget.resize(860, 1000)
    widget.show()
    qt_application.processEvents()
    form = panel.intent_controls
    assert not form.advanced.isVisibleTo(widget)
    form.advanced_toggle.click()
    qt_application.processEvents()
    assert form.advanced.isVisibleTo(widget)
    assert form.data_uri.window() is widget
    form.advanced_toggle.click()
    assert not form.advanced.isVisibleTo(widget)


@pytest.mark.parametrize("width,font_size", [(420, 12), (860, 18)])
def test_expanded_intent_controls_stay_inside_card(
    qt_application, monkeypatch, tmp_path, width, font_size,
):
    from tests.test_responsive_panels import _resize_feature_viewport, _show_feature_panel

    panel, system, scroll, _content = _show_feature_panel(
        "system", width, font_size, qt_application, monkeypatch,
    )
    try:
        form = system.intent_controls
        form.advanced_toggle.click()
        row = form.add_extra_row()
        row.key.setText("attempts")
        row.value_type.setCurrentIndex(2)
        row.value.setText("3")
        _resize_feature_viewport(qt_application, panel, system, scroll, width)
        card = next(
            card for card in system._system_section_groups
            if card.headerLabel.text() == "广播与 Intent"
        )
        for control in (
            system.activity_spec, system.btn_start_activity,
            form.data_uri, form.mime_type, form.flags, form.wait,
            row.key, row.value_type, row.value, row.remove,
        ):
            assert control.isVisibleTo(card)
            geometry = QRect(control.mapTo(card, QPoint()), control.size())
            assert card.rect().contains(geometry), (control, card.rect(), geometry)
        path = tmp_path / "intent-expanded.png"
        assert card.grab().save(str(path))
        print(f"Intent preview: {path}")
    finally:
        panel.close()
        panel.deleteLater()
