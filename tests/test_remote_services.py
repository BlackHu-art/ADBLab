import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import SIGNAL, Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListWidgetItem
from qfluentwidgets import InfoLevel

from adblab.application.supervision import StopDisposition, TaskSupervisor
from core.adb_bridge import ADBBridge, ADBInputSession
from core.exec import CommandResult, ProcessRunner
from gui.panels.remote_panel import RemotePanel
from gui.panels.side_panel import SidePanel
from services.remote import (
    RemoteControlService,
    RemoteInputEngine,
    RemoteWindowManager,
    ScrcpyConfig,
    ScrcpyService,
    build_scrcpy_args,
)
from services.remote.control_mapping import directional_swipe, notification_swipe


class _TestSignal:
    """提供 launch worker 延迟释放测试所需的最小信号协议。"""

    def __init__(self):
        self.callbacks = []

    def connect(self, callback, *_args):
        self.callbacks.append(callback)

    def emit(self):
        for callback in tuple(self.callbacks):
            callback()


@pytest.mark.parametrize(
    ("devices", "text", "level"),
    (
        ([], "未选择", InfoLevel.INFOAMTION),
        (["device-1"], "可启动", InfoLevel.SUCCESS),
        (["device-1", "device-2"], "可启动", InfoLevel.SUCCESS),
    ),
)
def test_remote_status_badge_matches_selected_device_requirement(devices, text, level):
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=devices)
    panel.remote_status_badge = Mock()

    RemotePanel._refresh_remote_status_badge(panel)

    panel.remote_status_badge.setText.assert_called_once_with(text)
    panel.remote_status_badge.setLevel.assert_called_once_with(level)
    panel.remote_status_badge.setToolTip.assert_called_once()
    panel.remote_status_badge.setAccessibleDescription.assert_called_once()


def test_remote_target_selection_broadcasts_keys_and_actions_without_changing_mirrors():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=[])
    panel._update_action_states = Mock()
    panel._launch_worker = None
    panel._session_devices = ("mirrored-device",)
    panel._active_device = "mirrored-device"
    panel._remote_control = Mock()
    panel._submit_remote_input = lambda task: task()
    panel.set_target_devices(["device-1", "device-2", "device-1"])

    panel._send_keyevent("HOME")
    panel._send_remote_action("swipe_up")

    assert panel.selected_devices == ["device-1", "device-2"]
    assert panel.get_remote_session_devices() == ["mirrored-device"]
    assert panel._remote_control.send_keyevent.call_args_list == [
        (("device-1", "HOME"),), (("device-2", "HOME"),),
    ]
    assert panel._remote_control.perform_action.call_args_list == [
        (("device-1", "swipe_up"),), (("device-2", "swipe_up"),),
    ]


def test_remote_selection_change_cancels_queued_input_even_after_reselection():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=[])
    panel._update_action_states = Mock()
    panel._launch_worker = None
    panel._remote_control = Mock()
    panel._remote_executor = Mock()
    panel._emit_remote_queue_status = Mock()
    panel._log = Mock()
    panel.set_target_devices(["device-1", "device-2"])
    panel._send_keyevent("HOME")
    queued = [call.args[0] for call in panel._remote_executor.submit.call_args_list]
    assert len(queued) == 2

    panel.set_target_devices([])
    panel.set_target_devices(["device-1", "device-2"])
    for task in queued:
        task()

    panel._remote_control.send_keyevent.assert_not_called()
    assert panel._remote_failed == 2


def test_remote_batch_start_snapshots_configs_for_every_selected_device():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1", "device-2"])
    panel._process = None
    panel._launch_worker = None
    panel._process_key = "scrcpy_test"
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.resolve_executable.return_value = "scrcpy.exe"
    panel._scrcpy_config = lambda exe, device: _scrcpy_config(exe=exe, device=device)
    panel._set_session_state = Mock()
    panel._update_status = Mock()
    panel._log = Mock()
    with (
        patch("gui.panels.remote_panel.os.path.isfile", return_value=True),
        patch("gui.panels.remote_panel.ScrcpyLaunchWorker") as worker_type,
    ):
        panel._start_scrcpy()

    configs = worker_type.call_args.args[0]
    assert [config.device for config in configs] == ["device-1", "device-2"]
    assert panel.get_remote_session_devices() == ["device-1", "device-2"]
    worker_type.return_value.start.assert_called_once()


def _remote_batch_panel():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1", "device-2"])
    panel._target_devices = ("device-1", "device-2")
    panel._session_devices = panel._target_devices
    panel._session_process_keys = ()
    panel._processes = {}
    panel._process = None
    panel._process_key = "batch"
    panel._session_state = RemotePanel._SESSION_STARTING
    panel._device_admission_revision = 0
    panel._launch_admission_revision = 0
    panel._launch_worker = None
    panel._watchdog = Mock()
    panel._set_running = Mock()
    panel._set_session_state = Mock()
    panel._update_status = Mock()
    panel._update_action_states = Mock()
    panel._log = Mock()
    panel._remote_control = Mock()
    panel._input_engine = Mock()
    panel._adb = Mock()
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.start.side_effect = lambda *_args: Mock(stderr=[], poll=lambda: None)
    return panel


def _remote_batch_plans():
    return [
        (_scrcpy_config(device=device), ["scrcpy", "-s", device], "1080x2400")
        for device in ("device-1", "device-2")
    ]


def test_remote_batch_launches_independent_processes_and_keeps_stop_ownership():
    panel = _remote_batch_panel()
    panel._on_batch_launch_ready(_remote_batch_plans())
    assert panel._scrcpy_service.start.call_args_list == [
        (("batch_0", ["scrcpy", "-s", "device-1"]),),
        (("batch_1", ["scrcpy", "-s", "device-2"]),),
    ]
    assert tuple(panel._processes) == ("device-1", "device-2")
    panel._set_running.assert_called_once_with(True)

    panel.set_target_devices(["new-device"])
    assert panel.get_remote_session_devices() == ["device-1", "device-2"]
    panel._request_scrcpy_stop_once()
    panel._request_scrcpy_stop_once()
    assert panel._scrcpy_service.request_stop.call_args_list == [
        (("batch_0",),), (("batch_1",),),
    ]
    panel.shutdown()
    assert panel._remote_input_shutdown.wait(1)


def test_remote_batch_partial_launch_failure_keeps_successful_mirror_stoppable():
    panel = _remote_batch_panel()
    panel._scrcpy_service.start.side_effect = [
        OSError("failed"), Mock(stderr=[], poll=lambda: None),
    ]
    panel._on_batch_launch_ready(_remote_batch_plans())
    assert panel.get_remote_session_devices() == ["device-2"]
    assert panel._scrcpy_process_keys() == ("batch_1",)
    panel._set_running.assert_called_once_with(True)
    panel.shutdown()
    assert panel._remote_input_shutdown.wait(1)
    panel._scrcpy_service.request_stop.assert_called_once_with("batch_1")


def test_remote_batch_process_exit_keeps_other_mirror_running():
    panel = _remote_batch_panel()
    first = Mock(stderr=[], poll=Mock(return_value=1))
    second = Mock(stderr=[], poll=Mock(return_value=None))
    panel._scrcpy_service.start.side_effect = [first, second]
    panel._on_batch_launch_ready(_remote_batch_plans())
    panel._set_running.reset_mock()
    panel._poll_process()
    assert panel._process is second
    assert panel.get_remote_session_devices() == ["device-2"]
    panel._set_running.assert_not_called()
    second.poll.return_value = 0
    panel._poll_process()
    assert panel.get_remote_session_devices() == []
    panel._set_running.assert_called_once_with(False)
    panel.shutdown()
    assert panel._remote_input_shutdown.wait(1)


@pytest.mark.parametrize("cancel_by_selection", [False, True])
def test_remote_batch_rejects_queued_launch_after_cancel_or_selection_change(cancel_by_selection):
    panel = _remote_batch_panel()
    if cancel_by_selection:
        panel.set_target_devices(["device-1"])
    else:
        panel._session_state = RemotePanel._SESSION_STOPPING
    panel._on_batch_launch_ready(_remote_batch_plans())
    panel._scrcpy_service.start.assert_not_called()


def test_remote_batch_background_thread_failure_preserves_process_ownership():
    panel = _remote_batch_panel()
    with patch("gui.panels.remote_panel.threading.Thread") as thread_type:
        thread_type.return_value.start.side_effect = RuntimeError("no thread")
        panel._on_batch_launch_ready(_remote_batch_plans())
    assert panel.get_remote_session_devices() == ["device-1", "device-2"]
    panel.shutdown()
    assert panel._remote_input_shutdown.wait(1)
    assert panel._scrcpy_service.request_stop.call_count == 2


def test_remote_batch_supervisor_closes_all_processes_after_selection_is_cleared():
    panel = _remote_batch_panel()
    active = set()

    def start(key, _args):
        active.add(key)
        return Mock(stderr=[], poll=lambda: None)

    def request_stop(key):
        active.discard(key)
        return True

    panel._scrcpy_service.start.side_effect = start
    panel._scrcpy_service.request_stop.side_effect = request_stop
    panel._scrcpy_service.is_active.side_effect = lambda key: key in active
    panel._on_batch_launch_ready(_remote_batch_plans())
    panel.set_target_devices([])
    supervisor = TaskSupervisor()
    assert panel.register_shutdown_task(supervisor, owner_id="remote", task_id="batch")
    panel.shutdown()
    results = supervisor.stop_all(deadline=1)
    assert results[0].disposition is StopDisposition.GRACEFUL
    assert not active
    assert panel._scrcpy_service.request_stop.call_count == 2
    assert all(not thread.is_alive() for thread in panel._scrcpy_threads)
    panel._adb.close_input_sessions.assert_called_once()


def test_remote_batch_worker_keeps_successful_plan_when_another_device_fails():
    from gui.panels.remote_panel import ScrcpyLaunchWorker
    service = Mock()
    service.build_launch_plan.side_effect = [
        OSError("failed"),
        Mock(args=["scrcpy", "-s", "device-2"], device_info="1080x2400", messages=[]),
    ]
    worker = ScrcpyLaunchWorker([item[0] for item in _remote_batch_plans()], service=service)
    received = []
    worker.batch_ready.connect(received.append)
    worker.run()
    assert len(received) == 1
    assert [config.device for config, _args, _info in received[0]] == ["device-2"]
    worker.deleteLater()


def test_remote_batch_retry_only_requests_devices_whose_stop_request_failed():
    panel = _remote_batch_panel()
    panel._session_process_keys = ("batch_0", "batch_1")
    panel._scrcpy_service.request_stop.side_effect = [True, OSError("failed"), True]
    with pytest.raises(OSError):
        panel._request_scrcpy_stop_once()
    panel._request_scrcpy_stop_once()
    assert panel._scrcpy_service.request_stop.call_args_list == [
        (("batch_0",),), (("batch_1",),), (("batch_1",),),
    ]


