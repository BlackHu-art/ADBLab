"""验证 Remote 逐台启动、追加、取消与逐台操作的用户可观察行为。"""

import queue
import threading
import time
from collections import Counter
from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QThread

from gui.panels.side_panel import SidePanel
from services.remote.types import ScrcpyLaunchPlan


def _wait(app, predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        threading.Event().wait(0.002)
    return bool(predicate())


@pytest.mark.parametrize("tool", ["adb", "server (portable)", "icon (portable)"])
def test_scrcpy_tool_discovery_logs_remove_derived_runtime_paths(remote_session, tool):
    remote, _service = remote_session
    message = f"DEBUG: Using {tool}: C:\\private-runtime\\nested\\tool.exe"
    assert remote._redact_remote_diagnostic(message) == f"DEBUG: Using {tool}: <path>"


class _Process:
    def __init__(self):
        self.returncode = None
        self.lines = queue.Queue()
        self.output_lines = queue.Queue()
        self.stderr = iter(self.lines.get, None)
        self.stdout = iter(self.output_lines.get, None)

    def poll(self):
        return self.returncode

    def finish(self, code=0):
        self.returncode = code
        self.lines.put(None)
        self.output_lines.put(None)


class _Service:
    def __init__(self):
        self.gates = {}
        self.failures = set()
        self.prepared = []
        self.configs = []
        self.started = []
        self.start_threads = []
        self.processes = {}
        self.keys = {}
        self.stopped = []
        self.cleanup_pending = set()
        self.lock = threading.Lock()
        self.inflight = 0
        self.max_inflight = 0

    def resolve_executable(self):
        return "scrcpy.exe"

    def build_launch_plan(self, config, *, cancelled):
        with self.lock:
            self.prepared.append(config.device)
            self.configs.append(config)
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            gate = self.gates.get(config.device)
            while gate is not None and not gate.wait(0.002):
                if cancelled():
                    raise InterruptedError("cancelled")
            if cancelled():
                raise InterruptedError("cancelled")
            if config.device in self.failures:
                raise OSError("synthetic preflight failure")
            return ScrcpyLaunchPlan(
                args=["scrcpy", "-s", config.device], device_info="1080x2400", version="3.3",
            )
        finally:
            with self.lock:
                self.inflight -= 1

    def start(self, key, args):
        device = args[2]
        process = _Process()
        self.started.append(device)
        self.start_threads.append(QThread.currentThread())
        self.processes[device] = process
        self.keys[key] = process
        return process

    def start_plan(self, key, plan):
        return self.start(key, plan.args)

    def stop(self, key, timeout=2):
        self.stopped.append(key)
        process = self.keys.get(key)
        if process is not None:
            process.finish()

    def request_stop(self, key):
        self.stop(key)
        return True

    def is_active(self, key):
        process = self.keys.get(key)
        return key in self.cleanup_pending or (process is not None and process.poll() is None)

    def parse_fps(self, _line):
        return ""


@pytest.fixture
def remote_session(monkeypatch, qt_application):
    service = _Service()
    monkeypatch.setattr("gui.panels.remote_panel.ScrcpyService", lambda: service)
    monkeypatch.setattr("gui.panels.remote_panel.ADBBridge", lambda: Mock(path="adb"))
    monkeypatch.setattr("gui.panels.remote_panel.RemoteControlService", lambda _adb: Mock())
    monkeypatch.setattr("gui.panels.remote_panel.RemoteInputEngine", lambda: Mock())
    monkeypatch.setattr("gui.panels.remote_panel.os.path.isfile", lambda _path: True)
    side = SidePanel()
    remote = side._ensure_tab_loaded(2)
    try:
        yield remote, service
    finally:
        remote.shutdown()
        for gate in service.gates.values():
            gate.set()
        for process in service.processes.values():
            process.finish()
        assert remote._remote_input_shutdown.wait(2)
        assert _wait(qt_application, lambda: not service.inflight)
        side.close()


def test_fast_device_starts_before_slow_preflight_finishes_in_gui(remote_session, qt_application):
    remote, service = remote_session
    gate = service.gates["slow"] = threading.Event()
    remote.set_target_devices(["slow", "fast"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: "fast" in service.started)
    assert not gate.is_set()
    assert service.started == ["fast"]
    assert service.start_threads == [qt_application.thread()]


def test_preflight_limits_parallelism_to_three_devices(remote_session, qt_application):
    remote, service = remote_session
    devices = [f"device-{index}" for index in range(6)]
    for device in devices:
        service.gates[device] = threading.Event()
    remote.set_target_devices(devices)
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.inflight == 3)
    assert len(service.prepared) == 3
    for gate in service.gates.values():
        gate.set()
    assert _wait(qt_application, lambda: len(service.started) == 6)
    assert service.max_inflight == 3


def test_append_uses_frozen_configuration_without_restarting_existing_device(
    remote_session, qt_application,
):
    remote, service = remote_session
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.started == ["first"])
    first_process = service.processes["first"]
    assert not remote.fps.isEnabled()
    remote.set_target_devices(["first", "second"])
    assert remote.btn_start.isEnabled()
    remote.btn_start.click()
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: "second" in service.started)
    assert Counter(service.started) == {"first": 1, "second": 1}
    assert service.processes["first"] is first_process
    assert service.configs[0].fps == service.configs[1].fps
    assert not remote.fps.isEnabled()


