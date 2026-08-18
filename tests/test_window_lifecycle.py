import os
import subprocess
import sys
from contextlib import ExitStack
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QMainWindow
from shiboken6 import delete

from adblab.presentation.qt_task_supervisor import QtTaskSupervisor
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.app_manager import AppManagerDialog
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.lifecycle import (
    alive_forwarding_callback,
    alive_signal_emitter,
    configure_independent_secondary_window,
    fit_secondary_window_to_owner_screen,
)
from gui.dialogs.live_logcat import LiveLogcatDialog
from gui.dialogs.performance_launcher import PerformanceLauncherDialog
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.dialogs.settings_dialog import SettingsDialog


class _LifecycleProbe(QObject):
    message = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []

    def record(self, *args):
        self.calls.append(args)


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
def test_closing_secondary_window_keeps_main_window_visible(
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
            dialog = AppManagerDialog(device_ip="target")
        elif dialog_kind == "file_explorer":
            stack.enter_context(pytest.MonkeyPatch.context()).setattr(
                FileExplorerDialog, "_refresh", lambda _self: None
            )
            dialog = FileExplorerDialog(device_ip="target")
        elif dialog_kind == "live_logcat":
            dialog = LiveLogcatDialog(
                device_ip="target",
                task_supervisor=QtTaskSupervisor(),
            )
        elif dialog_kind == "performance":
            dialog = PerformanceLauncherDialog(
                device_ip="target",
            )
        else:
            dialog = ScreenshotViewer([])

        if dialog_kind not in {"about", "settings"}:
            configure_independent_secondary_window(dialog)
            assert dialog.parentWidget() is None
            assert dialog.windowModality() == Qt.NonModal
            assert not dialog.windowFlags() & Qt.WindowStaysOnTopHint
            assert dialog.windowFlags() & Qt.WindowCloseButtonHint
            assert not dialog.testAttribute(Qt.WA_QuitOnClose)

        # 避免延迟删除事件泄漏到其他共享 QApplication 的测试。
        dialog.setAttribute(Qt.WA_DeleteOnClose, False)
        dialog.show()
        dialog.close()

        assert main_window.isVisible()

    main_window.close()


def test_deleting_last_screenshot_keeps_main_window_visible(qt_application, tmp_path):
    main_window = QMainWindow()
    main_window.show()

    image_path = tmp_path / "last.png"
    image = QPixmap(120, 80)
    image.fill(Qt.GlobalColor.cyan)
    assert image.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    configure_independent_secondary_window(viewer)
    viewer.setAttribute(Qt.WA_DeleteOnClose, False)
    viewer.show()

    viewer._delete_file()

    assert not viewer.isVisible()
    assert main_window.isVisible()
    assert not image_path.exists()

    main_window.close()


def test_independent_window_policy_detaches_existing_qt_parent(qt_application):
    main_window = QMainWindow()
    dialog = QDialog(main_window, Qt.Window | Qt.WindowStaysOnTopHint)

    configure_independent_secondary_window(dialog)

    assert dialog.parentWidget() is None
    assert dialog.windowModality() == Qt.NonModal
    assert not dialog.windowFlags() & Qt.WindowStaysOnTopHint
    assert dialog.windowFlags() & Qt.WindowCloseButtonHint
    assert not dialog.testAttribute(Qt.WA_QuitOnClose)

    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    dialog.close()
    main_window.close()


def test_secondary_window_is_clamped_to_owner_screen(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(980, 700)
    dialog.resize(1100, 800)
    screen = SimpleNamespace(availableGeometry=lambda: QRect(100, 50, 800, 600))
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(200, 100, 500, 400),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(776, 576)
    assert dialog.size() == QSize(776, 576)
    assert 100 <= dialog.x() <= 124
    assert 50 <= dialog.y() <= 74
    dialog.close()


def test_secondary_window_keeps_smaller_declared_minimum(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(520, 420)
    dialog.resize(760, 620)
    screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1200, 800))
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(100, 100, 860, 500),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(520, 420)
    assert dialog.size() == QSize(760, 620)
    dialog.close()


def test_secondary_window_restores_original_geometry_after_small_screen_clamp(qt_application):
    dialog = QDialog()
    dialog.setMinimumSize(980, 700)
    dialog.resize(1100, 800)
    screen_geometry = {"value": QRect(100, 50, 800, 600)}
    screen = SimpleNamespace(availableGeometry=lambda: screen_geometry["value"])
    owner = SimpleNamespace(
        screen=lambda: screen,
        frameGeometry=lambda: QRect(200, 100, 500, 400),
    )

    fit_secondary_window_to_owner_screen(dialog, owner)
    assert dialog.minimumSize() == QSize(776, 576)
    assert dialog.size() == QSize(776, 576)

    screen_geometry["value"] = QRect(0, 0, 1600, 1000)
    fit_secondary_window_to_owner_screen(dialog, owner)

    assert dialog.minimumSize() == QSize(980, 700)
    assert dialog.size() == QSize(1100, 800)
    dialog.close()


def test_late_callbacks_ignore_deleted_qobject(qt_application):
    probe = _LifecycleProbe()
    probe.message.connect(probe.record)
    forward = alive_forwarding_callback(probe, "record")
    emit = alive_signal_emitter(probe, "message", "RAW")

    forward("direct")
    emit("signal")

    assert probe.calls == [("direct",), ("RAW", "signal")]

    delete(probe)
    forward("late-direct")
    emit("late-signal")


def test_independent_window_has_no_native_transient_parent_in_isolated_process():
    """在隔离 QApplication 中验证原生窗口所有权，避免共享事件队列干扰。"""
    script = """
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow
from gui.dialogs.lifecycle import configure_independent_secondary_window

app = QApplication([])
main_window = QMainWindow()
dialog = QDialog(main_window, Qt.Window | Qt.WindowStaysOnTopHint)
configure_independent_secondary_window(dialog)
dialog.show()
app.processEvents()
handle = dialog.windowHandle()
assert handle is not None
assert handle.transientParent() is None
assert dialog.windowFlags() & Qt.WindowCloseButtonHint
dialog.close()
main_window.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