def test_remote_batch_user_stop_attempts_all_devices_when_one_stop_fails():
    panel = _remote_batch_panel()
    panel._on_batch_launch_ready(_remote_batch_plans())
    panel._session_state = RemotePanel._SESSION_RUNNING
    panel._scrcpy_service.stop.side_effect = [OSError("failed"), 0]
    panel._stop_completed_requested = Mock()
    with patch("gui.panels.remote_panel.threading.Thread") as thread_type:
        panel._stop_scrcpy()
        thread_type.call_args.kwargs["target"]()
    assert [call.args[0] for call in panel._scrcpy_service.stop.call_args_list] == [
        "batch_0", "batch_1",
    ]
    panel._stop_completed_requested.emit.assert_called_once_with(False)
    assert panel._scrcpy_stop_claim is None
    panel.shutdown()
    assert panel._remote_input_shutdown.wait(1)


def test_remote_batch_worker_cancellation_does_not_prepare_or_launch_remaining_devices():
    from gui.panels.remote_panel import ScrcpyLaunchWorker
    service = Mock()
    service.build_launch_plan.side_effect = InterruptedError("cancelled")
    worker = ScrcpyLaunchWorker([item[0] for item in _remote_batch_plans()], service=service)
    received = []
    worker.batch_ready.connect(received.append)
    worker.run()
    service.build_launch_plan.assert_called_once()
    assert received == []
    worker.deleteLater()


def test_remote_batch_does_not_launch_after_shutdown_resource_snapshot():
    panel = _remote_batch_panel()
    panel._remote_input_shutdown_handle()
    panel._on_batch_launch_ready(_remote_batch_plans())
    panel._scrcpy_service.start.assert_not_called()
    panel.shutdown()
    assert panel._remote_input_shutdown.wait(1)


def test_remote_input_failure_on_one_device_does_not_skip_other_targets():
    panel = _remote_batch_panel()
    panel._remote_executor = Mock()
    panel._emit_remote_queue_status = Mock()
    panel._remote_control.send_keyevent.side_effect = [OSError("failed"), True]
    panel._send_keyevent("HOME")
    for call in panel._remote_executor.submit.call_args_list:
        call.args[0]()
    assert panel._remote_failed == 1
    assert panel._remote_sent == 1
    assert panel._remote_completed == 2


def test_remote_batch_configuration_failure_leaves_start_available():
    panel = _remote_batch_panel()
    panel._session_state = RemotePanel._SESSION_IDLE
    panel._scrcpy_service.resolve_executable.return_value = "scrcpy.exe"
    panel._scrcpy_config = Mock(side_effect=OSError("recording directory unavailable"))
    with (
        patch("gui.panels.remote_panel.os.path.isfile", return_value=True),
        patch("gui.panels.remote_panel.ScrcpyLaunchWorker") as worker_type,
    ):
        panel._start_scrcpy()
    worker_type.assert_not_called()
    assert panel.get_remote_session_devices() == []
    panel._set_running.assert_called_once_with(False)


def test_remote_real_batch_worker_delivers_all_processes_once_and_stops_in_gui(qt_application):
    service = Mock()
    service.resolve_executable.return_value = "scrcpy.exe"
    service.build_launch_plan.side_effect = lambda config, **_kwargs: Mock(
        args=["scrcpy", "-s", config.device], device_info="1080x2400", messages=[],
    )
    active = set()

    def start(key, _args):
        active.add(key)
        return Mock(stderr=[], poll=lambda: None)

    service.start.side_effect = start
    service.stop.side_effect = lambda key, **_kwargs: active.discard(key)
    service.is_active.side_effect = lambda key: key in active
    with (
        patch("gui.panels.remote_panel.ScrcpyService", return_value=service),
        patch("gui.panels.remote_panel.ADBBridge", return_value=Mock(path="adb")),
        patch("gui.panels.remote_panel.RemoteControlService"),
        patch("gui.panels.remote_panel.RemoteInputEngine"),
        patch("gui.panels.remote_panel.os.path.isfile", return_value=True),
    ):
        side = SidePanel()
        remote = side._ensure_tab_loaded(2)
        try:
            remote.set_target_devices(["device-1", "device-2"])
            remote._start_scrcpy()
            remote._start_scrcpy()
            assert _wait_for_qt(qt_application, lambda: (
                remote._launch_worker is None and len(remote._processes) == 2
            ))
            assert service.start.call_count == 2
            assert remote._session_state == remote._SESSION_RUNNING
            remote.set_target_devices([])
            assert remote.btn_stop.isEnabled()
            remote._stop_scrcpy()
            remote._stop_scrcpy()
            assert _wait_for_qt(
                qt_application, lambda: remote._session_state == remote._SESSION_IDLE,
            )
            assert service.stop.call_count == 2
            assert not active
            remote.shutdown()
            assert remote._remote_input_shutdown.wait(1)
            assert all(not thread.is_alive() for thread in remote._scrcpy_threads)
        finally:
            remote.shutdown()
            side.close()


def test_remote_single_mirror_shutdown_waits_for_reader_and_focus_tasks():
    panel = _remote_batch_panel()
    panel._target_devices = ("device-1",)
    panel._session_devices = ("device-1",)
    panel._active_device = "device-1"
    panel._start_warm_remote_input_session = Mock()
    focus_entered = threading.Event()
    reader_entered = threading.Event()
    release_focus = threading.Event()
    release_reader = threading.Event()
    workers = []

    class BlockingStderr:
        def __iter__(self):
            workers.append(threading.current_thread())
            reader_entered.set()
            assert release_reader.wait(2)
            return iter(())

    def focus(_title):
        workers.append(threading.current_thread())
        focus_entered.set()
        assert release_focus.wait(2)
        return True

    process = Mock(stderr=BlockingStderr(), poll=lambda: None)
    panel._scrcpy_service.start.return_value = process
    panel._scrcpy_service.start.side_effect = None
    panel._input_engine.focus_window.side_effect = focus
    try:
        panel._on_launch_ready(["scrcpy", "-s", "device-1"], "1080x2400")
        assert focus_entered.wait(1) and reader_entered.wait(1)
        panel.shutdown()
        assert not panel._remote_input_shutdown.wait(0.05)
        panel._adb.close_input_sessions.assert_not_called()
        release_focus.set()
        assert not panel._remote_input_shutdown.wait(0.05)
        release_reader.set()
        assert panel._remote_input_shutdown.wait(1)
        assert all(not worker.is_alive() for worker in workers)
        panel._adb.close_input_sessions.assert_called_once()
        panel._scrcpy_service.request_stop.assert_called_once_with("batch")
    finally:
        release_focus.set()
        release_reader.set()
        for worker in workers:
            worker.join(1)
        panel.shutdown()


@pytest.mark.parametrize("failing_thread", ["focus", "reader", "warmup"])
def test_remote_single_background_start_failure_preserves_running_process(failing_thread):
    panel = _remote_batch_panel()
    panel._target_devices = ("device-1",)
    panel._session_devices = ("device-1",)
    panel._active_device = "device-1"
    process = Mock(stderr=[], poll=lambda: None)
    panel._scrcpy_service.start.return_value = process
    panel._scrcpy_service.start.side_effect = None
    panel._start_warm_remote_input_session = Mock()
    if failing_thread == "warmup":
        panel._start_warm_remote_input_session.side_effect = RuntimeError("no thread")
    with patch("gui.panels.remote_panel.threading.Thread") as thread_type:
        thread_type.return_value.start.side_effect = (
            [RuntimeError("no thread"), None]
            if failing_thread == "focus" else [None, RuntimeError("no thread")]
            if failing_thread == "reader" else None
        )
        panel._on_launch_ready(["scrcpy", "-s", "device-1"], "1080x2400")
    assert panel._process is process
    assert panel.get_remote_session_devices() == ["device-1"]
    panel._set_running.assert_called_once_with(True)
    panel.shutdown()
    assert panel._remote_input_shutdown.wait(1)
    panel._scrcpy_service.request_stop.assert_called_once_with("batch")


class _FaultInjectingLaunchWorker:
    """在指定 QThread 生命周期步骤注入异常，并记录最终所有权动作。"""

    def __init__(self, *faults):
        self.faults = set(faults)
        self.finished = _TestSignal()
        self.is_running_calls = 0
        self.request_calls = 0
        self.wait_calls = []
        self.parent_calls = []
        self.delete_calls = 0

    def isRunning(self):
        self.is_running_calls += 1
        if "is_running" in self.faults:
            raise RuntimeError("isRunning failed")
        return True

    def requestInterruption(self):
        self.request_calls += 1
        if "request" in self.faults:
            raise RuntimeError("request failed")

    def wait(self, timeout_ms):
        self.wait_calls.append(timeout_ms)
        if "wait" in self.faults:
            raise RuntimeError("wait failed")
        return True

    def setParent(self, parent):
        self.parent_calls.append(parent)
        if "set_parent" in self.faults:
            raise ValueError("setParent failed")

    def deleteLater(self):
        self.delete_calls += 1
        if "delete" in self.faults:
            raise RuntimeError("delete failed")


class _DeleteFailingQThread(QThread):
    """用真实线程完成信号验证删除重试，不允许测试手工重发 ``finished``。"""

    def __init__(self, *, failures: int | None):
        super().__init__()
        self.failures = failures
        self.delete_calls = 0

    def run(self):
        return None

    def deleteLater(self):
        self.delete_calls += 1
        if self.failures is None or self.delete_calls <= self.failures:
            raise RuntimeError("delete failed")
        super().deleteLater()


class _ProbeAndDeleteFailingQThread(QThread):
    """真实发出 ``finished``，同时永久拒绝状态探测和延迟删除。"""

    def __init__(self):
        super().__init__()
        self.started_running = threading.Event()
        self.release_run = threading.Event()
        self.delete_calls = 0

    def run(self):
        self.started_running.set()
        self.release_run.wait(2.0)

    def isRunning(self):
        raise RuntimeError("isRunning failed")

    def deleteLater(self):
        self.delete_calls += 1
        raise RuntimeError("delete failed")


def _wait_for_qt(qt_application, predicate, *, attempts: int = 100) -> bool:
    """在有界事件循环轮次内等待真实 Qt 回收条件。"""

    for _attempt in range(attempts):
        qt_application.processEvents()
        if predicate():
            return True
        QTest.qWait(2)
    qt_application.processEvents()
    return bool(predicate())


def _scrcpy_config(**overrides):
    values = {
        "exe": "scrcpy.exe",
        "adb": "adb.exe",
        "device": "device-1",
        "maxsize": "1080p",
        "fps": "60",
        "bitrate": "12",
        "codec": "h264",
        "buffer": "50",
        "orientation": "0",
    }
    values.update(overrides)
    return ScrcpyConfig(**values)


def test_scrcpy_service_builds_launch_plan_with_preflight_and_encoder():
    runner = Mock()
    runner.run.side_effect = [
        CommandResult(success=True, output="scrcpy 4.1"),
        CommandResult(success=True, output="ok"),
        CommandResult(success=True, output="Physical size: 1080x2400"),
        CommandResult(success=True, output="OMX.qcom.video.encoder.avc h264 encoder"),
    ]
    service = ScrcpyService(command_runner=runner)

    plan = service.build_launch_plan(_scrcpy_config(hw_encoder=True))

    assert plan.version == "4.1"
    assert plan.device_info == "1080x2400"
    assert plan.encoder == "OMX.qcom.video.encoder.avc"
    assert "--video-encoder" in plan.args
    assert ("INFO", "Using encoder: OMX.qcom.video.encoder.avc") in plan.messages
    assert runner.run.call_count == 4


