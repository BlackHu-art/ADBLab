"""Screen Mirroring & Remote Control tab -- scrcpy launcher, D-Pad, quick keys."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.adb_bridge import ADBBridge
from core.settings_manager import AppSettings
from gui.panels.base_panel import BasePanel
from gui.styles import BaseStyles
from models.remote import RemoteControlService, ScrcpyConfig, ScrcpyService


class ScrcpyLaunchWorker(QThread):
    """Runs slow scrcpy launch checks away from the UI thread."""

    launch_ready = Signal(list, str)
    log_message = Signal(str, str)

    def __init__(self, config: ScrcpyConfig, service: ScrcpyService | None = None):
        super().__init__()
        self.config = config
        self.service = service or ScrcpyService()

    def run(self):
        # scrcpy 版本、设备预检和编码器探测都可能阻塞，放到 QThread 避免卡住 UI。
        try:
            plan = self.service.build_launch_plan(self.config)
        except Exception as exc:
            self.log_message.emit("ERROR", f"scrcpy preflight failed: {exc}")
            return
        for level, message in plan.messages:
            if self.isInterruptionRequested():
                return
            self.log_message.emit(level, message)
        if self.isInterruptionRequested():
            return
        self.launch_ready.emit(plan.args, plan.device_info)

    @staticmethod
    def _build_args(cfg: dict, encoder: str | None) -> list[str]:
        from models.remote import build_scrcpy_args

        return build_scrcpy_args(ScrcpyConfig.from_mapping(cfg), encoder)


class RemotePanel(BasePanel):
    """Screen mirroring + remote key input."""

    _status_update_requested = Signal(str, object)
    _remote_queue_status_requested = Signal(int, int, str)

    _PRESETS = {
        0: {"maxsize": "1024", "fps": "30", "bitrate": "4",  "codec": "h264", "buffer": "50"},
        1: {"maxsize": "1280", "fps": "30", "bitrate": "8",  "codec": "h264", "buffer": "20"},
        2: {"maxsize": "1920", "fps": "60", "bitrate": "12", "codec": "h265", "buffer": "50"},
        3: {"maxsize": "720",  "fps": "24", "bitrate": "2",  "codec": "h264", "buffer": "0"},
    }

    _PRESET_NAMES = ["Smooth", "Balanced", "Quality", "Low Latency"]

    _SIZES = ["1024", "1280", "1920", "480p", "720p", "1080p", "Default"]
    _FPS   = ["24", "30", "60", "120"]
    _CODECS = ["h264", "h265", "av1"]
    _BUFFERS = ["0", "10", "20", "30", "50", "100", "150", "200"]
    _BITRATES = ["2", "4", "6", "8", "12", "16", "24", "32"]
    _ORIENTATIONS = ["0", "90", "180", "270"]

    def __init__(self, panel, parent=None):
        super().__init__(panel, parent)
        self._process = None
        self._running = False
        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._poll_process)
        self._settings = AppSettings.instance()
        self._adb = ADBBridge()
        self._scrcpy_service = ScrcpyService()
        self._remote_control = RemoteControlService(self._adb)
        self._loading = True
        self._launch_worker = None
        self._process_key = f"scrcpy_{id(self)}"
        self._active_device = None
        self._remote_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="adblab-remote")
        self._remote_submitted = 0
        self._remote_completed = 0
        self._status_update_requested.connect(self._update_status)
        self._remote_queue_status_requested.connect(self._update_remote_queue_status)

    # -- UI ----------------------------------------------------------------

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addWidget(self._build_mirroring())
        lo.addWidget(self._build_control())
        lo.addStretch()
        return w

    def _build_mirroring(self) -> QWidget:
        g = self._g("Screen Mirroring")
        gl = QVBoxLayout(g)
        gl.setSpacing(4)

        # ── Preset + Status ──
        r0 = QHBoxLayout()
        r0.setSpacing(6)
        r0.addWidget(QLabel("Preset:"))

        self.preset = self._combo(self._PRESET_NAMES)
        saved_preset = self._load("preset", "Smooth")
        self.preset.setCurrentText(saved_preset)
        if self.preset.currentText() != saved_preset:
            self.preset.setCurrentIndex(-1)  # "Custom" etc. → no preset selected
        r0.addWidget(self.preset, 1)  # 减少权重，让下拉框占用较少空间

        # 创建右侧信息区域
        right_widget = QWidget()
        right_layout = QHBoxLayout(right_widget)
        right_layout.setSpacing(6)
        right_layout.setContentsMargins(0, 0, 0, 0)  # 移除边距

        self._status_label = QLabel("Status: Idle")
        self._status_label.setFont(self._font_sm)
        right_layout.addWidget(self._status_label)

        self._device_info = QLabel("")
        self._device_info.setFont(self._font_sm)
        right_layout.addWidget(self._device_info)

        # 将右侧信息区域作为一个整体添加到主布局
        r0.addWidget(right_widget, 1)  # 给右侧信息区域相同权重

        gl.addLayout(r0)

        # ── Video ──
        vg = QGridLayout()
        vg.setHorizontalSpacing(10)
        vg.setVerticalSpacing(5)
        settings = [
            ("Size:",   "maxsize",     self._SIZES,        "720"),
            ("FPS:",    "fps",         self._FPS,          "60"),
            ("Codec:",  "codec",       self._CODECS,       "h264"),
            ("Buffer:", "buffer",      self._BUFFERS,      "50"),
            ("Bitrate:","bitrate",     self._BITRATES,     "8"),
            ("Orient:", "orientation", self._ORIENTATIONS, "0"),
        ]
        for i, (lbl, attr, items, default) in enumerate(settings):
            row, col = divmod(i, 3)
            label = QLabel(lbl)
            label.setFixedWidth(45)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            vg.addWidget(label, row, col * 2)
            combo = self._combo(items)
            combo.setCurrentText(self._load(attr, default))
            vg.addWidget(combo, row, col * 2 + 1)
            setattr(self, attr, combo)
        self.orientation.setToolTip("Lock orientation (0=auto)")
        gl.addLayout(vg)

        # ── Record ──
        rr = QHBoxLayout()
        rr.setSpacing(8)
        self.chk_record = self._create_checkbox("Record")  # 使用统一的工厂方法创建
        self.chk_record.setToolTip("Record mirroring to file")
        self.chk_record.toggled.connect(self._on_record_toggled)
        rr.addWidget(self.chk_record, 1)  # 占1份空间
        self.record_path = QLabel("")
        self.record_path.setFont(self._font_sm)
        rr.addWidget(self.record_path, 3)  # 占3份空间
        gl.addLayout(rr)

        # ── Display ──
        self.chk_fullscreen = self._create_checkbox("Fullscreen")
        self.chk_fullscreen.setToolTip("Launch in fullscreen mode")
        self.chk_aot = self._create_checkbox("Always on Top")
        self.chk_aot.setToolTip("Keep window above all others")
        self.chk_showtouches = self._create_checkbox("Show Touches")
        self.chk_showtouches.setToolTip("Visualize touch points on screen")
        self.chk_stayawake = self._create_checkbox("Stay Awake")
        self.chk_stayawake.setToolTip("Keep device screen on while mirroring")
        rd1 = QHBoxLayout()
        rd1.setSpacing(8)
        for cb in (self.chk_fullscreen, self.chk_aot, self.chk_showtouches, self.chk_stayawake):
            rd1.addWidget(cb)  # 不设置权重，让它们平均分配空间
        gl.addLayout(rd1)

        self.chk_turnscreenoff = self._create_checkbox("Turn Screen Off")
        self.chk_turnscreenoff.setToolTip("Turn off device screen on connect")
        self.chk_hw_encoder = self._create_checkbox("HW Encoder")
        self.chk_hw_encoder.setToolTip("Force hardware encoder (may cause stutter)")
        self.chk_noplayback = self._create_checkbox("No Window")
        self.chk_noplayback.setToolTip("Record only, no display window")
        self.chk_noaudio = self._create_checkbox("No Audio")  # 改为使用_create_checkbox方法创建
        self.chk_noaudio.setChecked(True)  # 保留初始勾选状态
        self.chk_noaudio.setToolTip("Disable audio forwarding")
        rd2 = QHBoxLayout()
        rd2.setSpacing(8)
        for cb in (self.chk_turnscreenoff, self.chk_hw_encoder, self.chk_noplayback, self.chk_noaudio):
            rd2.addWidget(cb)  # 不设置权重，让它们平均分配空间
        gl.addLayout(rd2)

        # ── Start / Stop ──
        rs = QHBoxLayout()
        rs.setSpacing(6)
        self.btn_start = self._b("Start (Ctrl+Enter)", "monitor-play.svg", "accent")
        self.btn_start.setFixedHeight(32)
        self.btn_start.setIconSize(QSize(16, 16))
        self.btn_stop = self._b("Stop (Ctrl+Q)", "stop-circle.svg", "danger")
        self.btn_stop.setFixedHeight(32)
        self.btn_stop.setIconSize(QSize(16, 16))
        self.btn_stop.setEnabled(False)
        rs.addWidget(self.btn_start, 1)
        rs.addWidget(self.btn_stop, 1)
        gl.addLayout(rs)

        return g

    def _create_checkbox(self, text: str) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setFont(self._font_sm)
        return cb

    def _build_control(self) -> QWidget:
        g = self._g("Remote Control")
        outer = QVBoxLayout(g)
        outer.setSpacing(4)
        gl = QHBoxLayout()
        gl.setSpacing(8)

        # D-Pad
        dpad = QWidget()
        dg = QGridLayout(dpad)
        dg.setSpacing(2)

        def _dk(label, code):
            b = self._qb(label, tooltip=f"Send keyevent {code}")
            b.setFont(self._font_base)
            b.setFixedSize(32, 32)
            b.clicked.connect(lambda _, c=code: self._send_keyevent(c))
            return b

        dg.addWidget(_dk("^", "DPAD_UP"), 0, 1)
        dg.addWidget(_dk("<", "DPAD_LEFT"), 1, 0)
        dg.addWidget(_dk("OK", "DPAD_CENTER"), 1, 1)
        dg.addWidget(_dk(">", "DPAD_RIGHT"), 1, 2)
        dg.addWidget(_dk("v", "DPAD_DOWN"), 2, 1)
        gl.addWidget(dpad)

        # Quick keys
        qk = QWidget()
        kg = QGridLayout(qk)
        kg.setSpacing(2)
        keys = [
            [("HOME", "HOME"), ("BACK", "BACK"), ("POWER", "POWER"), ("RECENTS", "RECENTS")],
            [("MENU", "MENU"), ("VOL+", "VOL_UP"), ("VOL-", "VOL_DOWN"), ("NOTIF", "NOTIFICATION")],
            [("SETTINGS", "SETTINGS"), ("APPS", "APP_SWITCH"), ("CAMERA", "CAMERA"), ("SEARCH", "SEARCH")],
            [("PLAY", "MEDIA_PLAY"), ("NEXT", "MEDIA_NEXT"), ("PREV", "MEDIA_PREV"), ("ENTER", "ENTER")],
        ]
        for r, row in enumerate(keys):
            for c, (label, code) in enumerate(row):
                b = self._qb(label, tooltip=f"Send keyevent {code}")
                b.setFont(self._font_sm)
                b.setFixedHeight(28)
                b.setMinimumWidth(56)
                b.clicked.connect(lambda _, cd=code: self._send_keyevent(cd))
                kg.addWidget(b, r, c)
        gl.addWidget(qk, 1)

        gestures = QWidget()
        gg = QGridLayout(gestures)
        gg.setSpacing(2)
        actions = [
            [("Swipe ↑", "swipe_up"), ("Swipe ↓", "swipe_down")],
            [("Swipe ←", "swipe_left"), ("Swipe →", "swipe_right")],
            [("Notif ↓", "notif_expand"), ("Notif ↑", "notif_collapse")],
            [("Portrait", "rotate_portrait"), ("Landscape", "rotate_landscape")],
        ]
        for r, row in enumerate(actions):
            for c, (label, action) in enumerate(row):
                b = self._qb(label, tooltip=f"Run remote action {action}")
                b.setFont(self._font_sm)
                b.setFixedHeight(28)
                b.setMinimumWidth(66)
                b.clicked.connect(lambda _, act=action: self._send_remote_action(act))
                gg.addWidget(b, r, c)
        gl.addWidget(gestures)
        outer.addLayout(gl)

        self._remote_status_label = QLabel("Input: Idle")
        self._remote_status_label.setFont(self._font_sm)
        self._remote_status_label.setStyleSheet(f"color: {BaseStyles.color('TEXT_SECONDARY')};")
        outer.addWidget(self._remote_status_label)

        return g

    # -- signals + shortcuts (B9) ----------------------------------------

    def connect_signals(self):
        self.btn_start.clicked.connect(self._start_scrcpy)
        self.btn_stop.clicked.connect(self._stop_scrcpy)
        self.preset.currentIndexChanged.connect(self._on_preset_changed)
        # Track individual changes → auto-switch to Custom
        for combo in (self.maxsize, self.fps, self.codec, self.buffer, self.bitrate,
                      self.orientation):
            combo.currentTextChanged.connect(self._on_custom_setting_changed)
        # B9: Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._start_scrcpy)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self._stop_scrcpy)
        # Apply loaded preset on startup (loading is still True → no re-save)
        idx = self.preset.currentIndex()
        if idx in self._PRESETS:
            self._on_preset_changed(idx)
        self._loading = False

    # -- B6: settings persistence ----------------------------------------

    def _on_custom_setting_changed(self, _value):
        """Any individual change switches preset to nothing (custom)."""
        if getattr(self, "_loading", False):
            return
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(-1)
        self.preset.blockSignals(False)
        self._save_all()

    def _save(self, key: str, value: str):
        if getattr(self, "_loading", False):
            return
        self._settings.set(f"scrcpy_{key}", value)

    def _save_all(self):
        p = self.preset.currentText()
        self._settings.set("scrcpy_preset", p if p else "Custom")
        for k in ("maxsize", "fps", "codec", "buffer", "bitrate", "orientation"):
            self._settings.set(f"scrcpy_{k}", getattr(self, k).currentText())

    def _load(self, key: str, default: str) -> str:
        return self._settings.get(f"scrcpy_{key}", default)

    # -- scrcpy presets ---------------------------------------------------

    def _on_preset_changed(self, idx: int):
        if idx in self._PRESETS:
            was_loading = getattr(self, "_loading", False)
            self._loading = True
            p = self._PRESETS[idx]
            self.maxsize.setCurrentText(p["maxsize"])
            self.fps.setCurrentText(p["fps"])
            self.bitrate.setCurrentText(p["bitrate"])
            self.codec.setCurrentText(p["codec"])
            self.buffer.setCurrentText(p["buffer"])
            self._loading = was_loading
            if not was_loading:
                self._save_all()

    # -- A3: record toggle ------------------------------------------------

    def _on_record_toggled(self, checked: bool):
        if not checked:
            self.record_path.setText("")
            return
        save_dir = self._settings.save_directory
        os.makedirs(save_dir, exist_ok=True)
        device = self.selected_devices[0] if self.selected_devices else "unknown"
        device_tag = device.replace(":", "_").replace(".", "_")
        from datetime import datetime
        filename = f"scrcpy_{device_tag}_{datetime.now().strftime('%H%M%S')}.mp4"
        self._record_path = os.path.join(save_dir, filename)
        self.record_path.setText(self._record_path.replace("\\", "/"))

    # -- scrcpy start / stop ----------------------------------------------

    def _start_scrcpy(self):
        if self._process or (self._launch_worker and self._launch_worker.isRunning()):
            return
        exe = self._scrcpy_service.resolve_executable()
        if not os.path.isfile(exe):
            self._log("WARNING", f"scrcpy not found: {exe}")
            return
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return

        self._set_running(True)
        self._update_status("Checking...", "#FFC107")
        self._active_device = devices[0]

        config = self._scrcpy_config(exe, self._active_device)

        worker = ScrcpyLaunchWorker(config, service=self._scrcpy_service)
        worker.log_message.connect(self._log)
        worker.launch_ready.connect(self._on_launch_ready)
        worker.finished.connect(lambda _w=worker: self._on_launch_finished(_w))
        self._launch_worker = worker
        worker.start()

    def _on_launch_ready(self, args: list, device_info: str):
        if self._launch_worker and self._launch_worker.isInterruptionRequested():
            return
        self._device_info.setText(device_info)
        active_device = getattr(self, "_active_device", None)
        if active_device and device_info:
            self._remote_control.remember_dimensions(active_device, device_info.split("x"))
        self._update_status("Running", "#28A745")
        self._log("INFO", f"Launching: scrcpy {' '.join(args[2:])}")

        try:
            self._process = self._scrcpy_service.start(
                self._process_key,
                args,
            )
            threading.Thread(target=self._read_stderr, daemon=True).start()
            self._watchdog.start(500)
        except Exception as e:
            self._log("ERROR", f"scrcpy start failed: {e}")
            self._set_running(False)
            self._update_status("Error", "#DC3545")

    def _on_launch_finished(self, worker: ScrcpyLaunchWorker):
        interrupted = worker.isInterruptionRequested()
        if self._launch_worker is worker:
            self._launch_worker = None
        worker.deleteLater()
        if not self._process:
            self._active_device = None
            self._set_running(False)
            if interrupted:
                self._update_status("Idle", None)
            else:
                self._update_status("Error", "#DC3545")

    def _read_stderr(self):
        proc = self._process
        if proc and proc.stderr:
            for line in proc.stderr:
                line = line.strip()
                if not line:
                    continue
                # C13: extract FPS from scrcpy stderr
                fps = self._scrcpy_service.parse_fps(line)
                if fps:
                    self._status_update_requested.emit(fps, None)
                else:
                    self._log("DEBUG", f"[scrcpy] {line}")

    def _poll_process(self):
        if not self._process:
            self._watchdog.stop()
            return
        rc = self._process.poll()
        if rc is not None:
            self._watchdog.stop()
            self._process = None
            self._set_running(False)
            self._update_status("Disconnected", "#FFC107")
            if rc != 0:
                self._log("WARNING", f"scrcpy exited with code {rc}")

    def _stop_scrcpy(self):
        if self._launch_worker and self._launch_worker.isRunning():
            self._launch_worker.requestInterruption()
            self._update_status("Stopping...", "#FFC107")
            return
        if not self._process:
            return
        self._watchdog.stop()
        self._process = None
        self._active_device = None
        self._set_running(False)
        self._update_status("Idle", None)
        def _do_stop():
            try:
                self._scrcpy_service.stop(self._process_key, timeout=2)
                self._log("INFO", "scrcpy stopped")
            except Exception as e:
                self._log("ERROR", f"stop failed: {e}")
        threading.Thread(target=_do_stop, daemon=True).start()

    def _set_running(self, running: bool):
        self._running = running
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    # -- B8: status indicator ---------------------------------------------

    def _update_status(self, text: str, color: str | None):
        style = "font-size: 10px; font-weight: bold;"
        if color:
            style = f"color: {color}; {style}"
        self._status_label.setStyleSheet(style)
        self._status_label.setText(f"Status: {text}")

    # -- key events -------------------------------------------------------

    def _send_keyevent(self, key_name: str):
        devices = self.selected_devices
        if not devices:
            return
        self._submit_remote_input(
            lambda: self._remote_control.send_keyevent(devices[0], key_name)
        )

    def _send_remote_action(self, action: str):
        devices = self.selected_devices
        if not devices:
            return
        device = devices[0]
        def _run():
            try:
                self._remote_control.perform_action(device, action)
            except Exception as exc:
                self._log("ERROR", f"remote action failed: {exc}")

        self._submit_remote_input(_run)

    def _submit_remote_input(self, task):
        """遥控输入放入单线程队列，并把队列状态回写到 UI。"""
        executor = getattr(self, "_remote_executor", None)
        if executor is None:
            self._mark_remote_submitted()
            task()
            self._mark_remote_completed("sent")
            return
        self._mark_remote_submitted()

        def _wrapped():
            try:
                task()
                result = "sent"
            except Exception as exc:
                result = "failed"
                self._log("ERROR", f"remote input failed: {exc}")
            self._mark_remote_completed(result)

        try:
            executor.submit(_wrapped)
        except RuntimeError as exc:
            self._remote_submitted = max(
                getattr(self, "_remote_completed", 0),
                getattr(self, "_remote_submitted", 0) - 1,
            )
            self._emit_remote_queue_status(
                self._remote_submitted,
                getattr(self, "_remote_completed", 0),
                "failed",
            )
            self._log("ERROR", f"remote executor stopped: {exc}")

    def _mark_remote_submitted(self):
        self._remote_submitted = getattr(self, "_remote_submitted", 0) + 1
        self._emit_remote_queue_status(
            self._remote_submitted,
            getattr(self, "_remote_completed", 0),
            "queued",
        )

    def _mark_remote_completed(self, result: str):
        self._remote_completed = min(
            getattr(self, "_remote_submitted", 0),
            getattr(self, "_remote_completed", 0) + 1,
        )
        self._emit_remote_queue_status(
            getattr(self, "_remote_submitted", 0),
            self._remote_completed,
            result,
        )

    def _emit_remote_queue_status(self, submitted: int, completed: int, result: str):
        try:
            self._remote_queue_status_requested.emit(submitted, completed, result)
        except RuntimeError:
            # Tests may exercise service wiring on __new__ objects without QObject init.
            pass

    def _update_remote_queue_status(self, submitted: int, completed: int, result: str):
        label = getattr(self, "_remote_status_label", None)
        if label is None:
            return
        pending = max(0, submitted - completed)
        if pending > 1:
            text = f"Input: Queued {pending}"
            color = BaseStyles.color("TEXT_SECONDARY")
        elif pending == 1:
            text = "Input: Sending"
            color = BaseStyles.color("TEXT_SECONDARY")
        elif result == "failed":
            text = "Input: Failed"
            color = BaseStyles.color("LOG_ERROR")
        elif result == "sent":
            text = "Input: Sent"
            color = BaseStyles.color("LOG_SUCCESS")
        else:
            text = "Input: Idle"
            color = BaseStyles.color("TEXT_SECONDARY")
        label.setText(text)
        label.setStyleSheet(f"color: {color};")

    def _scrcpy_config(self, exe: str, device: str) -> ScrcpyConfig:
        return ScrcpyConfig(
            exe=exe,
            adb=self._adb.path,
            device=device,
            maxsize=self.maxsize.currentText(),
            fps=self.fps.currentText(),
            bitrate=self.bitrate.currentText(),
            codec=self.codec.currentText(),
            buffer=self.buffer.currentText(),
            orientation=self.orientation.currentText(),
            hw_encoder=self.chk_hw_encoder.isChecked(),
            fullscreen=self.chk_fullscreen.isChecked(),
            always_on_top=self.chk_aot.isChecked(),
            no_audio=self.chk_noaudio.isChecked(),
            show_touches=self.chk_showtouches.isChecked(),
            stay_awake=self.chk_stayawake.isChecked(),
            turn_screen_off=self.chk_turnscreenoff.isChecked(),
            record_path=self._record_path
            if self.chk_record.isChecked() and hasattr(self, "_record_path")
            else "",
            no_window=self.chk_noplayback.isChecked(),
        )

    # -- helpers ----------------------------------------------------------

    def _log(self, level: str, msg: str):
        self.signals.log_message.emit(level, msg)

    def closeEvent(self, event):
        if self._process:
            self._watchdog.stop()
            self._process = None
            try:
                self._scrcpy_service.stop(self._process_key, timeout=2)
            except Exception:
                pass
        if self._launch_worker and self._launch_worker.isRunning():
            self._launch_worker.requestInterruption()
        executor = getattr(self, "_remote_executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        adb = getattr(self, "_adb", None)
        if adb is not None and hasattr(adb, "close_input_sessions"):
            adb.close_input_sessions()
        super().closeEvent(event)
