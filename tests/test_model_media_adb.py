# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import os
import subprocess
import threading
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from core.adb_bridge import ADBBridge, ADBInputSession
from core.log_service import LogService
from gui.dialogs.file_explorer import FileExplorerDialog
from gui.dialogs.screenshot_viewer import ScreenshotViewer
from gui.panels.log_panel import LogPanel
from models.adb_advanced import ADBAdvanced
from models.adb_app import ADBApp
from models.adb_system import ADBSystemMixin
from models.adb_testing import ADBTesting
from models.base.command_runner import CommandResult
from models.file_explorer_worker import ADBWorker, TransferWorker


def test_screenshot_viewer_opens_folder_via_process_runner():
    path = os.path.abspath(__file__)
    viewer = SimpleNamespace()
    viewer._current_path = lambda: path
    runner = Mock()

    with (
        patch("gui.dialogs.screenshot_viewer.ProcessRunner", return_value=runner),
        patch("gui.dialogs.screenshot_viewer.os.path.exists", return_value=True),
        patch("gui.dialogs.screenshot_viewer.os.name", "nt"),
    ):
        ScreenshotViewer._open_file_location(viewer)

    runner.spawn.assert_called_once()
    assert runner.spawn.call_args.args[0][0] == "explorer"


def test_screenshot_viewer_uses_bottom_toolbar_with_tooltips(tmp_path):
    _app = QApplication.instance() or QApplication([])
    image_path = tmp_path / "shot.png"
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.red)
    assert pixmap.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    try:
        assert "120 x 80" in viewer._info_label.text()
        assert "shot.png" not in viewer._info_label.text()
        assert viewer._path_label.text().endswith("shot.png")
        assert viewer._path_label.toolTip() == str(image_path)
        assert viewer._copy_btn.text() == ""
        assert viewer._bottom_bar.objectName() == "bottomBar"
        assert viewer._bottom_dock.objectName() == "bottomDock"
        assert viewer._thumb_list.isHidden()
        assert not hasattr(viewer, "_close_btn")
        assert not hasattr(viewer, "_copy_path_btn")
        assert not hasattr(viewer, "_save_btn")
        assert not hasattr(viewer, "copy_path_to_clipboard")
        assert not hasattr(viewer, "save_as")
        expected_tips = {
            viewer._prev_btn: "Previous screenshot (Left)",
            viewer._next_btn: "Next screenshot (Right)",
            viewer._zoom_out_btn: "Zoom out (Ctrl+-)",
            viewer._zoom_in_btn: "Zoom in (Ctrl+=)",
            viewer._fit_btn: "Fit to window (Ctrl+0)",
            viewer._actual_btn: "Actual size (Ctrl+1)",
            viewer._copy_btn: "Copy image to clipboard (Ctrl+C)",
            viewer._folder_btn: "Open file location",
            viewer._delete_btn: "Delete screenshot",
        }
        assert all(button.toolTip() == tooltip for button, tooltip in expected_tips.items())
    finally:
        viewer.close()


def test_screenshot_viewer_thumbnail_and_navigation_update_current_image(tmp_path):
    _app = QApplication.instance() or QApplication([])
    paths = []
    for name, color in (
        ("first.png", Qt.GlobalColor.red),
        ("second.png", Qt.GlobalColor.green),
        ("third.png", Qt.GlobalColor.blue),
    ):
        path = tmp_path / name
        pixmap = QPixmap(80, 60)
        pixmap.fill(color)
        assert pixmap.save(str(path))
        paths.append(str(path))

    viewer = ScreenshotViewer(paths)
    try:
        assert not viewer._thumb_list.isHidden()
        assert viewer._thumb_list.count() == 3
        assert viewer._nav_label.text() == "1 / 3"

        viewer.navigate_next()
        assert viewer._current_idx == 1
        assert viewer._path_label.text() == "second.png"
        assert viewer._nav_label.text() == "2 / 3"
        assert viewer._thumb_list.currentRow() == 1

        viewer._on_thumbnail_clicked(viewer._thumb_list.item(2))
        assert viewer._current_idx == 2
        assert viewer._path_label.text() == "third.png"
        assert viewer._nav_label.text() == "3 / 3"

        viewer.navigate_prev()
        assert viewer._current_idx == 1
        assert viewer._path_label.text() == "second.png"
    finally:
        viewer.close()


