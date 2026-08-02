"""验证二级窗口统一使用应用字体角色，并能响应运行时字体变更。"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyleOptionGroupBox,
    QWidget,
)

from core.settings_manager import AppSettings
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.app_manager import AppDetailsDialog, AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.performance_launcher import PerformanceLauncherDialog
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.styles import BaseStyles
from gui.styles.typography import FontRole


def _font_size(font) -> int:
    return font.pointSize() if font.pointSize() > 0 else font.pixelSize()


def _assert_role(widget_or_font, role: FontRole, *, size: int | None = None) -> None:
    expected = BaseStyles.font_for_role(role, size=size)
    actual = widget_or_font if isinstance(widget_or_font, QFont) else widget_or_font.font()
    assert actual.family() == expected.family()
    assert _font_size(actual) == expected.pointSize()


def _group_title_gap(group: QGroupBox) -> int:
    option = QStyleOptionGroupBox()
    group.initStyleOption(option)
    title_rect = group.style().subControlRect(
        QStyle.ComplexControl.CC_GroupBox,
        option,
        QStyle.SubControl.SC_GroupBoxLabel,
        group,
    )
    children = [
        child
        for child in group.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
        if not child.isHidden()
    ]
    return min(child.geometry().top() for child in children) - title_rect.bottom() - 1


@contextmanager
def _dialog_set(qt_application):
    previous_application_font = QFont(qt_application.font())
    qt_application.setFont(BaseStyles.font_for_role(FontRole.UI))
    with (
        patch.object(AppDetailsDialog, "_load_data"),
        patch.object(AppManagerDialog, "_load_apps"),
        patch.object(FileExplorerDialog, "_refresh"),
    ):
        dialogs = {
            "about": AboutDialog(),
            "details": AppDetailsDialog(None, "test-device", "com.example.app"),
            "apps": AppManagerDialog(device_ip="test-device"),
            "files": FileExplorerDialog(device_ip="test-device"),
            "logcat": LiveLogcatDialog(device_ip="test-device"),
            "performance": PerformanceLauncherDialog(device_ip="test-device"),
            "screenshots": ScreenshotViewer([]),
        }
        try:
            yield dialogs
        finally:
            for dialog in reversed(tuple(dialogs.values())):
                dialog.close()
            qt_application.processEvents()
            qt_application.setFont(previous_application_font)


def test_secondary_dialogs_use_semantic_font_roles(qt_application):
    with _dialog_set(qt_application) as dialogs:
        about = dialogs["about"]
        details = dialogs["details"]
        apps = dialogs["apps"]
        files = dialogs["files"]
        logcat = dialogs["logcat"]
        performance = dialogs["performance"]
        screenshots = dialogs["screenshots"]

        for widget in (
            about,
            apps.search_input,
            files.search_field,
            logcat.level_combo,
            performance.frequency_combo,
            screenshots,
        ):
            _assert_role(widget, FontRole.UI)

        for widget in (
            details.detail_text,
            files.path_field,
            logcat.pkg_input,
            logcat.tag_input,
            performance.package_edit,
            performance.exception_edit,
            performance.phone_log_edit,
            performance.save_path_edit,
            performance.serialnum_label,
            screenshots._path_label,
        ):
            _assert_role(widget, FontRole.MONO)

        for widget in (apps.log_output, logcat.output, performance.log_view):
            _assert_role(widget, FontRole.LOG)
            _assert_role(widget.document().defaultFont(), FontRole.LOG)

        _assert_role(screenshots._info_label, FontRole.UI_SMALL)
        _assert_role(
            about._title,
            FontRole.TITLE,
            size=max(24, BaseStyles.DEFAULT_FONT_SIZE + 12),
        )


@pytest.mark.parametrize(
    ("role", "initial_text_size", "updated_text_size"),
    [(FontRole.MONO, 14, 18), (FontRole.LOG, 12, 16)],
)
def test_file_explorer_temporary_text_dialog_refreshes_font(
    monkeypatch,
    qt_application,
    role,
    initial_text_size,
    updated_text_size,
):
    class SignalStub:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def disconnect(self, callback):
            self.callbacks.remove(callback)

        def emit(self, value):
            for callback in tuple(self.callbacks):
                callback(value)

    sizes = {FontRole.UI: 17, role: initial_text_size}
    signal = SignalStub()
    monkeypatch.setattr(BaseStyles, "fonts_changed", signal)
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, role, size=None: QFont("Arial", size or sizes[FontRole(role)])),
    )
    dialog = QDialog()
    editor = QPlainTextEdit(dialog)
    FileExplorerDialog._bind_dialog_font_refresh(
        dialog,
        lambda: FileExplorerDialog._apply_text_dialog_fonts(
            dialog,
            editor,
            role,
        ),
    )

    assert _font_size(dialog.font()) == 17
    assert _font_size(editor.font()) == initial_text_size
    assert _font_size(editor.document().defaultFont()) == initial_text_size

    sizes.update({FontRole.UI: 20, role: updated_text_size})
    signal.emit(None)
    assert _font_size(dialog.font()) == 20
    assert _font_size(editor.font()) == updated_text_size
    assert _font_size(editor.document().defaultFont()) == updated_text_size

    dialog.reject()
    assert signal.callbacks == []


def test_open_secondary_dialogs_refresh_fonts_and_text_constraints(qt_application, monkeypatch):
    original = BaseStyles.current_font_config()
    settings = {
        "font_family": original.ui_family,
        "ui_font_size": 20,
        "log_font_size": 15,
    }

    class _Settings:
        save_directory = "."

        def get(self, key, default=None):
            return settings.get(key, default)

    monkeypatch.setattr(AppSettings, "instance", staticmethod(lambda: _Settings()))

    with _dialog_set(qt_application) as dialogs:
        try:
            BaseStyles.reload_from_settings()
            qt_application.processEvents()

            apps = dialogs["apps"]
            logcat = dialogs["logcat"]
            performance = dialogs["performance"]
            about = dialogs["about"]

            _assert_role(apps.search_input, FontRole.UI)
            _assert_role(logcat.pkg_input, FontRole.MONO)
            _assert_role(performance.log_view, FontRole.LOG)
            _assert_role(dialogs["screenshots"]._info_label, FontRole.UI_SMALL)

            adaptive_buttons = [
                button
                for button in apps.findChildren(QPushButton)
                if button.property("adaptiveBaseHeight") is not None
            ]
            assert adaptive_buttons
            assert all(
                button.minimumHeight() >= button.sizeHint().height() for button in adaptive_buttons
            )
            assert all(button.maximumHeight() > 1_000_000 for button in adaptive_buttons)

            assert about._close_btn.minimumHeight() >= about._close_btn.sizeHint().height()
            assert about.maximumWidth() > 1_000_000
            assert logcat.btn_get_pkg.minimumWidth() >= logcat.btn_get_pkg.sizeHint().width()
            assert logcat.btn_get_pkg.maximumWidth() > 1_000_000
            assert (
                performance.progress_bar.minimumHeight()
                >= performance.progress_bar.sizeHint().height()
            )
            assert performance.progress_bar.maximumHeight() > 1_000_000
            performance.resize(900, 700)
            performance.show()
            qt_application.processEvents()
            performance_group = performance.findChild(QGroupBox, "performanceConfig")
            assert performance_group is not None
            assert _group_title_gap(performance_group) >= 4
        finally:
            settings.update(
                {
                    "font_family": original.ui_family,
                    "ui_font_size": original.ui_size,
                    "log_font_size": original.log_size,
                }
            )
            BaseStyles.reload_from_settings()
            qt_application.processEvents()
