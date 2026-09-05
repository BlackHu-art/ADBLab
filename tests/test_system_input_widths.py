"""验证 System 的端口与设置输入使用真实文本净宽并跟随字体变化。"""

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle, QStyleOptionFrame

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _show_feature_panel,
)

pytestmark = pytest.mark.ui


def _set_font_size(size):
    config = replace(BaseStyles.current_font_config(), ui_family="Segoe UI", ui_size=size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)


def _assert_editor_text_is_visible(field, text):
    option = QStyleOptionFrame()
    field.initStyleOption(option)
    contents = field.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, field)
    margins = field.textMargins()
    # QLineEdit 在原生样式内容区内还保留左右各 2px 的文本绘制余量。
    available = contents.width() - margins.left() - margins.right() - 4
    assert field.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, available) == text, (
        text, field.font().pointSize(), field.width(), available, field.maximumWidth()
    )


@pytest.mark.parametrize("font_size", (12, 22))
@pytest.mark.parametrize("viewport_width", (292, 960))
@pytest.mark.parametrize("category", ("commands", "connectivity"))
def test_system_port_and_settings_inputs_keep_visible_text(
    qt_application, monkeypatch, font_size, viewport_width, category
):
    _set_font_size(font_size)
    owner, panel, scroll, _content = _show_feature_panel(
        "system", viewport_width, font_size, qt_application, monkeypatch,
        patch_font_factory=False,
    )
    try:
        panel.category_stack.set_current(category)
        _resize_feature_viewport(qt_application, owner, panel, scroll, viewport_width)
        if category == "commands":
            fields = (panel.settings_key, panel.settings_val)
        else:
            fields = (panel.tcpip_port_input, panel.fwd_local, panel.fwd_remote)
            assert panel.tcpip_port_input.text() == "5555"
        for field in fields:
            _assert_editor_text_is_visible(field, field.placeholderText())
            if category == "connectivity":
                _assert_editor_text_is_visible(field, "65535")
        assert scroll.viewport().width() == viewport_width
    finally:
        _close_feature_panel(owner)


def test_system_input_minimum_tracks_font_without_tracking_user_text(qt_application, monkeypatch):
    _set_font_size(12)
    owner, panel, scroll, _content = _show_feature_panel(
        "system", 292, 12, qt_application, monkeypatch, patch_font_factory=False,
    )
    try:
        fields = (
            panel.tcpip_port_input, panel.fwd_local, panel.settings_key, panel.settings_val,
            panel.kill_pid_input, panel.battery_val, panel.ime_id_input,
            panel.emu_sms_sender, panel.emu_sms_text, panel.emu_call_num,
            panel.emu_geo_lon, panel.emu_geo_lat,
        )
        initial_widths = tuple(field.minimumWidth() for field in fields)
        _set_font_size(22)
        _resize_feature_viewport(qt_application, owner, panel, scroll, 292)
        large_widths = tuple(field.minimumWidth() for field in fields)
        assert all(large > initial for large, initial in zip(large_widths, initial_widths))
        for field in (panel.settings_key, panel.settings_val):
            _assert_editor_text_is_visible(field, field.placeholderText())

        panel.category_stack.set_current("connectivity")
        _resize_feature_viewport(qt_application, owner, panel, scroll, 292)
        for field in (
            panel.ime_id_input, panel.emu_sms_sender, panel.emu_sms_text,
            panel.emu_call_num, panel.emu_geo_lon, panel.emu_geo_lat,
        ):
            _assert_editor_text_is_visible(field, field.placeholderText())

        panel.settings_val.setText("用户可输入任意长度的设置值" * 30)
        panel.emu_sms_text.setText("短信内容可以长于输入框，但不改变布局下限" * 30)
        panel.emu_call_num.setText("1234567890" * 30)
        panel.refresh_responsive_metrics()
        assert tuple(field.minimumWidth() for field in fields) == large_widths
        _set_font_size(12)
        _resize_feature_viewport(qt_application, owner, panel, scroll, 292)
        assert tuple(field.minimumWidth() for field in fields) == initial_widths
        assert panel.tcpip_port_input.text() == "5555"
        assert panel.settings_val.text() == "用户可输入任意长度的设置值" * 30
        assert panel.emu_sms_text.text() == "短信内容可以长于输入框，但不改变布局下限" * 30
        assert panel.emu_call_num.text() == "1234567890" * 30
    finally:
        _close_feature_panel(owner)


@pytest.mark.parametrize("font_size", (12, 22))
@pytest.mark.parametrize("viewport_width", (292, 960))
@pytest.mark.parametrize("category", ("commands", "connectivity"))
def test_system_emulator_and_numeric_inputs_keep_visible_purpose_and_range(
    qt_application, monkeypatch, font_size, viewport_width, category
):
    _set_font_size(font_size)
    owner, panel, scroll, _content = _show_feature_panel(
        "system", viewport_width, font_size, qt_application, monkeypatch,
        patch_font_factory=False,
    )
    try:
        panel.category_stack.set_current(category)
        _resize_feature_viewport(qt_application, owner, panel, scroll, viewport_width)
        samples = (
            ((panel.kill_pid_input, "2147483647"),)
            if category == "commands"
            else (
                (panel.battery_val, "100"), (panel.ime_id_input, ""),
                (panel.emu_sms_sender, ""), (panel.emu_sms_text, ""),
                (panel.emu_call_num, ""), (panel.emu_geo_lon, "-180.000000"),
                (panel.emu_geo_lat, "-90.000000"),
            )
        )
        for field, sample in samples:
            _assert_editor_text_is_visible(field, field.placeholderText())
            if sample:
                _assert_editor_text_is_visible(field, sample)
                field.setText(sample)
                assert field.hasAcceptableInput()
        assert panel.emu_label.buddy() is panel.emu_sms_sender
        assert panel.battery_label.buddy() is panel.battery_val
        assert scroll.viewport().width() == viewport_width
    finally:
        _close_feature_panel(owner)