def test_screenshot_viewer_refreshes_themed_icons(tmp_path):
    _app = QApplication.instance() or QApplication([])
    image_path = tmp_path / "shot.png"
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.green)
    assert pixmap.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    try:
        with patch(
            "gui.dialogs.screenshot_viewer.get_themed_icon", return_value=QIcon()
        ) as themed_icon:
            viewer._refresh_button_icons()

        icon_names = [call.args[0] for call in themed_icon.call_args_list]
        assert "camera.svg" in icon_names
        assert {button.property("iconName") for button in viewer._icon_buttons}.issubset(icon_names)
    finally:
        viewer.close()


def test_screenshot_viewer_actual_size_updates_zoom_label(tmp_path):
    _app = QApplication.instance() or QApplication([])
    image_path = tmp_path / "shot.png"
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.blue)
    assert pixmap.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    try:
        viewer._actual_size()

        assert viewer._fit_to_window is False
        assert viewer._zoom_label.text() == "100%"
    finally:
        viewer.close()


def test_screenshot_viewer_delete_without_confirmation_auto_closes_when_last_image_removed(
    tmp_path,
):
    _app = QApplication.instance() or QApplication([])
    image_path = tmp_path / "shot.png"
    pixmap = QPixmap(120, 80)
    pixmap.fill(Qt.GlobalColor.magenta)
    assert pixmap.save(str(image_path))

    viewer = ScreenshotViewer([str(image_path)])
    try:
        viewer._delete_file()

        assert not image_path.exists()
        assert viewer._image_paths == []
        assert not viewer.isVisible()
    finally:
        if viewer.isVisible():
            viewer.close()


def test_pull_recorded_video_reports_pull_failure():
    model = ADBAdvanced()

    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "remote object does not exist"}

        result = ADBAdvanced.pull_recorded_video_async.__wrapped__(
            model,
            "device-1",
            "/sdcard/missing.mp4",
            "C:/tmp",
            "missing.mp4",
        )

    assert result["success"] is False
    assert result["device_ip"] == "device-1"
    assert "pull failed" in result["error"]
    run.assert_called_once()


def test_settings_get_async_returns_value_alias():
    model = ADBAdvanced()

    with patch.object(model, "_run") as run:
        run.return_value = {
            "success": True,
            "output": "1",
            "device_ip": "device-1",
            "key": "show_touches",
        }

        result = ADBAdvanced.settings_get_async.__wrapped__(
            model,
            "device-1",
            "system",
            "show_touches",
        )

    assert result["value"] == "1"
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "settings", "get", "system", "show_touches"],
        device_ip="device-1",
        key="show_touches",
    )


def test_capture_bugreport_reports_command_failure(tmp_path):
    model = ADBTesting()

    with patch.object(model, "_run") as run:
        run.side_effect = [
            {"success": True, "output": "11"},
            {"success": False, "error": "bugreport crashed"},
        ]

        result = ADBTesting.capture_bugreport_async.__wrapped__(
            model,
            "device-1",
            str(tmp_path),
            1,
        )

    assert result == {
        "device_ip": "device-1",
        "index": 1,
        "success": False,
        "message": "Bugreport failed: bugreport crashed",
    }


def test_safe_extract_zip_rejects_paths_outside_target(tmp_path):
    from utils.archive import safe_extract_zip

    zip_path = tmp_path / "bad.zip"
    target = tmp_path / "target"
    target.mkdir()
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.txt", "bad")

    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            safe_extract_zip(zf, target)
            rejected = False
        except ValueError:
            rejected = True

    assert rejected is True
    assert not (tmp_path / "evil.txt").exists()