def test_scrcpy_service_device_info_prefers_override_size():
    runner = Mock()
    runner.run.return_value = CommandResult(
        success=True,
        output="Physical size: 1080x2400\nOverride size: 1080x1920\n",
    )
    service = ScrcpyService(command_runner=runner)

    assert service.device_info("adb.exe", "device-1") == "1080x1920"


def test_scrcpy_service_device_info_falls_back_to_physical_size():
    runner = Mock()
    runner.run.return_value = CommandResult(success=True, output="Physical size: 1080x2400\n")
    service = ScrcpyService(command_runner=runner)

    assert service.device_info("adb.exe", "device-1") == "1080x2400"


def test_scrcpy_service_launch_plan_warns_and_skips_device_info_when_preflight_fails():
    runner = Mock()
    runner.run.side_effect = [
        CommandResult(success=True, output="scrcpy 4.1"),
        CommandResult(success=False, error="device offline"),
    ]
    service = ScrcpyService(command_runner=runner)

    plan = service.build_launch_plan(_scrcpy_config())

    assert plan.args[:3] == ["scrcpy.exe", "-s", "device-1"]
    assert plan.device_info == ""
    assert ("WARNING", "Device device-1 not responding") in plan.messages
    assert ("WARNING", "Pre-flight check failed - launching anyway...") in plan.messages
    assert runner.run.call_count == 2


def test_scrcpy_service_caches_version_per_executable():
    runner = Mock()
    runner.run.return_value = CommandResult(success=True, output="scrcpy 4.1")
    service = ScrcpyService(command_runner=runner)

    assert service.version("scrcpy.exe") == "4.1"
    assert service.version("scrcpy.exe") == "4.1"

    runner.run.assert_called_once_with(["scrcpy.exe", "--version"], timeout=3)


def test_scrcpy_launch_interruption_stops_current_query_and_remaining_plan():
    """停止发生于版本查询期间时，执行边界收到取消且不再探测设备。"""
    from gui.panels.remote_panel import ScrcpyLaunchWorker

    entered, release = threading.Event(), threading.Event()
    commands = []
    observed_cancel = []

    def run(command, **kwargs):
        commands.append(command)
        if len(commands) == 1:
            entered.set()
            assert release.wait(2)
            cancelled = kwargs.get("cancelled")
            observed_cancel.append(bool(cancelled and cancelled()))
        return CommandResult(success=True, output="scrcpy 4.1" if len(commands) == 1 else "ok")

    worker = ScrcpyLaunchWorker(
        _scrcpy_config(hw_encoder=True), service=ScrcpyService(command_runner=Mock(run=run)),
    )
    worker.start()
    try:
        assert entered.wait(2)
        worker.requestInterruption()
        release.set()
        assert worker.wait(2000)
        assert observed_cancel == [True]
        assert len(commands) == 1
    finally:
        release.set()
        worker.wait(2000)


def test_scrcpy_launch_plan_shares_deadline_between_queries():
    """后续查询仅使用剩余预算，到期后不再生成可启动的计划。"""
    clock = [100.0]
    budgets = []

    def run(command, **kwargs):
        budgets.append(kwargs["timeout"])
        clock[0] += 2.0
        outputs = ["scrcpy 4.1", "ok", "Physical size: 1080x2400"]
        return CommandResult(success=True, output=outputs[len(budgets) - 1])

    service = ScrcpyService(command_runner=Mock(run=run))
    with patch("services.remote.scrcpy_service.time.monotonic", side_effect=lambda: clock[0]):
        with pytest.raises(TimeoutError):
            service.build_launch_plan(_scrcpy_config(), timeout=6)
    assert budgets == [3, 4, 2]


def test_scrcpy_launch_plan_skips_advisory_speed_probe():
    """启动只等待必要预检，不因额外传输测速延迟产生计划。"""
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        output = "scrcpy 4.1" if "--version" in command else (
            "ok" if command[-1] == "echo ok" else "Physical size: 1080x2400"
        )
        return CommandResult(success=True, output=output)

    plan = ScrcpyService(command_runner=Mock(run=run)).build_launch_plan(_scrcpy_config())
    assert plan.device_info == "1080x2400"
    assert len(commands) == 3
    assert not any("dd if=" in command[-1] for command in commands)


def test_scrcpy_service_resolves_bundled_windows_executable():
    service = ScrcpyService()

    bundled_tool = Mock(return_value="C:/ADBLab/scrcpy.exe")
    with (
        patch("services.remote.scrcpy_service.platform.system", return_value="Windows"),
        patch(
            "services.remote.scrcpy_service.bundled_tool_path",
            bundled_tool,
        ),
    ):
        assert service.resolve_executable() == "C:/ADBLab/scrcpy.exe"
    bundled_tool.assert_called_once_with("scrcpy-win64", "scrcpy.exe")


def test_scrcpy_service_resolves_path_scrcpy_on_non_windows():
    service = ScrcpyService()

    with (
        patch("services.remote.scrcpy_service.platform.system", return_value="Linux"),
        patch("services.remote.scrcpy_service.shutil.which", return_value="/usr/bin/scrcpy"),
    ):
        assert service.resolve_executable() == "/usr/bin/scrcpy"


def test_scrcpy_service_start_and_stop_delegate_to_process_runner():
    process_runner = Mock()
    proc = Mock()
    process_runner.start.return_value = proc
    service = ScrcpyService(process_runner=process_runner)

    assert service.start("scrcpy_device", ["scrcpy.exe"]) is proc
    service.stop("scrcpy_device", timeout=2)

    process_runner.start.assert_called_once_with(
        "scrcpy_device",
        ["scrcpy.exe"],
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1,
    )
    process_runner.stop.assert_called_once_with("scrcpy_device", timeout=2)


def test_scrcpy_service_force_stop_only_confirms_released_process_key():
    """底层只尝试 kill 但进程仍受跟踪时，不得把强停误报为成功。"""

    process_runner = Mock()
    process_runner.force_stop.return_value = True
    process_runner.active_keys = ["scrcpy_device"]
    service = ScrcpyService(process_runner=process_runner)

    assert service.force_stop("scrcpy_device", timeout=0.1) is False

    process_runner.active_keys = []
    assert service.force_stop("scrcpy_device", timeout=0.1) is True
    assert process_runner.force_stop.call_count == 2
    process_runner.force_stop.assert_called_with("scrcpy_device", 0.1)


def test_scrcpy_service_parse_fps_returns_status_text():
    assert ScrcpyService.parse_fps("[server] INFO: [59.8 fps]") == "59.8 fps"
    assert ScrcpyService.parse_fps("INFO: renderer ready") is None


def test_remote_control_service_sends_keyevent_and_directional_swipe():
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    service = RemoteControlService(adb)

    service.send_keyevent("device-1", "HOME")
    service.directional_swipe("device-1", "up", duration_ms=200)

    adb.shell_input.assert_any_call("keyevent 3", device_id="device-1")
    adb.shell_input.assert_any_call("swipe 540 2160 540 240 200", device_id="device-1")


def test_remote_control_service_send_keyevent_rejects_injection():
    adb = Mock()
    service = RemoteControlService(adb)

    # 白名单键名 -> 映射 keycode
    service.send_keyevent("device-1", "HOME")
    adb.shell_input.assert_called_once_with("keyevent 3", device_id="device-1")
    adb.shell_input.reset_mock()

    # 显式数字 keycode -> 允许
    service.send_keyevent("device-1", "123")
    adb.shell_input.assert_called_once_with("keyevent 123", device_id="device-1")
    adb.shell_input.reset_mock()

    # 注入负载 / 未知键名 -> 拒绝，不调用 shell_input
    assert service.send_keyevent("device-1", "3; rm -rf /data") is None
    assert service.send_keyevent("device-1", "abc") is None
    adb.shell_input.assert_not_called()


def test_adb_bridge_warm_input_session_prepares_persistent_session():
    bridge = ADBBridge(path="adb.exe")
    session = Mock()
    session.warm.return_value = True

    with patch.object(bridge, "_input_session", return_value=session) as input_session:
        assert bridge.warm_input_session("device-1") is True

    input_session.assert_called_once_with("device-1")
    session.warm.assert_called_once_with()


def test_adb_input_session_warm_opens_shell_without_writing_input():
    proc = Mock()
    proc.stdin = Mock()
    proc.poll.return_value = None
    runner = Mock()
    runner.start.return_value = proc

    with patch("core.adb_bridge.ProcessRunner", return_value=runner):
        session = ADBInputSession("adb.exe", "device-1")
        assert session.warm() is True

    runner.start.assert_called_once()
    assert runner.start.call_args.args[:2] == (
        session._key,
        ["adb.exe", "-s", "device-1", "shell"],
    )
    proc.stdin.write.assert_not_called()
    proc.stdin.flush.assert_not_called()


def test_remote_control_service_reuses_cached_dimensions_for_fast_gestures():
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    service = RemoteControlService(adb)

    service.directional_swipe("device-1", "up")
    service.directional_swipe("device-1", "down")

    adb.get_dimensions.assert_called_once_with(device_id="device-1")


def test_remote_control_service_uses_launch_plan_dimensions_without_adb_query():
    adb = Mock()
    service = RemoteControlService(adb)
    service.remember_dimensions("device-1", ["720", "1280"])

    service.expand_notifications("device-1")

    adb.get_dimensions.assert_not_called()
    adb.shell_input.assert_called_once_with("swipe 360 0 360 1279 300", device_id="device-1")


def test_remote_control_service_perform_action_dispatches_known_actions():
    adb = Mock()
    adb.get_dimensions.return_value = ["1080", "2400"]
    service = RemoteControlService(adb)

    service.perform_action("device-1", "swipe_left")

    adb.shell_input.assert_called_once_with("swipe 972 1200 108 1200 300", device_id="device-1")


def test_remote_control_service_perform_action_rejects_unknown_action():
    service = RemoteControlService(Mock())

    try:
        service.perform_action("device-1", "does_not_exist")
    except ValueError as exc:
        assert "Unknown remote action" in str(exc)
    else:
        raise AssertionError("unknown remote action should fail")


def test_remote_control_service_rotation_clears_dimension_cache():
    adb = Mock()
    adb.shell.return_value = CommandResult(success=True)
    adb.get_dimensions.return_value = ["1080", "2400"]
    service = RemoteControlService(adb)
    service.remember_dimensions("device-1", ["720", "1280"])

    service.rotate_portrait("device-1")
    service.directional_swipe("device-1", "up")

    adb.get_dimensions.assert_called_once_with(device_id="device-1")


def test_remote_control_service_rotation_falls_back_to_legacy_setting():
    adb = Mock()
    adb.shell.side_effect = [
        CommandResult(success=True),
        CommandResult(success=False, error="unknown setting"),
        CommandResult(success=True),
    ]
    service = RemoteControlService(adb)

    service.rotate_landscape("device-1")

    assert adb.shell.call_args_list[0].args[0] == "settings put system accelerometer_rotation 0"
    assert adb.shell.call_args_list[1].args[0] == "settings put system user_rotation 1"
    assert adb.shell.call_args_list[2].args[0] == "settings put system rotation 1"


def test_remote_mapping_uses_safe_default_dimensions():
    assert notification_swipe(None, expand=True) == (540, 0, 540, 1919)
    assert directional_swipe(None, "left") == (972, 960, 108, 960)


