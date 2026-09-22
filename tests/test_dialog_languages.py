"""验证业务页真实语言呈现，并保证翻译后的标签不进入设备操作参数。"""

import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
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


@pytest.mark.parametrize("language, single_title, batch_title, file_filter", [
    ("zh_CN", "选择 APK 文件", "选择要安装的 APK 文件", "APK 文件 (*.apk);;所有文件 (*)"),
    ("zh_HK", "選擇 APK 檔案", "選擇要安裝的 APK 檔案", "APK 檔案 (*.apk);;所有檔案 (*)"),
    ("en_US", "Select APK File", "Select APK files to install", "APK Files (*.apk);;All Files (*)"),
])
@pytest.mark.parametrize("operation", ["parse_apk_info", "install_apk", "batch_install_apk"])
def test_apk_choosers_translate_titles_and_filters_without_submitting_on_cancel(
    qt_application, monkeypatch, dialog_language, language, single_title, batch_title,
    file_filter, operation,
):
    from controllers._app import ADBAppMixin
    from controllers._app_install import ADBAppInstallMixin

    dialog_language(language)
    owner = QWidget()
    controller = SimpleNamespace(
        window_owner=owner, _require_devices=Mock(return_value=True),
        _emit_operation=Mock(), _start_install_batch=Mock(), app_model=Mock(),
    )
    multiple = operation == "batch_install_apk"
    chooser = Mock(return_value=([] if multiple else "", ""))
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog." + ("getOpenFileNames" if multiple else "getOpenFileName"),
        chooser,
    )
    try:
        if operation == "parse_apk_info":
            assert ADBAppMixin.parse_apk_info(controller) is None
            controller._emit_operation.assert_not_called()
        else:
            assert getattr(ADBAppInstallMixin, operation)(controller, ["demo-device"]) is None
            controller._emit_operation.assert_called_once_with(
                "batch_install" if multiple else "install", False, "APK selection canceled",
            )
        chooser.assert_called_once_with(
            owner, batch_title if multiple else single_title, "", file_filter,
        )
        controller._start_install_batch.assert_not_called()
        controller.app_model.parse_apk_info_async.assert_not_called()
    finally:
        owner.deleteLater()


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


@pytest.mark.parametrize("language, label, description", [
    ("zh_CN", "清空反向规则", "移除所选设备的全部反向转发规则"),
    ("zh_HK", "清空反向規則", "移除所選裝置的全部反向轉發規則"),
    ("en_US", "Clear reverse rules", "Remove all reverse forwarding rules from selected devices"),
])
def test_reverse_clear_scope_is_explicit_in_every_language(
    qt_application, dialog_language, language, label, description,
):
    from tests.test_system_panel_categories import _build_system_panel

    dialog_language(language)
    panel, widget = _build_system_panel()
    try:
        assert panel.btn_remove_rev.text() == label
        assert panel.btn_remove_rev.toolTip() == description
        assert panel.btn_remove_rev.accessibleDescription() == description
    finally:
        widget.deleteLater()


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
        assert message.content_edit.text() == tr("请先选择应用。")
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
        displayed = content.replace("\n", " ")
        assert message.content_edit.text() == displayed
        assert message.content_edit.toolTip() == content
        assert message.content_edit.accessibleDescription() == content
        expected_font = BaseStyles.font_for_role(FontRole.UI)
        for label in (message.titleLabel, message.content_edit):
            assert label.font().family() == expected_font.family()
            assert label.font().pointSizeF() == expected_font.pointSizeF()
        message.content_edit.selectAll()
        assert message.content_edit.selectedText() == displayed
    finally:
        message.close()
        owner.close()
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("language", ["zh_CN", "zh_HK", "en_US"])
def test_single_line_toast_action_keeps_translation_after_layout(
    qt_application, dialog_language, language,
):
    dialog_language(language)
    owner = QWidget()
    owner.resize(1000, 600)
    owner.show()
    message = show_toast(
        owner, tr("Success"), "example.png", duration=-1,
        action_text="查看结果", on_action=lambda: None,
    )
    assert isinstance(message, ToastNotification)
    try:
        qt_application.processEvents()
        assert message.action_button.text() == tr("查看结果")
        assert message.action_button.toolTip() == tr("查看结果")
        owner.resize(900, 600)
        qt_application.processEvents()
        assert message.action_button.text() == tr("查看结果")
    finally:
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
    created: list = []

    class _FakePermissionWorker(QObject):
        """复刻权限写入 worker 的最小信号面，用于驱动逐项串行批次。"""

        app_details_loaded = Signal(dict)
        permissions_loaded = Signal(list, list, list)
        operation_done = Signal(str)
        operation_feedback = Signal(str, str)
        log_message = Signal(str)
        finished = Signal()

        def __init__(self, _device, operation, **kwargs):
            super().__init__()
            self.operation = operation
            self.kwargs = kwargs
            self.running = False
            created.append(self)

        def start(self) -> None:
            self.running = True

        def isRunning(self) -> bool:
            return self.running

        def abort(self) -> None:
            self.running = False

        def finish(self) -> None:
            self.running = False
            if self.operation == "modify_permission":
                self.operation_done.emit("permissions_changed")
            self.finished.emit()

    monkeypatch.setattr(
        "gui.dialogs.app_manager_details.AppManagerWorker", _FakePermissionWorker
    )
    monkeypatch.setattr(
        "gui.dialogs.app_manager_details.report_feedback", lambda *args, **kwargs: None
    )
    page = AppDetailsPage(device_ip="demo-device")
    page.package_name = "com.example.demo"
    monkeypatch.setattr(page, "_can_operate", lambda: True)

    def submitted_permissions() -> list:
        return [
            (worker.kwargs["permission"], worker.kwargs["action"])
            for worker in created
            if worker.operation == "modify_permission"
        ]

    try:
        page._op([], ["android.permission.RECORD_AUDIO"], [("android.permission.CAMERA", True)])
        page.runtime_list.item(0).setCheckState(Qt.CheckState.Checked)
        page.requested_list.item(0).setCheckState(Qt.CheckState.Checked)
        # 显示文字可任意翻译；参数只来自不可见的原始权限名。
        page.runtime_list.item(0).setText("Translated permission label")
        page.requested_list.item(0).setText("Another translated label")
        page._mp("grant")
        assert submitted_permissions() == [("android.permission.CAMERA", "grant")]
        created[0].finish()
        qt_application.processEvents()
        assert submitted_permissions() == [
            ("android.permission.CAMERA", "grant"),
            ("android.permission.RECORD_AUDIO", "grant"),
        ]
    finally:
        for worker in created:
            if worker.running:
                worker.finish()
        qt_application.processEvents()
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