def test_take_screenshot_prefers_exec_out_direct_path(tmp_path):
    model = ADBTesting()
    save_path = tmp_path / "shot.png"

    def write_png(_cmd, path, timeout=30):
        with open(path, "wb") as image_file:
            image_file.write(b"\x89PNG\r\n\x1a\npayload")
        return CommandResult(success=True, output=path)

    with (
        patch("models.adb_testing.CommandRunner.run_to_file", side_effect=write_png),
        patch.object(model, "_run") as run,
    ):
        result = ADBTesting.take_screenshot_async.__wrapped__(
            model,
            "device-1",
            str(save_path),
        )

    assert result == {"success": True, "device_ip": "device-1", "screenshot_path": str(save_path)}
    run.assert_not_called()


def test_take_screenshot_falls_back_when_exec_out_is_invalid_png(tmp_path):
    model = ADBTesting()
    save_path = tmp_path / "shot.png"

    def write_bad(_cmd, path, timeout=30):
        with open(path, "wb") as image_file:
            image_file.write(b"not png")
        return CommandResult(success=True, output=path)

    with (
        patch("models.adb_testing.CommandRunner.run_to_file", side_effect=write_bad),
        patch.object(model, "_run") as run,
    ):
        run.side_effect = [
            {"success": True, "output": ""},
            {"success": True, "output": "ok"},
            {"success": True, "output": "pulled"},
            {"success": True, "output": ""},
        ]

        result = ADBTesting.take_screenshot_async.__wrapped__(
            model,
            "device-1",
            str(save_path),
        )

    assert result == {"success": True, "device_ip": "device-1", "screenshot_path": str(save_path)}
    assert run.call_count == 4


def test_list_installed_packages_parses_command_output():
    model = ADBApp()

    with patch.object(model, "_run") as run:
        run.return_value = {
            "success": True,
            "output": "package:com.example.one\npackage:com.example.two\n",
            "device_ip": "device-1",
        }

        result = model.list_installed_packages("device-1", 3)

    assert result == {
        "device_ip": "device-1",
        "success": True,
        "packages": ["com.example.one", "com.example.two"],
        "index": 3,
    }


def test_file_explorer_worker_uses_command_runner_for_short_commands():
    worker = ADBWorker("device-1", ["shell", "ls", "/sdcard"])
    emitted = []
    worker.result_ready.connect(lambda output, failed: emitted.append((output, failed)))

    with patch("models.file_explorer_worker.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output="Download\nPictures")

        worker.run()

    assert emitted == [("Download\nPictures", False)]
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "ls", "/sdcard"],
        timeout=30,
    )


def test_file_explorer_worker_passes_custom_timeout_to_command_runner():
    worker = ADBWorker("device-1", ["shell", "du", "-sh", "/sdcard"], timeout=120)
    emitted = []
    worker.result_ready.connect(lambda output, failed: emitted.append((output, failed)))

    with patch("models.file_explorer_worker.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output="1G /sdcard")

        worker.run()

    assert emitted == [("1G /sdcard", False)]
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "du", "-sh", "/sdcard"],
        timeout=120,
    )