def test_single_stop_and_retry_preserve_other_mirror(remote_session, qt_application):
    remote, service = remote_session
    remote.set_target_devices(["first", "second"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: len(service.started) == 2)
    second_process = service.processes["second"]
    remote._stop_device_scrcpy("first")
    assert _wait(qt_application, lambda: "first" not in remote._processes)
    assert second_process.poll() is None
    remote._retry_device_scrcpy("first")
    assert _wait(qt_application, lambda: service.started.count("first") == 2)
    assert service.processes["second"] is second_process


def test_mirror_ready_requires_explicit_video_output_and_exit_exposes_retry(
    remote_session, qt_application,
):
    remote, service = remote_session
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.started == ["first"])
    assert remote._session_rows["first"][1].text() == "连接中"
    process = service.processes["first"]
    process.output_lines.put("INFO: Renderer: direct3d")
    process.output_lines.put("INFO: Texture: 1080x2400")
    assert _wait(qt_application, lambda: remote._session_rows["first"][1].text() == "就绪")
    process.finish(1)
    remote._poll_process()
    assert remote._session_rows["first"][1].text() == "失败"
    assert remote._session_rows["first"][2].isEnabled()
    assert remote._session_rows["first"][2].text() == "重试"


def test_selection_change_revokes_unsent_launch_but_keeps_existing_process(
    remote_session, qt_application,
):
    remote, service = remote_session
    gate = service.gates["slow"] = threading.Event()
    remote.set_target_devices(["fast", "slow"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: "fast" in service.started)
    process = service.processes["fast"]
    remote.set_target_devices([])
    remote.set_target_devices(["fast", "slow"])
    gate.set()
    assert _wait(qt_application, lambda: remote._launch_worker is None)
    assert service.started == ["fast"]
    assert process.poll() is None
    assert remote.btn_stop.isEnabled()


def test_stop_all_keeps_start_locked_until_focus_thread_exits(remote_session, qt_application):
    remote, service = remote_session
    entered = threading.Event()
    release = threading.Event()

    def focus(_title):
        entered.set()
        assert release.wait(2)
        return False

    remote._input_engine.focus_window.side_effect = focus
    try:
        remote.set_target_devices(["first"])
        remote._start_scrcpy()
        assert _wait(qt_application, lambda: entered.is_set())
        remote._stop_scrcpy()
        assert _wait(qt_application, lambda: not remote._processes)
        assert remote._session_state == remote._SESSION_STOPPING
        assert not remote.btn_start.isEnabled()
        assert not remote.fps.isEnabled()
        remote._start_scrcpy()
        assert service.started == ["first"]
        release.set()
        assert _wait(qt_application, lambda: remote._session_state == remote._SESSION_IDLE)
        assert remote.btn_start.isEnabled()
        assert all(not thread.is_alive() for thread in remote._scrcpy_threads)
    finally:
        release.set()


def test_single_preparation_cancel_preserves_other_device_and_retry_generation(
    remote_session, qt_application,
):
    remote, service = remote_session
    service.gates["slow"] = threading.Event()
    remote.set_target_devices(["slow", "fast"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.started == ["fast"])
    old_config = remote._device_sessions["slow"].config
    remote._stop_device_scrcpy("slow")
    remote._retry_device_scrcpy("slow")
    service.gates["slow"].set()
    remote._on_device_plan_ready(
        old_config,
        ScrcpyLaunchPlan(args=["scrcpy", "-s", "slow"], device_info="", version="3.3"),
    )
    assert _wait(qt_application, lambda: len(service.started) == 2)
    assert Counter(service.started) == {"fast": 1, "slow": 1}
    assert remote._device_sessions["slow"].config is not old_config


def test_preflight_failure_has_retry_without_stopping_successful_device(
    remote_session, qt_application,
):
    remote, service = remote_session
    service.failures.add("failed")
    remote.set_target_devices(["failed", "fast"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: remote._launch_worker is None)
    assert service.started == ["fast"]
    assert remote._session_rows["failed"][1].text() == "失败"
    service.failures.clear()
    remote._session_rows["failed"][2].click()
    assert _wait(qt_application, lambda: len(service.started) == 2)
    assert service.processes["fast"].poll() is None


def test_stop_cancels_warmup_and_shutdown_waits_for_preparation(remote_session, qt_application):
    from adblab.application.supervision import StopDisposition, TaskSupervisor

    remote, service = remote_session
    entered = threading.Event()
    release = threading.Event()
    original = service.build_launch_plan

    def build(config, *, cancelled):
        entered.set()
        assert release.wait(2)
        return original(config, cancelled=cancelled)

    service.build_launch_plan = build
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, entered.is_set)
    supervisor = TaskSupervisor()
    assert remote.register_shutdown_task(supervisor, owner_id="test", task_id="remote")
    remote.shutdown()
    result = supervisor.stop_all(deadline=0.03)
    assert result[0].disposition is StopDisposition.TIMED_OUT
    assert not service.started
    release.set()
    assert _wait(qt_application, lambda: not remote._orphaned_launch_workers)
    assert not service.started


def test_stop_cancels_device_warmup_without_retargeting(remote_session, qt_application):
    remote, service = remote_session
    entered = threading.Event()
    cancelled_seen = threading.Event()
    warmed = []

    def warm(device, *, cancelled):
        warmed.append(device)
        entered.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if cancelled():
                cancelled_seen.set()
                return False
            threading.Event().wait(0.002)
        pytest.fail("Warmup did not receive cancellation")

    remote._adb.warm_input_session.side_effect = warm
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, entered.is_set)
    remote.set_target_devices(["second"])
    remote._stop_scrcpy()
    assert _wait(qt_application, cancelled_seen.is_set)
    assert _wait(qt_application, lambda: remote._session_state == remote._SESSION_IDLE)
    assert warmed == ["first"]
    assert service.started == ["first"]


def test_finished_session_diagnostics_redact_device_after_selection_is_cleared(
    remote_session, qt_application,
):
    remote, service = remote_session
    remote.set_target_devices(["synthetic-secret-device"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: bool(service.started))
    remote.set_target_devices([])
    service.processes["synthetic-secret-device"].finish(1)
    remote._poll_process()
    text = remote._redact_remote_diagnostic("late error from synthetic-secret-device")
    assert "synthetic-secret-device" not in text


def test_parent_exit_retains_process_key_until_helper_cleanup_finishes(
    remote_session, qt_application,
):
    remote, service = remote_session
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.started == ["first"])
    key = remote._scrcpy_process_keys()[0]
    service.cleanup_pending.add(key)
    service.processes["first"].finish(1)
    remote._poll_process()
    assert key in remote._scrcpy_process_keys()
    assert not remote.btn_start.isEnabled()
    assert not remote.fps.isEnabled()
    service.cleanup_pending.clear()
    remote._poll_process()
    assert remote._session_rows["first"][1].text() == "失败"
    assert remote.btn_start.isEnabled()


def test_start_exception_after_spawn_keeps_resources_stoppable(remote_session, qt_application):
    remote, service = remote_session
    original = service.start_plan

    def start_plan(key, plan):
        original(key, plan)
        raise RuntimeError("cleanup thread unavailable")

    service.start_plan = start_plan
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: remote._launch_worker is None)
    key = next(iter(service.keys))
    assert key in remote._scrcpy_process_keys()
    assert not remote.btn_start.isEnabled()
    assert remote.btn_stop.isEnabled()
    remote._stop_scrcpy()
    assert _wait(qt_application, lambda: remote._session_state == remote._SESSION_IDLE)
    assert service.stopped == [key]


