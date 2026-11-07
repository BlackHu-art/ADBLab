"""设置页字号、响应式卡片和配置交互的回归覆盖。"""

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QWidget
from qfluentwidgets import FluentIcon, FluentWindow

from core.diagnostics import DiagnosticJournal
from core.settings_manager import DEFAULTS, AppSettings
from gui.action_feedback import ActionFeedbackPresenter
from gui.i18n import install_translators, tr
from gui.pages.fluent_pages import SettingsPage
from gui.styles import BaseStyles, FontRole
from services.app_update import ReleaseInfo, UpdateSnapshot
from tests.test_settings_expand_animation import make_page as make_page
from tests.ui_geometry_helpers import assert_contained, wait_for_stable_geometry, wait_until


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
        (page.diagnostics_card, page.diagnostics_card.button),
        (page.restart_adb_card, page.restart_adb_card.button),
        (page.about_panel.project_card, page.about_panel.project_button),
        (page.about_panel.project_card, page.about_panel.check_update_button),
        (page.about_panel.project_card, page.about_panel.release_button),
        (page.about_panel.support_card, page.about_panel.support_button),
    )


def _settle_settings(qt_application, page):
    wait_until(qt_application, lambda: (
        page.about_panel.support_reveal.animation.state() == QAbstractAnimation.State.Stopped
    ))
    cards = [card for card, _control in _setting_card_controls(page)]
    cards.append(page.about_panel.support_card)
    wait_for_stable_geometry(qt_application, (page, *cards))


@pytest.fixture
def settings_page(monkeypatch, qt_application):
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda self: None,
    )
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


def test_visible_resize_defers_and_coalesces_settings_reflow(
    qt_application, settings_page, monkeypatch,
):
    page, _values, _writes, _frame = settings_page
    page.resize(1000, 640)
    page.show()
    qt_application.processEvents()

    calls = []
    monkeypatch.setattr(
        page, "_reflow_settings", lambda *, force=True: calls.append(force),
    )
    page.resize(900, 640)
    qt_application.processEvents()
    assert calls == [True]
    page.resize(880, 640)
    qt_application.processEvents()
    assert calls == [True]
    QTest.qWait(90)
    assert calls == [True, False]


def test_accent_color_changes_are_coalesced_and_flushed_on_shutdown(
    qt_application, settings_page, monkeypatch,
):
    page, _values, writes, _frame = settings_page
    applied: list[str] = []
    monkeypatch.setattr(
        BaseStyles,
        "set_accent_color",
        classmethod(lambda _cls, color: applied.append(color) or color),
    )

    page._set_accent_color(QColor("#112233"))
    page._set_accent_color(QColor("#445566"))
    assert applied == []

    QTest.qWait(160)
    assert applied == ["#445566"]
    assert writes[-1] == {"accent_color": "#445566"}

    page._set_accent_color(QColor("#abcdef"))
    page.prepare_shutdown()
    assert writes[-1] == {"accent_color": "#ABCDEF"}
    assert applied == ["#445566"]


def test_reset_cancels_pending_accent_color(qt_application, settings_page, monkeypatch):
    page, values, _writes, _frame = settings_page
    applied: list[str] = []
    monkeypatch.setattr(
        BaseStyles,
        "set_accent_color",
        classmethod(lambda _cls, color: applied.append(color) or color),
    )

    page._set_accent_color(QColor("#112233"))
    page._reset_settings()
    QTest.qWait(160)

    assert applied[-1] == "#0F6CBD"
    assert "#112233" not in applied
    assert values["accent_color"] == "#0F6CBD"