def test_file_explorer_worker_keeps_result_separate_from_thread_completion(qt_application):
    worker = ADBWorker("device-1", ["shell", "ls", "/sdcard"])
    results = []
    thread_completions = []
    worker.result_ready.connect(lambda output, failed: results.append((output, failed)))
    worker.finished.connect(lambda: thread_completions.append(True))

    with patch("models.file_explorer_worker.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output="Pictures")
        worker.start()
        assert worker.wait(1000)
        qt_application.processEvents()

    assert results == [("Pictures", False)]
    assert thread_completions == [True]


class _FakeFileExplorerADBWorker(QObject):
    result_ready = Signal(str, bool)
    finished = Signal()
    instances = []

    def __init__(self, device_ip, args, timeout=30):
        super().__init__()
        self.device_ip = device_ip
        self.args = list(args)
        self.timeout = timeout
        self.running = False
        self.abort_calls = 0
        self.wait_calls = 0
        type(self).instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def abort(self):
        self.abort_calls += 1
        self.running = False

    def wait(self, *_args):
        self.wait_calls += 1
        self.running = False
        return True

    def complete(self, output, error=False):
        self.running = False
        self.result_ready.emit(output, error)
        self.finished.emit()


def test_file_explorer_refresh_carries_monotonic_request_identity(qt_application):
    _FakeFileExplorerADBWorker.instances = []
    with (
        patch.object(FileExplorerDialog, "_refresh"),
        patch("gui.dialogs.file_explorer.ADBWorker", _FakeFileExplorerADBWorker),
    ):
        dialog = FileExplorerDialog(device_ip="device-1")

    try:
        with patch("gui.dialogs.file_explorer.ADBWorker", _FakeFileExplorerADBWorker):
            FileExplorerDialog._refresh(dialog)
            dialog.current_path = "/sdcard/next"
            FileExplorerDialog._refresh(dialog)

        first, second = _FakeFileExplorerADBWorker.instances
        assert first.property("refreshRequestId") == 1
        assert first.property("requestedPath") == "/storage/emulated/0"
        assert second.property("refreshRequestId") == 2
        assert second.property("requestedPath") == "/sdcard/next"
        assert dialog._active_refresh == (2, "/sdcard/next")
    finally:
        dialog.close()
        qt_application.processEvents()


def test_file_explorer_ignores_stale_result_after_quick_navigation(qt_application):
    _FakeFileExplorerADBWorker.instances = []
    with (
        patch.object(FileExplorerDialog, "_refresh"),
        patch("gui.dialogs.file_explorer.ADBWorker", _FakeFileExplorerADBWorker),
    ):
        dialog = FileExplorerDialog(device_ip="device-1")

    try:
        with patch("gui.dialogs.file_explorer.ADBWorker", _FakeFileExplorerADBWorker):
            dialog._navigate("/sdcard/first")
            dialog._navigate("/sdcard/second")

        first, second = _FakeFileExplorerADBWorker.instances
        second.complete("-rw-r--r-- 1 shell shell 20 May 30 current.txt")
        qt_application.processEvents()
        current_status = dialog.status_bar.currentMessage()

        first.complete("-rw-r--r-- 1 shell shell 10 May 30 stale.txt")
        qt_application.processEvents()

        assert dialog.current_path == "/sdcard/second"
        assert dialog._file_name_at(1) == "current.txt"
        assert dialog.status_bar.currentMessage() == current_status
        assert current_status == "/sdcard/second  |  0 folders, 1 files"
        assert first not in dialog._workers
        assert second not in dialog._workers
    finally:
        dialog.close()
        qt_application.processEvents()


def test_file_explorer_close_disconnects_late_worker_ui_and_retains_worker(qt_application):
    _FakeFileExplorerADBWorker.instances = []
    with (
        patch.object(FileExplorerDialog, "_refresh"),
        patch("gui.dialogs.file_explorer.ADBWorker", _FakeFileExplorerADBWorker),
    ):
        dialog = FileExplorerDialog(device_ip="device-1")

    with patch("gui.dialogs.file_explorer.ADBWorker", _FakeFileExplorerADBWorker):
        worker = dialog._run_adb("shell", "ls /sdcard")
    dialog.status_bar.showMessage = Mock()
    queued_ui_callback = dialog._connect_worker_ui(
        worker,
        worker.result_ready,
        lambda output, error: dialog.status_bar.showMessage(output),
    )
    worker.start()

    with patch.object(FileExplorerDialog, "_retain_workers_until_stopped") as retain:
        dialog.closeEvent(QCloseEvent())

    # 模拟关闭事件发生前已排队、关闭后才被事件循环投递的界面回调。
    queued_ui_callback("queued result", False)
    worker.result_ready.emit("late result", False)
    qt_application.processEvents()

    assert dialog._closing is True
    assert dialog._worker_ui_bindings == {}
    assert dialog._worker_lifecycle_handlers == {}
    assert worker.abort_calls == 1
    dialog.status_bar.showMessage.assert_not_called()
    retain.assert_called_once()
    assert retain.call_args.args[0] == [worker]
    dialog.deleteLater()
    qt_application.processEvents()


def test_file_explorer_transfer_failure_does_not_refresh():
    dialog = SimpleNamespace()
    dialog.status_bar = Mock()
    dialog._refresh = Mock()

    with patch("gui.dialogs.file_explorer.QMessageBox.critical") as critical:
        FileExplorerDialog._on_transfer_done(dialog, "failed to copy", True, "Pulled demo.txt")

    critical.assert_called_once()
    dialog.status_bar.showMessage.assert_called_once_with("Failed: failed to copy")
    dialog._refresh.assert_not_called()


def test_file_explorer_file_operation_failure_does_not_show_success():
    dialog = SimpleNamespace()
    dialog.status_bar = Mock()
    dialog._refresh = Mock()

    with patch("gui.dialogs.file_explorer.QMessageBox.critical") as critical:
        FileExplorerDialog._on_file_op_done(dialog, "Permission denied", True, "Deleted demo.txt")

    critical.assert_called_once()
    dialog.status_bar.showMessage.assert_called_once_with("Failed: Permission denied")
    dialog._refresh.assert_not_called()


def test_transfer_worker_uses_process_runner_for_streaming_transfer(tmp_path):
    class FakeStdout:
        def __init__(self):
            self.lines = iter(["pulled file\n", ""])

        def readline(self):
            return next(self.lines)

    proc = Mock()
    proc.stdout = FakeStdout()
    proc.poll.return_value = 0
    proc.wait.return_value = 0

    worker = TransferWorker("device-1", ["pull", "/sdcard/demo.txt", "demo.txt"], cwd=str(tmp_path))
    progress = []
    finished = []
    worker.progress.connect(progress.append)
    worker.result_ready.connect(
        lambda message, failed, local: finished.append((message, failed, local))
    )

    with (
        patch.object(worker._process_runner, "start", return_value=proc) as start,
        patch.object(worker._process_runner, "stop") as stop,
    ):
        worker.run()

    start.assert_called_once_with(
        worker._process_key,
        ["adb", "-s", "device-1", "pull", "/sdcard/demo.txt", "demo.txt"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(tmp_path),
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1,
    )
    stop.assert_called_once_with(worker._process_key, timeout=0)
    assert progress == ["pulled file"]
    assert finished == [("pulled file", False, "demo.txt")]


def test_file_explorer_ls_result_prefills_rows_without_insert_loop():
    _app = QApplication.instance() or QApplication([])
    dialog = SimpleNamespace()
    dialog.current_path = "/sdcard"
    dialog.TYPE_COL = FileExplorerDialog.TYPE_COL
    dialog.NAME_COL = FileExplorerDialog.NAME_COL
    dialog.SIZE_COL = FileExplorerDialog.SIZE_COL
    dialog.MODIFIED_COL = FileExplorerDialog.MODIFIED_COL
    dialog.table = Mock()
    dialog.status_bar = Mock()
    dialog.symlink_targets = {}
    dialog._file_type_icon = Mock(return_value=QIcon())
    dialog._set_file_row = lambda row, name, file_type, size, modified: (
        FileExplorerDialog._set_file_row(dialog, row, name, file_type, size, modified)
    )
    output = """
total 8
drwxr-xr-x 2 shell shell 4096 May 30 DCIM
-rw-r--r-- 1 shell shell 1024 May 30 readme.txt
"""

    FileExplorerDialog._on_ls_result(dialog, output, "")

    dialog.table.setUpdatesEnabled.assert_any_call(False)
    dialog.table.setUpdatesEnabled.assert_any_call(True)
    dialog.table.setSortingEnabled.assert_any_call(False)
    dialog.table.setSortingEnabled.assert_any_call(True)
    dialog.table.setRowCount.assert_called_once_with(3)
    dialog.table.insertRow.assert_not_called()
    assert dialog.table.setItem.call_count == 12
    first_row_calls = dialog.table.setItem.call_args_list[:4]
    assert [call_.args[1] for call_ in first_row_calls] == [
        FileExplorerDialog.TYPE_COL,
        FileExplorerDialog.NAME_COL,
        FileExplorerDialog.SIZE_COL,
        FileExplorerDialog.MODIFIED_COL,
    ]
    assert first_row_calls[0].args[2].text() == "Folder"
    assert first_row_calls[1].args[2].text() == ".."
    dialog.status_bar.showMessage.assert_called_once_with("/sdcard  |  1 folders, 1 files")


def test_file_explorer_table_moves_type_first_and_hides_row_numbers():
    _app = QApplication.instance() or QApplication([])
    with patch.object(FileExplorerDialog, "_refresh"):
        dialog = FileExplorerDialog(device_ip="device-1")

    try:
        assert dialog.table.horizontalHeaderItem(0).text() == "Type"
        assert dialog.table.horizontalHeaderItem(1).text() == "Name"
        assert dialog.table.verticalHeader().isVisible() is False
        assert dialog.NAME_COL == 1
        assert dialog._file_type_icon_name("demo.apk", "APK") == "android-logo.svg"
        assert dialog._file_type_icon_name("photo.png", "PNG") == "file-png.svg"
        assert dialog._file_type_icon_name("movie.mp4", "MP4") == "file-video.svg"
        assert dialog._file_type_icon_name("notes.txt", "TXT") == "file-txt.svg"
    finally:
        dialog.close()


def test_adb_bridge_shell_uses_command_runner():
    bridge = ADBBridge(path="adb.exe")

    with patch("core.adb_bridge.CommandRunner.run") as run:
        run.return_value = CommandResult(success=True, output="ok")

        result = bridge.shell("wm size", device_id="device-1")

    assert result.output == "ok"
    run.assert_called_once_with(["adb.exe", "-s", "device-1", "shell", "wm size"], timeout=15)


def test_adb_bridge_shell_input_uses_process_runner_spawn():
    bridge = ADBBridge(path="adb.exe")
    proc = Mock()

    with (
        patch.object(bridge, "_input_session") as input_session,
        patch.object(bridge._process_runner, "spawn", return_value=proc) as spawn,
    ):
        input_session.return_value.send.return_value = False
        result = bridge.shell_input("keyevent 3", device_id="device-1")

    assert result is proc
    input_session.assert_called_once_with("device-1")
    spawn.assert_called_once_with(["adb.exe", "-s", "device-1", "shell", "input keyevent 3"])


def test_adb_bridge_shell_input_prefers_persistent_session():
    bridge = ADBBridge(path="adb.exe")
    session = Mock()
    session.send.return_value = True

    with (
        patch.object(bridge, "_input_session", return_value=session),
        patch.object(bridge._process_runner, "spawn") as spawn,
    ):
        result = bridge.shell_input("keyevent 3", device_id="device-1")

    assert result is session
    session.send.assert_called_once_with("keyevent 3")
    spawn.assert_not_called()


def test_adb_bridge_close_input_sessions_closes_and_removes_sessions():
    bridge = ADBBridge(path="adb.exe")
    session_1 = Mock()
    session_2 = Mock()
    bridge._input_sessions = {"device-1": session_1, "device-2": session_2}

    bridge.close_input_sessions("device-1")

    session_1.close.assert_called_once()
    session_2.close.assert_not_called()
    assert "device-1" not in bridge._input_sessions
    assert "device-2" in bridge._input_sessions

    bridge.close_input_sessions()

    session_2.close.assert_called_once()
    assert bridge._input_sessions == {}


def test_adb_advanced_input_uses_persistent_shell_bridge():
    model = ADBAdvanced()
    model._adb_bridge = Mock()

    result = ADBAdvanced.input_tap_async.__wrapped__(model, "device-1", 10, 20)

    assert result == {"success": True, "device_ip": "device-1", "x": 10, "y": 20}
    model._adb_bridge.shell_input.assert_called_once_with("tap 10 20", device_id="device-1")


def test_adb_advanced_input_failure_is_reported():
    model = ADBAdvanced()
    model._adb_bridge = Mock()
    model._adb_bridge.shell_input.side_effect = OSError("adb died")

    result = ADBAdvanced.input_keyevent_async.__wrapped__(model, "device-1", "3")

    assert result == {"success": False, "device_ip": "device-1", "keycode": "3"}


def test_adb_advanced_shutdown_stops_recording_and_input_sessions():
    model = ADBAdvanced()
    model._rec_procs = Mock()
    model._adb_bridge = Mock()

    model.shutdown()

    model._rec_procs.stop_all.assert_called_once()
    model._adb_bridge.close_input_sessions.assert_called_once_with(None)


def test_quick_setting_batches_animation_commands_into_one_shell():
    model = ADBAdvanced()

    with patch.object(model, "_run") as run:
        run.return_value = {"success": True, "device_ip": "device-1"}

        result = ADBSystemMixin.quick_setting_async.__wrapped__(model, "device-1", "anim_off")

    assert result == {"success": True, "device_ip": "device-1", "action": "anim_off"}
    run.assert_called_once_with(
        [
            "adb",
            "-s",
            "device-1",
            "shell",
            "settings put global animator_duration_scale 0 && "
            "settings put global transition_animation_scale 0 && "
            "settings put global window_animation_scale 0",
        ],
        device_ip="device-1",
        action="anim_off",
    )


def test_disable_package_commands_keep_global_and_user_scopes_distinct():
    model = SimpleNamespace(_run=Mock(return_value={"success": True}))

    ADBSystemMixin.disable_package_async.__wrapped__(
        model,
        "device-1",
        "com.example.app",
    )

    model._run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "pm", "disable", "com.example.app"],
        device_ip="device-1",
        package="com.example.app",
    )

    model._run.reset_mock()
    ADBSystemMixin.disable_package_user_async.__wrapped__(
        model,
        "device-1",
        "com.example.app",
    )

    model._run.assert_called_once_with(
        ["adb", "-s", "device-1", "shell", "pm", "disable-user", "com.example.app"],
        device_ip="device-1",
        package="com.example.app",
    )


