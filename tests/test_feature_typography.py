"""验证内嵌功能页统一使用应用字体角色，并响应运行时字体变更。"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPushButton, QScrollArea
from qfluentwidgets import HeaderCardWidget

from core.settings_manager import AppSettings
from gui.features import AboutPanel
from gui.features.app_manager import AppDetailsPage, AppManagerPage
from gui.features.file_explorer import FileExplorerPage
from gui.features.logcat import LiveLogcatPage
from gui.features.media import ScreenshotPage
from gui.features.performance import PerformancePage
from gui.styles import BaseStyles
from gui.styles.typography import FontRole
from tests.ui_geometry_helpers import assert_scroll_target_reachable


def _font_size(font) -> int:
    return font.pointSize() if font.pointSize() > 0 else font.pixelSize()


def _assert_role(widget_or_font, role: FontRole, *, size: int | None = None) -> None:
    expected = BaseStyles.font_for_role(role, size=size)
    actual = widget_or_font if isinstance(widget_or_font, QFont) else widget_or_font.font()
    assert actual.family() == expected.family()
    assert _font_size(actual) == expected.pointSize()


@contextmanager
def _feature_page_set(qt_application):
    previous_application_font = QFont(qt_application.font())
    qt_application.setFont(BaseStyles.font_for_role(FontRole.UI))
    with (
        patch.object(AppDetailsPage, "_load_data"),
        patch.object(AppManagerPage, "_load_apps"),
        patch.object(FileExplorerPage, "_refresh"),
    ):
        pages = {
            "about": AboutPanel(),
            "details": AppDetailsPage(None, "test-device", "com.example.app"),
            "apps": AppManagerPage(device_ip="test-device"),
            "files": FileExplorerPage(device_ip="test-device"),
            "logcat": LiveLogcatPage(device_ip="test-device"),
            "performance": PerformancePage(device_ip="test-device"),
            "screenshots": ScreenshotPage([]),
        }
        try:
            yield pages
        finally:
            for page in reversed(tuple(pages.values())):
                dispose = getattr(page, "request_dispose", None)
                if callable(dispose):
                    dispose("test_cleanup")
                page.close()
            qt_application.processEvents()
            qt_application.setFont(previous_application_font)


def test_feature_pages_use_semantic_font_roles(qt_application):
    with _feature_page_set(qt_application) as pages:
        about = pages["about"]
        details = pages["details"]
        apps = pages["apps"]
        files = pages["files"]
        logcat = pages["logcat"]
        performance = pages["performance"]
        screenshots = pages["screenshots"]

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
            about.title_label,
            FontRole.TITLE,
        )


@pytest.mark.parametrize(
    ("role", "initial_text_size", "updated_text_size"),
    [(FontRole.MONO, 14, 18), (FontRole.LOG, 12, 16)],
)
def test_file_explorer_inline_preview_refreshes_font(
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

    sizes = {
        FontRole.UI: 17,
        FontRole.TITLE: 19,
        FontRole.MONO: 14,
        FontRole.LOG: 12,
    }
    sizes[role] = initial_text_size
    signal = SignalStub()
    monkeypatch.setattr(BaseStyles, "fonts_changed", signal)
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(
            lambda _cls, role, size=None: QFont(
                "Arial",
                size or sizes.get(FontRole(role), sizes[FontRole.UI]),
            )
        ),
    )
    page = FileExplorerPage(device_ip="device-1")
    editor = page.preview_text_edit if role is FontRole.MONO else page.preview_output

    assert _font_size(page.font()) == 17
    assert _font_size(editor.font()) == initial_text_size
    assert _font_size(editor.document().defaultFont()) == initial_text_size

    sizes.update({FontRole.UI: 20, role: updated_text_size})
    signal.emit(None)
    assert _font_size(page.font()) == 20
    assert _font_size(editor.font()) == updated_text_size
    assert _font_size(editor.document().defaultFont()) == updated_text_size

    assert page.request_dispose("test") is True
    assert signal.callbacks == []


def test_loaded_feature_pages_refresh_fonts_and_text_constraints(qt_application, monkeypatch):
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

    with _feature_page_set(qt_application) as pages:
        try:
            BaseStyles.reload_from_settings()
            qt_application.processEvents()
            apps = pages["apps"]
            logcat = pages["logcat"]
            performance = pages["performance"]
            about = pages["about"]

            _assert_role(apps.search_input, FontRole.UI)
            _assert_role(logcat.pkg_input, FontRole.MONO)
            _assert_role(performance.log_view, FontRole.LOG)
            _assert_role(pages["screenshots"]._info_label, FontRole.UI_SMALL)

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

            assert about.support_qr.size().width() == 132
            assert about.maximumWidth() > 1_000_000
            assert logcat.btn_get_pkg.minimumWidth() >= logcat.btn_get_pkg.sizeHint().width()
            assert logcat.btn_get_pkg.maximumWidth() > 1_000_000
            assert performance.progress_bar.maximumHeight() == 4
            performance.resize(900, 700)
            performance.show()
            qt_application.processEvents()
            performance_group = performance.findChild(
                HeaderCardWidget, "performanceConfig"
            )
            assert performance_group is not None
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


def test_performance_large_font_keeps_bounded_scrollable_content(
    qt_application,
    monkeypatch,
):
    original = BaseStyles.current_font_config()
    settings = {
        "font_family": original.ui_family,
        "ui_font_size": 22,
        "log_font_size": original.log_size,
    }

    class _Settings:
        save_directory = "."

        def get(self, key, default=None):
            return settings.get(key, default)

    monkeypatch.setattr(AppSettings, "instance", staticmethod(lambda: _Settings()))
    page = None
    try:
        BaseStyles.reload_from_settings()
        qt_application.processEvents()
        page = PerformancePage(device_ip="test-device")
        page.show()
        qt_application.processEvents()

        assert page.minimumSize().width() == 0
        assert page.minimumSize().height() == 0
        assert page.findChildren(QScrollArea) == [page._config_scroll]
        assert page._config_scroll.verticalScrollBar().maximum() > 0
        assert_scroll_target_reachable(page._config_scroll, page.package_edit)
        assert_scroll_target_reachable(page._config_scroll, page.phone_log_edit)
        assert page.log_view.height() <= 110
    finally:
        if page is not None:
            page._theme_sync_timer.stop()
            page.close()
        settings.update(
            {
                "font_family": original.ui_family,
                "ui_font_size": original.ui_size,
                "log_font_size": original.log_size,
            }
        )
        BaseStyles.reload_from_settings()
        qt_application.processEvents()