def test_build_scrcpy_args_appends_extra_args_before_print_fps():
    args = build_scrcpy_args(_scrcpy_config(extra_args=["--window-title", "ADBLab"]))

    assert args[-3:] == ["--window-title", "ADBLab", "--print-fps"]


def test_build_scrcpy_args_enables_prefer_text_and_window_title():
    args = build_scrcpy_args(_scrcpy_config(window_title="ADBLab Remote - device-1"))

    assert "--prefer-text" in args
    title_index = args.index("--window-title")
    assert args[title_index : title_index + 2] == [
        "--window-title",
        "ADBLab Remote - device-1",
    ]
    assert args[-1] == "--print-fps"


def test_remote_input_engine_delegates_window_focus():
    window_manager = Mock()
    engine = RemoteInputEngine(window_manager=window_manager)

    assert engine.window_title("device-1") == "ADBLab Remote - device-1"
    engine.focus_window("ADBLab Remote - device-1", timeout_seconds=0.5)

    window_manager.focus.assert_called_once_with(
        "ADBLab Remote - device-1",
        timeout_seconds=0.5,
    )


def test_remote_window_manager_non_windows_focus_is_noop():
    manager = RemoteWindowManager()

    with patch("services.remote.window_manager.sys.platform", "linux"):
        assert manager.focus("ADBLab Remote - device-1", timeout_seconds=0) is False


def test_remote_window_manager_focus_accepts_already_foreground_window():
    manager = RemoteWindowManager()
    user32 = Mock()
    user32.GetForegroundWindow.return_value = 123

    with (
        patch("services.remote.window_manager.sys.platform", "win32"),
        patch("services.remote.window_manager.ctypes.windll") as windll,
        patch.object(manager, "_find_window", return_value=123),
    ):
        windll.user32 = user32

        assert manager.focus("ADBLab Remote - device-1", timeout_seconds=0.01) is True

    user32.ShowWindow.assert_called_once()
    user32.SetForegroundWindow.assert_not_called()


def test_remote_window_manager_focus_retries_after_set_foreground():
    manager = RemoteWindowManager(poll_interval_seconds=0.01)
    user32 = Mock()
    user32.GetForegroundWindow.side_effect = [999, 123]

    with (
        patch("services.remote.window_manager.sys.platform", "win32"),
        patch("services.remote.window_manager.ctypes.windll") as windll,
        patch.object(manager, "_find_window", return_value=123),
    ):
        windll.user32 = user32

        assert manager.focus("ADBLab Remote - device-1", timeout_seconds=1.0) is True

    user32.SetForegroundWindow.assert_called_once_with(123)
    assert user32.GetForegroundWindow.call_count == 2


def test_remote_panel_launch_ready_uses_scrcpy_service_start():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1"])
    panel._launch_worker = None
    panel._active_device = "device-1"
    panel._status_label = Mock()
    panel._update_status = lambda text, color: RemotePanel._update_status(panel, text, color)
    panel._log = Mock()
    panel._scrcpy_service = Mock()
    panel._remote_control = Mock()
    panel._input_engine = Mock()
    panel._process_key = "scrcpy_test"
    panel._watchdog = Mock()
    panel._set_running = Mock()
    panel._process = None
    old_stop_claim = object()
    panel._scrcpy_stop_claim = old_stop_claim
    proc = Mock()
    proc.stderr = None
    panel._scrcpy_service.start.return_value = proc

    with patch("gui.panels.remote_panel.threading.Thread") as thread_cls:
        RemotePanel._on_launch_ready(panel, ["scrcpy.exe", "-s", "device-1"], "1080x2400")

    panel._status_label.setText.assert_called_once_with("状态：运行中")
    panel._status_label.setToolTip.assert_called_once_with(
        "状态：运行中\n设备：1080x2400"
    )
    panel._status_label.setAccessibleDescription.assert_called_once_with(
        "状态：运行中\n设备：1080x2400"
    )
    assert panel._status_device_info == "1080x2400"
    panel._remote_control.remember_dimensions.assert_called_once_with("device-1", ["1080", "2400"])
    panel._scrcpy_service.start.assert_called_once_with(
        "scrcpy_test",
        ["scrcpy.exe", "-s", "device-1"],
    )
    assert panel._process is proc
    assert panel._scrcpy_stop_claim is None
    panel._set_running.assert_called_once_with(True)
    assert thread_cls.return_value.start.call_count == 3
    panel._watchdog.start.assert_called_once_with(500)

    panel._status_label.reset_mock()
    RemotePanel._update_status(panel, "60 fps", None)
    panel._status_label.setToolTip.assert_called_once_with(
        "状态：60 fps\n设备：1080x2400"
    )
    panel._status_label.setAccessibleDescription.assert_called_once_with(
        "状态：60 fps\n设备：1080x2400"
    )


def test_remote_panel_launch_failure_returns_controls_to_idle():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1"])
    panel._closing = False
    panel._launch_worker = None
    panel._active_device = "device-1"
    panel._status_label = Mock()
    panel._update_status = Mock()
    panel._log = Mock()
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.start.side_effect = OSError("launch failed")
    panel._remote_control = Mock()
    panel._process_key = "scrcpy_test"
    panel._set_running = Mock()
    panel._process = None
    old_stop_claim = object()
    panel._scrcpy_stop_claim = old_stop_claim

    RemotePanel._on_launch_ready(panel, ["scrcpy.exe", "-s", "device-1"], "1080x2400")

    assert panel._active_device is None
    assert panel._status_device_info == ""
    assert panel._scrcpy_stop_claim is old_stop_claim
    panel._set_running.assert_called_once_with(False)
    panel._update_status.assert_called_once_with("Error", None)


def test_remote_panel_worker_start_failure_returns_to_idle():
    panel = RemotePanel.__new__(RemotePanel)
    panel._process = None
    panel._launch_worker = None
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.resolve_executable.return_value = "C:/tools/scrcpy.exe"
    panel.panel = Mock(selected_devices=["device-1"])
    panel._set_session_state = Mock()
    panel._set_running = Mock()
    panel._update_status = Mock()
    panel._scrcpy_config = Mock(return_value=Mock())
    panel._log = Mock()
    worker = Mock()
    worker.start.side_effect = RuntimeError("thread unavailable")

    with (
        patch("gui.panels.remote_panel.os.path.isfile", return_value=True),
        patch("gui.panels.remote_panel.ScrcpyLaunchWorker", return_value=worker),
    ):
        RemotePanel._start_scrcpy(panel)

    assert panel._launch_worker is None
    assert panel._active_device is None
    panel._set_session_state.assert_called_once_with(RemotePanel._SESSION_STARTING)
    panel._set_running.assert_called_once_with(False)
    panel._update_status.assert_any_call("Checking...", None)
    panel._update_status.assert_any_call("Error", None)
    worker.deleteLater.assert_called_once_with()


def test_remote_panel_stop_scrcpy_uses_scrcpy_service_stop():
    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._active_device = "device-1"
    panel._process = Mock()
    panel._watchdog = Mock()
    panel._set_session_state = Mock()
    panel._update_status = Mock()
    panel._scrcpy_service = Mock()
    panel._process_key = "scrcpy_test"
    panel._log = Mock()

    panel._scrcpy_service.is_active.return_value = False
    with patch("gui.panels.remote_panel.threading.Thread") as thread_cls:
        RemotePanel._stop_scrcpy(panel)

    assert panel._process is not None
    assert panel._active_device == "device-1"
    panel._watchdog.stop.assert_called_once()
    panel._set_session_state.assert_called_once_with(RemotePanel._SESSION_STOPPING)
    panel._update_status.assert_called_once_with("Stopping...", None)

    stop_target = thread_cls.call_args.kwargs["target"]
    stop_target()

    panel._scrcpy_service.stop.assert_called_once_with("scrcpy_test", timeout=2)


def test_remote_user_stop_claim_prevents_shutdown_and_supervisor_duplicate_terminate(
    qt_application,
):
    """用户 Stop 正在等待时，直接关闭与 supervisor 不得再次终止同一进程。"""

    class BlockingProcess:
        def __init__(self):
            self.returncode = None
            self.stderr = None
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = []
            self.wait_entered = threading.Event()
            self.release_wait = threading.Event()

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminate_calls += 1

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            self.wait_entered.set()
            if not self.release_wait.wait(2.0):
                raise subprocess.TimeoutExpired("scrcpy", timeout)
            self.returncode = 0
            return 0

        def kill(self):
            self.kill_calls += 1
            self.returncode = -9

    side_panel = SidePanel()
    remote = side_panel._ensure_tab_loaded(2)
    process_key = "scrcpy_interleaving"
    process = BlockingProcess()
    runner = ProcessRunner()
    runner._procs[process_key] = process
    service = ScrcpyService(process_runner=runner)
    service.force_stop = Mock(wraps=service.force_stop)
    remote._scrcpy_service = service
    remote._process_key = process_key
    remote._process = process
    remote._active_device = "device-1"
    remote._adb = Mock()
    remote._set_session_state(RemotePanel._SESSION_RUNNING)
    remote._set_running = Mock()
    remote._update_status = Mock()
    remote._log = Mock()
    supervisor = TaskSupervisor()
    assert remote.register_shutdown_task(
        supervisor,
        owner_id="remote-owner",
        task_id="remote-session",
    )

    real_thread = threading.Thread
    stop_threads = []

    def capture_stop_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        stop_threads.append(thread)
        return thread

    supervisor_thread = None
    supervisor_results = []
    try:
        with patch(
            "gui.panels.remote_panel.threading.Thread",
            side_effect=capture_stop_thread,
        ):
            remote._stop_scrcpy()

        assert len(stop_threads) == 1
        assert process.wait_entered.wait(1.0)
        assert process.terminate_calls == 1

        original_request_stop_once = remote._request_scrcpy_stop_once
        request_attempts = []
        supervisor_request_seen = threading.Event()

        def observed_request_stop_once(*args, **kwargs):
            request_attempts.append((args, kwargs))
            if len(request_attempts) >= 2:
                supervisor_request_seen.set()
            return original_request_stop_once(*args, **kwargs)

        remote._request_scrcpy_stop_once = observed_request_stop_once
        remote.shutdown()

        def stop_supervised_task():
            supervisor_results.extend(supervisor.stop_all(deadline=1.0))

        supervisor_thread = real_thread(target=stop_supervised_task, daemon=True)
        supervisor_thread.start()
        assert supervisor_request_seen.wait(1.0)
        assert process.terminate_calls == 1
        status_calls_before_completion = remote._update_status.call_count
        running_calls_before_completion = remote._set_running.call_count

        process.release_wait.set()
        stop_threads[0].join(timeout=1.0)
        supervisor_thread.join(timeout=1.0)
        assert not stop_threads[0].is_alive()
        assert not supervisor_thread.is_alive()
        qt_application.processEvents()

        assert process.terminate_calls == 1
        assert process.kill_calls == 0
        assert process.wait_calls == [2]
        assert runner.active_keys == []
        assert len(supervisor_results) == 1
        assert supervisor_results[0].disposition is StopDisposition.GRACEFUL
        assert supervisor.active_count == 0
        service.force_stop.assert_not_called()
        assert remote._update_status.call_count == status_calls_before_completion
        assert remote._set_running.call_count == running_calls_before_completion
    finally:
        process.release_wait.set()
        for thread in stop_threads:
            thread.join(timeout=1.0)
        if supervisor_thread is not None:
            supervisor_thread.join(timeout=1.0)
        side_panel.close()