def test_adb_input_session_writes_input_command_to_stdin():
    proc = Mock()
    proc.stdin = Mock()
    proc.poll.return_value = None
    runner = Mock()
    runner.start.return_value = proc

    with patch("core.adb_bridge.ProcessRunner", return_value=runner):
        session = ADBInputSession("adb.exe", "device-1")
        assert session.send("keyevent 3") is True

    runner.start.assert_called_once()
    assert runner.start.call_args.args[:2] == (
        session._key,
        ["adb.exe", "-s", "device-1", "shell"],
    )
    proc.stdin.write.assert_called_once_with("input keyevent 3\n")
    proc.stdin.flush.assert_called_once()


def test_adb_input_session_returns_false_when_process_cannot_start():
    runner = Mock()
    runner.start.side_effect = OSError("boom")

    with patch("core.adb_bridge.ProcessRunner", return_value=runner):
        session = ADBInputSession("adb.exe", "device-1")
        assert session.send("keyevent 3") is False


def test_adb_bridge_devices_parses_command_runner_output():
    bridge = ADBBridge(path="adb.exe")

    with patch("core.adb_bridge.CommandRunner.run") as run:
        run.return_value = CommandResult(
            success=True,
            output="List of devices attached\ndevice-1\tdevice\ndevice-2\toffline",
        )

        devices = bridge.devices()

    assert devices == [["device-1", "device"], ["device-2", "offline"]]
    run.assert_called_once_with(["adb.exe", "devices"], timeout=15)