@pytest.mark.parametrize("width,font_size", [(1000, 12), (420, 12), (1000, 22), (420, 22)])
def test_initial_settings_reflow_uses_final_path_font_metrics(
    qt_application, settings_page, width, font_size,
):
    page, values, writes, _frame = settings_page
    values["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    page.resize(width, 640)
    page.show()
    _settle_settings(qt_application, page)
    path = page.save_card.contentLabel
    assert path.height() == path.fontMetrics().height()
    initial = (
        page.save_card.height(), page.save_card.parentWidget().height(),
        page.widget().height(), page.verticalScrollBar().maximum(),
    )

    page._reflow_settings()
    _settle_settings(qt_application, page)

    assert (
        page.save_card.height(), page.save_card.parentWidget().height(),
        page.widget().height(), page.verticalScrollBar().maximum(),
    ) == initial
    assert not writes


@pytest.mark.parametrize("width,font_size", [(1000, 12), (420, 12), (1000, 22), (420, 22)])
def test_diagnostics_card_and_dynamic_summary_remain_inside_visible_ancestors(
    qt_application, settings_page, width, font_size,
):
    page, values, _writes, _frame = settings_page
    values["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    page.resize(width, 640)
    page.show()
    _settle_settings(qt_application, page)
    card = page.diagnostics_card
    group = card.parentWidget()
    page.ensureWidgetVisible(card.button, 0, 0)
    qt_application.processEvents()
    assert not card.button.isEnabled()
    assert_contained(card, group)
    assert_contained(card.button, card)
    assert_contained(card.button, page.viewport())
    assert card.button.visibleRegion().boundingRect() == card.button.rect()

    host = QWidget()
    host._settings_page = page
    host._closing = False
    journal = DiagnosticJournal()
    host.log_service = Mock(diagnostics=journal)
    host.run_library = Mock()
    host.left_panel = Mock()
    host.adb_controller = Mock()
    host._task_page = Mock()
    presenter = ActionFeedbackPresenter(host)
    presenter.export_result = Mock()
    QTest.mouseClick(card.button, Qt.MouseButton.LeftButton)
    presenter.export_result.assert_not_called()
    before = (card.height(), group.height(), page.widget().height())
    try:
        message = "保存应用设置时发生异常，请检查输出目录后重试。" * 5
        journal.accept([("12:00:00", "ERROR", message)])
        presenter._diagnostics_changed(notify=False)
        page.ensureWidgetVisible(card.button, 0, 0)
        _settle_settings(qt_application, page)
        wait_for_stable_geometry(qt_application, (
            page.widget(), group, card, card.titleLabel, card.contentLabel, card.button,
        ))
        assert card.button.isEnabled()
        assert "保存应用设置" in card.contentLabel.text()
        assert card.button.accessibleDescription() == card.contentLabel.text()
        assert card.contentLabel.height() >= card.contentLabel.heightForWidth(
            card.contentLabel.width(),
        )
        assert all(after > previous for after, previous in zip(
            (card.height(), group.height(), page.widget().height()), before,
        ))
        assert_contained(card, group)
        for control in (card.titleLabel, card.contentLabel, card.button):
            assert_contained(control, control.parentWidget())
            assert_contained(control, card)
            assert_contained(control, group)
        page.ensureWidgetVisible(card.button, 0, 0)
        qt_application.processEvents()
        assert_contained(card.button, page.viewport())
        assert card.button.visibleRegion().boundingRect() == card.button.rect()
        QTest.mouseClick(card.button, Qt.MouseButton.LeftButton)
        presenter.export_result.assert_called_once_with("application-diagnostics", journal.text())
        journal.entries.clear()
        journal.accept([("12:00:01", "INFO", "运行状态已更新")], include_info=True)
        presenter._diagnostics_changed(notify=False)
        _settle_settings(qt_application, page)
        assert (card.height(), group.height(), page.widget().height()) == before
        assert card.button.isEnabled()
        assert_contained(card, group)
        assert card.button.accessibleDescription() == card.contentLabel.text()
        assert_contained(card.contentLabel, card.contentLabel.parentWidget())
    finally:
        host.close()


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
            assert_contained(label, label.parentWidget())
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


@pytest.mark.parametrize("language,auto_label", [
    ("zh_CN", "跟随系统"), ("zh_HK", "跟隨系統"), ("en_US", "Use system setting"),
])
@pytest.mark.parametrize("stored_size", ["Auto", 8, 12, 22])
def test_settings_size_choices_show_raw_auto_or_saved_numeric_value_without_writing(
    qt_application, settings_page, language, auto_label, stored_size,
):
    _original, values, writes, frame = settings_page
    values["ui_font_size"] = stored_size
    translators = install_translators(qt_application, language)
    page = SettingsPage(frame)
    try:
        page.resize(420, 640)
        page.show()
        _settle_settings(qt_application, page)
        combo = page.ui_size_card.combo_box
        assert [combo.itemText(index) for index in range(combo.count())] == [
            auto_label, *map(str, range(8, 23)),
        ]
        assert page.ui_size_card.value() == (
            auto_label if stored_size == "Auto" else str(stored_size)
        )
        assert values["ui_font_size"] == stored_size
        assert not writes
    finally:
        page.close()
        for translator in reversed(translators):
            qt_application.removeTranslator(translator)
            translator.deleteLater()


def test_settings_auto_size_round_trip_preserves_raw_choice_when_other_fonts_change(
    qt_application, settings_page,
):
    page, values, writes, _frame = settings_page
    page.resize(420, 640)
    page.show()
    _settle_settings(qt_application, page)
    original_path = values["save_directory"]
    page.ui_size_card.combo_box.setCurrentText("22")
    _settle_settings(qt_application, page)
    assert values["ui_font_size"] == 22
    assert page.mica_card.titleLabel.font().pointSizeF() == 22

    page.ui_size_card.combo_box.setCurrentText(tr("跟随系统"))
    _settle_settings(qt_application, page)
    assert values["ui_font_size"] == "Auto"
    assert writes[-1] == {
        "font_family": "Microsoft YaHei", "ui_font_size": "Auto", "log_font_size": 9,
    }
    page.font_family_card.combo_box.setCurrentText(tr("系统默认"))
    page.log_size_card.combo_box.setCurrentText("10")
    _settle_settings(qt_application, page)
    assert writes[-1] == {
        "font_family": "", "ui_font_size": "Auto", "log_font_size": 10,
    }
    assert all(change["ui_font_size"] == "Auto" for change in writes[1:])
    assert values["save_directory"] == original_path

    page.ui_size_card.combo_box.setCurrentText("8")
    _settle_settings(qt_application, page)
    assert values["ui_font_size"] == 8
    assert values["font_family"] == ""
    assert values["log_font_size"] == 10
    assert page.mica_card.titleLabel.font().pointSizeF() == 8


def test_settings_font_change_and_restore_preserve_values_and_signal_contract(
    qt_application, settings_page, monkeypatch,
):
    monkeypatch.setitem(DEFAULTS, "ui_font_size", "Auto")
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
    assert values["ui_font_size"] == "Auto"
    assert page.ui_size_card.value() == tr("跟随系统")
    assert page.log_size_card.value() == "9"
    assert page.scan_card.isChecked() is True
    assert (
        page.mica_card.titleLabel.font().pointSizeF()
        == BaseStyles.font_for_role(FontRole.UI).pointSizeF()
    )
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
    assert not about.support_qr.isVisibleTo(page)
    about.support_button.click()
    _settle_settings(qt_application, page)
    for theme in ("Light", "Dark"):
        BaseStyles.switch_theme(theme)
        _settle_settings(qt_application, page)
        for control in (about.project_button, about.support_qr):
            assert control.isVisibleTo(page)
            page.ensureWidgetVisible(control, 0, 0)
            qt_application.processEvents()
            position = control.mapTo(page.viewport(), QPoint())
            assert position.y() >= 0
            assert position.y() + control.height() <= page.viewport().height()
            assert position.x() >= 0
            assert position.x() + control.width() <= page.viewport().width()
        assert page.horizontalScrollBar().maximum() == 0
        assert about.support_qr.width() == about.support_qr.height() == 196
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


@pytest.mark.parametrize("width,font_size", [(1000, 12), (420, 12), (1000, 22), (420, 22)])
def test_about_support_qr_expands_on_click_and_collapses_with_keyboard(
    qt_application, settings_page, width, font_size,
):
    page, values, writes, _frame = settings_page
    values["ui_font_size"] = font_size
    BaseStyles.reload_from_settings()
    page.resize(width, 640)
    page.show()
    _settle_settings(qt_application, page)
    about = page.about_panel
    assert not about.support_qr.isVisibleTo(page)
    button = about.support_button
    assert button.isVisibleTo(page)
    assert button.text() == "显示二维码"
    assert button.accessibleName() == button.text()
    collapsed_height = about.support_card.height()
    collapsed_scroll_maximum = page.verticalScrollBar().maximum()

    for _ in range(2):
        page.ensureWidgetVisible(button, 0, 0)
        qt_application.processEvents()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        _settle_settings(qt_application, page)
        assert about.support_qr.isVisibleTo(page)
        assert not about.support_qr.image.isNull()
        assert button.isChecked()
        assert button.text() == "收起二维码"
        assert button.accessibleName() == button.text()
        assert about.support_card.height() > collapsed_height
        assert page.verticalScrollBar().maximum() > collapsed_scroll_maximum
        position = about.support_qr.mapTo(about.support_card, QPoint())
        assert position.y() >= button.mapTo(about.support_card, QPoint()).y() + button.height()
        assert position.y() + about.support_qr.height() <= about.support_card.height()
        assert page.horizontalScrollBar().maximum() == 0

        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Space)
        _settle_settings(qt_application, page)
        assert not about.support_qr.isVisibleTo(page)
        assert not button.isChecked()
        assert button.text() == "显示二维码"
        assert about.support_card.height() == collapsed_height
        assert page.verticalScrollBar().maximum() == collapsed_scroll_maximum
    assert not writes


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
        UpdateSnapshot(status="idle", release=release),
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
        if snapshot.status == "idle":
            assert "更新状态：尚未检查" in card.contentLabel.text()
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
    page.about_panel.support_button.click()
    _settle_settings(qt_application, page)
    assert page.about_panel.support_qr.isVisibleTo(page)
    card = page.about_panel.support_card
    icon = card.iconLabel
    center = icon.mapTo(card, icon.rect().center()).y()
    title_top = card.titleLabel.mapTo(card, QPoint()).y()
    description_bottom = card.contentLabel.mapTo(card, card.contentLabel.rect().bottomLeft()).y()
    assert title_top <= center <= description_bottom


@pytest.mark.parametrize("width,font_size", [(1000, 12), (420, 22)])
@pytest.mark.parametrize("language", ["zh_CN", "en_US", "zh_HK"])
def test_support_toggle_keeps_header_in_place_without_reflowing_other_cards(
    qt_application, make_page, monkeypatch, width, font_size, language,
):
    page = make_page(width, font_size, language)
    _settle_settings(qt_application, page)
    about = page.about_panel
    page.ensureWidgetVisible(about.support_button, 0, 0)
    qt_application.processEvents()
    header = (about.support_card.titleLabel, about.support_card.contentLabel, about.support_button)
    positions = [widget.mapTo(about.support_card, QPoint()) for widget in header]
    calls = []
    for presentation in page._card_presentations:
        original = presentation.reflow

        def record(width, original=original):
            calls.append(width)
            original(width)

        monkeypatch.setattr(presentation, "reflow", record)

    heights = []
    for expanded in (True, False, True, False):
        about.support_button.setChecked(expanded)
        qt_application.processEvents()
        heights.append(about.support_card.height())
        assert [widget.mapTo(about.support_card, QPoint()) for widget in header] == positions
    _settle_settings(qt_application, page)
    assert heights[0] == heights[2] > heights[1] == heights[3]
    assert not calls, "二维码显隐只应同步局部高度，不能重排其他设置卡"


def test_support_toggle_commits_complete_content_before_returning(
    qt_application, make_page,
):
    page = make_page(1000, 15)
    _settle_settings(qt_application, page)
    about = page.about_panel
    button = about.support_button
    collapsed_height = about.support_card.height()
    for expanded in (True, False, True, False, True):
        button.setChecked(expanded)
        assert about.support_reveal.animation.state() == QAbstractAnimation.State.Stopped
        assert about.support_reveal.height() == (about.support_actions.height() if expanded else 0)
        assert about.support_qr.isVisibleTo(page) is expanded
        assert about.support_card.height() == collapsed_height + about.support_reveal.height()
    page.hide()
    qt_application.processEvents()
    assert about.support_reveal.animation.state() == QAbstractAnimation.State.Stopped
    assert about.support_reveal.height() == about.support_actions.height()
    page.show()
    _settle_settings(qt_application, page)
    button.setChecked(False)
    _settle_settings(qt_application, page)
    assert about.support_card.height() == collapsed_height
    assert not about.support_qr.isVisibleTo(page)


@pytest.mark.parametrize("width,font_size", [(1000, 12), (420, 22)])
def test_support_toggle_never_moves_header_or_clip_through_intermediate_positions(
    qt_application, make_page, width, font_size,
):
    page = make_page(width, font_size)
    about = page.about_panel
    about.support_button.setChecked(True)
    qt_application.processEvents()
    moved = []

    class PositionProbe(QObject):
        def eventFilter(self, watched, event):
            if (event.type() == QEvent.Type.Move and watched.isVisibleTo(page)
                    and event.pos() != event.oldPos()):
                moved.append((type(watched).__name__, event.oldPos(), event.pos()))
            return False

    probe = PositionProbe(page)
    presentation = about._support_presentation
    for widget in (presentation.column, presentation.header, about.support_reveal):
        widget.installEventFilter(probe)
    for expanded in (False, True, False, True, False):
        about.support_button.setChecked(expanded)
        qt_application.processEvents()
        assert presentation.column.height() == (
            presentation.header.height() + about.support_reveal.height()
        )
        target = about.support_qr if expanded else about.support_button
        page.ensureWidgetVisible(target, 0, 0)
        qt_application.processEvents()
        assert not target.visibleRegion().isEmpty()
    assert not moved, "单帧内往返位移也会造成闪烁，不能只检查事件循环结束后的坐标"


def test_support_qr_shows_only_code_with_white_scan_margin(settings_page):
    page, _values, _writes, _frame = settings_page
    image = page.about_panel.support_qr.image
    assert not image.isNull()
    side = image.width()
    assert image.height() == side
    for y in range(side):
        for x in range(side):
            color = image.pixelColor(x, y)
            assert not (color.blue() > 180 and color.red() < 80), "不应保留收款页蓝色外框"
    for x, y in ((0, 0), (side // 2, 0), (0, side // 2), (side // 2, side - 1)):
        assert image.pixelColor(x, y).lightness() >= 250


@pytest.mark.parametrize("width,font_size", [(1000, 12), (420, 12), (1000, 22), (420, 22)])
@pytest.mark.parametrize("language,heading,hint,thanks", [
    ("zh_CN", "支付宝扫码支持", "打开支付宝「扫一扫」扫描二维码",
     "感谢你支持 ADBLab 的开发与维护。"),
    ("zh_HK", "支付寶掃碼支持", "開啟支付寶「掃一掃」掃描二維碼",
     "感謝你支持 ADBLab 的開發與維護。"),
    ("en_US", "Support with Alipay", "Open Alipay and use Scan to scan this code.",
     "Thank you for supporting ADBLab's development and maintenance."),
])
def test_support_details_explain_alipay_and_fit_responsive_layout(
    qt_application, make_page, width, font_size, language, heading, hint, thanks,
):
    page = make_page(width, font_size, language)
    about = page.about_panel
    labels = {label.text(): label for label in about.support_actions.findChildren(QLabel)
              if label.text()}
    assert {heading, hint, thanks} <= labels.keys()
    assert all(not labels[text].isVisibleTo(page) for text in (heading, hint, thanks))
    about.support_button.click()
    _settle_settings(qt_application, page)
    for theme in ("Light", "Dark"):
        BaseStyles.switch_theme(theme)
        _settle_settings(qt_application, page)
        for control in (labels[heading], labels[hint], labels[thanks], about.support_qr):
            assert control.isVisibleTo(page)
            assert_contained(control, about.support_card)
            page.ensureWidgetVisible(control, 0, 0)
            qt_application.processEvents()
            point = control.mapTo(page.viewport(), QPoint())
            assert point.x() >= 0 and point.x() + control.width() <= page.viewport().width()
        for label in labels.values():
            assert label.height() >= label.heightForWidth(label.width())
        qr = about.support_qr.mapTo(about.support_card, QPoint())
        instructions = labels[hint].mapTo(about.support_card, QPoint())
        assert instructions.x() < qr.x() if width == 1000 else instructions.y() < qr.y()
        assert page.horizontalScrollBar().maximum() == 0