def test_remote_shutdown_claim_before_user_stop_does_not_start_blocking_stop():
    """关闭链路先取得 claim 后，晚到的用户 Stop 不得创建第二位 owner。"""

    panel = RemotePanel.__new__(RemotePanel)
    panel._session_state = RemotePanel._SESSION_RUNNING
    panel._launch_worker = None
    panel._process = object()
    panel._watchdog = Mock()
    panel._set_session_state = Mock()
    panel._update_status = Mock()
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.request_stop.return_value = True
    panel._process_key = "scrcpy_test"
    panel._log = Mock()

    assert RemotePanel._request_scrcpy_stop_once(panel)
    with patch("gui.panels.remote_panel.threading.Thread") as thread_cls:
        RemotePanel._stop_scrcpy(panel)

    thread_cls.assert_not_called()
    panel._watchdog.stop.assert_not_called()
    panel._set_session_state.assert_not_called()
    panel._update_status.assert_not_called()
    panel._scrcpy_service.request_stop.assert_called_once_with("scrcpy_test")
    panel._scrcpy_service.stop.assert_not_called()


def test_remote_stop_claim_release_cannot_clear_a_new_session_claim():
    """旧停止调用晚到释放时，不得清除新会话已经取得的 claim。"""

    panel = RemotePanel.__new__(RemotePanel)
    first_claim = RemotePanel._claim_scrcpy_stop(panel)
    assert first_claim is not None

    RemotePanel._reset_scrcpy_stop_claim(panel)
    second_claim = RemotePanel._claim_scrcpy_stop(panel)
    assert second_claim is not None
    assert second_claim is not first_claim

    assert RemotePanel._release_scrcpy_stop_claim(panel, first_claim) is False
    assert RemotePanel._claim_scrcpy_stop(panel) is None
    assert RemotePanel._release_scrcpy_stop_claim(panel, second_claim) is True
    assert RemotePanel._claim_scrcpy_stop(panel) is not None


def test_remote_user_stop_exception_releases_claim_for_shutdown_retry():
    """阻塞 stop 抛错后释放当前 token，让关闭路径可以重新请求停止。"""

    panel = RemotePanel.__new__(RemotePanel)
    panel._session_state = RemotePanel._SESSION_RUNNING
    panel._launch_worker = None
    panel._process = object()
    panel._watchdog = Mock()
    panel._set_session_state = Mock()
    panel._update_status = Mock()
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.stop.side_effect = RuntimeError("stop failed")
    panel._scrcpy_service.request_stop.return_value = True
    panel._process_key = "scrcpy_test"
    panel._log = Mock()

    with patch("gui.panels.remote_panel.threading.Thread") as thread_cls:
        RemotePanel._stop_scrcpy(panel)
    stop_target = thread_cls.call_args.kwargs["target"]
    stop_target()

    assert RemotePanel._request_scrcpy_stop_once(panel)
    panel._scrcpy_service.request_stop.assert_called_once_with("scrcpy_test")


def test_remote_shutdown_request_exception_allows_supervisor_retry_and_input_cleanup():
    """直接停止异常后 supervisor 可重试，executor 与 ADB 清理仍能完成。"""

    class RetryService:
        def __init__(self):
            self.active = True
            self.request_calls = 0
            self.force_calls = 0

        def is_active(self, _process_key):
            return self.active

        def request_stop(self, _process_key):
            self.request_calls += 1
            if self.request_calls == 1:
                raise RuntimeError("stop failed")
            self.active = False
            return True

        def force_stop(self, _process_key, _timeout):
            self.force_calls += 1
            self.active = False
            return True

    panel = RemotePanel.__new__(RemotePanel)
    panel._process = object()
    panel._watchdog = Mock()
    panel._scrcpy_service = RetryService()
    panel._process_key = "scrcpy_test"
    panel._launch_worker = None
    panel._remote_executor = Mock()
    panel._adb = Mock()
    executor = panel._remote_executor
    supervisor = TaskSupervisor()
    assert RemotePanel.register_shutdown_task(
        panel,
        supervisor,
        owner_id="remote-owner",
        task_id="remote-session",
    )

    RemotePanel.shutdown(panel)
    results = supervisor.stop_all(deadline=1.0)

    executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)
    panel._adb.close_input_sessions.assert_called_once_with()
    assert panel._scrcpy_service.request_calls == 2
    assert panel._scrcpy_service.force_calls == 0
    assert len(results) == 1
    assert results[0].disposition is StopDisposition.GRACEFUL
    assert supervisor.active_count == 0


def test_remote_shutdown_worker_exception_does_not_skip_executor_or_adb_cleanup():
    """启动 worker 清理失败时，executor 与 ADB 会话仍各自收口。"""

    panel = RemotePanel.__new__(RemotePanel)
    panel._process = None
    worker = _FaultInjectingLaunchWorker("request")
    panel._launch_worker = worker
    panel._disconnect_launch_worker = Mock()
    panel._remote_executor = Mock()
    panel._adb = Mock()
    executor = panel._remote_executor
    input_closed = threading.Event()
    panel._adb.close_input_sessions.side_effect = input_closed.set

    RemotePanel.shutdown(panel)

    assert panel._remote_input_shutdown.wait(1.0)
    assert panel._launch_worker is None
    assert worker.request_calls == 1
    assert worker.wait_calls == [0]
    assert worker.delete_calls == 1
    assert worker not in RemotePanel._orphaned_launch_workers
    executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)
    assert input_closed.wait(1.0)


@pytest.mark.parametrize(
    ("faults", "expected_error", "deferred"),
    [
        (("is_running",), "isRunning failed", False),
        (("request",), "request failed", False),
        (("wait",), "wait failed", True),
        (("request", "wait"), "request failed", True),
        (("delete",), "delete failed", True),
    ],
)
def test_remote_stop_launch_worker_fault_keeps_worker_owned_until_cleanup(
    qt_application,
    faults,
    expected_error,
    deferred,
):
    """worker 任一步异常后必须已等待删除，或由 orphan 集合强引用。"""

    panel = RemotePanel.__new__(RemotePanel)
    worker = _FaultInjectingLaunchWorker(*faults)
    panel._launch_worker = worker
    panel._disconnect_launch_worker = Mock()

    with pytest.raises(RuntimeError, match=expected_error):
        RemotePanel._stop_launch_worker(panel, wait_ms=0)

    assert panel._launch_worker is None
    assert worker.wait_calls == [0]
    if deferred:
        assert worker in RemotePanel._orphaned_launch_workers
        if "delete" in faults:
            assert worker.delete_calls == 1
            worker.faults.clear()
        else:
            assert worker.delete_calls == 0
        worker.finished.emit()
        assert _wait_for_qt(
            qt_application,
            lambda: worker not in RemotePanel._orphaned_launch_workers,
        )
        assert worker.delete_calls == (2 if "delete" in faults else 1)
    else:
        assert worker not in RemotePanel._orphaned_launch_workers
        assert worker.delete_calls == 1


def test_remote_defer_worker_tracks_before_set_parent_failure(qt_application):
    """defer 的辅助 Qt 操作失败前，worker 必须已经进入强引用集合。"""

    worker = _FaultInjectingLaunchWorker("set_parent")

    RemotePanel._defer_launch_worker_delete(worker)

    assert worker in RemotePanel._orphaned_launch_workers
    worker.faults.clear()
    worker.finished.emit()
    assert _wait_for_qt(
        qt_application,
        lambda: worker not in RemotePanel._orphaned_launch_workers,
    )
    assert worker.delete_calls == 1


def test_remote_finished_delete_failure_releases_after_bounded_retries(qt_application):
    """finished 已确认终止时，删除耗尽后必须结束 orphan 跟踪。"""

    worker = _FaultInjectingLaunchWorker("delete")
    RemotePanel._defer_launch_worker_delete(worker)

    worker.finished.emit()

    assert worker in RemotePanel._orphaned_launch_workers
    assert _wait_for_qt(
        qt_application,
        lambda: worker.delete_calls >= RemotePanel._LAUNCH_WORKER_DELETE_RETRY_LIMIT,
    )
    assert worker not in RemotePanel._orphaned_launch_workers
    assert worker.delete_calls == RemotePanel._LAUNCH_WORKER_DELETE_RETRY_LIMIT


def test_remote_finished_qthread_retries_delete_without_reemitting_finished(qt_application):
    """已结束线程的首次删除失败后，事件循环必须主动重试而不是等待旧信号。"""

    panel = RemotePanel.__new__(RemotePanel)
    worker = _DeleteFailingQThread(failures=1)
    panel._launch_worker = worker
    panel._disconnect_launch_worker = Mock()
    worker.start()
    assert worker.wait(1000)
    assert not worker.isRunning()

    with pytest.raises(RuntimeError, match="delete failed"):
        RemotePanel._stop_launch_worker(panel, wait_ms=0)

    assert worker in RemotePanel._orphaned_launch_workers
    assert _wait_for_qt(
        qt_application,
        lambda: worker not in RemotePanel._orphaned_launch_workers,
    )
    assert worker.delete_calls == 2


def test_remote_finished_qthread_delete_retry_exhaustion_has_finite_terminal_state(
    qt_application,
):
    """删除始终失败时，已停止线程不得永久残留或继续忙重试。"""

    panel = RemotePanel.__new__(RemotePanel)
    worker = _DeleteFailingQThread(failures=None)
    panel._launch_worker = worker
    panel._disconnect_launch_worker = Mock()
    worker.start()
    assert worker.wait(1000)
    assert not worker.isRunning()

    with pytest.raises(RuntimeError, match="delete failed"):
        RemotePanel._stop_launch_worker(panel, wait_ms=0)

    assert _wait_for_qt(
        qt_application,
        lambda: worker not in RemotePanel._orphaned_launch_workers,
    )
    terminal_calls = worker.delete_calls
    assert terminal_calls > 1
    QTest.qWait(50)
    qt_application.processEvents()
    assert worker.delete_calls == terminal_calls
    assert worker not in RemotePanel._orphaned_launch_workers


def test_remote_real_finished_signal_releases_orphan_when_probe_and_delete_fail(
    qt_application,
):
    """真实 finished 是可靠终态，探测与删除永久失败也不得留下回收闭包。"""

    worker = _ProbeAndDeleteFailingQThread()
    worker_key = id(worker)
    worker.start()
    try:
        assert worker.started_running.wait(1.0)
        RemotePanel._defer_launch_worker_delete(worker)
        assert worker in RemotePanel._orphaned_launch_workers
        assert worker.receivers(SIGNAL("finished()")) == 1

        worker.release_run.set()
        assert worker.wait(1000)
        assert _wait_for_qt(
            qt_application,
            lambda: worker not in RemotePanel._orphaned_launch_workers,
        )

        terminal_calls = worker.delete_calls
        assert terminal_calls > 0
        assert worker_key not in RemotePanel._launch_worker_reaper_states
        assert worker.receivers(SIGNAL("finished()")) == 0
        QTest.qWait(50)
        qt_application.processEvents()
        assert worker.delete_calls == terminal_calls
    finally:
        worker.release_run.set()
        worker.wait(1000)
        RemotePanel._forget_launch_worker(worker)