def test_testing_model_current_package_uses_shared_detector():
    model = ADBTesting()

    with patch("models.adb_testing.detect_current_package") as detect:
        detect.return_value = {
            "success": True,
            "device_ip": "device-1",
            "package_name": "com.example.app",
        }

        package_name = model._get_current_package("device-1")

    assert package_name == "com.example.app"
    detect.assert_called_once_with("device-1")


def test_kill_monkey_treats_empty_device_stop_error_as_idempotent_success():
    model = ADBTesting()
    proc = Mock()
    proc.poll.return_value = None
    proc.wait.return_value = 0
    model._procs._procs["device-1_monkey"] = proc

    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "", "device_ip": "device-1"}

        result = model.kill_monkey_async.__wrapped__(model, "device-1", 1)

    assert result == {
        "device_ip": "device-1",
        "index": 1,
        "success": True,
        "message": "Monkey process stopped",
        "already_stopped": False,
    }
    proc.terminate.assert_called_once()
    assert model._procs._procs == {}


def test_kill_monkey_reports_not_running_when_no_local_process_and_empty_device_error():
    model = ADBTesting()

    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "", "device_ip": "device-1"}

        result = model.kill_monkey_async.__wrapped__(model, "device-1", 1)

    assert result == {
        "device_ip": "device-1",
        "index": 1,
        "success": True,
        "message": "Monkey is not running",
        "already_stopped": True,
    }


