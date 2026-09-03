# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import os
import subprocess
import threading
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from adblab.application.device_batch import DeviceBatchUseCase
from adblab.application.install_batch import InstallBatchUseCase, InstallRequest, InstallUnit
from adblab.application.operations import OperationManager
from controllers._app import ADBAppMixin
from core.exec import CommandResult
from gui.dialogs.app_manager import AppDetailsDialog, AppManagerDialog
from gui.styles import BaseStyles
from models.adb_app import ADBApp
from models.adb_testing import ADBTesting
from models.base.focus_detector import detect_current_package, extract_package_name


def _app_manager_for_unit_tests():
    class UnitDialog:
        pass

    _app = QApplication.instance() or QApplication([])
    dialog = UnitDialog()
    dialog._apps_data = []
    dialog._app_labels = {}
    dialog._app_versions = {}
    dialog._detail_cache = {}
    dialog._pending_detail_packages = set()
    dialog._detail_worker_running = False
    dialog._detail_row_by_pkg = {}
    dialog._detail_icon_by_pkg = {}
    dialog._view_mode = False
    dialog._syncing_selection = False
    dialog._closing = False
    dialog.device_ip = "device-1"
    dialog.status_bar = Mock()
    dialog.log = Mock()
    dialog._track_worker = Mock()
    dialog._detail_timer = Mock()
    dialog._detail_timer.isActive.return_value = False
    dialog._detail_timer.start = Mock()
    dialog._detail_timer.stop = Mock()
    dialog._filter = Mock()
    dialog.model = Mock()
    dialog.model.rowCount.return_value = 0
    dialog.model.removeRows = Mock()
    dialog.tree = Mock()
    dialog.tree.rootIndex.return_value = Mock()
    dialog.tree.viewport.return_value.rect.return_value = Mock()
    dialog.proxy = Mock()
    dialog.proxy.rowCount.return_value = 0
    dialog.icon_list = Mock()
    dialog.icon_list.clear = Mock()
    dialog.icon_list.addItem = Mock()
    dialog._sync_selection_views = Mock()
    dialog._gen_icon = AppManagerDialog._gen_icon
    dialog._on_detail = lambda *args: AppManagerDialog._on_detail(dialog, *args)
    dialog._on_detail_worker_finished = lambda packages=None: (
        AppManagerDialog._on_detail_worker_finished(dialog, packages)
    )
    dialog._has_unloaded_details = lambda: AppManagerDialog._has_unloaded_details(dialog)
    dialog._next_unloaded_detail_packages = lambda limit=30: (
        AppManagerDialog._next_unloaded_detail_packages(dialog, limit)
    )
    dialog._schedule_visible_detail_load = lambda delay_ms=120: (
        AppManagerDialog._schedule_visible_detail_load(dialog, delay_ms)
    )
    return dialog


def test_app_manager_populate_schedules_visible_details_only():
    dialog = _app_manager_for_unit_tests()

    with patch("gui.dialogs.app_manager.AppManagerWorker") as worker:
        AppManagerDialog._populate(dialog, [("Demo", "com.example.demo", "Enabled", "User")])

    worker.assert_not_called()
    dialog._detail_timer.start.assert_called()
    assert dialog._detail_row_by_pkg == {"com.example.demo": 0}
    assert "com.example.demo" in dialog._detail_icon_by_pkg
    dialog.status_bar.setText.assert_called()


def test_app_manager_detail_update_uses_cached_indexes():
    dialog = _app_manager_for_unit_tests()
    icon_item = Mock()
    name_item = Mock()
    version_item = Mock()
    dialog._detail_icon_by_pkg = {"com.example.demo": icon_item}
    dialog._detail_row_by_pkg = {"com.example.demo": 2}
    dialog.model.item.side_effect = lambda row, col: {
        (2, 1): name_item,
        (2, 3): version_item,
    }.get((row, col))

    AppManagerDialog._on_detail(dialog, "com.example.demo", "Demo", "1.0 (1)", "2026-05-31")

    assert dialog._detail_cache["com.example.demo"] == ("Demo", "1.0 (1)", "2026-05-31")
    icon_item.setToolTip.assert_called_once_with("Demo\ncom.example.demo\n1.0 (1)")
    name_item.setText.assert_called_once_with("Demo")
    version_item.setText.assert_called_once_with("1.0 (1)")
    assert dialog.model.item.call_count == 2


