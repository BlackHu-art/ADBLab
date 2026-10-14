"""验证语言解析、Qt 翻译资源和源文案回退，隔离测试进程内的翻译器。"""

from __future__ import annotations

import ast
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


@pytest.mark.parametrize("language,expected", [
    ("zh_CN", (
        "此项不能为空，请输入内容",
        "请输入 1–65535 范围内的整数",
        "请输入 0–100 范围内的数值，最多 2 位小数",
        "输入格式无效，请检查后重试",
    )),
    ("zh_HK", (
        "此項不能為空，請輸入內容",
        "請輸入 1–65535 範圍內的整數",
        "請輸入 0–100 範圍內的數值，最多 2 位小數",
        "輸入格式無效，請檢查後重試",
    )),
    ("en_US", (
        "This field is required. Enter a value.",
        "Enter an integer between 1 and 65535.",
        "Enter a number between 0 and 100 with at most 2 decimal places.",
        "Invalid input format. Check the value and try again.",
    )),
])
def test_form_validation_hints_use_bundled_translations(installed_translators, language, expected):
    """错误原因通过实际内嵌词库翻译，保留整数和小数范围占位符。"""
    installed_translators(language)
    actual = (
        i18n.tr("此项不能为空，请输入内容"),
        i18n.tr("请输入 {minimum}–{maximum} 范围内的整数").format(minimum=1, maximum=65535),
        i18n.tr("请输入 {minimum}–{maximum} 范围内的数值，最多 {decimals} 位小数").format(
            minimum=0, maximum=100, decimals=2,
        ),
        i18n.tr("输入格式无效，请检查后重试"),
    )
    assert actual == expected


@pytest.mark.parametrize("language,ready,starting,cleared,status,reading", [
    ("zh_CN",
     "准备采集设备日志\n点击上方「开始」，应用可留空以查看全部日志。",
     "正在启动日志采集\n正在准备日志流，请稍候。",
     "正在等待新日志\n已清空显示，采集仍在继续。",
     "正在启动日志采集…",
     "缓存 2 / 8000 行 · 已暂停跟随（2 行新日志）\n"
     "仅保留最近 8000 行原始日志，超出后移除最旧记录；导出保存当前筛选结果"),
    ("zh_HK",
     "準備擷取裝置日誌\n點擊上方「開始」，應用程式可留空以查看全部日誌。",
     "正在啟動日誌擷取\n正在準備日誌串流，請稍候。",
     "正在等待新日誌\n已清空顯示，擷取仍在繼續。",
     "正在啟動日誌擷取…",
     "緩存 2 / 8000 行 · 已暫停跟隨（2 行新日誌）\n"
     "僅保留最近 8000 行原始日誌，超出後移除最舊記錄；匯出會儲存目前的篩選結果"),
    ("en_US",
     'Ready to capture device logs\n'
     'Click "Start" above. Leave the app field empty to view all logs.',
     "Starting log capture\nPreparing the log stream. Please wait.",
     "Waiting for new logs\nDisplay cleared; capture is still running.",
     "Starting log capture…",
     "Buffered 2 / 8000 lines · Following paused (2 new lines)\n"
     "Only the latest 8000 original log lines are retained; the oldest are removed "
     "when the limit is reached. Export saves the current filtered results."),
], ids=["zh_CN", "zh_HK", "en_US"])
def test_logcat_empty_hints_and_reading_status_use_bundled_translations(
    installed_translators, monkeypatch, language, ready, starting, cleared, status, reading,
):
    """真实页面从内嵌词库显示空态和启动状态，阅读计数保留格式参数。"""
    from gui.dialogs.live_logcat import LiveLogcatPage, LogcatWorker
    from tests.test_live_logcat_empty_state import _release_worker
    from tests.test_phase2_live_logcat_gate import FakeQtTaskSupervisor

    installed_translators(language)
    monkeypatch.setattr(LogcatWorker, "start", lambda _worker: None)
    page = LiveLogcatPage(device_ip="demo", task_supervisor=FakeQtTaskSupervisor())
    try:
        assert page.output.placeholderText() == ready
        assert page.output.accessibleDescription() == ready
        page._start()
        assert page.output.placeholderText() == starting
        assert page.status_bar.text() == page.status_bar.toolTip() == status
        page._on_worker_status(page.worker, "正在采集")
        page._clear()
        assert page.output.placeholderText() == cleared
        assert page.output.accessibleDescription() == cleared
        assert page.output.document().isEmpty()
        page.follow_action.trigger()
        page._on_line("first device record", "I")
        page._on_line("second device record", "I")
        page._flush_pending_lines()
        assert page.cache_ring.toolTip() == reading
        assert page.cache_ring.accessibleDescription() == reading
        assert page.output.toPlainText() == "first device record\nsecond device record"
        assert page.output.placeholderText() == page.output.accessibleDescription() == ""
    finally:
        _release_worker(page)
        page.close()


