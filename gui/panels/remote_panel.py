"""提供 scrcpy 投屏启动、快捷按键和 Remote 输入控制面板。"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from core.adb_bridge import ADBBridge
from core.settings_manager import AppSettings
from gui.panels.base_panel import BasePanel
from gui.styles import BaseStyles
from gui.widgets.responsive_layout import reflow_widgets, responsive_column_count
from models.remote import RemoteControlService, RemoteInputEngine, ScrcpyConfig, ScrcpyService


class ScrcpyLaunchWorker(QThread):
    """在 GUI 线程之外执行可能阻塞的 scrcpy 启动检查。"""

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
    """管理 scrcpy 会话、串行 Remote 输入队列和相关界面状态。"""

    _orphaned_launch_workers: list[ScrcpyLaunchWorker] = []
    _status_update_requested = Signal(str, object)
    _remote_queue_status_requested = Signal(int, int, str)
    _IGNORED_SCRCPY_LOG_PATTERNS = (
        "Could not inject char u+",
        "libpng warning: iCCP: known incorrect sRGB profile",
    )

    _PRESETS = {
        0: {"maxsize": "1024", "fps": "30", "bitrate": "4", "codec": "h264", "buffer": "50"},
        1: {"maxsize": "1280", "fps": "30", "bitrate": "8", "codec": "h264", "buffer": "20"},
        2: {"maxsize": "1920", "fps": "60", "bitrate": "12", "codec": "h265", "buffer": "50"},
        3: {"maxsize": "720", "fps": "24", "bitrate": "2", "codec": "h264", "buffer": "0"},
    }

    _PRESET_NAMES = ["Smooth", "Balanced", "Quality", "Low Latency"]

    _SIZES = ["1024", "1280", "1920", "480p", "720p", "1080p", "Default"]
    _FPS = ["24", "30", "60", "120"]
    _CODECS = ["h264", "h265", "av1"]
    _BUFFERS = ["0", "10", "20", "30", "50", "100", "150", "200"]
    _BITRATES = ["2", "4", "6", "8", "12", "16", "24", "32"]
    _ORIENTATIONS = ["0", "90", "180", "270"]
    _KEY_ICONS = {
        "HOME": "house.svg",
        "BACK": "arrow-u-left-up.svg",
        "RECENTS": "squares-four.svg",
        "MENU": "list.svg",
        "POWER": "power.svg",
        "SETTINGS": "gear.svg",
        "CAMERA": "camera.svg",
        "SEARCH": "magnifying-glass.svg",
        "ENTER": "keyboard.svg",
        "DEL": "backspace.svg",
        "VOL_DOWN": "speaker-low.svg",
        "VOL_UP": "speaker-high.svg",
        "MEDIA_PLAY": "play.svg",
        "MEDIA_PREV": "skip-back.svg",
        "MEDIA_NEXT": "skip-forward.svg",
    }
    _ACTION_ICONS = {
        "swipe_up": "arrow-up.svg",
        "swipe_down": "arrow-down.svg",
        "swipe_left": "arrow-left.svg",
        "swipe_right": "arrow-right.svg",
        "notif_expand": "tray-arrow-down.svg",
        "notif_collapse": "tray-arrow-up.svg",
        "rotate_portrait": "device-rotate.svg",
        "rotate_landscape": "device-rotate.svg",
    }

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
        self._input_engine = RemoteInputEngine()
        self._loading = True
        self._closing = False
        self._launch_worker = None
        self._process_key = f"scrcpy_{id(self)}"
        self._active_device = None
        self._remote_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="adblab-remote"
        )
        self._remote_submitted = 0
        self._remote_completed = 0
        self._status_update_requested.connect(self._update_status)
        self._remote_queue_status_requested.connect(self._update_remote_queue_status)

    # ── 界面构建 ─────────────────────────────────────────────────────────

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

        preset_label = self._label("Preset:")

        self.preset = self._combo(self._PRESET_NAMES)
        saved_preset = self._load("preset", "Smooth")
        self.preset.setCurrentText(saved_preset)
        if self.preset.currentText() != saved_preset:
            self.preset.setCurrentIndex(-1)  # 自定义值不对应任何预设。

        right_widget = QWidget()
        right_layout = QHBoxLayout(right_widget)
        right_layout.setSpacing(6)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._status_label = self._status_text("Status: Idle")
        right_layout.addWidget(self._status_label)

        self._device_info = self._status_text("")
        right_layout.addWidget(self._device_info)

        self._add_responsive_row(
            gl,
            preset_label,
            self.preset,
            right_widget,
            spacing=6,
            compact_columns=1,
            medium_columns=2,
            wide_columns=3,
        )

        settings = [
            ("Size:", "maxsize", self._SIZES, "720"),
            ("FPS:", "fps", self._FPS, "60"),
            ("Codec:", "codec", self._CODECS, "h264"),
            ("Buffer:", "buffer", self._BUFFERS, "50"),
            ("Bitrate:", "bitrate", self._BITRATES, "8"),
            ("Orient:", "orientation", self._ORIENTATIONS, "0"),
        ]
        setting_widgets = []
        for lbl, attr, items, default in settings:
            label = self._label(lbl)
            label.setMinimumWidth(56)
            label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            combo = self._combo(items)
            combo.setCurrentText(self._load(attr, default))
            setattr(self, attr, combo)
            setting_widgets.extend((label, combo))
        self._add_responsive_row(
            gl,
            *setting_widgets,
            spacing=5,
            compact_columns=2,
            medium_columns=4,
            wide_columns=6,
        )
        self.orientation.setToolTip("Lock orientation (0=auto)")

        self.chk_record = self._create_checkbox("Record")
        self.chk_record.setToolTip("Record mirroring to file")
        self.chk_record.toggled.connect(self._on_record_toggled)
        self.record_path = self._status_text("")
        self._add_responsive_row(
            gl,
            self.chk_record,
            self.record_path,
            spacing=8,
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )

        self.chk_fullscreen = self._create_checkbox("Fullscreen")
        self.chk_fullscreen.setToolTip("Launch in fullscreen mode")
        self.chk_aot = self._create_checkbox("Pin Top")
        self.chk_aot.setToolTip("Keep window above all others")
        self.chk_showtouches = self._create_checkbox("Touches")
        self.chk_showtouches.setToolTip("Visualize touch points on screen")
        self.chk_stayawake = self._create_checkbox("Awake")
        self.chk_stayawake.setToolTip("Keep device screen on while mirroring")
        self._add_responsive_row(
            gl,
            self.chk_fullscreen,
            self.chk_aot,
            self.chk_showtouches,
            self.chk_stayawake,
            spacing=8,
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )

        self.chk_turnscreenoff = self._create_checkbox("Screen Off")
        self.chk_turnscreenoff.setToolTip("Turn off device screen on connect")
        self.chk_hw_encoder = self._create_checkbox("HW Enc")
        self.chk_hw_encoder.setToolTip("Force hardware encoder (may cause stutter)")
        self.chk_noplayback = self._create_checkbox("No Window")
        self.chk_noplayback.setToolTip("Record only, no display window")
        self.chk_noaudio = self._create_checkbox("No Audio")
        self.chk_noaudio.setChecked(True)
        self.chk_noaudio.setToolTip("Disable audio forwarding")
        self._add_responsive_row(
            gl,
            self.chk_turnscreenoff,
            self.chk_hw_encoder,
            self.chk_noplayback,
            self.chk_noaudio,
            spacing=8,
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )

        self.btn_start = self._b(
            "Start", "monitor-play.svg", "accent", tooltip="Start mirroring (Ctrl+Enter)"
        )
        self.btn_start.setMinimumHeight(32)
        self.btn_start.setIconSize(QSize(16, 16))
        self.btn_stop = self._b(
            "Stop", "stop-circle.svg", "danger", tooltip="Stop mirroring (Ctrl+Q)"
        )
        self.btn_stop.setMinimumHeight(32)
        self.btn_stop.setIconSize(QSize(16, 16))
        self.btn_stop.setEnabled(False)
        self._add_responsive_row(
            gl,
            self.btn_start,
            self.btn_stop,
            spacing=6,
            compact_columns=2,
            medium_columns=2,
            wide_columns=2,
        )

        return g

    def _create_checkbox(self, text: str) -> QCheckBox:
        return self._checkbox(text)

    def _build_control(self) -> QWidget:
        g = self._g("Remote Control")
        outer = QVBoxLayout(g)
        outer.setSpacing(6)
        self._remote_control_buttons = []
        self._remote_key_buttons = []
        self._remote_action_buttons = []

        # RECENTS 已覆盖 APP_SWITCH；通知栏操作由下方手势处理。
        keys = QWidget()
        kg = QGridLayout(keys)
        kg.setSpacing(2)
        kg.setContentsMargins(0, 0, 0, 0)
        key_rows = [
            [
                ("HOME", "HOME"),
                ("BACK", "BACK"),
                ("RECENT", "RECENTS"),
                ("MENU", "MENU"),
                ("PWR", "POWER"),
            ],
            [
                ("SET", "SETTINGS"),
                ("CAM", "CAMERA"),
                ("SRCH", "SEARCH"),
                ("ENTER", "ENTER"),
                ("DEL", "DEL"),
            ],
        ]
        for r, row in enumerate(key_rows):
            for c, (label, code) in enumerate(row):
                kg.addWidget(self._remote_key_button(label, code, f"Send keyevent {code}"), r, c)
        self._remote_key_layout = kg
        self._remote_primary_key_buttons = tuple(self._remote_key_buttons)
        outer.addWidget(keys)

        media = QWidget()
        mg = QGridLayout(media)
        mg.setSpacing(2)
        mg.setContentsMargins(0, 0, 0, 0)
        media_rows = [
            [
                ("VOL-", "VOL_DOWN"),
                ("VOL+", "VOL_UP"),
                ("PLAY", "MEDIA_PLAY"),
                ("PREV", "MEDIA_PREV"),
                ("NEXT", "MEDIA_NEXT"),
            ],
        ]
        for r, row in enumerate(media_rows):
            for c, (label, code) in enumerate(row):
                mg.addWidget(self._remote_key_button(label, code, f"Send keyevent {code}"), r, c)
        self._remote_media_layout = mg
        self._remote_media_buttons = tuple(
            self._remote_key_buttons[len(self._remote_primary_key_buttons) :]
        )
        outer.addWidget(media)

        actions = QWidget()
        gg = QGridLayout(actions)
        gg.setSpacing(2)
        gg.setContentsMargins(0, 0, 0, 0)
        action_rows = [
            [
                ("Swipe Up", "swipe_up", "Swipe up"),
                ("Swipe Down", "swipe_down", "Swipe down"),
                ("Swipe Left", "swipe_left", "Swipe left"),
                ("Swipe Right", "swipe_right", "Swipe right"),
            ],
            [
                ("Notif+", "notif_expand", "Expand notifications"),
                ("Notif-", "notif_collapse", "Collapse notifications"),
                ("Portrait", "rotate_portrait", "Rotate portrait"),
                ("Land", "rotate_landscape", "Rotate landscape"),
            ],
        ]
        for r, row in enumerate(action_rows):
            for c, (label, action, tooltip) in enumerate(row):
                gg.addWidget(self._remote_action_button(label, action, tooltip), r, c)
        self._remote_action_layout = gg
        outer.addWidget(actions)

        return g

    def apply_responsive_width(self, width: int) -> None:
        """按面板宽度重排投屏参数和遥控按钮，不重建任何控件。"""

        super().apply_responsive_width(width)
        if not hasattr(self, "_remote_key_layout"):
            return

        key_columns = responsive_column_count(
            width,
            compact_columns=3,
            medium_columns=5,
            wide_columns=5,
        )
        media_columns = responsive_column_count(
            width,
            compact_columns=3,
            medium_columns=5,
            wide_columns=5,
        )
        action_columns = responsive_column_count(
            width,
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        reflow_widgets(
            self._remote_key_layout,
            self._remote_primary_key_buttons,
            key_columns,
        )
        reflow_widgets(
            self._remote_media_layout,
            self._remote_media_buttons,
            media_columns,
        )
        reflow_widgets(
            self._remote_action_layout,
            self._remote_action_buttons,
            action_columns,
        )

    def _remote_key_button(self, label: str, code: str, tooltip: str):
        b = self._b(label, self._KEY_ICONS.get(code, "keyboard.svg"), tooltip=tooltip)
        b.setProperty("remoteKey", code)
        b.setFont(self._font_sm)
        b.setIconSize(QSize(13, 13))
        b.setMinimumHeight(28)
        b.setMinimumWidth(56)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.clicked.connect(lambda _, cd=code: self._send_keyevent(cd))
        self._remote_control_buttons.append(b)
        self._remote_key_buttons.append(b)
        return b

    def _remote_action_button(self, label: str, action: str, tooltip: str):
        b = self._b(label, self._ACTION_ICONS.get(action, "keyboard.svg"), tooltip=tooltip)
        b.setProperty("remoteAction", action)
        b.setFont(self._font_sm)
        b.setIconSize(QSize(13, 13))
        b.setMinimumHeight(28)
        b.setMinimumWidth(76)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.clicked.connect(lambda _, act=action: self._send_remote_action(act))
        self._remote_control_buttons.append(b)
        self._remote_action_buttons.append(b)
        return b

    # ── 信号与快捷键 ────────────────────────────────────────────────────

    def connect_signals(self):
        self.btn_start.clicked.connect(self._start_scrcpy)
        self.btn_stop.clicked.connect(self._stop_scrcpy)
        self.preset.currentIndexChanged.connect(self._on_preset_changed)
        # 任一参数变化后切换为自定义配置。
        for combo in (
            self.maxsize,
            self.fps,
            self.codec,
            self.buffer,
            self.bitrate,
            self.orientation,
        ):
            combo.currentTextChanged.connect(self._on_custom_setting_changed)
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._start_scrcpy)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self._stop_scrcpy)
        # 启动时应用已加载预设；此时仍处于 loading 状态，不会重复保存。
        idx = self.preset.currentIndex()
        if idx in self._PRESETS:
            self._on_preset_changed(idx)
        self._loading = False

    # ── 设置持久化 ──────────────────────────────────────────────────────

    def _on_custom_setting_changed(self, _value):
        """任一独立参数变化后取消预设选择并保存为自定义配置。"""
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

    # ── scrcpy 预设 ─────────────────────────────────────────────────────

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

    # ── 录制开关 ────────────────────────────────────────────────────────

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

    # ── scrcpy 启停 ─────────────────────────────────────────────────────

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
        if len(devices) > 1:
            self._log(
                "WARNING",
                f"Multiple devices selected; Remote will control one active session "
                f"and ignore {len(devices) - 1} additional selection(s).",
            )

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
        if getattr(self, "_closing", False):
            return
        if self._launch_worker and self._launch_worker.isInterruptionRequested():
            return
        self._device_info.setText(device_info)
        active_device = getattr(self, "_active_device", None)
        if active_device and device_info:
            self._remote_control.remember_dimensions(active_device, device_info.split("x"))
        self._set_running(True)
        self._update_status("Running", "#28A745")
        self._log("INFO", "Launching scrcpy")
        self._log("DEBUG", f"scrcpy launch plan prepared: argument_count={len(args)}")

        try:
            self._process = self._scrcpy_service.start(
                self._process_key,
                args,
            )
            threading.Thread(target=self._focus_scrcpy_window, daemon=True).start()
            threading.Thread(target=self._warm_remote_input_session, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()
            self._watchdog.start(500)
        except Exception as exc:
            self._log("ERROR", f"scrcpy start failed: {type(exc).__name__}")
            self._active_device = None
            self._set_running(False)
            self._update_status("Error", "#DC3545")

    def _on_launch_finished(self, worker: ScrcpyLaunchWorker):
        interrupted = worker.isInterruptionRequested()
        if self._launch_worker is worker:
            self._launch_worker = None
        worker.deleteLater()
        if getattr(self, "_closing", False):
            return
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
                if getattr(self, "_closing", False):
                    return
                line = line.strip()
                if not line:
                    continue
                # scrcpy 的标准错误流同时承载 FPS 和诊断信息，必须先识别 FPS。
                fps = self._scrcpy_service.parse_fps(line)
                if fps:
                    self._status_update_requested.emit(fps, None)
                elif self._should_ignore_scrcpy_log_line(line):
                    continue
                else:
                    self._log("DEBUG", f"[scrcpy] {self._redact_remote_diagnostic(line)}")

    def _poll_process(self):
        if not self._process:
            self._watchdog.stop()
            return
        rc = self._process.poll()
        if rc is not None:
            self._watchdog.stop()
            self._process = None
            self._active_device = None
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
            except Exception as exc:
                self._log("ERROR", f"stop failed: {type(exc).__name__}")

        threading.Thread(target=_do_stop, daemon=True).start()

    def _set_running(self, running: bool):
        self._running = running
        btn_start = getattr(self, "btn_start", None)
        btn_stop = getattr(self, "btn_stop", None)
        self._set_button_enabled(btn_start, not running)
        self._set_button_enabled(btn_stop, running)

    # ── 状态指示 ────────────────────────────────────────────────────────

    def _update_status(self, text: str, color: str | None):
        style = "font-weight: bold;"
        if color:
            style = f"color: {color}; {style}"
        self._status_label.setStyleSheet(style)
        self._status_label.setText(f"Status: {text}")

    # ── 按键与输入事件 ──────────────────────────────────────────────────

    def _selected_remote_device(self) -> str | None:
        # 兼容未运行 __init__ 的旧式轻量嵌入场景；正常面板始终持有该字段。
        if not hasattr(self, "_active_device"):
            devices = self.selected_devices
            if not devices:
                self._log("WARNING", "No device selected")
                return None
            return devices[0]

        device = getattr(self, "_active_device", None)
        process = getattr(self, "_process", None)
        if not device or process is None or not getattr(self, "_running", False):
            self._log("WARNING", "Remote session is not running")
            return None
        try:
            if process.poll() is not None:
                self._log("WARNING", "Remote session is not running")
                return None
        except (AttributeError, OSError):
            pass
        return device

    def _send_keyevent(self, key_name: str):
        device = self._selected_remote_device()
        if not device:
            return
        self._submit_remote_input(lambda: self._remote_control.send_keyevent(device, key_name))

    def _send_remote_action(self, action: str):
        device = self._selected_remote_device()
        if not device:
            return

        def _run():
            try:
                self._remote_control.perform_action(device, action)
            except Exception as exc:
                self._log("ERROR", f"remote action failed: {type(exc).__name__}")

        self._submit_remote_input(_run)

    @classmethod
    def _should_ignore_scrcpy_log_line(cls, line: str) -> bool:
        return any(pattern in line for pattern in cls._IGNORED_SCRCPY_LOG_PATTERNS)

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
                self._log("ERROR", f"remote input failed: {type(exc).__name__}")
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
            self._log("ERROR", f"remote executor stopped: {type(exc).__name__}")

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
            # 兼容尚未完成 QObject 初始化的轻量嵌入场景。
            pass

    def _update_remote_queue_status(self, submitted: int, completed: int, result: str):
        return

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
            prefer_text=True,
            window_title=self._input_engine.window_title(device),
            hw_encoder=self.chk_hw_encoder.isChecked(),
            fullscreen=self.chk_fullscreen.isChecked(),
            always_on_top=self.chk_aot.isChecked(),
            no_audio=self.chk_noaudio.isChecked(),
            show_touches=self.chk_showtouches.isChecked(),
            stay_awake=self.chk_stayawake.isChecked(),
            turn_screen_off=self.chk_turnscreenoff.isChecked(),
            record_path=(
                self._record_path
                if self.chk_record.isChecked() and hasattr(self, "_record_path")
                else ""
            ),
            no_window=self.chk_noplayback.isChecked(),
        )

    def _focus_scrcpy_window(self):
        active_device = getattr(self, "_active_device", None)
        if not active_device:
            return
        title = self._input_engine.window_title(active_device)
        if self._input_engine.focus_window(title):
            self._log("INFO", "scrcpy window focused for keyboard input")
        else:
            self._log("DEBUG", "scrcpy window focus was not acquired")

    def _warm_remote_input_session(self):
        active_device = getattr(self, "_active_device", None)
        if not active_device:
            return
        try:
            if self._adb.warm_input_session(active_device):
                self._log("DEBUG", "remote input session warmed")
        except Exception as exc:
            self._log(
                "DEBUG",
                f"remote input session warmup skipped: error_type={type(exc).__name__}",
            )

    # ── 辅助方法 ────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        if getattr(self, "_closing", False):
            return
        self.signals.log_message.emit(level, msg)

    def _redact_remote_diagnostic(self, message: str) -> str:
        """移除 Remote 诊断信息中的当前设备标识，并限制异常输出长度。"""
        text = str(message).replace("\r", " ").replace("\n", " ")
        active_device = str(getattr(self, "_active_device", "") or "")
        if active_device:
            text = text.replace(active_device, "<device>")
        return text[:1000]

    def shutdown(self):
        """先停止 scrcpy 和启动 worker，再关闭输入队列及持久 ADB 会话。"""
        self._closing = True
        if self._process:
            self._watchdog.stop()
            self._process = None
            self._scrcpy_service.request_stop(self._process_key)
        self._active_device = None
        self._running = False
        self._stop_launch_worker(wait_ms=0)
        executor = getattr(self, "_remote_executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
            self._remote_executor = None
        adb = getattr(self, "_adb", None)
        if (
            not getattr(self, "_shutdown_task_registered", False)
            and adb is not None
            and hasattr(adb, "close_input_sessions")
        ):
            threading.Thread(
                target=adb.close_input_sessions,
                name="adblab-remote-input-shutdown",
                daemon=True,
            ).start()

    def register_shutdown_task(self, supervisor, *, owner_id: str, task_id: str) -> bool:
        """在界面断开引用前注册 scrcpy、启动 worker 和输入会话清理任务。"""
        worker = getattr(self, "_launch_worker", None)
        adb = getattr(self, "_adb", None)
        close_input = getattr(adb, "close_input_sessions", None)
        scrcpy_service = getattr(self, "_scrcpy_service", None)
        process_key = getattr(self, "_process_key", "")

        def process_running() -> bool:
            if scrcpy_service is None or not process_key:
                return False
            try:
                return bool(scrcpy_service.is_active(process_key))
            except (AttributeError, RuntimeError, OSError):
                return True

        if worker is None and not callable(close_input) and not process_running():
            return False
        self._shutdown_task_registered = True
        input_finished = threading.Event()
        input_started = threading.Event()

        def worker_running() -> bool:
            if worker is None:
                return False
            try:
                return worker.isRunning()
            except RuntimeError:
                return False

        def is_running() -> bool:
            return worker_running() or not input_finished.is_set() or process_running()

        def request_stop() -> None:
            if worker_running():
                worker.requestInterruption()
            if process_running():
                scrcpy_service.request_stop(process_key)
            if callable(close_input) and not input_started.is_set():
                input_started.set()

                def close_sessions():
                    try:
                        close_input()
                    finally:
                        input_finished.set()

                threading.Thread(
                    target=close_sessions,
                    name="adblab-remote-input-shutdown",
                    daemon=True,
                ).start()
            elif not callable(close_input):
                input_finished.set()

        def wait(timeout: float) -> bool:
            deadline = time.monotonic() + max(0.0, float(timeout))
            while is_running():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                if worker_running():
                    worker.wait(max(0, min(50, int(remaining * 1000))))
                else:
                    time.sleep(min(remaining, 0.05))
            return True

        def force_stop(timeout: float) -> bool:
            if not process_running():
                return False
            return bool(scrcpy_service.force_stop(process_key, timeout))

        supervisor.register(
            task_id,
            owner_id=owner_id,
            kind="remote_session",
            request_stop=request_stop,
            wait=wait,
            is_running=is_running,
            force_stop=force_stop,
        )
        return True

    def _stop_launch_worker(self, wait_ms: int = 3000):
        worker = getattr(self, "_launch_worker", None)
        if worker is None:
            return
        self._launch_worker = None
        self._disconnect_launch_worker(worker)
        if worker.isRunning():
            worker.requestInterruption()
            if not worker.wait(wait_ms):
                self._defer_launch_worker_delete(worker)
                return
        worker.deleteLater()

    def _disconnect_launch_worker(self, worker: ScrcpyLaunchWorker):
        for disconnect in (
            lambda: worker.log_message.disconnect(self._log),
            lambda: worker.launch_ready.disconnect(self._on_launch_ready),
            lambda: worker.finished.disconnect(),
        ):
            try:
                disconnect()
            except (RuntimeError, TypeError):
                pass

    @classmethod
    def _defer_launch_worker_delete(cls, worker: ScrcpyLaunchWorker):
        try:
            worker.setParent(None)
        except RuntimeError:
            pass
        cls._orphaned_launch_workers.append(worker)

        def release():
            try:
                cls._orphaned_launch_workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()

        try:
            worker.finished.connect(release)
        except RuntimeError:
            release()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