def test_app_manager_load_visible_details_starts_small_worker_batch():
    dialog = _app_manager_for_unit_tests()
    dialog._visible_detail_packages = Mock(return_value=["com.example.one", "com.example.two"])

    with patch("gui.dialogs.app_manager.AppManagerWorker") as worker_cls:
        worker = worker_cls.return_value
        AppManagerDialog._load_visible_details(dialog)

    worker_cls.assert_called_once_with(
        "device-1",
        "load_detail_batch",
        packages=["com.example.one", "com.example.two"],
    )
    assert dialog._pending_detail_packages == {"com.example.one", "com.example.two"}
    assert dialog._detail_worker_running is True
    worker.app_detail_batch.connect.assert_called_once_with(dialog._on_detail)
    worker.start.assert_called_once()


def test_app_manager_worker_load_detail_batch_uses_single_batched_shell():
    from models.app_manager_worker import AppManagerWorker

    worker = AppManagerWorker("device-1", "load_detail_batch", packages=[])
    emitted = []
    worker.app_detail_batch.connect(lambda *args: emitted.append(args))
    output = (
        "__ADBLAB_PKG_BEGIN_0__\n"
        "nonLocalizedLabel=One App\n"
        "versionName=1.2\n"
        "versionCode=12\n"
        "firstInstallTime=2026-01-02\n"
        "__ADBLAB_PKG_END_0__\n"
        "__ADBLAB_PKG_BEGIN_1__\n"
        "versionName=2.0\n"
        "versionCode=20\n"
        "__ADBLAB_PKG_END_1__\n"
    )

    with patch.object(
        worker, "_adb", return_value=CommandResult(success=True, output=output)
    ) as adb:
        worker._load_detail_batch(["com.example.one", "com.example.two"])

    adb.assert_called_once()
    assert adb.call_args.args[0] == "shell"
    assert "dumpsys package com.example.one" in adb.call_args.args[1]
    assert emitted == [
        ("com.example.one", "One App", "1.2 (12)", "2026-01-02"),
        ("com.example.two", "two", "2.0 (20)", ""),
    ]


def test_app_manager_detail_worker_continues_after_first_visible_page():
    dialog = _app_manager_for_unit_tests()
    dialog._apps_data = [
        ("One", "com.example.one", "Enabled", "User"),
        ("Two", "com.example.two", "Enabled", "User"),
    ]
    dialog._detail_cache = {"com.example.one": ("One", "1.0", "")}
    dialog._pending_detail_packages = {"com.example.two"}

    AppManagerDialog._on_detail_worker_finished(dialog, ["com.example.two"])

    dialog._detail_timer.start.assert_called()
    dialog.status_bar.setText.assert_not_called()


def test_app_manager_load_visible_details_falls_back_to_next_unloaded_batch():
    dialog = _app_manager_for_unit_tests()
    dialog._apps_data = [
        ("One", "com.example.one", "Enabled", "User"),
        ("Two", "com.example.two", "Enabled", "User"),
    ]
    dialog._detail_cache = {"com.example.one": ("One", "1.0", "")}
    dialog._visible_detail_packages = Mock(return_value=[])

    with patch("gui.dialogs.app_manager.AppManagerWorker") as worker_cls:
        AppManagerDialog._load_visible_details(dialog)

    worker_cls.assert_called_once_with(
        "device-1",
        "load_detail_batch",
        packages=["com.example.two"],
    )
    assert dialog._pending_detail_packages == {"com.example.two"}