def test_remote_shutdown_executor_exception_does_not_skip_adb_cleanup():
    """输入执行器关闭失败时，持久 ADB 会话仍由独立边界清理。"""

    panel = RemotePanel.__new__(RemotePanel)
    panel._process = None
    panel._launch_worker = None
    panel._remote_executor = Mock()
    panel._remote_executor.shutdown.side_effect = RuntimeError("executor failed")
    panel._adb = Mock()
    input_closed = threading.Event()
    panel._adb.close_input_sessions.side_effect = input_closed.set

    RemotePanel.shutdown(panel)

    assert panel._remote_executor is None
    assert input_closed.wait(1.0)


def test_registered_remote_shutdown_defers_fast_input_error_to_supervisor():
    """注册后的 UI shutdown 不抢跑清理，确保快速失败仍由 supervisor 上报。"""

    panel = RemotePanel.__new__(RemotePanel)
    panel._process = None
    panel._launch_worker = None
    panel._remote_executor = None
    panel._remote_input_closing = False
    panel._remote_input_shutdown = None
    panel._remote_futures = set()
    panel._remote_futures_lock = threading.Lock()
    panel._warmup_threads = set()
    panel._warmup_threads_lock = threading.Lock()
    panel._adb = Mock()
    panel._adb.close_input_sessions.side_effect = OSError("input close failed")
    supervisor = TaskSupervisor()

    assert RemotePanel.register_shutdown_task(
        panel,
        supervisor,
        owner_id="remote-owner",
        task_id="remote-session",
    )

    RemotePanel.shutdown(panel)

    panel._adb.close_input_sessions.assert_not_called()
    results = supervisor.stop_all(deadline=0.5)
    assert len(results) == 1
    assert results[0].disposition is StopDisposition.FAILED
    assert results[0].error_type == "OSError"
    panel._adb.close_input_sessions.assert_called_once_with()
    assert supervisor.active_count == 1


def test_remote_shutdown_waits_for_running_input_before_closing_session_and_reports_timeout():
    """direct close 不阻塞 GUI；supervisor 能看到仍在执行的输入 producer。"""

    input_started = threading.Event()
    release_input = threading.Event()
    input_finished = threading.Event()
    session_closed = threading.Event()
    order = []

    def input_task():
        input_started.set()
        try:
            assert release_input.wait(2.0)
        finally:
            order.append("input-finished")
            input_finished.set()

    def close_input_sessions():
        order.append("session-closed")
        session_closed.set()

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="remote-shutdown-test")
    panel = RemotePanel.__new__(RemotePanel)
    panel._process = None
    panel._launch_worker = None
    panel._remote_executor = executor
    panel._remote_futures = set()
    panel._remote_futures_lock = threading.Lock()
    panel._warmup_threads = set()
    panel._warmup_threads_lock = threading.Lock()
    panel._remote_input_shutdown = None
    panel._adb = Mock()
    panel._adb.close_input_sessions.side_effect = close_input_sessions
    future = executor.submit(input_task)
    RemotePanel._track_remote_future(panel, future)
    supervisor = TaskSupervisor()

    try:
        assert input_started.wait(1.0)
        assert RemotePanel.register_shutdown_task(
            panel,
            supervisor,
            owner_id="remote-owner",
            task_id="remote-session",
        )

        RemotePanel.shutdown(panel)

        assert not session_closed.is_set()
        results = supervisor.stop_all(deadline=0.0)
        assert len(results) == 1
        assert results[0].disposition is StopDisposition.TIMED_OUT
        assert supervisor.active_count == 1

        release_input.set()
        assert panel._remote_input_shutdown.wait(2.0)
        assert input_finished.is_set()
        assert session_closed.is_set()
        assert order == ["input-finished", "session-closed"]
        assert future.done()

        completed = supervisor.stop_all(deadline=1.0)
        assert len(completed) == 1
        assert completed[0].disposition is StopDisposition.ALREADY_STOPPED
        assert supervisor.active_count == 0
    finally:
        release_input.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_remote_shutdown_capture_rejects_late_input_without_sync_fallback():
    """注册关闭资源后立即拒绝输入，不因 executor 已摘除而同步执行。"""

    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1"])
    panel._closing = False
    panel._remote_input_closing = False
    panel._remote_executor = Mock()
    panel._remote_futures = set()
    panel._remote_futures_lock = threading.Lock()
    panel._warmup_threads = set()
    panel._warmup_threads_lock = threading.Lock()
    panel._remote_input_shutdown = None
    panel._adb = Mock()
    panel._mark_remote_submitted = Mock()
    panel._mark_remote_completed = Mock()
    task = Mock(return_value=True)

    RemotePanel._remote_input_shutdown_handle(panel)
    RemotePanel._submit_remote_input(panel, task)

    assert panel._remote_input_closing is True
    task.assert_not_called()
    panel._mark_remote_submitted.assert_not_called()
    panel._mark_remote_completed.assert_not_called()


def test_remote_submit_registration_is_atomic_with_shutdown_capture():
    """executor 已读出后，shutdown 必须等待 submit 与 future 注册完成。"""

    submit_entered = threading.Event()
    allow_submit = threading.Event()
    capture_attempted = threading.Event()
    capture_finished = threading.Event()
    task_running = threading.Event()
    release_task = threading.Event()
    session_closed = threading.Event()
    order = []
    captured = []
    underlying = ThreadPoolExecutor(max_workers=1, thread_name_prefix="remote-admission-test")

    class GatedExecutor:
        def submit(self, task):
            submit_entered.set()
            assert allow_submit.wait(2.0)
            return underlying.submit(task)

        def shutdown(self, *, wait, cancel_futures):
            return underlying.shutdown(wait=wait, cancel_futures=cancel_futures)

    panel = RemotePanel.__new__(RemotePanel)
    panel._closing = False
    panel._remote_input_closing = False
    panel._remote_executor = GatedExecutor()
    panel.panel = Mock(selected_devices=["device-1"])
    panel._remote_futures = set()
    panel._remote_futures_lock = threading.Lock()
    panel._warmup_threads = set()
    panel._warmup_threads_lock = threading.Lock()
    panel._remote_input_shutdown = None
    panel._shutdown_request_lock = threading.Lock()
    panel._adb = Mock()
    panel._mark_remote_submitted = Mock()
    panel._mark_remote_completed = Mock()

    def input_task():
        task_running.set()
        assert release_task.wait(2.0)
        order.append("input-finished")
        return True

    def close_input_sessions():
        order.append("session-closed")
        session_closed.set()

    panel._adb.close_input_sessions.side_effect = close_input_sessions

    def submit_input():
        RemotePanel._submit_remote_input(panel, input_task)

    def capture_shutdown_resources():
        capture_attempted.set()
        captured.append(RemotePanel._remote_input_shutdown_handle(panel))
        capture_finished.set()

    submitter = threading.Thread(target=submit_input)
    capturer = threading.Thread(target=capture_shutdown_resources)
    submitter.start()
    try:
        assert submit_entered.wait(1.0)
        capturer.start()
        assert capture_attempted.wait(1.0)
        lock_acquired = panel._shutdown_request_lock.acquire(blocking=False)
        if lock_acquired:
            panel._shutdown_request_lock.release()
        assert not lock_acquired
        assert not capture_finished.is_set()

        allow_submit.set()
        submitter.join(2.0)
        capturer.join(2.0)
        assert not submitter.is_alive()
        assert not capturer.is_alive()
        assert task_running.wait(1.0)
        assert len(captured) == 1
        assert len(panel._remote_futures) == 1

        handle = captured[0]
        handle.start()
        assert not session_closed.is_set()
        release_task.set()
        assert handle.wait(2.0)
        assert order == ["input-finished", "session-closed"]
    finally:
        allow_submit.set()
        release_task.set()
        submitter.join(2.0)
        if capturer.ident is not None:
            capturer.join(2.0)
        if captured:
            captured[0].start()
            captured[0].wait(2.0)
        else:
            underlying.shutdown(wait=True, cancel_futures=True)


def test_remote_warmup_publish_and_start_are_atomic_for_shutdown_capture():
    """shutdown 不能捕获尚未 start 的 warmup Thread 后提前关闭会话。"""

    real_thread = threading.Thread
    start_entered = threading.Event()
    allow_start = threading.Event()
    warmup_running = threading.Event()
    release_warmup = threading.Event()
    capture_attempted = threading.Event()
    capture_finished = threading.Event()
    session_closed = threading.Event()
    captured = []

    class StartGatedThread(real_thread):
        def start(self):
            start_entered.set()
            assert allow_start.wait(2.0)
            super().start()

    panel = RemotePanel.__new__(RemotePanel)
    panel._closing = False
    panel._remote_executor = None
    panel._remote_futures = set()
    panel._remote_futures_lock = threading.Lock()
    panel._warmup_threads = set()
    panel._warmup_threads_lock = threading.Lock()
    panel._remote_input_shutdown = None
    panel._adb = Mock()
    panel._adb.close_input_sessions.side_effect = session_closed.set
    panel.panel = Mock(selected_devices=["device-1"])

    def warmup():
        warmup_running.set()
        assert release_warmup.wait(2.0)

    panel._warm_remote_input_session = warmup

    def launch_warmup():
        RemotePanel._start_warm_remote_input_session(panel)

    def capture_shutdown_resources():
        capture_attempted.set()
        captured.append(RemotePanel._remote_input_shutdown_handle(panel))
        capture_finished.set()

    launcher = real_thread(target=launch_warmup)
    capturer = real_thread(target=capture_shutdown_resources)
    with patch("gui.panels.remote_panel_input.threading.Thread", StartGatedThread):
        launcher.start()
        try:
            assert start_entered.wait(1.0)
            capturer.start()
            assert capture_attempted.wait(1.0)
            lock_acquired = panel._warmup_threads_lock.acquire(blocking=False)
            if lock_acquired:
                panel._warmup_threads_lock.release()
            assert not lock_acquired
            assert not capture_finished.is_set()
            allow_start.set()
            launcher.join(2.0)
            capturer.join(2.0)
        finally:
            allow_start.set()
            launcher.join(2.0)
            if capturer.ident is not None:
                capturer.join(2.0)

    assert not launcher.is_alive()
    assert not capturer.is_alive()
    assert warmup_running.wait(1.0)
    assert len(captured) == 1
    handle = captured[0]
    assert len(handle._warmup_threads) == 1

    handle.start()
    assert not session_closed.is_set()
    release_warmup.set()
    assert handle.wait(2.0)
    assert session_closed.is_set()


