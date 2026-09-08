"""验证语言解析、Qt 翻译资源和源文案回退，隔离测试进程内的翻译器。"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from string import Formatter

import pytest
from PySide6.QtCore import QCoreApplication, QLocale, QTranslator

from gui import i18n


@pytest.mark.parametrize("locale,expected", [
    ("zh_CN", "zh_CN"), ("zh_SG", "zh_CN"), ("zh_Hans", "zh_CN"),
    ("zh_HK", "zh_HK"), ("zh_MO", "zh_HK"), ("zh_TW", "zh_HK"),
    ("zh_Hant", "zh_HK"), ("zh_Hans_HK", "zh_HK"),
    ("en_US", "en_US"), ("en_GB", "en_US"), ("ja_JP", "en_US"),
    ("de_DE", "en_US"), ("C", "en_US"),
])
def test_auto_language_selects_a_supported_locale(locale, expected):
    assert i18n.resolve_language("Auto", QLocale(locale)) == expected


@pytest.mark.parametrize("language", ["zh_CN", "zh_HK", "en_US"])
def test_explicit_language_is_independent_of_system_locale(language):
    assert i18n.resolve_language(language, QLocale("ja_JP")) == language


def test_auto_and_invalid_language_use_the_real_system_locale():
    expected = i18n.resolve_language("Auto", QLocale.system())
    assert i18n.resolve_language("Auto") == expected
    assert i18n.resolve_language("invalid") == expected


@pytest.fixture
def installed_translators(qt_application):
    installed = []

    def install(language):
        translators = i18n.install_translators(qt_application, language)
        installed.extend(translators)
        return translators

    yield install
    for translator in reversed(installed):
        qt_application.removeTranslator(translator)
        translator.deleteLater()


@pytest.mark.parametrize("language,expected", [
    ("en_US", "Settings"), ("zh_HK", "設定"), ("zh_CN", "设置"),
])
def test_application_catalog_translates_real_text_and_preserves_unknown_entries(
    installed_translators, language, expected,
):
    installed_translators(language)

    assert i18n.tr("设置") == expected
    assert i18n.tr("未收录的测试词条") == "未收录的测试词条"


def test_translation_installation_does_not_change_locale_or_environment(
    qt_application, installed_translators,
):
    locale_before = QLocale().name()
    environment_before = dict(os.environ)

    translators = installed_translators("en_US")

    assert translators
    assert all(translator.parent() is qt_application for translator in translators)
    assert QLocale().name() == locale_before
    assert dict(os.environ) == environment_before


def test_missing_application_resource_preserves_source_text_and_records_diagnostic(
    monkeypatch, caplog, installed_translators,
):
    class MissingAppTranslator(QTranslator):
        def load(self, *args):
            if isinstance(args[0], str) and args[0].startswith(":/adblab/"):
                return False
            return super().load(*args)

    monkeypatch.setattr(i18n, "QTranslator", MissingAppTranslator)
    installed_translators("en_US")

    assert i18n.tr("设置") == "设置"
    assert "Application translation for en_US is unavailable" in caplog.text


def test_traditional_language_uses_qt_and_fluent_catalogs(installed_translators):
    translators = installed_translators("zh_HK")

    assert len(translators) == 3
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") != "Cancel"
    assert QCoreApplication.translate("SwitchButton", "Off") != "Off"


def test_simplified_locale_translates_legacy_english_sources(installed_translators):
    translators = installed_translators("zh_CN")
    assert translators
    assert i18n.tr("Select Default Save Directory") == "选择默认保存目录"


def test_shared_display_helpers_translate_text_but_preserve_menu_data(
    qt_application, installed_translators,
):
    from PySide6.QtWidgets import QWidget
    from qfluentwidgets import PushButton, RoundMenu

    from gui.styles.fluent import add_menu_action, configure_button
    from gui.widgets.content_section import ContentSection

    installed_translators("en_US")
    parent = QWidget()
    button = configure_button(
        PushButton(parent), text="设置", tooltip="选择当前功能分类",
    )
    menu = RoundMenu(parent=parent)
    action = add_menu_action(menu, "设置", data="设置")
    section = ContentSection("设置", parent)
    assert button.text() == "Settings"
    assert button.accessibleName() == "Settings"
    assert button.toolTip() == "Choose the current tool category"
    assert action.text() == "Settings"
    assert action.data() == "设置"
    assert section.headerLabel.text() == "Settings"


@pytest.mark.parametrize("language", ["zh_CN", "en_US", "zh_HK"])
def test_embedded_catalog_matches_editable_source_and_preserves_format_fields(language):
    catalog = QTranslator()
    assert catalog.load(f":/adblab/i18n/adblab.{language}.qm")
    source_file = Path(__file__).resolve().parents[1] / "resources" / "i18n" / (
        f"adblab.{language}.ts"
    )
    messages = ET.parse(source_file).findall("./context/message")
    assert messages
    formatter = Formatter()

    def fields(text):
        return {field for _, field, _, _ in formatter.parse(text) if field}

    for message in messages:
        source = message.findtext("source")
        translated = message.findtext("translation")
        assert source and translated
        assert catalog.translate("ADBLab", source) == translated
        assert fields(source) == fields(translated), source


@pytest.mark.parametrize("language, expected", [
    ("zh_CN", "设备 7未安装目标应用，请先安装后重试"),
    ("zh_HK", "裝置 7未安裝目標應用程式，請先安裝後重試"),
    ("en_US", "The target app is not installed on Device 7. Install it and retry."),
])
def test_monkey_preparation_errors_use_frozen_global_device_label(
    installed_translators, language, expected,
):
    from gui.panels.app_panel import _monkey_error_text

    installed_translators(language)
    label = {"zh_CN": "设备 7", "zh_HK": "裝置 7", "en_US": "Device 7"}[language]
    assert _monkey_error_text("第 1 台设备未安装目标应用，请先安装后重试", (label,)) == expected