def test_app_details_dialog_close_disconnects_theme_handler():
    _app = QApplication.instance() or QApplication([])
    with patch.object(AppDetailsDialog, "_load_data"):
        dialog = AppDetailsDialog(None, "device-1", "com.example.demo")

    with (
        patch("gui.dialogs.app_manager.safe_disconnect") as disconnect,
        patch("gui.dialogs.app_manager.wait_for_threads_later") as wait_threads,
    ):
        dialog.close()

    assert dialog._closing is True
    assert disconnect.call_args_list == [
        call(BaseStyles.theme_changed, dialog._apply_theme),
        call(BaseStyles.fonts_changed, dialog._apply_theme),
    ]
    wait_threads.assert_called_once_with([], 5000)
    dialog.deleteLater()


def test_extract_package_name_ignores_log_prefix_and_returns_real_package():
    output = "ACTIVITY Sys2038: com.example.app/.MainActivity pid=123"

    assert extract_package_name(output) == "com.example.app"


def test_extract_package_name_prefers_focus_line_over_other_packages():
    output = (
        "ACTIVITY com.android.launcher3/.Launcher\n"
        "mCurrentFocus=Window{u0 com.example.app/.MainActivity}"
    )

    assert extract_package_name(output) == "com.example.app"


def test_extract_package_name_prefers_visible_top_activity():
    output = (
        "taskId=3: com.android.settings/com.android.settings.Settings "
        "visible=false "
        "topActivity=ComponentInfo{com.android.settings/com.android.settings.Settings}\n"
        "taskId=2: com.android.launcher3/com.android.launcher3.Launcher "
        "visible=true "
        "topActivity=ComponentInfo{com.android.launcher3/com.android.launcher3.Launcher}"
    )

    assert extract_package_name(output) == "com.android.launcher3"


def test_detect_current_package_uses_lightweight_activity_stack_first():
    runner = Mock()
    runner.run.return_value = CommandResult(
        success=True,
        output=(
            "taskId=9: com.example.app/com.example.app.MainActivity "
            "visible=true topActivity=ComponentInfo{com.example.app/com.example.app.MainActivity}"
        ),
    )

    result = detect_current_package("device-1", runner=runner)

    assert result == {
        "success": True,
        "device_ip": "device-1",
        "package_name": "com.example.app",
    }
    runner.run.assert_called_once_with(
        [
            "adb",
            "-s",
            "device-1",
            "shell",
            "cmd",
            "activity",
            "stack",
            "list",
        ],
        timeout=5,
    )


def test_detect_current_package_falls_back_to_resumed_activity():
    runner = Mock()
    runner.run.side_effect = [
        CommandResult(success=True, output=""),
        CommandResult(success=True, output=""),
        CommandResult(success=True, output="mResumedActivity: com.example.app/.MainActivity"),
    ]

    result = detect_current_package("device-1", runner=runner)

    assert result["success"] is True
    assert result["package_name"] == "com.example.app"
    assert runner.run.call_count == 3


def test_adb_testing_shutdown_stops_managed_processes():
    model = ADBTesting()
    model._procs = Mock()

    model.shutdown()

    model._procs.stop_all.assert_called_once()
    assert "*" in model._aborted_devices


def test_run_monkey_test_reports_nonzero_exit_as_failure(tmp_path):
    model = ADBTesting()
    model._procs = Mock()
    logcat_proc = Mock()
    monkey_proc = Mock(pid=1234)
    monkey_proc.poll.side_effect = [None, 1, 1]
    model._procs.start.side_effect = [logcat_proc, monkey_proc]
    model._procs.stop.return_value = None

    with (
        patch.object(model, "_run", return_value={"success": True, "output": ""}),
        patch.object(model, "_get_current_package", return_value="com.example.app"),
        patch.object(model, "_wait_for_monkey_abort", return_value=False),
        patch("models.adb_testing.time.sleep"),
    ):
        result = ADBTesting.run_monkey_test_async.__wrapped__(
            model,
            "device-1",
            "com.example.app",
            {"events": 10},
            "com_example_app",
            str(tmp_path),
            1,
        )

    assert result["success"] is False
    assert result["error"] == "Monkey exited with code 1"
    assert result["duration"]


