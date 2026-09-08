"""提供 Remote 面板的 scrcpy 生命周期与停止所有权管理。"""

import os
import threading
import time

from PySide6.QtCore import Qt

from services.remote import ScrcpyConfig


class RemotePanelScrcpy:
    """组合进 RemotePanel 的 scrcpy 控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame

    def _start_scrcpy(self):
        from gui.panels.remote_panel import ScrcpyLaunchWorker

        if getattr(self._frame, "_closing", False) or getattr(
            self._frame, "_remote_input_closing", False
        ):
            return
        if (
            getattr(self._frame, "_session_state", self._frame._SESSION_IDLE)
            != self._frame._SESSION_IDLE
        ):
            return
        if self._frame._process or (
            self._frame._launch_worker and self._frame._launch_worker.isRunning()
        ):
            return
        exe = self._frame._scrcpy_service.resolve_executable()
        if not os.path.isfile(exe):
            self._frame._log("WARNING", f"scrcpy not found: {exe}")
            return
        devices = self._frame.selected_devices
        if not devices:
            self._frame._log("WARNING", "No device selected")
            return
        self._frame._session_devices = tuple(devices)
        self._frame._session_process_keys = ()
        self._frame._processes = {}
        self._frame._scrcpy_threads = [
            thread for thread in getattr(self._frame, "_scrcpy_threads", ()) if thread.is_alive()
        ]
        self._frame._status_device_info = ""
        self._frame._set_session_state(self._frame._SESSION_STARTING)
        self._frame._update_status("Checking...", None)
        self._frame._active_device = devices[0]

        configs = []
        try:
            for device in devices:
                if (
                    getattr(self._frame, "chk_record", None) is not None
                    and self._frame.chk_record.isChecked()
                ):
                    self._frame._record_path = self._frame._allocate_record_path(device)
                    self._frame._display_record_path(self._frame._record_path)
                configs.append(self._frame._scrcpy_config(exe, device))
        except Exception as exc:
            self._frame._active_device = None
            self._frame._session_devices = ()
            self._frame._set_running(False)
            self._frame._update_status("Error", None)
            self._frame._log("ERROR", f"scrcpy configuration failed: {type(exc).__name__}")
            return
        config = configs[0] if len(configs) == 1 else configs
        self._frame._session_config = config
        self._frame._launch_admission_revision = getattr(
            self._frame, "_device_admission_revision", 0
        )

        worker = ScrcpyLaunchWorker(config, service=self._frame._scrcpy_service)
        worker.log_message.connect(self._frame._log)
        if len(configs) == 1:
            worker.launch_ready.connect(self._frame._on_launch_ready)
        else:
            worker.batch_ready.connect(self._frame._on_batch_launch_ready)
        worker.finished.connect(
            lambda _w=worker: self._frame._on_launch_finished(_w),
            Qt.ConnectionType.QueuedConnection,
        )
        self._frame._launch_worker = worker
        try:
            worker.start()
        except Exception as exc:
            self._frame._launch_worker = None
            self._frame._active_device = None
            self._frame._session_devices = ()
            self._frame._set_running(False)
            self._frame._update_status("Error", None)
            self._frame._log("ERROR", f"scrcpy preflight worker failed: {type(exc).__name__}")
            worker.deleteLater()

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

    def _start_process_task(self, target, argument) -> None:
        """保留每个镜像 reader/焦点任务，关闭屏障等待它们退出后再释放面板。"""
        frame = self._frame
        with frame._shutdown_lifecycle_lock():
            if getattr(frame, "_closing", False) or getattr(frame, "_remote_input_closing", False):
                return
            threads = getattr(frame, "_scrcpy_threads", None)
            if threads is None:
                threads = []
                frame._scrcpy_threads = threads
            try:
                thread = threading.Thread(target=target, args=(argument,), daemon=True)
                thread.start()
            except Exception as exc:
                frame._log("WARNING", f"scrcpy background task failed: {type(exc).__name__}")
                return
            # 发布与启动共用关闭锁，清理快照不能漏掉已启动但尚未登记的线程。
            threads.append(thread)

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
        if proc and proc.stderr:
            for line in proc.stderr:
                if getattr(self._frame, "_closing", False):
                    return
                line = line.strip()
                if not line:
                    continue
                # scrcpy 的标准错误流同时承载 FPS 和诊断信息，必须先识别 FPS。
                fps = self._frame._scrcpy_service.parse_fps(line)
                if fps:
                    self._frame._status_update_requested.emit(fps, None)
                elif self._frame._should_ignore_scrcpy_log_line(line):
                    continue
                else:
                    self._frame._log(
                        "DEBUG", f"[scrcpy] {self._frame._redact_remote_diagnostic(line)}"
                    )

    def _poll_process(self):
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
            and state == RemotePanel._SESSION_IDLE
            and (selected_devices is None or bool(selected_devices))
        )
        self._frame._set_button_enabled(btn_start, can_start)
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