def test_late_fps_from_stopped_process_cannot_replace_idle_status(remote_session, qt_application):
    remote, service = remote_session
    service.parse_fps = lambda line: "60 fps" if "fps" in line else ""
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.started == ["first"])
    process = service.processes["first"]
    remote._stop_scrcpy()
    assert _wait(qt_application, lambda: remote._session_state == remote._SESSION_IDLE)
    status = remote._status_label.text()
    remote._scrcpy_controller._read_process_output(process, ["60 fps"])
    assert remote._status_label.text() == status


@pytest.mark.parametrize("no_window", [False, True])
def test_recording_start_confirms_record_only_mode_and_redacts_output_path(
    remote_session, qt_application, monkeypatch, no_window,
):
    remote, service = remote_session
    original = remote._scrcpy_config
    private_path = r"C:\private-example\first-recording.mkv"
    monkeypatch.setattr(remote, "_scrcpy_config", lambda exe, device: replace(
        original(exe, device), no_window=no_window, record_path=private_path,
    ))
    messages = []
    remote.signals.log_message.connect(lambda _level, message: messages.append(message))
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.started == ["first"])
    process = service.processes["first"]
    remote._scrcpy_controller._read_process_output(
        process, [f"INFO: Recording started to matroska file: {private_path}"],
    )
    qt_application.processEvents()
    assert remote._session_rows["first"][1].text() == ("就绪" if no_window else "连接中")
    assert any("Recording started" in message for message in messages)
    assert all("private-example" not in message for message in messages)