def test_run_monkey_test_reports_repeated_timeouts_as_failure(tmp_path):
    model = ADBTesting()
    model._procs = Mock()
    logcat_proc = Mock()
    monkey_proc = Mock(pid=1234)
    monkey_proc.poll.return_value = None
    model._procs.start.side_effect = [logcat_proc, monkey_proc]
    model._procs.stop.return_value = None

    timeout = subprocess.TimeoutExpired(cmd="dumpsys", timeout=5)
    with (
        patch.object(model, "_run", return_value={"success": True, "output": ""}),
        patch.object(model, "_get_current_package", side_effect=[timeout, timeout, timeout]),
        patch.object(model, "_wait_for_monkey_abort", return_value=False),
        patch("models.adb_testing.time.sleep"),
    ):
        result = ADBTesting.run_monkey_test_async.__wrapped__(
            model,
            "device-1",
            "com.example.app",
            {"events": 10},
            "com_example_app",
            str(tmp_path),
            1,
        )

    assert result["success"] is False
    assert result["error"] == "Device appears disconnected"


def test_get_current_package_uses_shared_detector():
    model = ADBApp()

    with patch("models.adb_app.detect_current_package") as detect:
        detect.return_value = {
            "success": True,
            "device_ip": "device-1",
            "package_name": "com.example.app",
        }

        result = model.get_current_package("device-1")

    assert result["success"] is True
    assert result["package_name"] == "com.example.app"
    detect.assert_called_once_with("device-1")


def test_install_apk_uses_run_helper_and_preserves_result_fields():
    model = ADBApp()

    with patch.object(model, "_run") as run:
        run.return_value = {
            "success": True,
            "output": "Success",
            "device_ip": "device-1",
            "apk_path": "demo.apk",
            "index": 1,
            "apk_name": "demo.apk",
        }

        result = model.install_apk("device-1", "demo.apk", "demo.apk", 1)

    assert result["success"] is True
    assert result["apk_name"] == "demo.apk"
    run.assert_called_once_with(
        ["adb", "-s", "device-1", "install", "-r", "demo.apk"],
        timeout=120,
        device_ip="device-1",
        apk_path="demo.apk",
        index=1,
        apk_name="demo.apk",
        operation="install",
    )


def test_parse_apk_info_accepts_existing_apk_case_insensitively():
    controller = Mock()
    controller.app_model = Mock()

    with (
        patch("controllers._app.QFileDialog.getOpenFileName", return_value=("C:/tmp/DEMO.APK", "")),
        patch("controllers._app.os.path.isfile", return_value=True),
    ):
        ADBAppMixin.parse_apk_info(controller)

    controller.app_model.parse_apk_info_async.assert_called_once_with("C:/tmp/DEMO.APK")
    assert controller._emit_operation.call_args.args[1] is True


def test_parse_apk_info_rejects_missing_file():
    controller = Mock()
    controller.app_model = Mock()

    with (
        patch("controllers._app.QFileDialog.getOpenFileName", return_value=("C:/tmp/demo.apk", "")),
        patch("controllers._app.os.path.isfile", return_value=False),
    ):
        ADBAppMixin.parse_apk_info(controller)

    controller.app_model.parse_apk_info_async.assert_not_called()
    controller._emit_operation.assert_called_once()
    assert controller._emit_operation.call_args.args[1] is False