@pytest.mark.parametrize("language,qr,code,paired", [
    ("zh_CN", "扫码配对", "配对码", "已配对，连接尚未确认"),
    ("zh_HK", "掃碼配對", "配對碼", "已配對，連線尚未確認"),
    ("en_US", "Pair with QR code", "Pairing code", "Paired; connection not confirmed"),
])
def test_wireless_pairing_states_have_bundled_translations(
    installed_translators, language, qr, code, paired,
):
    """三种语言均区分配对入口与尚未确认连接的中间结果。"""
    installed_translators(language)
    assert i18n.tr("扫码配对") == qr
    assert i18n.tr("配对码") == code
    assert i18n.tr("已配对，连接尚未确认") == paired


@pytest.mark.parametrize("language,show_text,hide_text", [
    ("zh_CN", "显示二维码", "收起二维码"),
    ("en_US", "Show QR code", "Hide QR code"),
    ("zh_HK", "顯示二維碼", "收起二維碼"),
])
def test_about_support_toggle_translates_both_states(
    installed_translators, language, show_text, hide_text,
):
    from gui.features.about import AboutPanel

    installed_translators(language)
    panel = AboutPanel()
    try:
        assert panel.support_button.text() == show_text
        panel.support_button.click()
        assert panel.support_button.text() == hide_text
        assert panel.support_button.accessibleName() == hide_text
        panel.support_button.click()
        assert panel.support_button.text() == show_text
    finally:
        panel.close()


@pytest.mark.parametrize("language,single,current,collapse,unknown", [
    ("zh_CN", "单选", "当前", "收起设备", "Android 版本未知"),
    ("zh_HK", "單選", "目前", "收起裝置", "Android 版本未知"),
    ("en_US", "Single selection", "Current", "Collapse devices", "Android version unknown"),
])
def test_inline_device_selector_labels_have_bundled_translations(
    installed_translators, language, single, current, collapse, unknown,
):
    """紧凑选择列表的新短文案在三种界面语言中均可显示。"""
    installed_translators(language)
    assert i18n.tr("单选") == single
    assert i18n.tr("当前") == current
    assert i18n.tr("收起设备") == collapse
    assert i18n.tr("Android 版本未知") == unknown


@pytest.mark.parametrize("language,start,append,retry,summary,details", [
    ("zh_CN", "启动 2 台", "追加启动 2 台", "重试 2 台", "镜像中 2 台", "查看原因"),
    ("zh_HK", "啟動 2 台", "追加啟動 2 台", "重試 2 台", "鏡像中 2 台", "查看原因"),
    ("en_US", "Start 2", "Start 2 more", "Retry 2", "Mirroring: 2", "View details"),
])
def test_mirror_launch_counts_and_failure_details_have_bundled_translations(
    installed_translators, language, start, append, retry, summary, details,
):
    """镜像操作条的数量占位符与失败入口沿用实际打包词库。"""
    installed_translators(language)
    assert i18n.tr("启动 {count} 台").format(count=2) == start
    assert i18n.tr("追加启动 {count} 台").format(count=2) == append
    assert i18n.tr("重试 {count} 台").format(count=2) == retry
    assert i18n.tr("{state} {count} 台").format(state=i18n.tr("镜像中"), count=2) == summary
    assert i18n.tr("查看原因") == details


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

@pytest.mark.parametrize("language,stop,summary", [
    ("en_US", "Stop", "Device Shell: {count}/{checked} using the fast route"),
    ("zh_HK", "停止", "裝置 Shell {count}/{checked} 台使用快速通道"),
    ("zh_CN", "停止", "设备 Shell {count}/{checked} 台使用快速通道"),
])
def test_runtime_scope_and_session_stop_have_bundled_translations(
    installed_translators, language, stop, summary,
):
    installed_translators(language)
    assert i18n.tr("停止") == stop
    translated = i18n.tr("设备 Shell {count}/{checked} 台使用快速通道")
    assert translated == summary
    assert "1/2" in translated.format(count=1, checked=2)