def test_remote_shutdown_joins_all_overlapping_warmups_before_closing_sessions():
    """两个并发 warmup 都必须进入 shutdown 快照并先于 session close 完成。"""

    started = (threading.Event(), threading.Event())
    release = (threading.Event(), threading.Event())
    finished = (threading.Event(), threading.Event())
    assignment_lock = threading.Lock()
    assigned = 0
    order = []
    session_closed = threading.Event()

    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1"])
    panel._closing = False
    panel._remote_input_closing = False
    panel._remote_executor = None
    panel._remote_futures = set()
    panel._remote_futures_lock = threading.Lock()
    panel._warmup_threads = set()
    panel._warmup_threads_lock = threading.Lock()
    panel._remote_input_shutdown = None
    panel._shutdown_request_lock = threading.Lock()
    panel._adb = Mock()

    def warmup():
        nonlocal assigned
        with assignment_lock:
            index = assigned
            assigned += 1
        started[index].set()
        assert release[index].wait(2.0)
        order.append(f"warmup-{index}-finished")
        finished[index].set()

    def close_input_sessions():
        order.append("session-closed")
        session_closed.set()

    panel._warm_remote_input_session = warmup
    panel._adb.close_input_sessions.side_effect = close_input_sessions

    warmup_threads = [
        RemotePanel._start_warm_remote_input_session(panel),
        RemotePanel._start_warm_remote_input_session(panel),
    ]
    try:
        assert started[0].wait(1.0)
        assert started[1].wait(1.0)
        handle = RemotePanel._remote_input_shutdown_handle(panel)
        assert len(handle._warmup_threads) == 2

        handle.start()
        release[0].set()
        assert finished[0].wait(1.0)
        assert not session_closed.is_set()

        release[1].set()
        assert handle.wait(2.0)
        assert finished[1].is_set()
        assert order[-1] == "session-closed"
        assert set(order[:-1]) == {"warmup-0-finished", "warmup-1-finished"}
    finally:
        release[0].set()
        release[1].set()
        for thread in warmup_threads:
            if thread is not None:
                thread.join(2.0)


def test_remote_supervisor_process_probe_exception_still_requests_all_cleanup():
    """进程探测异常应回传错误，但不能阻止 scrcpy 请求与 ADB 会话清理。"""

    class ProbeFailureService:
        def __init__(self):
            self.active = True
            self.probe_calls = 0
            self.request_calls = 0
            self.force_calls = 0

        def is_active(self, _process_key):
            self.probe_calls += 1
            raise ValueError("probe failed")

        def request_stop(self, _process_key):
            self.request_calls += 1
            self.active = False
            return True

        def force_stop(self, _process_key, _timeout):
            self.force_calls += 1
            self.active = False
            return True

    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._scrcpy_service = ProbeFailureService()
    panel._process_key = "scrcpy_test"
    panel._adb = Mock()
    input_closed = threading.Event()
    panel._adb.close_input_sessions.side_effect = input_closed.set
    supervisor = TaskSupervisor()
    assert RemotePanel.register_shutdown_task(
        panel,
        supervisor,
        owner_id="remote-owner",
        task_id="remote-session",
    )

    results = supervisor.stop_all(deadline=0.2)

    assert input_closed.wait(1.0)
    assert panel._scrcpy_service.request_calls == 1
    assert panel._scrcpy_service.force_calls == 1
    assert len(results) == 1
    assert results[0].disposition is StopDisposition.FORCED
    assert results[0].error_type == "ValueError"
    assert supervisor.active_count == 0


def test_remote_supervisor_input_thread_start_failure_completes_with_error():
    """输入清理线程无法启动时，必须同步关闭真实持久会话后再收口。"""

    class ImmediateStopService:
        def __init__(self):
            self.active = True

        def is_active(self, _process_key):
            return self.active

        def request_stop(self, _process_key):
            self.active = False
            return True

        def force_stop(self, _process_key, _timeout):
            self.active = False
            return True

    class FailingThread:
        def __init__(self, **_kwargs):
            return None

        def start(self):
            raise RuntimeError("thread start failed")

    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._scrcpy_service = ImmediateStopService()
    panel._process_key = "scrcpy_test"
    panel._adb = ADBBridge(path="adb")
    input_session = Mock()
    panel._adb._input_sessions["device-1"] = input_session
    supervisor = TaskSupervisor()
    assert RemotePanel.register_shutdown_task(
        panel,
        supervisor,
        owner_id="remote-owner",
        task_id="remote-session",
    )

    with patch("gui.panels.remote_panel.threading.Thread", FailingThread):
        results = supervisor.stop_all(deadline=0.2)

    input_session.close.assert_called_once_with()
    assert panel._adb._input_sessions == {}
    assert len(results) == 1
    assert results[0].disposition is StopDisposition.GRACEFUL
    assert results[0].error_type == "RuntimeError"
    assert supervisor.active_count == 0


def test_remote_supervisor_input_fallback_failure_stays_visible_and_not_graceful():
    """同步输入兜底也失败时，监督结果必须保留失败和残余证据。"""

    class ImmediateStopService:
        def __init__(self):
            self.active = True

        def is_active(self, _process_key):
            return self.active

        def request_stop(self, _process_key):
            self.active = False
            return True

        def force_stop(self, _process_key, _timeout):
            self.active = False
            return True

    class FailingThread:
        def __init__(self, **_kwargs):
            return None

        def start(self):
            raise RuntimeError("thread start failed")

    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._scrcpy_service = ImmediateStopService()
    panel._process_key = "scrcpy_test"
    panel._adb = ADBBridge(path="adb")
    input_session = Mock()
    input_session.close.side_effect = OSError("input close failed")
    panel._adb._input_sessions["device-1"] = input_session
    supervisor = TaskSupervisor()
    assert RemotePanel.register_shutdown_task(
        panel,
        supervisor,
        owner_id="remote-owner",
        task_id="remote-session",
    )

    with patch("gui.panels.remote_panel.threading.Thread", FailingThread):
        results = supervisor.stop_all(deadline=0.2)

    input_session.close.assert_called_once_with()
    assert len(results) == 1
    assert results[0].disposition is StopDisposition.FAILED
    assert results[0].error_type == "OSError"
    assert supervisor.active_count == 1


def test_remote_supervisor_input_fallback_error_survives_process_timeout():
    """进程同时超时时，输入同步兜底的实际异常仍应作为残余原因上报。"""

    class UnstoppableService:
        def is_active(self, _process_key):
            return True

        def request_stop(self, _process_key):
            return False

        def force_stop(self, _process_key, _timeout):
            return False

    class FailingThread:
        def __init__(self, **_kwargs):
            return None

        def start(self):
            raise RuntimeError("thread start failed")

    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._scrcpy_service = UnstoppableService()
    panel._process_key = "scrcpy_test"
    panel._adb = ADBBridge(path="adb")
    input_session = Mock()
    input_session.close.side_effect = OSError("input close failed")
    panel._adb._input_sessions["device-1"] = input_session
    supervisor = TaskSupervisor()
    assert RemotePanel.register_shutdown_task(
        panel,
        supervisor,
        owner_id="remote-owner",
        task_id="remote-session",
    )

    with patch("gui.panels.remote_panel.threading.Thread", FailingThread):
        results = supervisor.stop_all(deadline=0.02)

    input_session.close.assert_called_once_with()
    assert len(results) == 1
    assert results[0].disposition is StopDisposition.TIMED_OUT
    assert results[0].error_type == "OSError"
    assert supervisor.active_count == 1


@pytest.mark.parametrize("batch", [False, True], ids=["single", "batch"])
@pytest.mark.parametrize(
    ("with_force", "request_error_type", "force_error_type", "expected_error"),
    [
        (False, None, None, "OSError"),
        (True, None, None, "OSError"),
        (True, RuntimeError, None, "RuntimeError"),
        (True, RuntimeError, ValueError, "ValueError"),
    ],
    ids=[
        "completion-without-force",
        "completion-after-force",
        "request-over-completion",
        "force-over-request",
    ],
)
def test_task_supervisor_timeout_error_priority_is_identical_for_single_and_batch(
    batch,
    with_force,
    request_error_type,
    force_error_type,
    expected_error,
):
    """超时结果按 force、request、completion 顺序保留最有用的错误。"""

    supervisor = TaskSupervisor()

    def request_stop():
        if request_error_type is not None:
            raise request_error_type("request failed")

    def force_stop(_timeout):
        if force_error_type is not None:
            raise force_error_type("force failed")
        return False

    supervisor.register(
        "remote-timeout",
        owner_id="remote-owner",
        kind="remote_session",
        request_stop=request_stop,
        wait=lambda _timeout: False,
        is_running=lambda: True,
        force_stop=force_stop if with_force else None,
        error_type=lambda: "OSError",
    )

    if batch:
        results = supervisor.stop_all(deadline=0)
    else:
        result = supervisor.stop(
            "remote-timeout",
            graceful_timeout=0,
            force_timeout=0,
        )
        results = (result,)

    assert len(results) == 1
    assert results[0] is not None
    assert results[0].disposition is StopDisposition.TIMED_OUT
    assert results[0].error_type == expected_error
    assert supervisor.active_count == 1


@pytest.mark.parametrize("batch", [False, True], ids=["single", "batch"])
def test_task_supervisor_completed_task_with_completion_error_remains_failed(batch):
    """资源已停止但清理失败时，单项与批量路径都不得报告成功或移除残余。"""

    running = {"value": True}

    def request_stop():
        running["value"] = False

    supervisor = TaskSupervisor()
    supervisor.register(
        "remote-failed-cleanup",
        owner_id="remote-owner",
        kind="remote_session",
        request_stop=request_stop,
        wait=lambda _timeout: True,
        is_running=lambda: running["value"],
        error_type=lambda: "OSError",
    )

    if batch:
        results = supervisor.stop_all(deadline=0)
    else:
        result = supervisor.stop(
            "remote-failed-cleanup",
            graceful_timeout=0,
            force_timeout=0,
        )
        results = (result,)

    assert len(results) == 1
    assert results[0] is not None
    assert results[0].disposition is StopDisposition.FAILED
    assert results[0].error_type == "OSError"
    assert supervisor.active_count == 1


def test_remote_supervisor_async_input_error_survives_process_timeout():
    """正常启动的输入清理线程失败时，进程残余结果必须保留关闭异常。"""

    class UnstoppableService:
        def is_active(self, _process_key):
            return True

        def request_stop(self, _process_key):
            return False

        def force_stop(self, _process_key, _timeout):
            return False

    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = None
    panel._scrcpy_service = UnstoppableService()
    panel._process_key = "scrcpy_test"
    panel._adb = Mock()
    input_attempted = threading.Event()

    def fail_input_close():
        input_attempted.set()
        raise OSError("input close failed")

    panel._adb.close_input_sessions.side_effect = fail_input_close
    supervisor = TaskSupervisor()
    assert RemotePanel.register_shutdown_task(
        panel,
        supervisor,
        owner_id="remote-owner",
        task_id="remote-session",
    )

    results = supervisor.stop_all(deadline=0.02)

    assert input_attempted.wait(1.0)
    assert len(results) == 1
    assert results[0].disposition is StopDisposition.TIMED_OUT
    assert results[0].error_type == "OSError"
    assert supervisor.active_count == 1


def test_remote_shutdown_input_thread_start_failure_closes_sessions_synchronously():
    """direct shutdown 在线程无法启动时也必须实际关闭持久输入会话。"""

    class FailingThread:
        def __init__(self, **_kwargs):
            return None

        def start(self):
            raise RuntimeError("thread start failed")

    panel = RemotePanel.__new__(RemotePanel)
    panel._process = None
    panel._launch_worker = None
    panel._remote_executor = None
    panel._adb = ADBBridge(path="adb")
    input_session = Mock()
    panel._adb._input_sessions["device-1"] = input_session

    with patch("gui.panels.remote_panel.threading.Thread", FailingThread):
        RemotePanel.shutdown(panel)

    input_session.close.assert_called_once_with()
    assert panel._adb._input_sessions == {}


