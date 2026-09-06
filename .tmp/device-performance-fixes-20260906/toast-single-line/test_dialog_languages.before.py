"""验证业务页真实语言呈现，并保证翻译后的标签不进入设备操作参数。"""

import re
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QWidget

from gui.dialogs.app_manager import AppManagerPage
from gui.dialogs.app_manager_details import AppDetailsPage
from gui.dialogs.app_manager_icons import AppManagerIcons
from gui.dialogs.file_explorer import FileExplorerPage
from gui.dialogs.live_logcat import LiveLogcatPage
from gui.dialogs.performance_launcher import PerformancePage
from gui.features.media import ScreenshotPage
from gui.i18n import install_translators, tr
from gui.notifications import ToastNotification, show_toast
from gui.styles import BaseStyles, FontRole
from tests.ui_text_helpers import visible_ui_texts


@pytest.fixture
def dialog_language(qt_application):
    translators = []

    def install(language):
        translators.extend(install_translators(qt_application, language))

    yield install
    for translator in reversed(translators):
        qt_application.removeTranslator(translator)
        translator.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_business_pages_and_error_toast_render_english(
    qt_application, monkeypatch, dialog_language,
):
    monkeypatch.setattr(AppManagerPage, "_load_apps", Mock())
    monkeypatch.setattr(AppManagerPage, "_schedule_visible_detail_load", Mock())
    monkeypatch.setattr(AppManagerIcons, "schedule", Mock())
    monkeypatch.setattr(FileExplorerPage, "_refresh", Mock())
    dialog_language("en_US")
    pages = [
        AppManagerPage(device_ip="demo-device"), FileExplorerPage(device_ip="demo-device"),
        LiveLogcatPage(device_ip="demo-device"), PerformancePage(device_ip="demo-device"),
        ScreenshotPage([]),
    ]
    owner = QWidget()
    owner.resize(1000, 800)
    owner.show()
    message = show_toast(owner, tr("Error"), tr("请先选择应用。"), level="error", duration=-1)
    assert isinstance(message, ToastNotification)
    failures = []
    try:
        pages[0]._populate([("Example", "com.example.demo", "Enabled", "User")])
        # 按需展开的性能参数也属于页面文案，不能只验默认收起态。
        pages[3]._diagnostic_tools.toggle_button.setChecked(True)
        pages[3].monkey_check.setChecked(True)
        for page in [*pages, message]:
            if page is not message:
                page.resize(1000, 900)
            page.show()
            qt_application.processEvents()
            for name, field, text in visible_ui_texts(page):
                if re.search(r"[\u3400-\u9fff]", text):
                    failures.append((type(page).__name__, name, field, text))
        assert not failures, "\n".join(map(str, failures))
        assert message.content_edit.toPlainText() == tr("请先选择应用。")
    finally:
        message.close()
        message.deleteLater()
        owner.close()
        for page in pages:
            page.close()
            page.deleteLater()


@pytest.mark.parametrize("language", ["zh_CN", "zh_HK", "en_US"])
def test_error_toast_preserves_translated_text_format_fields_and_ui_font(
    qt_application, dialog_language, language,
):
    """消息入口替换后保留三语言正文、原始参数和项目字体，正文仍可完整选中。"""
    dialog_language(language)
    owner = QWidget()
    owner.resize(1000, 800)
    owner.show()
    content = tr("Name: {value0}\nPath: {value1}").format(
        value0="example.txt", value1="/example/example.txt",
    )
    message = show_toast(owner, tr("Error"), content, level="error", duration=-1)
    assert isinstance(message, ToastNotification)
    try:
        qt_application.processEvents()
        assert message.titleLabel.text() == tr("Error")
        assert message.content_edit.toPlainText() == content
        assert message.content_edit.accessibleDescription() == content
        expected_font = BaseStyles.font_for_role(FontRole.UI)
        for label in (message.titleLabel, message.content_edit):
            assert label.font().family() == expected_font.family()
            assert label.font().pointSizeF() == expected_font.pointSizeF()
        message.content_edit.selectAll()
        assert message.content_edit.textCursor().selectedText().replace("\u2029", "\n") == content
    finally:
        message.close()
        owner.close()
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("language", ["en_US", "zh_HK"])
def test_translated_file_type_keeps_directory_navigation_key(
    qt_application, monkeypatch, dialog_language, language,
):
    monkeypatch.setattr(FileExplorerPage, "_refresh", Mock())
    dialog_language(language)
    page = FileExplorerPage(device_ip="demo-device")
    page.table.setRowCount(1)
    try:
        page._set_file_row(0, "example", "Folder", "-", "-")
        item = page.table.item(0, page.TYPE_COL)
        assert item.text() == tr("Folder")
        assert item.data(Qt.ItemDataRole.UserRole) == "Folder"
        assert page._file_type_at(0) == "Folder"
        navigate = Mock()
        page._list_controller._navigate = navigate
        page._list_controller._on_double_click(0, page.NAME_COL)
        navigate.assert_called_once_with(page.current_path.rstrip("/") + "/example")
    finally:
        page.close()


@pytest.mark.parametrize("language", ["en_US", "zh_HK"])
def test_permission_submission_uses_raw_names_after_translation(
    qt_application, monkeypatch, dialog_language, language,
):
    dialog_language(language)
    page = AppDetailsPage(device_ip="demo-device")
    page.package_name = "com.example.demo"
    monkeypatch.setattr(page, "_rw", Mock())
    monkeypatch.setattr(page, "_can_operate", lambda: True)
    try:
        page._op([], ["android.permission.RECORD_AUDIO"], [("android.permission.CAMERA", True)])
        page.runtime_list.item(0).setCheckState(Qt.CheckState.Checked)
        page.requested_list.item(0).setCheckState(Qt.CheckState.Checked)
        # 显示文字可任意翻译；参数只来自不可见的原始权限名。
        page.runtime_list.item(0).setText("Translated permission label")
        page.requested_list.item(0).setText("Another translated label")
        page._mp("grant")
        permissions = [call.kwargs["permission"] for call in page._rw.call_args_list]
        assert permissions == ["android.permission.CAMERA", "android.permission.RECORD_AUDIO"]
        assert all(call.kwargs["action"] == "grant" for call in page._rw.call_args_list)
    finally:
        page.close()


def test_app_filter_uses_stable_values_with_english_labels(
    qt_application, monkeypatch, dialog_language,
):
    monkeypatch.setattr(AppManagerPage, "_load_apps", Mock())
    monkeypatch.setattr(AppManagerPage, "_schedule_visible_detail_load", Mock())
    monkeypatch.setattr(AppManagerIcons, "schedule", Mock())
    dialog_language("en_US")
    page = AppManagerPage(device_ip="demo-device")
    try:
        page._populate([
            ("User app", "com.example.user", "Enabled", "User"),
            ("System app", "com.example.system", "Enabled", "System"),
        ])
        page.type_filter.setCurrentIndex(1)
        assert page.type_filter.currentData() == "User Apps"
        assert page.proxy.rowCount() == 1
        assert page.proxy.index(0, 2).data() == "com.example.user"
        assert page.proxy.index(0, 5).data() == "User"
    finally:
        page.close()