def test_kill_monkey_reports_real_device_stop_error_without_local_process():
    model = ADBTesting()

    with patch.object(model, "_run") as run:
        run.return_value = {"success": False, "error": "device offline", "device_ip": "device-1"}

        result = model.kill_monkey_async.__wrapped__(model, "device-1", 1)

    assert result == {
        "device_ip": "device-1",
        "index": 1,
        "success": False,
        "message": "device offline",
        "already_stopped": False,
    }


@pytest.fixture
def isolated_log_service():
    """隔离日志服务的进程级单例，避免停止状态在测试用例之间传播。"""
    previous_instance = LogService._instance
    LogService._instance = None
    service = LogService()
    try:
        yield service
    finally:
        if service._state == service._STATE_ACCEPTING:
            service.shutdown()
        LogService._instance = previous_instance


def test_log_service_shutdown_rejects_background_thread_without_deadlock(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    service = isolated_log_service
    service.log("INFO", "shutdown sentinel")
    errors = []

    def shutdown_from_worker():
        try:
            service.shutdown()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=shutdown_from_worker, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    service._buffer_lock.lock()
    try:
        assert [entry[1:] for entry in service._buffer] == [("INFO", "shutdown sentinel")]
    finally:
        service._buffer_lock.unlock()


def test_log_service_worker_thread_log_flushes_on_owner_thread(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    service = isolated_log_service
    service._flush_buffer()
    sentinel = "worker-thread-flush-sentinel"
    emitted = []
    owner_thread_id = threading.get_ident()
    service.log_received.connect(
        lambda level, message: emitted.append((level, message, threading.get_ident()))
    )

    thread = threading.Thread(target=lambda: service.log("INFO", sentinel), daemon=True)
    thread.start()
    thread.join(timeout=0.5)
    service._flush_buffer()

    assert ("INFO", sentinel, owner_thread_id) in emitted


def test_log_service_emits_batch_before_compat_single_signals(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    service = isolated_log_service
    service._flush_buffer()
    batch_emitted = []
    singles = []
    service.logs_received.connect(lambda records: batch_emitted.append(records))
    service.log_received.connect(lambda level, message: singles.append((level, message)))

    service.log("INFO", "batched-1")
    service.log("WARNING", "batched-2")
    service._flush_buffer()

    assert [(level, message) for _ts, level, message in batch_emitted[-1]] == [
        ("INFO", "batched-1"),
        ("WARNING", "batched-2"),
    ]
    assert singles[-2:] == [("INFO", "batched-1"), ("WARNING", "batched-2")]


def test_log_panel_appends_large_batch_with_a_per_frame_budget(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    assert LogService() is isolated_log_service
    panel = LogPanel()
    try:
        calls = []
        original = panel._render_entries

        def counted(rows):
            calls.append(len(rows))
            return original(rows)

        panel._render_entries = counted
        records = [("12:00:00", "INFO", f"line-{i}") for i in range(1000)]

        panel._append_logs(records)
        while panel._pending_rows:
            panel._flush_pending_rows()

        assert sum(calls) == 1000
        assert all(size <= panel.FRAME_BATCH_SIZE for size in calls)
        assert len(calls) > 1
        assert len(panel._entries) == 1000
        assert "line-999" in panel.text_output.toPlainText()
    finally:
        panel.close()


def test_log_panel_coalesces_small_log_batches_before_rendering(isolated_log_service):
    _app = QApplication.instance() or QApplication([])
    assert LogService() is isolated_log_service
    panel = LogPanel()
    old_debounce = LogPanel.RENDER_DEBOUNCE_MS
    LogPanel.RENDER_DEBOUNCE_MS = 20
    try:
        calls = []
        original = panel._render_entries

        def counted(rows):
            calls.append(len(rows))
            return original(rows)

        panel._render_entries = counted

        panel._append_logs([("12:00:00", "INFO", "small-1")])
        panel._append_logs([("12:00:01", "INFO", "small-2")])

        assert calls == []
        panel._flush_pending_rows()

        assert calls == [2]
        assert "small-2" in panel.text_output.toPlainText()
    finally:
        LogPanel.RENDER_DEBOUNCE_MS = old_debounce
        panel.close()