def test_successful_stop_retry_clears_previous_stop_error(remote_session, qt_application):
    remote, service = remote_session
    remote.set_target_devices(["first"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.started == ["first"])
    original = service.stop
    service.stop = Mock(side_effect=OSError("synthetic stop failure"))
    remote._session_rows["first"][2].click()
    assert _wait(qt_application, lambda: remote._session_rows["first"][1].text() == "停止失败")
    service.stop = original
    remote._session_rows["first"][2].click()
    assert _wait(qt_application, lambda: not remote._processes)
    assert remote._session_rows["first"][1].text() == "已停止"
    assert remote._session_rows["first"][2].text() == "重试"


@pytest.mark.parametrize(("width", "font_size"), [(420, 12), (640, 22), (1024, 12)])
def test_three_session_rows_fit_narrow_width_and_large_font(
    remote_session, qt_application, tmp_path, monkeypatch, width, font_size,
):
    from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap

    from gui.styles import BaseStyles
    from gui.styles.typography import FontConfig, typography_manager
    from tests.ui_geometry_helpers import (
        assert_contained,
        assert_non_overlapping,
        assert_scroll_target_reachable,
        wait_for_stable_geometry,
    )

    remote, service = remote_session
    monkeypatch.setattr("gui.panels.remote_panel_form.report_feedback", lambda *_a, **_k: None)
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family=current.ui_family, ui_size=font_size,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    service.failures.add("synthetic-failed")
    service.gates["synthetic-preparing"] = threading.Event()
    remote.set_target_devices(["synthetic-ready", "synthetic-preparing", "synthetic-failed"])
    remote._start_scrcpy()
    assert _wait(qt_application, lambda: service.started == ["synthetic-ready"])
    service.processes["synthetic-ready"].output_lines.put("INFO: Texture: 1080x2400")
    assert _wait(qt_application, lambda: (
        remote._session_rows["synthetic-ready"][1].text() == "就绪"
        and remote._session_rows["synthetic-failed"][1].text() == "失败"
    ))
    scroll = remote.panel._tab_scroll_areas[2]
    scroll.resize(width, 800)
    background = QColor(BaseStyles.color_for(BaseStyles.resolved_theme(), "WINDOW_BG"))
    palette = scroll.viewport().palette()
    palette.setColor(QPalette.ColorRole.Window, background)
    scroll.viewport().setPalette(palette)
    scroll.viewport().setAutoFillBackground(True)
    scroll.show()
    remote.apply_responsive_width(scroll.viewport().width())
    assert _wait(qt_application, lambda: remote._session_list.isVisibleTo(scroll))
    wait_for_stable_geometry(qt_application, (scroll, remote._session_list))
    for name, status, action in remote._session_rows.values():
        container = action.parentWidget()
        assert_non_overlapping((name, status, action), container)
        assert_contained(action, container)
        assert status.width() >= status.fontMetrics().horizontalAdvance(status.text())
        assert action.font().pointSizeF() >= font_size
        assert_scroll_target_reachable(scroll, action)
    scroll.ensureWidgetVisible(remote._session_list)
    qt_application.processEvents()
    snapshot = QPixmap(scroll.size())
    snapshot.fill(background)
    painter = QPainter(snapshot)
    painter.drawPixmap(0, 0, scroll.grab())
    painter.end()
    assert snapshot.save(str(tmp_path / f"remote-{width}px-{font_size}pt.png"))
