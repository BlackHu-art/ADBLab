"""主窗口非视觉动作：快捷键、主题、保存目录与关闭请求。"""

from __future__ import annotations

import os

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFileDialog

from core.settings_manager import AppSettings
from gui.styles import BaseStyles


class MainFrameActions:
    """集中实现主窗口动作，不创建或包装任何 UI 控件。"""

    def __init__(self, frame) -> None:
        self._frame = frame

    def setup_shortcuts(self) -> None:
        bindings = (
            ("F5", self._frame._request_device_refresh),
            ("Ctrl+,", self._frame._show_settings),
            ("Ctrl+Shift+L", self._frame.clear_log),
        )
        self._frame._main_shortcuts = []
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self._frame)
            shortcut.activated.connect(callback)
            self._frame._main_shortcuts.append(shortcut)

    def toggle_theme(self) -> str:
        from gui.main_frame import _debug_log

        _debug_log(
            self._frame,
            "ui.theme",
            action="toggle",
            phase="requested",
            current_theme=BaseStyles.current_theme(),
        )
        return BaseStyles.toggle_theme()

    def request_application_close(self) -> None:
        from gui.main_frame import _debug_log

        _debug_log(self._frame, "ui.window", action="close", phase="requested")
        self._frame.close()

    def choose_save_directory(self) -> None:
        from gui.main_frame import _debug_log

        _debug_log(self._frame, "ui.save_directory", action="choose", phase="requested")
        settings = AppSettings.instance()
        current = settings.save_directory
        directory = QFileDialog.getExistingDirectory(
            self._frame,
            "Select Default Save Directory",
            current if os.path.isdir(current) else "",
        )
        if not directory:
            _debug_log(self._frame, "ui.save_directory", action="choose", phase="cancelled")
            return
        settings.set("save_directory", directory)
        self._frame._refresh_save_path()
        _debug_log(self._frame, "ui.save_directory", action="choose", phase="updated")


__all__ = ["MainFrameActions"]
