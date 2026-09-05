"""提供 Remote 面板的 scrcpy 生命周期与停止所有权管理。"""

import os
import threading

from PySide6.QtCore import Qt

from services.remote import ScrcpyConfig


class RemotePanelScrcpy:
    """组合进 RemotePanel 的 scrcpy 控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame

    def _start_scrcpy(self):
        from gui.panels.remote_panel import ScrcpyLaunchWorker

        if getattr(self._frame, "_closing", False):
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
        if len(devices) != 1:
            self._frame._log("WARNING", "Select exactly one device for Remote")
            self._frame._update_action_states()
            return

        self._frame._status_device_info = ""
        self._frame._set_session_state(self._frame._SESSION_STARTING)
        self._frame._update_status("Checking...", None)
        self._frame._active_device = devices[0]

        if (
            getattr(self._frame, "chk_record", None) is not None
            and self._frame.chk_record.isChecked()
        ):
            self._frame._record_path = self._frame._allocate_record_path(self._frame._active_device)
            self._frame._display_record_path(self._frame._record_path)

        config = self._frame._scrcpy_config(exe, self._frame._active_device)
        self._frame._session_config = config
        self._frame._launch_admission_revision = getattr(
            self._frame, "_device_admission_revision", 0
        )

        worker = ScrcpyLaunchWorker(config, service=self._frame._scrcpy_service)
        worker.log_message.connect(self._frame._log)
        worker.launch_ready.connect(self._frame._on_launch_ready)
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
            self._frame._set_running(False)
            self._frame._update_status("Error", None)
            self._frame._log("ERROR", f"scrcpy preflight worker failed: {type(exc).__name__}")
            worker.deleteLater()

    def _on_launch_ready(self, args: list, device_info: str):
        if getattr(self._frame, "_closing", False):
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
            self._frame._reset_scrcpy_stop_claim()
            self._frame._set_running(True)
            self._frame._update_status("Running", None)
            threading.Thread(target=self._frame._focus_scrcpy_window, daemon=True).start()
            self._frame._start_warm_remote_input_session()
            threading.Thread(target=self._frame._read_stderr, daemon=True).start()
            self._frame._watchdog.start(500)
        except Exception as exc:
            self._frame._log("ERROR", f"scrcpy start failed: {type(exc).__name__}")
            self._frame._active_device = None
            self._frame._status_device_info = ""
            self._frame._set_running(False)
            self._frame._update_status("Error", None)

    def _on_launch_finished(self, worker):
        if self._frame._launch_worker is not worker:
            worker.deleteLater()
            return
        interrupted = worker.isInterruptionRequested()
        self._frame._launch_worker = None
        worker.deleteLater()
        if getattr(self._frame, "_closing", False):
            return
        if not self._frame._process:
            self._frame._active_device = None
            self._frame._status_device_info = ""
            self._frame._set_running(False)
            if interrupted:
                self._frame._update_status("Idle", None)
            else:
                self._frame._update_status("Error", None)

    def _read_stderr(self):
        proc = self._frame._process
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
        if not self._frame._process:
            self._frame._watchdog.stop()
            return
        rc = self._frame._process.poll()
        if rc is not None:
            self._frame._watchdog.stop()
            self._frame._process = None
            self._frame._active_device = None
            self._frame._status_device_info = ""
            self._frame._set_running(False)
            self._frame._update_status("Disconnected", None)
            if rc != 0:
                self._frame._log("WARNING", f"scrcpy exited with code {rc}")

    def _stop_scrcpy(self):
        if getattr(self._frame, "_session_state", None) == self._frame._SESSION_STOPPING:
            return
        if self._frame._launch_worker and self._frame._launch_worker.isRunning():
            self._frame._request_launch_worker_interruption_once(self._frame._launch_worker)
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
        process_key = self._frame._process_key

        def _do_stop():
            stopped = False
            try:
                scrcpy_service.stop(process_key, timeout=2)
                stopped = not scrcpy_service.is_active(process_key)
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
            raise

    def _on_stop_completed(self, stopped: bool):
        """在 GUI 线程收口停止结果，并避免旧进程尚未退出时提前允许再次启动。"""

        if getattr(self._frame, "_closing", False):
            return
        if stopped:
            self._frame._process = None
            self._frame._active_device = None
            self._frame._status_device_info = ""
            self._frame._set_running(False)
            self._frame._update_status("Idle", None)
            self._frame._log("INFO", "scrcpy stopped")
            return

        process = getattr(self._frame, "_process", None)
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
            and (selected_devices is None or len(selected_devices) == 1)
        )
        self._frame._set_button_enabled(btn_start, can_start)
        self._frame._set_button_enabled(
            btn_stop,
            state in {RemotePanel._SESSION_STARTING, RemotePanel._SESSION_RUNNING},
        )
        if selected_devices is None:
            can_control = running
        else:
            can_control = len(selected_devices) == 1
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
            maxsize=self._frame.maxsize.currentText(),
            fps=self._frame.fps.currentText(),
            bitrate=self._frame.bitrate.currentText(),
            codec=self._frame.codec.currentText(),
            buffer=self._frame.buffer.currentText(),
            orientation=self._frame.orientation.currentText(),
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

    def _request_scrcpy_stop_once(self, service=None, process_key: str | None = None) -> bool:
        """为一个 scrcpy 会话只发送一次异步停止请求。"""

        resolved_service = service or getattr(self._frame, "_scrcpy_service", None)
        resolved_key = process_key or getattr(self._frame, "_process_key", "")
        if resolved_service is None or not resolved_key:
            return False
        stop_claim = self._frame._claim_scrcpy_stop()
        if stop_claim is None:
            return False
        try:
            requested = resolved_service.request_stop(resolved_key)
        except Exception:
            self._frame._release_scrcpy_stop_claim(stop_claim)
            raise
        if requested is False:
            try:
                still_active = bool(resolved_service.is_active(resolved_key))
            except Exception:
                still_active = True
            if still_active:
                self._frame._release_scrcpy_stop_claim(stop_claim)
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