@pytest.mark.parametrize("language,summary,recommendation", [
    ("zh_CN", "Ubuntu 下自动选择", "Ubuntu 下自动选择（推荐）"),
    ("zh_HK", "Ubuntu 下自動選擇", "Ubuntu 下自動選擇（推薦）"),
    ("en_US", "Automatic selection on Ubuntu", "Automatic selection on Ubuntu (recommended)"),
])
def test_adb_host_summary_and_recommendation_use_bundled_translations(
    monkeypatch, installed_translators, language, summary, recommendation,
):
    from PySide6.QtWidgets import QLabel

    from gui.widgets import adb_client_card as cards

    installed_translators(language)
    monkeypatch.setattr(cards, "host_system_name", lambda: "Ubuntu")
    monkeypatch.setattr(cards, "list_adb_candidates", lambda: [])
    card = cards.AdbClientSettingCard()
    try:
        assert card.card.contentLabel.text() == summary
        labels = card.client_button("auto").parentWidget().findChildren(QLabel)
        assert recommendation in [label.text() for label in labels]
        assert card.selection() == "auto"
    finally:
        card.close()


@pytest.mark.parametrize("language,default_sdk,invalid_override", [
    ("en_US", "Android SDK (default macOS location)",
     "The file specified by SCRCPY_PATH is missing or not executable. "
     "Correct or unset this environment variable and retry."),
    ("zh_HK", "Android SDK（macOS 預設目錄）",
     "SCRCPY_PATH 指定的檔案不存在或無法執行，請修正或清除此環境變數後重試。"),
    ("zh_CN", "Android SDK（macOS 默认目录）",
     "SCRCPY_PATH 指定的文件不存在或不可执行，请修正或清除该环境变量后重试。"),
])
def test_macos_tool_sources_and_explicit_override_have_bundled_translations(
    installed_translators, language, default_sdk, invalid_override,
):
    installed_translators(language)
    assert i18n.tr("Android SDK（macOS 默认目录）") == default_sdk
    assert i18n.tr(
        "SCRCPY_PATH 指定的文件不存在或不可执行，请修正或清除该环境变量后重试。",
    ) == invalid_override
    for source in ("Homebrew（Apple Silicon）", "Homebrew（Intel）"):
        expected = source.replace("（", " (").replace("）", ")") if language == "en_US" else source
        assert i18n.tr(source) == expected


@pytest.mark.parametrize("language", ["zh_CN", "en_US", "zh_HK"])
def test_visible_ui_literals_have_catalog_entries(language):
    root = Path(__file__).resolve().parents[1]
    sources = {
        message.findtext("source")
        for message in ET.parse(root / f"resources/i18n/adblab.{language}.ts").findall(
            "./context/message"
        )
    }
    missing = []
    for path in (root / "gui").rglob("*.py"):
        if "generated" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "tr" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value not in sources
            ):
                missing.append((str(path.relative_to(root)), node.lineno, node.args[0].value))
    assert not missing


@pytest.mark.parametrize("language,advanced,add_extra,integer_error,metadata", [
    ("en_US", "Advanced options", "Add broadcast extra",
     "Integer extras must be 32-bit decimal integers", "Run metadata"),
    ("zh_HK", "進階參數", "新增廣播參數",
     "整數 Extra 必須是 32 位十進位整數", "執行中繼資料"),
    ("zh_CN", "高级参数", "添加广播参数",
     "整数 Extra 必须是 32 位十进制整数", "运行元数据"),
])
def test_intent_controls_and_validation_use_bundled_translations(
    installed_translators, language, advanced, add_extra, integer_error, metadata,
):
    from tests.test_system_panel_categories import _build_system_panel

    installed_translators(language)
    panel, widget = _build_system_panel()
    try:
        panel.connect_signals()
        form = panel.intent_controls
        assert form.advanced_toggle.text() == advanced
        assert form.add_extra.text() == add_extra
        panel.broadcast_action.setText("demo.ACTION")
        row = form.add_extra_row()
        row.key.setText("count")
        row.value_type.setCurrentIndex(2)
        row.value.setText("invalid-number")
        assert form.feedback.text() == integer_error
        assert i18n.tr("运行元数据") == metadata
    finally:
        widget.close()
        widget.deleteLater()


@pytest.mark.parametrize("source,expected", [
    ("Extra 值不能包含控制字符", "Extra values cannot contain control characters"),
    ("组件必须是文本", "The component must be text"),
    ("Flags不能包含控制字符", "Flags cannot contain control characters"),
    ("Intent 调试", "Intent debugging"),
    ("运行元数据不完整，部分版本或设备环境未知。",
     "Run metadata is incomplete; some version or device environment details are unknown."),
])
def test_intent_dynamic_errors_and_performance_metadata_have_english_translations(
    installed_translators, source, expected,
):
    installed_translators("en_US")
    assert i18n.tr(source) == expected