def test_app_controller_install_submission_uses_metadata_without_early_completion():
    controller = Mock()
    controller.operation_manager = OperationManager()
    controller._emit_operation = Mock()
    controller.log_service = Mock()
    controller.app_model = Mock()
    controller.executor = Mock()
    controller._install_terminal_lock = threading.RLock()
    controller._install_starting_operations = set()
    operation = controller.operation_manager.begin(
        "install",
        operation_id="operation-1",
        unit_ids=("task-1",),
    )
    controller.operation_manager.mark_running(operation.operation_id)
    unit = InstallUnit(
        "task-1",
        1,
        InstallRequest("device-1", "demo.apk", "demo.apk"),
    )
    owner_token = object()
    controller.install_batch_use_case = InstallBatchUseCase(controller.operation_manager)
    controller.install_batch_use_case._active_units[operation.operation_id] = (unit,)
    controller.install_batch_use_case._active_owner_tokens[operation.operation_id] = owner_token
    controller.install_batch_use_case._active_kinds[operation.operation_id] = operation.kind
    controller.install_batch_use_case._active_generations[operation.operation_id] = (
        operation.generation_token
    )

    ADBAppMixin._submit_install_unit(
        controller,
        operation.operation_id,
        unit,
        owner_token=owner_token,
    )

    controller.executor.submit.assert_not_called()
    controller.app_model.install_apk_async.assert_called_once_with(
        "device-1",
        "demo.apk",
        "demo.apk",
        1,
        "install",
        _operation_id="operation-1",
        _operation_kind="install",
        _operation_task_id="task-1",
        _operation_unit_id="task-1",
        _operation_target_id="device-1",
        _operation_owner_token=owner_token,
        _operation_generation_token=operation.generation_token,
    )
    controller._emit_operation.assert_not_called()


def test_app_controller_direct_async_paths_skip_python_executor():
    controller = Mock()
    controller._require_devices.return_value = True
    controller._pending_lock = threading.Lock()
    controller._batch_starts = {}
    controller.device_batches = DeviceBatchUseCase(OperationManager())
    controller._emit_operation = Mock()
    controller._reject_concurrent_batch = Mock(return_value=False)
    controller.app_model = Mock()
    controller.executor = Mock()

    ADBAppMixin.clear_app_data(controller, ["device-1"], "com.example")
    ADBAppMixin.restart_app(controller, ["device-1"], "com.example")
    ADBAppMixin.get_current_activity(controller, ["device-1"])

    controller.executor.submit.assert_not_called()
    controller.app_model.clear_app_data_async.assert_called_once_with("device-1", "com.example", 1)
    controller.app_model.restart_app_async.assert_called_once_with("device-1", "com.example", 1)
    controller.app_model.get_current_activity_async.assert_called_once_with("device-1", 1)


def test_reject_concurrent_batch_blocks_second_same_op_start():
    controller = ADBAppMixin.__new__(ADBAppMixin)
    controller._emit_operation = Mock()
    controller._pending_lock = threading.Lock()
    controller._batch_starts = {}
    controller.device_batches = DeviceBatchUseCase(OperationManager())
    controller.app_model = Mock()

    ADBAppMixin.uninstall_apk(controller, ["device-1"], "com.example")

    controller.app_model.uninstall_app_async.assert_called_once_with(
        "device-1", "com.example", 1
    )
    assert "uninstall" in controller._batch_starts

    # 同类批次尚未收口时，第二次启动应被拒绝且不发起新批次。
    controller.app_model.uninstall_app_async.reset_mock()
    ADBAppMixin.uninstall_apk(controller, ["device-2"], "com.example")

    controller.app_model.uninstall_app_async.assert_not_called()
    rejected = controller._emit_operation.call_args_list[-1]
    assert rejected.args[:2] == ("uninstall", False)
    assert "already in progress" in rejected.args[2]


def test_parse_apk_info_reports_missing_file():
    model = ADBApp()
    with patch("models.adb_app.os.path.isfile", return_value=False):
        result = ADBApp.parse_apk_info_async.__wrapped__(model, "missing.apk")

    assert result["success"] is False
    assert "APK file not found" in result["error"]


def test_parse_apk_info_reports_missing_aapt():
    model = ADBApp()
    with (
        patch("models.adb_app.os.path.isfile", return_value=True),
        patch("models.adb_app.shutil.which", return_value=None),
    ):
        result = ADBApp.parse_apk_info_async.__wrapped__(model, "demo.apk")

    assert result["success"] is False
    assert "aapt executable not found" in result["error"]
