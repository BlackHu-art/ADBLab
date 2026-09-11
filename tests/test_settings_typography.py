"""设置页字号、响应式卡片和配置交互的回归覆盖。"""

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel
from qfluentwidgets import FluentIcon, FluentWindow

from core.settings_manager import DEFAULTS, AppSettings
from gui.i18n import install_translators
from gui.pages.fluent_pages import SettingsPage
from gui.styles import BaseStyles, FontRole
from services.app_update import ReleaseInfo, UpdateSnapshot
from tests.ui_geometry_helpers import wait_for_stable_geometry


def _setting_card_controls(page):
    """从既有设置入口检查必需操作，避免空的内部呈现注册表让遍历假通过。"""
    return (
        (page.save_card, page.save_card.button),
        (page.scan_card, page.scan_card.switchButton),
        (page.log_lines_card, page.log_lines_card.combo_box),
        (page.theme_card, page.theme_card.combo_box),
        (page.scale_card, page.scale_card.combo_box),
        (page.language_card, page.language_card.combo_box),
        (page.accent_card, page.accent_card.color_button),
        (page.mica_card, page.mica_card.switchButton),
        (page.pin_card, page.pin_card.switchButton),
        (page.font_family_card, page.font_family_card.combo_box),
        (page.ui_size_card, page.ui_size_card.combo_box),
        (page.log_size_card, page.log_size_card.combo_box),
        (page.reset_card, page.reset_card.button),
        (page.restart_adb_card, page.restart_adb_card.button),
        (page.about_panel.project_card, page.about_panel.project_button),
        (page.about_panel.project_card, page.about_panel.check_update_button),
        (page.about_panel.project_card, page.about_panel.release_button),
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
    assert page.viewport().geometry().top() == 0
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
            assert label.height() >= label.heightForWidth(label.width()), (
                card.titleLabel.text(), label.text(), label.geometry(),
                control.geometry(), control.sizeHint(), card.size(),
            )
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


def test_language_selection_saves_stable_values_and_waits_for_restart(settings_page, monkeypatch):
    page, values, writes, _frame = settings_page
    show_hint = Mock()
    monkeypatch.setattr(page, "_show_language_restart_hint", show_hint)

    assert list(page._language_values.values()) == ["Auto", "zh_CN", "zh_HK", "en_US"]
    page.language_card.combo_box.setCurrentText("English")
    page.language_card.combo_box.setCurrentText("English")

    assert values["language"] == "en_US"
    assert writes == [{"language": "en_US"}]
    assert page.accessibleName() == "设置"
    assert "重启" in page.language_card.contentLabel.text()
    show_hint.assert_called_once_with()

    page._reset_settings()
    assert values["language"] == "Auto"
    assert page.language_card.value() == "跟随系统"
    assert writes == [{"language": "en_US"}, {"reset": True}]
    assert show_hint.call_count == 2


@pytest.mark.parametrize("supported", [False, True])
def test_mica_setting_gates_unsupported_systems_without_overwriting_preference(
    settings_page, monkeypatch, supported,
):
    _original, values, writes, frame = settings_page
    monkeypatch.setattr("gui.pages.fluent_pages.is_mica_supported", lambda: supported)
    page = SettingsPage(frame)
    try:
        assert page.mica_card.isEnabled() is supported
        assert values["mica_enabled"] is True
        assert not writes
        if supported:
            page.mica_card.setChecked(False)
            assert writes == [{"mica_enabled": False}]
            frame.setMicaEffectEnabled.assert_called_once_with(False)
            frame._refresh_window_chrome_theme.assert_called_once_with()
        else:
            assert "Windows 11" in page.mica_card.contentLabel.text()
    finally:
        page.close()


@pytest.mark.parametrize("language,title", [("en_US", "Settings"), ("zh_HK", "設定")])
@pytest.mark.parametrize("width,font_size", [(900, 12), (420, 12), (900, 22), (420, 22)])
def test_translated_settings_keep_controls_visible_and_persist_language_independent_values(
    qt_application, settings_page, language, title, width, font_size,
):
    _original, values, writes, frame = settings_page
    translators = install_translators(qt_application, language)
    page = SettingsPage(frame)
    try:
        test_setting_cards_keep_full_text_and_actions_inside_viewport(
            qt_application, (page, values, writes, frame), width, font_size,
        )
        assert page.accessibleName() == title
        assert page.language_card.titleLabel.text() == (
            "Language" if language == "en_US" else "語言"
        )
        page.theme_card.combo_box.setCurrentText(page.THEME_LABELS["Dark"])
        # 独立设置页发主题信号，持久化由真实 MainFrame 消费者负责。
        assert BaseStyles.current_theme() == "Dark"
        page.font_family_card.combo_box.setCurrentText(page.font_family_card.combo_box.itemText(0))
        assert values["font_family"] == ""
        page._reset_settings()
        assert values["language"] == "Auto"
        assert page.language_card.value() == page.LANGUAGE_LABELS["Auto"]
        for card in (page.scan_card, page.mica_card, page.pin_card):
            expected = ("On" if card.isChecked() else "Off") if language == "en_US" else (
                "開" if card.isChecked() else "關"
            )
            assert card.switchButton.label.text() == expected
    finally:
        page.close()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()


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


@pytest.mark.parametrize("width,font_size", [(1000, 12), (420, 12), (1000, 22), (420, 22)])
@pytest.mark.parametrize("status", ["checking", "available", "error", "current", "ahead"])
def test_update_card_states_reflow_and_keep_all_actions_reachable(
    settings_page, qt_application, width, font_size, status,
):
    page, values, _writes, _frame = settings_page
    values["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    page.resize(width, 640)
    page.show()
    about = page.about_panel
    release = ReleaseInfo(
        "3.2.12", "https://github.com/BlackHu-art/ADBLab/releases/tag/v3.2.12",
        datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    about.set_update_snapshot(UpdateSnapshot(
        status=status, release=release, checked_at=datetime.now(timezone.utc),
        error="network" if status == "error" else "", can_check=status != "checking",
    ))
    _settle_settings(qt_application, page)
    assert page.horizontalScrollBar().maximum() == 0
    assert about.check_update_button.isEnabled() == (status != "checking")
    label = about.project_card.contentLabel
    assert label.height() >= label.heightForWidth(label.width())
    for control in (about.check_update_button, about.project_button, about.release_button):
        assert about.project_card.isAncestorOf(control)
        page.ensureWidgetVisible(control, 0, 0)
        qt_application.processEvents()
        visible = control.mapTo(page.viewport(), QPoint())
        assert visible.y() >= 0
        assert visible.y() + control.height() <= page.viewport().height()
        assert visible.x() >= 0
        assert visible.x() + control.width() <= page.viewport().width()
        assert control.font().pointSizeF() == font_size


def test_update_card_only_opens_checked_release_on_explicit_click(settings_page, monkeypatch):
    from utils.app_metadata import APP_VERSION

    page, _values, _writes, _frame = settings_page
    about = page.about_panel
    assert about.project_card.isAncestorOf(about.check_update_button)
    assert about.project_card.isAncestorOf(about.release_button)
    assert about.project_card.contentLabel.text().count(APP_VERSION) == 1
    opener = Mock(return_value=True)
    monkeypatch.setattr("qfluentwidgets.components.widgets.button.QDesktopServices.openUrl", opener)
    requested = Mock()
    about.updateRequested.connect(requested)
    about.check_update_button.click()
    requested.assert_called_once_with()
    opener.assert_not_called()
    about.release_button.click()
    assert not about.release_button.isEnabled()
    opener.assert_not_called()
    major_minor, patch = APP_VERSION.rsplit(".", 1)
    next_version = f"{major_minor}.{int(patch) + 1}"
    release = ReleaseInfo(
        next_version, f"https://github.com/BlackHu-art/ADBLab/releases/tag/v{next_version}",
        datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    opener.reset_mock()
    about.set_update_snapshot(UpdateSnapshot(status="available", release=release))
    assert about.project_card.contentLabel.text().count(APP_VERSION) == 1
    opener.assert_not_called()
    about.release_button.click()
    assert opener.call_args.args[0].toString() == release.url
    about.set_update_snapshot(UpdateSnapshot(status="error", error="network", release=release))
    assert "失败" in about.project_card.contentLabel.text()
    assert "上次" in about.project_card.contentLabel.text()
    assert not about.release_button.isEnabled()


@pytest.mark.parametrize("font_size", [9, 12])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_update_card_keeps_existing_height_and_button_positions_across_checks(
    qt_application, settings_page, font_size, theme,
):
    page, values, _writes, _frame = settings_page
    values["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    page.resize(1000, 640)
    page.show()
    about = page.about_panel
    checked_at = datetime(2026, 9, 11, 7, 15, tzinfo=timezone.utc)
    release = ReleaseInfo(
        "3.2.14", "https://github.com/BlackHu-art/ADBLab/releases/tag/v3.2.14", checked_at,
    )
    # 由 Qt 度量修改前的四行文案；分数缩放下标签测高与整数字体高度可差 1px。
    original_content = QLabel(
        "版本 3.2.11 · 开源项目\nAndroid 设备管理、应用操作与诊断工作台\n"
        "发现新版本 3.2.14 · 发布于 2026-09-11\n检查时间：2026-09-11 15:15", page,
    )
    original_content.setFont(about.project_card.contentLabel.font())
    original_content.setWordWrap(True)
    original_content.hide()
    original_height = (
        about.project_card.titleLabel.heightForWidth(1000) + 6
        + original_content.heightForWidth(1000) + 32
    )
    snapshots = [
        UpdateSnapshot(status="available", release=release, checked_at=checked_at),
        UpdateSnapshot(),
        UpdateSnapshot(status="checking", can_check=False),
        UpdateSnapshot(status="checking", release=release, can_check=False),
        UpdateSnapshot(status="current", release=release, checked_at=checked_at),
        UpdateSnapshot(status="ahead", release=release, checked_at=checked_at),
        UpdateSnapshot(status="available"),
        *[
            UpdateSnapshot(status="error", error=error, release=previous)
            for previous in (None, release)
            for error in (
                "network", "tls", "timeout", "rate_limited", "unavailable", "invalid_response",
            )
        ],
    ]
    original_positions = None
    for snapshot in snapshots:
        about.set_update_snapshot(snapshot)
        _settle_settings(qt_application, page)
        card = about.project_card
        # 保留原四行版本说明的高度，检查过程不能撑高或收缩卡片。
        assert card.height() == original_height
        buttons = (about.project_button, about.check_update_button, about.release_button)
        positions = tuple((button.mapTo(card, QPoint()), button.size()) for button in buttons)
        if original_positions is None:
            original_positions = positions
        assert positions == original_positions
        assert len({button.height() for button in buttons}) == 1
        assert about.release_button.text() == "前往下载"
        assert about.release_button.isEnabled() == (
            snapshot.status == "available" and snapshot.release is not None
        )
        for button in buttons:
            if not button.isEnabled():
                continue
            button.setFocus(Qt.FocusReason.TabFocusReason)
            wait_for_stable_geometry(qt_application, (*buttons, about.update_actions))
            assert tuple(
                (action.mapTo(card, QPoint()), action.size()) for action in buttons
            ) == original_positions


@pytest.mark.parametrize("published", [
    "0001-01-01T00:00:00+14:00", "0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z",
])
def test_release_date_outside_platform_local_time_range_remains_displayable(
    settings_page, published,
):
    from services.app_update import parse_release
    from tests.test_app_update import release_payload

    page, _values, _writes, _frame = settings_page
    release = parse_release(release_payload("v999.0.0", published_at=published))
    page.about_panel.set_update_snapshot(UpdateSnapshot(status="available", release=release))
    assert "999.0.0" in page.about_panel.project_card.contentLabel.text()


@pytest.mark.parametrize("language,button_text", [
    ("zh_CN", "检查更新"), ("en_US", "Check for updates"), ("zh_HK", "檢查更新"),
])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_update_card_translated_states_at_large_font(
    qt_application, settings_page, language, button_text, theme,
):
    _original, values, _writes, frame = settings_page
    values["ui_font_size"] = 22
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    translators = install_translators(qt_application, language)
    page = SettingsPage(frame)
    try:
        page.resize(420, 640)
        page.show()
        about = page.about_panel
        checked_at = datetime(2026, 9, 11, 7, 15, tzinfo=timezone.utc)
        release = ReleaseInfo(
            "3.2.14", "https://github.com/BlackHu-art/ADBLab/releases/tag/v3.2.14", checked_at,
        )
        snapshots = [
            UpdateSnapshot(),
            UpdateSnapshot(status="checking", can_check=False),
            *[UpdateSnapshot(status=status, release=release, checked_at=checked_at)
              for status in ("available", "current", "ahead")],
            *[UpdateSnapshot(status="error", error=error)
              for error in ("network", "tls", "timeout", "rate_limited", "invalid_response")],
        ]
        for snapshot in snapshots:
            about.set_update_snapshot(snapshot)
            _settle_settings(qt_application, page)
            assert about.check_update_button.text() == button_text
            assert page.horizontalScrollBar().maximum() == 0
            assert about.release_button.font().pointSizeF() == 22
            label = about.project_card.contentLabel
            assert label.height() >= label.heightForWidth(label.width())
            page.ensureWidgetVisible(about.release_button, 0, 0)
            qt_application.processEvents()
            point = about.release_button.mapTo(page.viewport(), QPoint())
            assert point.x() >= 0 and point.y() >= 0
            assert point.x() + about.release_button.width() <= page.viewport().width()
            assert point.y() + about.release_button.height() <= page.viewport().height()
    finally:
        page.close()
        page.deleteLater()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()


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
