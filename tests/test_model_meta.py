# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import ctypes
import os
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.styles import BaseStyles, theme
from main import windows_app_user_model_id
from utils.app_metadata import APP_RELEASE_TAG, APP_VERSION


def test_app_metadata_derives_release_tag_and_windows_app_id():
    assert APP_RELEASE_TAG == f"v{APP_VERSION}"
    major_minor = APP_VERSION.rsplit(".", 1)[0]
    assert windows_app_user_model_id() == f"ADBLab.Frankie.{major_minor}"


def test_apply_dark_title_bar_calls_dwm_without_ctypes_side_effect_imports():
    had_wintypes = hasattr(ctypes, "wintypes")
    original_wintypes = getattr(ctypes, "wintypes", None)
    if had_wintypes:
        delattr(ctypes, "wintypes")

    window = Mock()
    window.winId.return_value = 12345
    calls = []

    class DwmApi:
        @staticmethod
        def DwmSetWindowAttribute(*args):
            calls.append(args)
            return 0

    try:
        with (
            patch.object(theme.sys, "platform", "win32"),
            patch.object(theme.ctypes, "windll", Mock(dwmapi=DwmApi()), create=True),
        ):
            theme.apply_dark_title_bar(window)
    finally:
        if had_wintypes:
            ctypes.wintypes = original_wintypes

    assert len(calls) == 1


def test_panel_base_status_bar_style_has_theme_background():
    current_theme = BaseStyles.current_theme()
    try:
        BaseStyles.switch_theme("Dark")
        expected_bg = BaseStyles.color("PANEL_BG")
        style = BaseStyles.PANEL_BASE_STYLE()
        marker = "QStatusBar {"
        start = style.index(marker) + len(marker)
        status_bar_block = style[start : style.index("}", start)]
    finally:
        BaseStyles.switch_theme(current_theme)

    assert f"background-color: {expected_bg}" in status_bar_block


def test_dialog_status_bar_style_has_theme_background():
    current_theme = BaseStyles.current_theme()
    try:
        BaseStyles.switch_theme("Dark")
        expected_bg = BaseStyles.color("PANEL_BG")
        style = BaseStyles.STATUS_BAR_STYLE()
    finally:
        BaseStyles.switch_theme(current_theme)

    assert f"background-color: {expected_bg}" in style


def test_combo_box_arrow_uses_theme_specific_qss_resource():
    with patch.object(BaseStyles, "current_theme", return_value="Light"):
        light_style = BaseStyles.INPUT_STYLE()
    with patch.object(BaseStyles, "current_theme", return_value="Dark"):
        dark_style = BaseStyles.INPUT_STYLE()

    assert "QComboBox::down-arrow" in light_style
    assert "icons:caret-down-qss-light.svg" in light_style
    assert "icons:caret-down-qss-dark.svg" in dark_style
    assert "icons:caret-down.svg" not in light_style + dark_style

    icon_dir = Path(__file__).parents[1] / "resources" / "icons"
    light_icon = (icon_dir / "caret-down-qss-light.svg").read_text(encoding="utf-8")
    dark_icon = (icon_dir / "caret-down-qss-dark.svg").read_text(encoding="utf-8")
    assert "currentColor" not in light_icon + dark_icon
    assert "#1a1a1a" in light_icon
    assert "#e0e0e8" in dark_icon


def test_live_logcat_worker_finished_during_close_does_not_touch_deleted_buttons():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.start_btn = Mock()
    dialog.stop_btn = Mock()

    try:
        dialog._on_worker_finished()

        dialog.start_btn.setEnabled.assert_not_called()
        dialog.stop_btn.setEnabled.assert_not_called()
        assert dialog.worker is None
    finally:
        dialog.close()


def test_live_logcat_apply_theme_does_not_reconnect_theme_signal():
    _app = QApplication.instance() or QApplication([])

    class CountingLiveLogcatDialog(LiveLogcatDialog):
        def __init__(self, *args, **kwargs):
            self.theme_calls = 0
            super().__init__(*args, **kwargs)

        def _apply_theme(self, *args, **kwargs):
            self.theme_calls += 1
            return super()._apply_theme(*args, **kwargs)

    dialog = CountingLiveLogcatDialog(device_ip="device-1")
    try:
        BaseStyles.switch_theme("Dark")
        BaseStyles.switch_theme("Light")

        assert dialog.theme_calls == 3
    finally:
        dialog.close()


def test_live_logcat_ignores_queued_status_after_close():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.status_bar = Mock()

    try:
        dialog._on_status("Logcat stopped")

        dialog.status_bar.showMessage.assert_not_called()
    finally:
        dialog.close()


def test_live_logcat_ignores_queued_line_after_close():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    dialog._closing = True
    dialog.output = Mock()

    try:
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: message", "I")

        dialog.output.appendPlainText.assert_not_called()
        assert not dialog.entries
    finally:
        dialog.close()


def test_live_logcat_batches_visible_line_appends():
    _app = QApplication.instance() or QApplication([])
    dialog = LiveLogcatDialog(device_ip="device-1")
    appended = []
    dialog.output = Mock()
    dialog.output.appendPlainText.side_effect = appended.append

    try:
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: one", "I")
        dialog._on_line("05-27 12:00:00.000 1 1 I Tag: two", "I")

        dialog.output.appendPlainText.assert_not_called()
        dialog._flush_pending_lines()

        assert appended == [
            "05-27 12:00:00.000 1 1 I Tag: one\n" "05-27 12:00:00.000 1 1 I Tag: two"
        ]
        assert len(dialog.entries) == 2
    finally:
        dialog.close()
