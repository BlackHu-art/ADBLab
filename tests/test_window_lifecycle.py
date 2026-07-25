import os
from contextlib import ExitStack

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow

from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.app_manager import AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.performance_launcher import PerformanceLauncherDialog
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.dialogs.settings_dialog import SettingsDialog


@pytest.mark.parametrize(
    "dialog_kind",
    (
        "about",
        "settings",
        "app_manager",
        "file_explorer",
        "live_logcat",
        "performance",
        "screenshot",
    ),
)
def test_closing_owned_secondary_window_keeps_main_window_visible(
    qt_application,
    dialog_kind,
):
    """关闭任一主界面二级窗口时，主窗口必须继续保持可见。"""
    main_window = QMainWindow()
    main_window.show()

    with ExitStack() as stack:
        if dialog_kind == "about":
            dialog = AboutDialog(parent=main_window)
        elif dialog_kind == "settings":
            dialog = SettingsDialog(parent=main_window)
        elif dialog_kind == "app_manager":
            stack.enter_context(pytest.MonkeyPatch.context()).setattr(
                AppManagerDialog, "_load_apps", lambda _self: None
            )
            dialog = AppManagerDialog(parent=main_window, device_ip="target")
        elif dialog_kind == "file_explorer":
            stack.enter_context(pytest.MonkeyPatch.context()).setattr(
                FileExplorerDialog, "_refresh", lambda _self: None
            )
            dialog = FileExplorerDialog(parent=main_window, device_ip="target")
        elif dialog_kind == "live_logcat":
            dialog = LiveLogcatDialog(
                parent=main_window,
                device_ip="target",
                task_supervisor=QtTaskSupervisor(),
            )
        elif dialog_kind == "performance":
            dialog = PerformanceLauncherDialog(
                parent=main_window,
                device_ip="target",
            )
        else:
            dialog = ScreenshotViewer([], parent=main_window)

        # 避免延迟删除事件泄漏到其他共享 QApplication 的测试。
        dialog.setAttribute(Qt.WA_DeleteOnClose, False)
        dialog.show()
        dialog.close()

        assert main_window.isVisible()

    main_window.close()