def test_remote_panel_ignores_repeated_stop_while_stopping():
    panel = RemotePanel.__new__(RemotePanel)
    panel._session_state = RemotePanel._SESSION_STOPPING
    panel._launch_worker = Mock()
    panel._process = Mock()
    panel._watchdog = Mock()

    RemotePanel._stop_scrcpy(panel)

    panel._launch_worker.isRunning.assert_not_called()
    panel._watchdog.stop.assert_not_called()


def test_remote_panel_controls_follow_full_session_state(qt_application):
    side_panel = SidePanel()
    try:
        remote = side_panel._ensure_tab_loaded(2)

        assert remote.btn_start.isEnabled() is False
        assert remote.btn_stop.isEnabled() is False
        assert all(not button.isEnabled() for button in remote._remote_control_buttons)

        item = QListWidgetItem("device-1")
        item.setData(Qt.ItemDataRole.UserRole, {"ip": "device-1"})
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        side_panel._devices_tab.listbox_devices.addItem(item)
        side_panel._connected_device_cache = ["device-1"]
        remote.update_action_states()

        assert remote.btn_start.isEnabled() is True
        assert all(button.isEnabled() for button in remote._remote_control_buttons)

        remote._set_session_state(RemotePanel._SESSION_STARTING)
        assert remote.btn_start.isEnabled() is False
        assert remote.btn_stop.isEnabled() is True
        assert all(button.isEnabled() for button in remote._remote_control_buttons)

        remote._set_session_state(RemotePanel._SESSION_RUNNING)
        assert remote.btn_start.isEnabled() is False
        assert remote.btn_stop.isEnabled() is True
        assert all(button.isEnabled() for button in remote._remote_control_buttons)

        remote._set_session_state(RemotePanel._SESSION_STOPPING)
        assert remote.btn_start.isEnabled() is False
        assert remote.btn_stop.isEnabled() is False
        assert all(button.isEnabled() for button in remote._remote_control_buttons)

        remote._set_session_state(RemotePanel._SESSION_IDLE)
        assert remote.btn_start.isEnabled() is True
        assert remote.btn_stop.isEnabled() is False
        assert all(button.isEnabled() for button in remote._remote_control_buttons)
    finally:
        side_panel.close()


def test_remote_panel_control_targets_selected_device_without_mirroring_session():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1"])
    panel._active_device = None
    panel._process = None
    panel._running = False
    panel._log = Mock()

    assert RemotePanel._selected_remote_device(panel) == "device-1"
    panel._log.assert_not_called()


def test_remote_panel_successful_stop_completion_returns_to_idle():
    panel = RemotePanel.__new__(RemotePanel)
    panel._closing = False
    panel._process = Mock()
    panel._active_device = "device-1"
    panel._set_running = Mock()
    panel._update_status = Mock()
    panel._log = Mock()

    RemotePanel._on_stop_completed(panel, True)

    assert panel._process is None
    assert panel._active_device is None
    panel._set_running.assert_called_once_with(False)
    panel._update_status.assert_called_once_with("Idle", None)
    panel._log.assert_called_once_with("INFO", "scrcpy stopped")


def test_remote_panel_failed_stop_restores_running_controls_for_live_process():
    panel = RemotePanel.__new__(RemotePanel)
    panel._closing = False
    panel._process = Mock()
    panel._process.poll.return_value = None
    panel._active_device = "device-1"
    panel._set_running = Mock()
    panel._update_status = Mock()
    panel._watchdog = Mock()

    RemotePanel._on_stop_completed(panel, False)

    assert panel._active_device == "device-1"
    panel._set_running.assert_called_once_with(True)
    panel._watchdog.start.assert_called_once_with(500)
    panel._update_status.assert_called_once_with("Stop Failed", None)


def test_remote_panel_close_requests_scrcpy_stop_without_waiting():
    panel = RemotePanel.__new__(RemotePanel)
    panel._process = Mock()
    panel._watchdog = Mock()
    panel._scrcpy_service = Mock()
    panel._process_key = "scrcpy_test"
    panel._launch_worker = None
    panel._remote_executor = Mock()
    panel._adb = Mock()
    executor = panel._remote_executor

    with patch("gui.panels.remote_panel.QWidget.closeEvent"):
        RemotePanel.closeEvent(panel, Mock())

    assert panel._remote_input_shutdown.wait(1.0)
    panel._watchdog.stop.assert_called_once()
    panel._scrcpy_service.request_stop.assert_called_once_with("scrcpy_test")
    panel._scrcpy_service.stop.assert_not_called()
    executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)
    panel._adb.close_input_sessions.assert_called_once()


def test_remote_panel_shutdown_detaches_launch_worker_without_blocking():
    panel = RemotePanel.__new__(RemotePanel)
    panel._process = None
    panel._watchdog = Mock()
    panel._scrcpy_service = Mock()
    panel._process_key = "scrcpy_test"
    panel._remote_executor = Mock()
    panel._adb = Mock()
    panel._log = Mock()
    panel._on_launch_ready = Mock()
    worker = Mock()
    worker.isRunning.return_value = True
    worker.wait.return_value = True
    panel._launch_worker = worker
    executor = panel._remote_executor

    RemotePanel.shutdown(panel)

    assert panel._remote_input_shutdown.wait(1.0)
    worker.requestInterruption.assert_called_once()
    worker.wait.assert_called_once_with(0)
    worker.deleteLater.assert_called_once()
    executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)
    panel._adb.close_input_sessions.assert_called_once()


def test_remote_panel_start_scrcpy_resolves_executable_via_service():
    panel = RemotePanel.__new__(RemotePanel)
    panel._process = None
    panel._launch_worker = None
    panel._scrcpy_service = Mock()
    panel._scrcpy_service.resolve_executable.return_value = "C:/tools/scrcpy.exe"
    panel._log = Mock()

    with patch("gui.panels.remote_panel.os.path.isfile", return_value=False):
        RemotePanel._start_scrcpy(panel)

    panel._scrcpy_service.resolve_executable.assert_called_once_with()
    panel._log.assert_called_once_with("WARNING", "scrcpy not found: C:/tools/scrcpy.exe")


def test_remote_panel_start_ignores_shortcut_while_stopping_after_worker_exits():
    panel = RemotePanel.__new__(RemotePanel)
    panel._session_state = RemotePanel._SESSION_STOPPING
    panel._process = None
    old_worker = Mock()
    old_worker.isRunning.return_value = False
    panel._launch_worker = old_worker
    panel._scrcpy_service = Mock()

    with patch("gui.panels.remote_panel.ScrcpyLaunchWorker") as worker_cls:
        RemotePanel._start_scrcpy(panel)

    panel._scrcpy_service.resolve_executable.assert_not_called()
    worker_cls.assert_not_called()


def test_remote_panel_remote_action_rejects_when_executor_is_unavailable():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1"])
    panel._remote_control = Mock()
    panel._log = Mock()

    RemotePanel._send_remote_action(panel, "swipe_up")

    panel._remote_control.perform_action.assert_not_called()
    panel._log.assert_not_called()


def test_remote_panel_remote_action_uses_executor_when_available():
    panel = RemotePanel.__new__(RemotePanel)
    panel.panel = Mock(selected_devices=["device-1"])
    panel._remote_control = Mock()
    panel._log = Mock()
    panel._remote_executor = Mock()
    panel._emit_remote_queue_status = Mock()
    panel._remote_submitted = 0
    panel._remote_completed = 0

    RemotePanel._send_remote_action(panel, "swipe_up")

    panel._remote_executor.submit.assert_called_once()
    panel._remote_control.perform_action.assert_not_called()
    panel._emit_remote_queue_status.assert_called_once_with(1, 0, "queued")

    queued_task = panel._remote_executor.submit.call_args.args[0]
    queued_task()

    panel._remote_control.perform_action.assert_called_once_with("device-1", "swipe_up")
    panel._emit_remote_queue_status.assert_any_call(1, 1, "sent")


def test_remote_panel_rejects_new_input_after_shutdown_admission_closes():
    panel = RemotePanel.__new__(RemotePanel)
    panel._closing = True
    panel._remote_executor = Mock()
    panel._mark_remote_submitted = Mock()
    task = Mock()

    RemotePanel._submit_remote_input(panel, task)

    panel._remote_executor.submit.assert_not_called()
    panel._mark_remote_submitted.assert_not_called()
    task.assert_not_called()


def test_remote_panel_queue_status_keeps_primary_text_compact_and_details_in_tooltip():
    panel = RemotePanel.__new__(RemotePanel)
    panel._remote_queue_label = Mock()
    panel._remote_sent = 7
    panel._remote_failed = 0

    RemotePanel._update_remote_queue_status(panel, 8, 7, "queued")

    panel._remote_queue_label.setText.assert_called_once_with("队列：1")
    panel._remote_queue_label.setToolTip.assert_called_once_with(
        "排队：1 · 已发送：7 · 失败：0"
    )
    panel._remote_queue_label.setAccessibleDescription.assert_called_once_with(
        "排队：1 · 已发送：7 · 失败：0"
    )

    panel._remote_queue_label.reset_mock()
    panel._remote_failed = 2
    RemotePanel._update_remote_queue_status(panel, 9, 9, "failed")

    panel._remote_queue_label.setText.assert_called_once_with("队列：0 · 失败：2")
    panel._remote_queue_label.setToolTip.assert_called_once_with(
        "排队：0 · 已发送：7 · 失败：2"
    )
    panel._remote_queue_label.setAccessibleDescription.assert_called_once_with(
        "排队：0 · 已发送：7 · 失败：2"
    )


def test_remote_panel_ignores_known_scrcpy_noise_lines():
    assert (
        RemotePanel._should_ignore_scrcpy_log_line("[server] WARN: Could not inject char u+4e2d")
        is True
    )
    assert (
        RemotePanel._should_ignore_scrcpy_log_line(
            "libpng warning: iCCP: known incorrect sRGB profile"
        )
        is True
    )
    assert RemotePanel._should_ignore_scrcpy_log_line("[server] INFO: ready") is False


def test_remote_panel_launch_finished_clears_active_device_when_start_fails():
    panel = RemotePanel.__new__(RemotePanel)
    panel._launch_worker = Mock()
    panel._active_device = "device-1"
    panel._process = None
    panel._set_running = Mock()
    panel._update_status = Mock()
    worker = Mock()
    worker.isInterruptionRequested.return_value = False
    panel._launch_worker = worker

    RemotePanel._on_launch_finished(panel, worker)

    assert panel._active_device is None
    panel._set_running.assert_called_once_with(False)
    panel._update_status.assert_called_once_with("Error", None)
    worker.deleteLater.assert_called_once()


def test_remote_panel_launch_finished_only_recycles_stale_worker():
    panel = RemotePanel.__new__(RemotePanel)
    current_worker = Mock()
    stale_worker = Mock()
    stale_worker.isInterruptionRequested.return_value = False
    panel._launch_worker = current_worker
    panel._active_device = "new-device"
    panel._session_state = RemotePanel._SESSION_STARTING
    panel._process = None
    panel._set_running = Mock()
    panel._update_status = Mock()

    RemotePanel._on_launch_finished(panel, stale_worker)

    assert panel._launch_worker is current_worker
    assert panel._active_device == "new-device"
    assert panel._session_state == RemotePanel._SESSION_STARTING
    panel._set_running.assert_not_called()
    panel._update_status.assert_not_called()
    stale_worker.deleteLater.assert_called_once_with()
