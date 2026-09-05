"""设置页字号、响应式卡片和配置交互的回归覆盖。"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint
from qfluentwidgets import FluentIcon, FluentWindow

from core.settings_manager import DEFAULTS, AppSettings
from gui.pages.fluent_pages import SettingsPage
from gui.styles import BaseStyles, FontRole
from tests.ui_geometry_helpers import wait_for_stable_geometry


def _setting_card_controls(page):
    """从既有设置入口检查必需操作，避免空的内部呈现注册表让遍历假通过。"""
    return (
        (page.save_card, page.save_card.button),
        (page.scan_card, page.scan_card.switchButton),
        (page.log_lines_card, page.log_lines_card.combo_box),
        (page.theme_card, page.theme_card.combo_box),
        (page.scale_card, page.scale_card.combo_box),
        (page.accent_card, page.accent_card.color_button),
        (page.mica_card, page.mica_card.switchButton),
        (page.pin_card, page.pin_card.switchButton),
        (page.font_family_card, page.font_family_card.combo_box),
        (page.ui_size_card, page.ui_size_card.combo_box),
        (page.log_size_card, page.log_size_card.combo_box),
        (page.reset_card, page.reset_card.button),
        (page.restart_adb_card, page.restart_adb_card.button),
        (page.about_panel.project_card, page.about_panel.project_button),
    )


def _settle_settings(qt_application, page):
    cards = [card for card, _control in _setting_card_controls(page)]
    cards.append(page.about_panel.support_card)
    wait_for_stable_geometry(qt_application, (page, *cards))


@pytest.fixture
def settings_page(monkeypatch, qt_application):
    values = dict(DEFAULTS)
    values.update(font_family="Microsoft YaHei", ui_font_size=12, save_directory="C:/示例输出")
    writes = []

    def update(changes):
        values.update(changes)
        writes.append(dict(changes))

    def reset():
        values.clear()
        values.update(DEFAULTS)
        writes.append({"reset": True})

    settings = SimpleNamespace(
        get=values.get, set=lambda key, value: update({key: value}),
        set_many=update, reset=reset,
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    BaseStyles.reload_from_settings()
    frame = Mock()
    frame._always_on_top = False
    page = SettingsPage(frame)
    yield page, values, writes, frame
    page.close()


@pytest.mark.parametrize("width,font_size", [(1000, 12), (420, 12), (1000, 22), (420, 22)])
def test_setting_cards_keep_full_text_and_actions_inside_viewport(
    qt_application, settings_page, width, font_size,
):
    page, values, writes, _frame = settings_page
    values["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    page.resize(width, 640)
    page.show()
    _settle_settings(qt_application, page)

    assert not writes
    assert page.horizontalScrollBar().maximum() == 0
    for card, control in _setting_card_controls(page):
        assert card.isVisibleTo(page)
        assert control.isVisibleTo(page)
        assert (
            card.titleLabel.font().pointSizeF()
            == BaseStyles.font_for_role(FontRole.UI).pointSizeF()
        )
        assert (
            card.contentLabel.font().pointSizeF()
            == BaseStyles.font_for_role(FontRole.UI_SMALL).pointSizeF()
        )
        assert control.font().pointSizeF() == BaseStyles.font_for_role(FontRole.UI).pointSizeF()
        assert control.height() >= control.fontMetrics().height() + 14
        for label in (card.titleLabel, card.contentLabel):
            assert label.height() >= label.heightForWidth(label.width())
            assert label.height() >= label.fontMetrics().height()
        point = control.mapTo(card, QPoint())
        assert 0 <= point.x() and point.x() + control.width() <= card.width()
        assert 0 <= point.y() and point.y() + control.height() <= card.height()
        page.ensureWidgetVisible(control, 0, 0)
        qt_application.processEvents()
        visible = control.mapTo(page.viewport(), QPoint())
        assert visible.y() >= 0
        assert visible.y() + control.height() <= page.viewport().height()


def test_settings_font_change_and_restore_preserve_values_and_signal_contract(
    qt_application, settings_page,
):
    page, values, writes, frame = settings_page
    page.resize(420, 640)
    page.show()
    _settle_settings(qt_application, page)
    original_card_height = page.mica_card.height()
    page.ui_size_card.combo_box.setCurrentText("22")
    _settle_settings(qt_application, page)
    assert values["ui_font_size"] == 22
    assert values["save_directory"] == "C:/示例输出"
    assert page.mica_card.height() > original_card_height
    assert len(writes) == 1
    page.ui_size_card.combo_box.setCurrentText("12")
    _settle_settings(qt_application, page)
    assert page.mica_card.height() <= original_card_height
    page.ui_size_card.combo_box.setCurrentText("22")
    _settle_settings(qt_application, page)
    page.restart_adb_card.button.click()
    frame.left_panel.signals.restart_adb_requested.emit.assert_called_once_with()

    page._reset_settings()
    _settle_settings(qt_application, page)
    assert page.ui_size_card.value() == "12"
    assert page.log_size_card.value() == "9"
    assert page.scan_card.isChecked() is True
    assert page.mica_card.titleLabel.font().pointSizeF() == 12
    for card in (page.scan_card, page.mica_card, page.pin_card):
        assert card.switchButton.label.text() == ("开" if card.isChecked() else "关")
    # 恢复默认也会更换字体族；与同配置的新页比较，避免把原字体度量当成默认字体。
    fresh = SettingsPage(frame)
    try:
        fresh.resize(page.size())
        fresh.show()
        _settle_settings(qt_application, fresh)
        assert page.mica_card.height() == fresh.mica_card.height()
    finally:
        fresh.close()
    assert writes[-1] == {"reset": True}
    frame.restore_default_window_size.assert_called_once_with()


def test_settings_long_path_and_theme_changes_keep_readable_font_and_original_value(
    qt_application, settings_page,
):
    page, values, _writes, _frame = settings_page
    values["ui_font_size"] = 22
    path = "C:/" + "long-output-folder/" * 12 + "reports"
    page.save_card.setContent(path)
    BaseStyles.reload_from_settings()
    page.resize(420, 640)
    page.show()
    for theme in ("Dark", "Light"):
        BaseStyles.switch_theme(theme)
        _settle_settings(qt_application, page)
        assert page.save_card.contentLabel.text() == path
        assert page.save_card.contentLabel.toolTip() == path
        assert page.save_card.contentLabel.accessibleDescription() == path
        assert (
            page.save_card.contentLabel.height()
            == page.save_card.contentLabel.fontMetrics().height()
        )
        assert page.scan_card.switchButton.label.font().pointSizeF() == 22
        assert page.ui_size_card.combo_box.font().pointSizeF() == 22
        assert page.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("label,expected", list(SettingsPage.SCALE_VALUES.items()))
def test_settings_scale_is_saved_for_restart_without_changing_runtime_font_or_dpi(
    qt_application, settings_page, label, expected,
):
    page, values, writes, _frame = settings_page
    initial_font = qt_application.font()
    initial_dpr = page.devicePixelRatioF()
    initial_environment = dict(os.environ)
    page.scale_card.combo_box.setCurrentText(label)

    assert values["ui_scale"] == expected
    assert values["ui_font_size"] == 12
    assert values["font_family"] == "Microsoft YaHei"
    assert qt_application.font() == initial_font
    assert page.devicePixelRatioF() == initial_dpr
    assert dict(os.environ) == initial_environment
    assert writes == ([] if expected == "Auto" else [{"ui_scale": expected}])
    assert "重启" in page.scale_card.contentLabel.text()


def test_settings_restore_resets_scale_card_without_an_extra_save(settings_page):
    page, values, writes, _frame = settings_page
    page.scale_card.combo_box.setCurrentText("175%")
    page._reset_settings()

    assert values["ui_scale"] == "Auto"
    assert page.scale_card.value() == "跟随系统"
    assert writes == [{"ui_scale": 1.75}, {"reset": True}]


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_settings_scroll_margins_share_fluent_window_background(
    qt_application, settings_page, theme,
):
    page, _values, _writes, _frame = settings_page
    BaseStyles.switch_theme(theme)
    window = FluentWindow()
    window.setMicaEffectEnabled(False)
    window.addSubInterface(page, FluentIcon.SETTING, "设置")
    window.resize(900, 640)
    window.show()
    window.switchTo(page)
    _settle_settings(qt_application, page)
    for bottom in (False, True):
        scroll = page.verticalScrollBar()
        scroll.setValue(scroll.maximum() if bottom else 0)
        qt_application.processEvents()
        pixels = window.grab().toImage()
        surface = page.viewport().mapTo(window, QPoint(8, 20))
        background = pixels.pixelColor(surface)
        for point in (QPoint(8, 20), QPoint(8, page.height() - 10)):
            pixel = page.mapTo(window, point)
            assert pixels.pixelColor(pixel).rgb() == background.rgb()
    window.close()


@pytest.mark.parametrize("font_size", [11, 22])
def test_about_cards_keep_metadata_and_actions_reachable_at_bottom_of_short_window(
    qt_application, settings_page, font_size,
):
    page, values, _writes, _frame = settings_page
    values["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    page.resize(420, 420)
    page.show()
    _settle_settings(qt_application, page)
    about = page.about_panel
    for theme in ("Light", "Dark"):
        BaseStyles.switch_theme(theme)
        _settle_settings(qt_application, page)
        for control in (about.project_button, about.support_qr):
            page.ensureWidgetVisible(control, 0, 0)
            qt_application.processEvents()
            position = control.mapTo(page.viewport(), QPoint())
            assert position.y() >= 0
            assert position.y() + control.height() <= page.viewport().height()
            assert position.x() >= 0
            assert position.x() + control.width() <= page.viewport().width()
        assert page.horizontalScrollBar().maximum() == 0
        assert about.support_qr.width() == about.support_qr.height() == 132
        assert about.title_label.text() == "ADBLab"
        assert about.project_button.font().pointSizeF() == font_size
        for label in (about.support_card.titleLabel, about.support_card.contentLabel):
            assert label.height() >= label.heightForWidth(label.width())
            point = label.mapTo(about.support_card, QPoint())
            assert point.y() >= 0
            assert point.y() + label.height() <= about.support_card.height()
        title = about.support_card.titleLabel
        description = about.support_card.contentLabel
        assert description.y() - (title.y() + title.height()) <= 6


def test_about_homepage_opens_only_on_explicit_click(settings_page, monkeypatch):
    page, _values, _writes, _frame = settings_page
    opener = Mock(return_value=True)
    monkeypatch.setattr("qfluentwidgets.components.widgets.button.QDesktopServices.openUrl", opener)
    from utils.app_metadata import APP_VERSION

    about = page.about_panel
    about._refresh_typography()
    assert APP_VERSION in about.version_label.text()
    opener.assert_not_called()
    about.project_button.click()
    opener.assert_called_once()
    assert opener.call_args.args[0].toString() == "https://github.com/BlackHu-art/ADBLab"


def test_about_support_icon_stays_aligned_with_text_beside_tall_qr(
    qt_application, settings_page,
):
    page, _values, _writes, _frame = settings_page
    page.resize(1120, 800)
    page.show()
    _settle_settings(qt_application, page)
    card = page.about_panel.support_card
    icon = card.iconLabel
    center = icon.mapTo(card, icon.rect().center()).y()
    title_top = card.titleLabel.mapTo(card, QPoint()).y()
    description_bottom = card.contentLabel.mapTo(card, card.contentLabel.rect().bottomLeft()).y()
    assert title_top <= center <= description_bottom
