"""提供 Remote 面板的 scrcpy 生命周期与停止所有权管理。"""

import os
import threading
import time
from dataclasses import dataclass, field, replace

from PySide6.QtCore import Qt

from gui.i18n import tr
from services.remote import ScrcpyConfig


@dataclass
class RemoteDeviceSession:
    """保存一个设备配置代次及其唯一进程，全部状态变更由 GUI 线程负责。"""

    config: ScrcpyConfig
    state: str = "preparing"
    key: str = ""
    process: object | None = None
    resource_owned: bool = False
    error_type: str = ""
    stop_requested: bool = False
    stop_inflight: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)


class RemotePanelScrcpy:
    """组合进 RemotePanel 的 scrcpy 控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame

    def _start_scrcpy(self, requested_devices=None):
        """只为当前已选且未活动的设备排队，追加共享本轮冻结的配置。"""
        frame = self._frame
        if (
            getattr(frame, "_closing", False)
            or getattr(frame, "_remote_input_closing", False)
            or getattr(frame, "_session_state", frame._SESSION_IDLE) == frame._SESSION_STOPPING
        ):
            return
        sessions = getattr(frame, "_device_sessions", {})
        selected = frame.selected_devices
        devices = [
            device for device in (requested_devices if requested_devices is not None else selected)
            if device in selected and (
                device not in sessions or (
                    sessions[device].state in {"failed", "stopped"}
                    and not sessions[device].resource_owned
                )
            )
        ]
        if not devices:
            return
        exe = frame._scrcpy_service.resolve_executable()
        if not os.path.isfile(exe):
            frame._log("WARNING", "scrcpy executable is unavailable")
            return
        configs = []
        frozen = getattr(frame, "_frozen_session_config", None)
        try:
            for device in devices:
                if frozen is None:
                    config = frame._scrcpy_config(exe, device)
                else:
                    config = replace(
                        frozen, device=device,
                        window_title=frame._input_engine.window_title(device),
                    )
                if (getattr(frame, "chk_record", None) is not None
                        and frame.chk_record.isChecked()):
                    frame._record_path = frame._allocate_record_path(device)
                    frame._display_record_path(frame._record_path)
                    config = replace(config, record_path=frame._record_path)
                configs.append(config)
        except Exception as exc:
            if not getattr(frame, "_process", None):
                frame._session_devices = ()
                frame._set_running(False)
                frame._update_status("Error", None)
            frame._log("ERROR", f"scrcpy configuration failed: {type(exc).__name__}")
            return
        frame._device_sessions = sessions
        frame._frozen_session_config = frozen or configs[0]
        frame._session_config = configs[0] if len(configs) == 1 else configs
        for config in configs:
            sessions[config.device] = RemoteDeviceSession(config)
        frame._status_device_info = ""
        frame._launch_admission_revision = getattr(frame, "_device_admission_revision", 0)
        self._queue_launch_configs(configs)
        self._refresh_sessions()

    def _queue_launch_configs(self, configs: list[ScrcpyConfig]) -> None:
        """一个协调 worker 包含所有准备线程，结束交接期间的追加保留在面板队列。"""
        from gui.panels.remote_panel import ScrcpyLaunchWorker

        frame = self._frame
        worker = getattr(frame, "_launch_worker", None)
        if worker is not None:
            if not worker.add_configs(configs):
                frame._pending_launch_configs = [
                    *getattr(frame, "_pending_launch_configs", ()), *configs,
                ]
            return
        config = configs[0] if len(configs) == 1 else configs
        worker = ScrcpyLaunchWorker(config, service=frame._scrcpy_service)
        worker.plan_ready.connect(frame._on_device_plan_ready, Qt.ConnectionType.QueuedConnection)
        worker.plan_failed.connect(frame._on_device_plan_failed, Qt.ConnectionType.QueuedConnection)
        worker.log_message.connect(frame._log, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(
            lambda current=worker: frame._on_launch_finished(current),
            Qt.ConnectionType.QueuedConnection,
        )
        frame._launch_worker = worker
        try:
            worker.start()
        except Exception as exc:
            frame._launch_worker = None
            for config in configs:
                frame._device_sessions[config.device].state = "failed"
            frame._log("ERROR", f"scrcpy preflight worker failed: {type(exc).__name__}")
            worker.deleteLater()

    def _on_device_plan_ready(self, config: ScrcpyConfig, plan) -> None:
        """仅当前配置可提交一次进程，建立所有权后才启动 reader、焦点和预热。"""
        frame = self._frame
        session = getattr(frame, "_device_sessions", {}).get(config.device)
        if (
            session is None or session.config is not config or session.state != "preparing"
            or getattr(frame, "_closing", False)
            or getattr(frame, "_remote_input_closing", False)
            or getattr(frame, "_session_state", None) == frame._SESSION_STOPPING
            or config.device not in frame.selected_devices
        ):
            return
        sequence = getattr(frame, "_session_key_sequence", 0)
        frame._session_key_sequence = sequence + 1
        key = f"{frame._process_key}_{sequence}"
        session.key = key
        try:
            process = frame._scrcpy_service.start_plan(key, plan)
        except Exception as exc:
            # 服务可能已创建进程、仅在后续资源登记失败；异常不等于没有清理所有权。
            session.resource_owned = frame._scrcpy_service.is_active(key)
            self._on_device_plan_failed(config, type(exc).__name__)
            if session.resource_owned:
                frame._reset_scrcpy_stop_claim()
                frame._watchdog.start(500)
            frame._log("ERROR", f"scrcpy start failed: {type(exc).__name__}")
            return
        session.resource_owned = True
        session.process = process
        session.state = "connecting"
        frame._session_process_keys = (*getattr(frame, "_session_process_keys", ()), key)
        frame._reset_scrcpy_stop_claim()
        if plan.device_info:
            frame._remote_control.remember_dimensions(config.device, plan.device_info.split("x"))
        self._refresh_sessions()
        self._start_process_task(self._read_process_stderr, process)
        self._start_process_task(self._read_process_stdout, process)
        if not config.no_window:
            self._start_process_task(self._focus_window_title, config.window_title)
        self._start_process_task(self._warm_device_input, session)
        frame._watchdog.start(500)

    def _on_device_plan_failed(self, config: ScrcpyConfig, error_type: str) -> None:
        """失败仅改变本设备代次，不重置已经成功启动的其他镜像。"""
        session = getattr(self._frame, "_device_sessions", {}).get(config.device)
        if (session is None or session.config is not config or session.state != "preparing"
                or getattr(self._frame, "_closing", False)):
            return
        session.state = "failed"
        session.error_type = error_type
        self._refresh_sessions()

    def _warm_device_input(self, session) -> None:
        """预热使用启动时的设备快照，并登记在同一关闭屏障中。"""
        def cancelled() -> bool:
            return (
                session.cancel_event.is_set()
                or getattr(self._frame, "_closing", False)
                or getattr(self._frame, "_remote_input_closing", False)
            )

        if cancelled():
            return
        try:
            self._frame._adb.warm_input_session(session.config.device, cancelled=cancelled)
        except Exception as exc:
            self._frame._log("DEBUG", f"remote input warmup skipped: {type(exc).__name__}")

    def _refresh_sessions(self) -> None:
        """从逐台资源投影整体按钮状态，停止排空前持续冻结启动配置。"""
        frame = self._frame
        sessions = getattr(frame, "_device_sessions", {})
        frame._processes = {
            device: session.process for device, session in sessions.items()
            if session.process is not None
        }
        frame._process = next(iter(frame._processes.values()), None)
        frame._session_process_keys = tuple(
            session.key for session in sessions.values() if session.resource_owned
        )
        frame._active_device = next(iter(frame._processes), None)
        frame._session_devices = tuple(
            device for device, session in sessions.items()
            if session.resource_owned or session.state == "preparing"
        )
        pending = any(session.state == "preparing" for session in sessions.values())
        worker = getattr(frame, "_launch_worker", None)
        if getattr(frame, "_stop_all_pending", False):
            busy_threads = any(
                thread.is_alive() for thread in getattr(frame, "_scrcpy_threads", ())
            )
            if frame._session_process_keys or worker is not None or busy_threads:
                frame._set_session_state(frame._SESSION_STOPPING)
                frame._watchdog.start(100)
                self._refresh_session_rows()
                return
            frame._stop_all_pending = False
        if frame._session_process_keys:
            frame._set_session_state(frame._SESSION_RUNNING)
            ready = any(session.state == "ready" for session in sessions.values())
            status = "Running" if ready else "Connecting"
        elif pending or worker is not None:
            frame._set_session_state(frame._SESSION_STARTING)
            status = "Checking..."
        else:
            frame._set_session_state(frame._SESSION_IDLE)
            status = "Error" if any(s.state == "failed" for s in sessions.values()) else "Idle"
            frame._frozen_session_config = None
            frame._watchdog.stop()
        frame._update_status(status, None)
        self._refresh_session_rows()

    def _refresh_session_rows(self) -> None:
        form = getattr(self._frame, "_form_controller", None)
        if form is not None:
            form.refresh_session_rows()

    def _on_scrcpy_output(self, process, line: str) -> None:
        """只有视频纹理或录制开始输出确认可用，进程存在本身不代表就绪。"""
        if getattr(self._frame, "_closing", False):
            return
        for session in getattr(self._frame, "_device_sessions", {}).values():
            if (session.process is not process or session.state not in {"connecting", "ready"}
                    or session.cancel_event.is_set()):
                continue
            video_ready = "Texture:" in line
            recording_ready = session.config.no_window and "Recording started to " in line
            if session.state == "connecting" and (video_ready or recording_ready):
                session.state = "ready"
                self._refresh_sessions()
            fps = self._frame._scrcpy_service.parse_fps(line)
            if fps:
                self._frame._update_status(fps, None)
            break

    def _stop_device_scrcpy(self, device: str) -> None:
        """停止一台设备使用其原进程键；准备取消后拒绝该配置的晚到结果。"""
        frame = self._frame
        session = getattr(frame, "_device_sessions", {}).get(device)
        if (session is None or session.stop_inflight
                or (not session.resource_owned and session.state != "preparing")):
            return
        session.cancel_event.set()
        session.stop_requested = True
        if session.state == "preparing":
            worker = getattr(frame, "_launch_worker", None)
            if worker is not None:
                worker.cancel_config(session.config)
            session.state = "stopped"
            self._refresh_sessions()
            return
        session.state = "stopping"
        session.stop_inflight = True
        key = session.key
        self._refresh_sessions()

        def stop(_argument):
            stopped = False
            try:
                frame._scrcpy_service.stop(key, timeout=2)
                stopped = not frame._scrcpy_service.is_active(key)
            except Exception as exc:
                frame._log("ERROR", f"scrcpy stop failed: {type(exc).__name__}")
            frame._device_stop_completed_requested.emit(device, session, stopped)

        if not self._start_process_task(stop, None):
            self._on_device_stop_completed(device, session, False)

    def _on_device_stop_completed(self, device: str, original_session, stopped: bool) -> None:
        """单台停止失败保留原进程及停止入口，成功才释放当前代次。"""
        frame = self._frame
        if getattr(frame, "_closing", False):
            return
        session = getattr(frame, "_device_sessions", {}).get(device)
        if session is None or session is not original_session:
            return
        session.stop_inflight = False
        if stopped:
            session.process = None
            session.resource_owned = False
            session.state = "stopped"
        else:
            session.state = "connecting"
            session.error_type = "StopFailed"
        self._refresh_sessions()

    def _stop_all_sessions(self) -> None:
        """停止全部原目标并保持排空状态，直到准备、reader、焦点和预热退出。"""
        frame = self._frame
        if getattr(frame, "_stop_all_pending", False):
            return
        frame._stop_all_pending = True
        frame._pending_launch_configs = []
        worker = getattr(frame, "_launch_worker", None)
        if worker is not None:
            frame._request_launch_worker_interruption_once(worker)
        keys = []
        for session in frame._device_sessions.values():
            session.cancel_event.set()
            session.stop_requested = True
            if session.state == "preparing":
                session.state = "stopped"
            elif session.resource_owned:
                session.state = "stopping"
                keys.append(session.key)
        self._refresh_sessions()
        if not keys:
            return
        claim = frame._claim_scrcpy_stop()
        if claim is None:
            return

        def stop_all(_argument):
            succeeded = True
            deadline = time.monotonic() + 2
            for key in keys:
                try:
                    frame._scrcpy_service.stop(key, timeout=max(0, deadline - time.monotonic()))
                    succeeded = not frame._scrcpy_service.is_active(key) and succeeded
                except Exception as exc:
                    succeeded = False
                    frame._log("ERROR", f"scrcpy stop failed: {type(exc).__name__}")
            if not succeeded:
                frame._release_scrcpy_stop_claim(claim)
            frame._stop_completed_requested.emit(succeeded)

        if not self._start_process_task(stop_all, None):
            frame._release_scrcpy_stop_claim(claim)
            self._on_stop_completed(False)

    def _on_batch_launch_ready(self, plans: list) -> None:
        """独立启动同一批次的各台设备；单台失败不会丢失其他进程的停止归属。"""
        frame = self._frame
        if (
            getattr(frame, "_closing", False)
            or getattr(frame, "_remote_input_closing", False)
            or frame._session_state != frame._SESSION_STARTING
            or frame._launch_admission_revision != frame._device_admission_revision
            or (frame._launch_worker and frame._launch_worker.isInterruptionRequested())
        ):
            return
        keys = []
        processes = {}
        frame._processes = processes
        for index, (config, args, device_info) in enumerate(plans):
            if config.device not in frame.selected_devices:
                continue
            key = f"{frame._process_key}_{index}"
            try:
                process = frame._scrcpy_service.start(key, args)
            except Exception as exc:
                frame._log("ERROR", f"scrcpy start failed: {type(exc).__name__}")
                continue
            keys.append(key)
            processes[config.device] = process
            frame._session_process_keys = tuple(keys)
            frame._process = next(iter(processes.values()))
            if device_info:
                frame._remote_control.remember_dimensions(config.device, device_info.split("x"))
            # reader 和焦点任务捕获本次进程/设备，禁止后台再读取可能变化的活动目标。
            self._start_process_task(self._read_process_stderr, process)
            title = frame._input_engine.window_title(config.device)
            self._start_process_task(self._focus_window_title, title)
        frame._session_process_keys = tuple(keys)
        frame._processes = processes
        frame._session_devices = tuple(processes)
        frame._process = next(iter(processes.values()), None)
        frame._active_device = next(iter(processes), None)
        if processes:
            frame._reset_scrcpy_stop_claim()
            frame._set_running(True)
            frame._update_status("Running", None)
            frame._watchdog.start(500)
        else:
            frame._set_running(False)
            frame._update_status("Error", None)

    def _start_process_task(self, target, argument) -> bool:
        """保留每个镜像 reader/焦点任务，关闭屏障等待它们退出后再释放面板。"""
        frame = self._frame
        with frame._shutdown_lifecycle_lock():
            if getattr(frame, "_closing", False) or getattr(frame, "_remote_input_closing", False):
                return False
            threads = getattr(frame, "_scrcpy_threads", None)
            if threads is None:
                threads = []
                frame._scrcpy_threads = threads
            try:
                thread = threading.Thread(target=target, args=(argument,), daemon=True)
                thread.start()
            except Exception as exc:
                frame._log("WARNING", f"scrcpy background task failed: {type(exc).__name__}")
                return False
            # 发布与启动共用关闭锁，清理快照不能漏掉已启动但尚未登记的线程。
            threads.append(thread)
            return True

    def _on_launch_ready(self, args: list, device_info: str):
        if getattr(self._frame, "_closing", False) or getattr(
            self._frame, "_remote_input_closing", False
        ):
            return
        if getattr(self._frame, "_session_state", None) == self._frame._SESSION_STOPPING:
            return
        if not self._frame._can_operate_device():
            return
        if getattr(self._frame, "_launch_admission_revision", 0) != getattr(
            self._frame, "_device_admission_revision", 0
        ):
            # QThread 已退出时中断标志可能已清除，仍须拒绝排队中的旧启动结果。
            return
        if self._frame._launch_worker and self._frame._launch_worker.isInterruptionRequested():
            return
        self._frame._status_device_info = str(device_info or "").strip()
        active_device = getattr(self._frame, "_active_device", None)
        if active_device and device_info:
            self._frame._remote_control.remember_dimensions(active_device, device_info.split("x"))
        self._frame._log("INFO", "Launching scrcpy")
        self._frame._log("DEBUG", f"scrcpy launch plan prepared: argument_count={len(args)}")

        try:
            self._frame._process = self._frame._scrcpy_service.start(
                self._frame._process_key,
                args,
            )
        except Exception as exc:
            self._frame._log("ERROR", f"scrcpy start failed: {type(exc).__name__}")
            self._frame._active_device = None
            self._frame._session_devices = ()
            self._frame._status_device_info = ""
            self._frame._set_running(False)
            self._frame._update_status("Error", None)
            return
        self._frame._reset_scrcpy_stop_claim()
        self._frame._set_running(True)
        self._frame._update_status("Running", None)
        title = self._frame._input_engine.window_title(active_device)
        self._start_process_task(self._focus_window_title, title)
        try:
            self._frame._start_warm_remote_input_session()
        except Exception as exc:
            # 输入预热失败不改变已经启动的镜像归属，后续输入仍可自行建立会话。
            self._frame._log("WARNING", f"remote input warmup failed: {type(exc).__name__}")
        self._start_process_task(self._read_process_stderr, self._frame._process)
        self._frame._watchdog.start(500)

    def _on_launch_finished(self, worker):
        if self._frame._launch_worker is not worker:
            worker.deleteLater()
            return
        if hasattr(self._frame, "_device_sessions"):
            frame = self._frame
            frame._launch_worker = None
            worker.deleteLater()
            if getattr(frame, "_closing", False):
                return
            queued = getattr(frame, "_pending_launch_configs", ())
            frame._pending_launch_configs = []
            queued = [
                config for config in queued
                if frame._device_sessions[config.device].config is config
                and frame._device_sessions[config.device].state == "preparing"
            ]
            if queued and not getattr(frame, "_remote_input_closing", False):
                self._queue_launch_configs(queued)
            for session in frame._device_sessions.values():
                if session.state == "preparing" and session.config not in queued:
                    session.state = "failed"
            self._refresh_sessions()
            return
        interrupted = worker.isInterruptionRequested() or (
            getattr(self._frame, "_session_state", None) == self._frame._SESSION_STOPPING
        ) or (
            getattr(self._frame, "_launch_admission_revision", 0)
            != getattr(self._frame, "_device_admission_revision", 0)
        )
        self._frame._launch_worker = None
        worker.deleteLater()
        if getattr(self._frame, "_closing", False):
            return
        if not self._frame._process:
            self._frame._active_device = None
            self._frame._session_devices = ()
            self._frame._status_device_info = ""
            self._frame._set_running(False)
            if interrupted:
                self._frame._update_status("Idle", None)
            else:
                self._frame._update_status("Error", None)

    def _read_stderr(self):
        proc = self._frame._process
        self._read_process_stderr(proc)

    def _read_process_stderr(self, proc):
        """读取指定进程的诊断流，进程引用不随用户选择变化。"""
        if proc:
            self._read_process_output(proc, proc.stderr)

    def _read_process_stdout(self, proc):
        """scrcpy 的 INFO 与 FPS 位于 stdout，必须单独排空才能取得就绪证据。"""
        if proc:
            self._read_process_output(proc, proc.stdout)

    def _read_process_output(self, proc, stream):
        """两个输出流使用同一进程身份投递事件，关闭屏障分别等待各 reader。"""
        if stream:
            for line in stream:
                if getattr(self._frame, "_closing", False):
                    return
                line = line.strip()
                if not line:
                    continue
                if hasattr(self._frame, "_device_sessions"):
                    self._frame._scrcpy_output_requested.emit(proc, line)
                # 兼容旧版将 FPS 写入 stderr 的行为，两个输出流均先识别 FPS。
                fps = self._frame._scrcpy_service.parse_fps(line)
                if fps:
                    if not hasattr(self._frame, "_device_sessions"):
                        self._frame._status_update_requested.emit(fps, None)
                elif self._frame._should_ignore_scrcpy_log_line(line):
                    continue
                else:
                    self._frame._log(
                        "DEBUG", f"[scrcpy] {self._frame._redact_remote_diagnostic(line)}"
                    )

    def _poll_process(self):
        if hasattr(self._frame, "_device_sessions"):
            for session in self._frame._device_sessions.values():
                process = session.process
                rc = process.poll() if process is not None else None
                if session.resource_owned and (process is None or rc is not None):
                    session.cancel_event.set()
                    # 父进程退出后，直连 helper 与端口清理仍可能活动；进程键保留到服务收口。
                    if self._frame._scrcpy_service.is_active(session.key):
                        if process is not None:
                            session.state = "stopping"
                        continue
                    session.process = None
                    session.resource_owned = False
                    stopped = session.stop_requested or rc == 0
                    session.state = "stopped" if stopped else "failed"
                    if rc is not None and rc != 0:
                        self._frame._log("WARNING", f"scrcpy exited with code {rc}")
            self._refresh_sessions()
            return
        processes = getattr(self._frame, "_processes", {})
        if processes:
            for device, process in tuple(processes.items()):
                rc = process.poll()
                if rc is not None:
                    del processes[device]
                    if rc != 0:
                        self._frame._log("WARNING", f"scrcpy exited with code {rc}")
            self._frame._process = next(iter(processes.values()), None)
            self._frame._active_device = next(iter(processes), None)
            self._frame._session_devices = tuple(processes)
            if processes:
                return
            self._frame._watchdog.stop()
            self._frame._set_running(False)
            self._frame._update_status("Disconnected", None)
            return
        if not self._frame._process:
            self._frame._watchdog.stop()
            return
        rc = self._frame._process.poll()
        if rc is not None:
            self._frame._watchdog.stop()
            self._frame._process = None
            self._frame._active_device = None
            self._frame._session_devices = ()
            self._frame._status_device_info = ""
            self._frame._set_running(False)
            self._frame._update_status("Disconnected", None)
            if rc != 0:
                self._frame._log("WARNING", f"scrcpy exited with code {rc}")

    def _stop_scrcpy(self):
        if hasattr(self._frame, "_device_sessions"):
            self._stop_all_sessions()
            return
        if getattr(self._frame, "_session_state", None) == self._frame._SESSION_STOPPING:
            return
        if self._frame._launch_worker:
            self._frame._request_launch_worker_interruption_once(self._frame._launch_worker)
            if not self._frame._process:
                self._frame._set_session_state(self._frame._SESSION_STOPPING)
                self._frame._update_status("Stopping...", None)
                return
        if not self._frame._process:
            return
        stop_claim = self._frame._claim_scrcpy_stop()
        if stop_claim is None:
            return
        self._frame._watchdog.stop()
        self._frame._set_session_state(self._frame._SESSION_STOPPING)
        self._frame._update_status("Stopping...", None)
        scrcpy_service = self._frame._scrcpy_service
        process_keys = self._frame._scrcpy_process_keys()

        def _do_stop():
            stopped = False
            try:
                deadline = time.monotonic() + 2
                stop_error = None
                for key in process_keys:
                    try:
                        timeout = (
                            2 if len(process_keys) == 1 else max(0, deadline - time.monotonic())
                        )
                        scrcpy_service.stop(key, timeout=timeout)
                    except Exception as exc:
                        stop_error = exc
                if stop_error is not None:
                    raise stop_error
                stopped = not any(scrcpy_service.is_active(key) for key in process_keys)
                if not stopped:
                    self._frame._release_scrcpy_stop_claim(stop_claim)
            except Exception as exc:
                self._frame._release_scrcpy_stop_claim(stop_claim)
                self._frame._log("ERROR", f"stop failed: {type(exc).__name__}")
            try:
                self._frame._stop_completed_requested.emit(stopped)
            except RuntimeError:
                # 窗口已经开始销毁时不再回写控件状态，关闭监督器继续负责资源清理。
                pass

        try:
            threading.Thread(target=_do_stop, daemon=True).start()
        except Exception:
            self._frame._release_scrcpy_stop_claim(stop_claim)
            self._frame._on_stop_completed(False)

    def _on_stop_completed(self, stopped: bool):
        """在 GUI 线程收口停止结果，并避免旧进程尚未退出时提前允许再次启动。"""

        if getattr(self._frame, "_closing", False):
            return
        if hasattr(self._frame, "_device_sessions"):
            frame = self._frame
            if not stopped:
                frame._stop_all_pending = False
            for session in frame._device_sessions.values():
                if session.state == "stopping":
                    if stopped or not frame._scrcpy_service.is_active(session.key):
                        session.process = None
                        session.resource_owned = False
                        session.state = "stopped"
                    else:
                        session.state = "connecting"
                        session.error_type = "StopFailed"
            self._refresh_sessions()
            if not stopped:
                frame._update_status("Stop Failed", None)
            return
        if stopped:
            self._frame._process = None
            self._frame._processes = {}
            self._frame._session_devices = ()
            self._frame._active_device = None
            self._frame._status_device_info = ""
            self._frame._set_running(False)
            self._frame._update_status("Idle", None)
            self._frame._log("INFO", "scrcpy stopped")
            return

        process = getattr(self._frame, "_process", None)
        processes = getattr(self._frame, "_processes", {})
        if processes:
            processes = {device: proc for device, proc in processes.items() if proc.poll() is None}
            self._frame._processes = processes
            self._frame._process = process = next(iter(processes.values()), None)
            self._frame._active_device = next(iter(processes), None)
            self._frame._session_devices = tuple(processes)
        try:
            process_alive = process is not None and process.poll() is None
        except (AttributeError, OSError):
            process_alive = process is not None
        if process_alive:
            self._frame._set_running(True)
            self._frame._watchdog.start(500)
        else:
            self._frame._process = None
            self._frame._active_device = None
            self._frame._status_device_info = ""
            self._frame._set_running(False)
        self._frame._update_status("Stop Failed", None)

    def _set_session_state(self, state: str):
        """统一应用 Idle/Starting/Running/Stopping 对应的按钮可用状态。"""

        from gui.panels.remote_panel import RemotePanel

        if state not in {
            RemotePanel._SESSION_IDLE,
            RemotePanel._SESSION_STARTING,
            RemotePanel._SESSION_RUNNING,
            RemotePanel._SESSION_STOPPING,
        }:
            raise ValueError(f"unsupported Remote session state: {state}")
        self._frame._session_state = state
        running = state == RemotePanel._SESSION_RUNNING
        self._frame._running = running

        btn_start = getattr(self._frame, "btn_start", None)
        btn_stop = getattr(self._frame, "btn_stop", None)
        try:
            selected_devices = self._frame.selected_devices
        except AttributeError:
            selected_devices = None
        can_start = (
            not getattr(self._frame, "_closing", False)
            and state != RemotePanel._SESSION_STOPPING
            and (selected_devices is None or bool(selected_devices))
        )
        sessions = getattr(self._frame, "_device_sessions", None)
        if sessions is None:
            can_start = can_start and state == RemotePanel._SESSION_IDLE
        elif selected_devices is not None:
            can_start = can_start and any(
                device not in sessions or (
                    sessions[device].state in {"failed", "stopped"}
                    and not sessions[device].resource_owned
                )
                for device in selected_devices
            )
        self._frame._set_button_enabled(btn_start, can_start)
        if sessions is not None and btn_start is not None:
            text = tr("追加镜像") if state != RemotePanel._SESSION_IDLE else tr("开始镜像")
            btn_start.setText(text)
        self._frame._set_button_enabled(
            btn_stop,
            state in {RemotePanel._SESSION_STARTING, RemotePanel._SESSION_RUNNING},
        )
        if selected_devices is None:
            can_control = running
        else:
            can_control = bool(selected_devices)
        can_control = can_control and not getattr(self._frame, "_closing", False)
        for button in getattr(self._frame, "_remote_control_buttons", ()):
            self._frame._set_button_enabled(button, can_control)
        locked = state != RemotePanel._SESSION_IDLE
        for control in RemotePanel._startup_configuration_controls(self._frame):
            control.setEnabled(not locked)
        if sessions is not None:
            self._refresh_session_rows()

    def _scrcpy_config(self, exe: str, device: str) -> ScrcpyConfig:
        return ScrcpyConfig(
            exe=exe,
            adb=self._frame._adb.path,
            device=device,
            maxsize=self._frame.maxsize.currentData(),
            fps=self._frame.fps.currentData(),
            bitrate=self._frame.bitrate.currentData(),
            codec=self._frame.codec.currentData(),
            buffer=self._frame.buffer.currentData(),
            orientation=self._frame.orientation.currentData(),
            prefer_text=True,
            window_title=self._frame._input_engine.window_title(device),
            hw_encoder=self._frame.chk_hw_encoder.isChecked(),
            fullscreen=self._frame.chk_fullscreen.isChecked(),
            always_on_top=self._frame.chk_aot.isChecked(),
            no_audio=self._frame.chk_noaudio.isChecked(),
            show_touches=self._frame.chk_showtouches.isChecked(),
            stay_awake=self._frame.chk_stayawake.isChecked(),
            turn_screen_off=self._frame.chk_turnscreenoff.isChecked(),
            record_path=(
                self._frame._record_path
                if self._frame.chk_record.isChecked() and hasattr(self._frame, "_record_path")
                else ""
            ),
            no_window=self._frame.chk_noplayback.isChecked(),
        )

    def _focus_scrcpy_window(self):
        active_device = getattr(self._frame, "_active_device", None)
        if not active_device:
            return
        title = self._frame._input_engine.window_title(active_device)
        self._focus_window_title(title)

    def _focus_window_title(self, title: str) -> None:
        """按启动时捕获的标题定位窗口，不读取后续可能变化的设备选择。"""
        if self._frame._input_engine.focus_window(title):
            self._frame._log("INFO", "scrcpy window focused for keyboard input")
        else:
            self._frame._log("DEBUG", "scrcpy window focus was not acquired")

    def _stop_launch_worker(self, wait_ms: int = 3000):
        worker = getattr(self._frame, "_launch_worker", None)
        if worker is None:
            return
        self._frame._launch_worker = None
        self._frame._disconnect_launch_worker(worker)
        first_error = None

        def remember_error(exc: Exception) -> None:
            nonlocal first_error
            if first_error is None:
                first_error = exc

        try:
            running = bool(worker.isRunning())
        except Exception as exc:
            remember_error(exc)
            running = True

        waited = not running
        if running:
            try:
                self._frame._request_launch_worker_interruption_once(worker)
            except Exception as exc:
                remember_error(exc)
            try:
                waited = bool(worker.wait(wait_ms))
            except Exception as exc:
                remember_error(exc)
                waited = False

        if waited:
            try:
                worker.deleteLater()
            except Exception as exc:
                remember_error(exc)
                self._frame._defer_launch_worker_delete(worker)
        else:
            try:
                self._frame._defer_launch_worker_delete(worker)
            except Exception as exc:
                remember_error(exc)
                if not any(item is worker for item in self._frame._orphaned_launch_workers):
                    self._frame._orphaned_launch_workers.append(worker)

        if first_error is not None:
            raise first_error

    def _claim_scrcpy_stop(self) -> object | None:
        """原子取得当前 scrcpy 会话的唯一停止所有权。"""

        lock = self._frame._shutdown_lifecycle_lock()
        with lock:
            if getattr(self._frame, "_scrcpy_stop_claim", None) is not None:
                return None
            claim = object()
            self._frame._scrcpy_stop_claim = claim
            return claim

    def _release_scrcpy_stop_claim(self, claim: object) -> bool:
        """仅允许持有者释放自己的停止 token，避免旧会话污染新会话。"""

        lock = self._frame._shutdown_lifecycle_lock()
        with lock:
            if getattr(self._frame, "_scrcpy_stop_claim", None) is not claim:
                return False
            self._frame._scrcpy_stop_claim = None
            return True

    def _reset_scrcpy_stop_claim(self) -> None:
        """在新 scrcpy 进程成功启动后开放该会话的第一次停止请求。"""

        lock = self._frame._shutdown_lifecycle_lock()
        with lock:
            self._frame._scrcpy_stop_claim = None
            self._frame._scrcpy_stop_requested_keys = set()

    def _request_scrcpy_stop_once(self, service=None, process_key: str | None = None) -> bool:
        """为一个 scrcpy 会话只发送一次异步停止请求。"""

        resolved_service = service or getattr(self._frame, "_scrcpy_service", None)
        resolved_keys = (process_key,) if process_key else self._frame._scrcpy_process_keys()
        if resolved_service is None or not any(resolved_keys):
            return False
        stop_claim = self._frame._claim_scrcpy_stop()
        if stop_claim is None:
            return False
        first_error = None
        retry = False
        requested_keys = getattr(self._frame, "_scrcpy_stop_requested_keys", None)
        if requested_keys is None:
            requested_keys = set()
            self._frame._scrcpy_stop_requested_keys = requested_keys
        for key in resolved_keys:
            if key in requested_keys:
                continue
            try:
                requested = resolved_service.request_stop(key)
                if requested is False and resolved_service.is_active(key):
                    retry = True
                else:
                    requested_keys.add(key)
            except Exception as exc:
                retry = True
                if first_error is None:
                    first_error = exc
        if retry:
            self._frame._release_scrcpy_stop_claim(stop_claim)
        if first_error is not None:
            raise first_error
        return True

    def _request_launch_worker_interruption_once(self, worker) -> bool:
        """同一启动 worker 在多条关闭路径中只接收一次中断请求。"""

        if worker is None:
            return False
        lock = self._frame._shutdown_lifecycle_lock()
        with lock:
            if getattr(self._frame, "_interrupted_launch_worker", None) is worker:
                return False
            self._frame._interrupted_launch_worker = worker
        try:
            worker.requestInterruption()
        except Exception:
            with lock:
                if getattr(self._frame, "_interrupted_launch_worker", None) is worker:
                    self._frame._interrupted_launch_worker = None
            raise
        return True
