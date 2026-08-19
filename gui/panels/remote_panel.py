"""提供 scrcpy 投屏启动、快捷按键和 Remote 输入控制面板。"""

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PySide6.QtCore import QCoreApplication, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QVBoxLayout, QWidget

from core.adb_bridge import ADBBridge
from core.settings_manager import SCRCPY_SETTING_DEFAULTS, AppSettings
from gui.panels.base_panel import BasePanel
from gui.widgets.responsive_layout import WidthPolicy, paired_mode, row_major_mode
from services.remote import RemoteControlService, RemoteInputEngine, ScrcpyConfig, ScrcpyService


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
        from services.remote import build_scrcpy_args

        return build_scrcpy_args(ScrcpyConfig.from_mapping(cfg), encoder)


class RemotePanel(BasePanel):
    """管理 scrcpy 会话、串行 Remote 输入队列和相关界面状态。"""

    _orphaned_launch_workers: list[ScrcpyLaunchWorker] = []
    _launch_worker_reaper_states: dict[int, dict[str, object]] = {}
    _launch_worker_reaper_lock = threading.RLock()
    _LAUNCH_WORKER_DELETE_RETRY_LIMIT = 3
    _LAUNCH_WORKER_DELETE_RETRY_MS = 1
    _status_update_requested = Signal(str, object)
    _remote_queue_status_requested = Signal(int, int, str)
    _stop_completed_requested = Signal(bool)
    _SESSION_IDLE = "idle"
    _SESSION_STARTING = "starting"
    _SESSION_RUNNING = "running"
    _SESSION_STOPPING = "stopping"
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
        self._session_state = self._SESSION_IDLE
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
        self._remote_sent = 0
        self._remote_failed = 0
        self._session_config = None
        self._allocated_record_paths = set()
        self._shutdown_request_lock = threading.Lock()
        self._scrcpy_stop_claim = None
        self._interrupted_launch_worker = None
        self._status_update_requested.connect(self._update_status)
        self._remote_queue_status_requested.connect(self._update_remote_queue_status)
        self._stop_completed_requested.connect(self._on_stop_completed)

    # ── 界面构建 ─────────────────────────────────────────────────────────

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addWidget(self._build_mirroring())
        lo.addWidget(self._build_control())
        self._set_session_state(self._SESSION_IDLE)
        lo.addStretch()
        return w

    def _build_mirroring(self) -> QWidget:
        g = self._g("Screen Mirroring")
        gl = QVBoxLayout(g)
        gl.setSpacing(4)

        preset_label = self._label("Preset:")

        self.preset = self._combo(self._PRESET_NAMES)
        saved_preset = self._load("preset")
        self.preset.setCurrentText(saved_preset)
        if self.preset.currentText() != saved_preset:
            self.preset.setCurrentIndex(-1)  # 自定义值不对应任何预设。

        self._status_label = self._status_text("Status: Idle")
        self._remote_queue_label = self._status_text("Queue: 0 queued · 0 sent · 0 failed")
        self._remote_queue_label.setAccessibleName("Remote input queue status")
        self._device_info = self._status_text("")

        self.preset_binding = self._add_responsive_row(
            gl,
            preset_label,
            self.preset,
            spacing=6,
            policies=(WidthPolicy.NATURAL, WidthPolicy.SHRINKABLE),
            modes=(paired_mode("one", 1, 0),),
        )
        self.status_binding = self._add_responsive_row(
            gl,
            self._status_label,
            self._remote_queue_label,
            self._device_info,
            spacing=6,
            policies=(
                WidthPolicy.WRAPPING,
                WidthPolicy.WRAPPING,
                WidthPolicy.WRAPPING,
            ),
            modes=(
                row_major_mode("three", 3, 0, column_stretches=(1, 1, 1)),
                row_major_mode("one", 1, 1, column_stretches=(1,)),
            ),
        )

        settings = [
            ("Size:", "maxsize", self._SIZES),
            ("FPS:", "fps", self._FPS),
            ("Codec:", "codec", self._CODECS),
            ("Buffer:", "buffer", self._BUFFERS),
            ("Bitrate:", "bitrate", self._BITRATES),
            ("Orient:", "orientation", self._ORIENTATIONS),
        ]
        setting_widgets = []
        self._parameter_labels = []
        for lbl, attr, items in settings:
            label = self._label(lbl)
            label.setMinimumWidth(56)
            label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            combo = self._combo(items)
            combo.setCurrentText(self._load(attr))
            setattr(self, attr, combo)
            self._parameter_labels.append(label)
            setting_widgets.extend((label, combo))
        self.parameter_binding = self._add_responsive_row(
            gl,
            *setting_widgets,
            spacing=5,
            policies=tuple(
                policy
                for _setting in settings
                for policy in (WidthPolicy.NATURAL, WidthPolicy.SHRINKABLE)
            ),
            modes=(
                paired_mode("three", 3, 0),
                paired_mode("two", 2, 1),
                paired_mode("one", 1, 2),
            ),
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
            "Stop",
            "stop-circle.svg",
            "danger",
            tooltip="Stop mirroring (Ctrl+Shift+Return)",
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
        key_specs = [
            ("HOME", "HOME"),
            ("BACK", "BACK"),
            ("RECENT", "RECENTS"),
            ("MENU", "MENU"),
            ("PWR", "POWER"),
            ("SET", "SETTINGS"),
            ("CAM", "CAMERA"),
            ("SRCH", "SEARCH"),
            ("ENTER", "ENTER"),
            ("DEL", "DEL"),
        ]
        for label, code in key_specs:
            self._remote_key_button(label, code, f"Send keyevent {code}")
        self._remote_primary_key_buttons = tuple(self._remote_key_buttons)
        control_modes = (
            row_major_mode("four", 4, 0, column_stretches=(1, 1, 1, 1)),
            row_major_mode("two", 2, 1, column_stretches=(1, 1)),
        )
        self._remote_key_binding = self._add_responsive_row(
            outer,
            *self._remote_primary_key_buttons,
            spacing=2,
            policies=(WidthPolicy.NATURAL,) * len(self._remote_primary_key_buttons),
            modes=control_modes,
        )

        media_specs = [
            ("VOL-", "VOL_DOWN"),
            ("VOL+", "VOL_UP"),
            ("PLAY", "MEDIA_PLAY"),
            ("PREV", "MEDIA_PREV"),
            ("NEXT", "MEDIA_NEXT"),
        ]
        for label, code in media_specs:
            self._remote_key_button(label, code, f"Send keyevent {code}")
        self._remote_media_buttons = tuple(
            self._remote_key_buttons[len(self._remote_primary_key_buttons) :]
        )
        self._remote_media_binding = self._add_responsive_row(
            outer,
            *self._remote_media_buttons,
            spacing=2,
            policies=(WidthPolicy.NATURAL,) * len(self._remote_media_buttons),
            modes=control_modes,
        )

        action_specs = [
            ("Swipe Up", "swipe_up", "Send an upward swipe gesture"),
            ("Swipe Down", "swipe_down", "Send a downward swipe gesture"),
            ("Swipe Left", "swipe_left", "Send a leftward swipe gesture"),
            ("Swipe Right", "swipe_right", "Send a rightward swipe gesture"),
            ("Notif+", "notif_expand", "Expand notifications"),
            ("Notif-", "notif_collapse", "Collapse notifications"),
            ("Portrait", "rotate_portrait", "Rotate portrait"),
            ("Land", "rotate_landscape", "Rotate landscape"),
        ]
        for label, action, tooltip in action_specs:
            self._remote_action_button(label, action, tooltip)
        self._remote_action_binding = self._add_responsive_row(
            outer,
            *self._remote_action_buttons,
            spacing=2,
            policies=(WidthPolicy.NATURAL,) * len(self._remote_action_buttons),
            modes=control_modes,
        )
        self.remote_control_bindings = (
            self._remote_key_binding,
            self._remote_media_binding,
            self._remote_action_binding,
        )

        return g

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
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self).activated.connect(self._stop_scrcpy)
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

    def _load(self, key: str) -> str:
        setting_key = f"scrcpy_{key}"
        return str(
            self._settings.get(
                setting_key,
                SCRCPY_SETTING_DEFAULTS[setting_key],
            )
        )

    def reload_from_settings(self) -> bool:
        """Idle 时幂等重载 scrcpy 设置；活动会话继续使用冻结快照。"""

        if getattr(self, "_session_state", self._SESSION_IDLE) != self._SESSION_IDLE:
            return False
        self._settings = AppSettings.instance()
        was_loading = getattr(self, "_loading", False)
        self._loading = True
        try:
            saved_preset = self._load("preset")
            preset_index = self.preset.findText(saved_preset)
            self.preset.setCurrentIndex(preset_index)
            for key in ("maxsize", "fps", "codec", "buffer", "bitrate", "orientation"):
                getattr(self, key).setCurrentText(self._load(key))
        finally:
            self._loading = was_loading
        self._update_action_states()
        return True

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
            self.record_path.setToolTip("")
            return
        self.record_path.setText("Recording path will be created on Start")
        self.record_path.setToolTip("")

    def _allocate_record_path(self, device: str) -> str:
        """为一次 Start 分配不会与本进程既有会话冲突的录制路径。"""

        save_dir = self._settings.save_directory
        os.makedirs(save_dir, exist_ok=True)
        device_tag = re.sub(r"[^A-Za-z0-9_-]+", "_", device).strip("_") or "device"
        stem = f"scrcpy_{device_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        sequence = 1
        while True:
            suffix = "" if sequence == 1 else f"_{sequence}"
            path = os.path.normpath(os.path.join(save_dir, f"{stem}{suffix}.mp4"))
            key = os.path.normcase(os.path.abspath(path))
            if key not in self._allocated_record_paths and not os.path.exists(path):
                self._allocated_record_paths.add(key)
                return path
            sequence += 1

    def _display_record_path(self, path: str) -> None:
        display_path = path.replace("\\", "/")
        self.record_path.setToolTip(display_path)
        if len(display_path) > 72:
            display_path = f"…/{os.path.basename(display_path)}"
        self.record_path.setText(display_path)

    # ── scrcpy 启停 ─────────────────────────────────────────────────────

    def _start_scrcpy(self):
        if getattr(self, "_session_state", self._SESSION_IDLE) != self._SESSION_IDLE:
            return
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
        if len(devices) != 1:
            self._log("WARNING", "Select exactly one device for Remote")
            self._update_action_states()
            return

        self._set_session_state(self._SESSION_STARTING)
        self._update_status("Checking...", None)
        self._active_device = devices[0]

        if getattr(self, "chk_record", None) is not None and self.chk_record.isChecked():
            self._record_path = self._allocate_record_path(self._active_device)
            self._display_record_path(self._record_path)

        config = self._scrcpy_config(exe, self._active_device)
        self._session_config = config

        worker = ScrcpyLaunchWorker(config, service=self._scrcpy_service)
        worker.log_message.connect(self._log)
        worker.launch_ready.connect(self._on_launch_ready)
        worker.finished.connect(lambda _w=worker: self._on_launch_finished(_w))
        self._launch_worker = worker
        try:
            worker.start()
        except Exception as exc:
            self._launch_worker = None
            self._active_device = None
            self._set_running(False)
            self._update_status("Error", None)
            self._log("ERROR", f"scrcpy preflight worker failed: {type(exc).__name__}")
            worker.deleteLater()

    def _on_launch_ready(self, args: list, device_info: str):
        if getattr(self, "_closing", False):
            return
        if self._launch_worker and self._launch_worker.isInterruptionRequested():
            return
        self._device_info.setText(device_info)
        active_device = getattr(self, "_active_device", None)
        if active_device and device_info:
            self._remote_control.remember_dimensions(active_device, device_info.split("x"))
        self._log("INFO", "Launching scrcpy")
        self._log("DEBUG", f"scrcpy launch plan prepared: argument_count={len(args)}")

        try:
            self._process = self._scrcpy_service.start(
                self._process_key,
                args,
            )
            self._reset_scrcpy_stop_claim()
            self._set_running(True)
            self._update_status("Running", None)
            threading.Thread(target=self._focus_scrcpy_window, daemon=True).start()
            threading.Thread(target=self._warm_remote_input_session, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()
            self._watchdog.start(500)
        except Exception as exc:
            self._log("ERROR", f"scrcpy start failed: {type(exc).__name__}")
            self._active_device = None
            self._set_running(False)
            self._update_status("Error", None)

    def _on_launch_finished(self, worker: ScrcpyLaunchWorker):
        if self._launch_worker is not worker:
            worker.deleteLater()
            return
        interrupted = worker.isInterruptionRequested()
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
                self._update_status("Error", None)

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
            self._update_status("Disconnected", None)
            if rc != 0:
                self._log("WARNING", f"scrcpy exited with code {rc}")

    def _stop_scrcpy(self):
        if getattr(self, "_session_state", None) == self._SESSION_STOPPING:
            return
        if self._launch_worker and self._launch_worker.isRunning():
            self._request_launch_worker_interruption_once(self._launch_worker)
            self._set_session_state(self._SESSION_STOPPING)
            self._update_status("Stopping...", None)
            return
        if not self._process:
            return
        stop_claim = self._claim_scrcpy_stop()
        if stop_claim is None:
            return
        self._watchdog.stop()
        self._set_session_state(self._SESSION_STOPPING)
        self._update_status("Stopping...", None)
        scrcpy_service = self._scrcpy_service
        process_key = self._process_key

        def _do_stop():
            stopped = False
            try:
                scrcpy_service.stop(process_key, timeout=2)
                stopped = not scrcpy_service.is_active(process_key)
                if not stopped:
                    self._release_scrcpy_stop_claim(stop_claim)
            except Exception as exc:
                self._release_scrcpy_stop_claim(stop_claim)
                self._log("ERROR", f"stop failed: {type(exc).__name__}")
            try:
                self._stop_completed_requested.emit(stopped)
            except RuntimeError:
                # 窗口已经开始销毁时不再回写控件状态，关闭监督器继续负责资源清理。
                pass

        try:
            threading.Thread(target=_do_stop, daemon=True).start()
        except Exception:
            self._release_scrcpy_stop_claim(stop_claim)
            raise

    def _on_stop_completed(self, stopped: bool):
        """在 GUI 线程收口停止结果，并避免旧进程尚未退出时提前允许再次启动。"""

        if getattr(self, "_closing", False):
            return
        if stopped:
            self._process = None
            self._active_device = None
            self._set_running(False)
            self._update_status("Idle", None)
            self._log("INFO", "scrcpy stopped")
            return

        process = getattr(self, "_process", None)
        try:
            process_alive = process is not None and process.poll() is None
        except (AttributeError, OSError):
            process_alive = process is not None
        if process_alive:
            self._set_running(True)
            self._watchdog.start(500)
        else:
            self._process = None
            self._active_device = None
            self._set_running(False)
        self._update_status("Stop Failed", None)

    def _set_session_state(self, state: str):
        """统一应用 Idle/Starting/Running/Stopping 对应的按钮可用状态。"""

        if state not in {
            RemotePanel._SESSION_IDLE,
            RemotePanel._SESSION_STARTING,
            RemotePanel._SESSION_RUNNING,
            RemotePanel._SESSION_STOPPING,
        }:
            raise ValueError(f"unsupported Remote session state: {state}")
        self._session_state = state
        running = state == RemotePanel._SESSION_RUNNING
        self._running = running

        btn_start = getattr(self, "btn_start", None)
        btn_stop = getattr(self, "btn_stop", None)
        try:
            selected_devices = self.selected_devices
        except AttributeError:
            selected_devices = None
        can_start = state == RemotePanel._SESSION_IDLE and (
            selected_devices is None or len(selected_devices) == 1
        )
        self._set_button_enabled(btn_start, can_start)
        self._set_button_enabled(
            btn_stop,
            state in {RemotePanel._SESSION_STARTING, RemotePanel._SESSION_RUNNING},
        )
        if selected_devices is None:
            can_control = running
        else:
            can_control = len(selected_devices) == 1
        for button in getattr(self, "_remote_control_buttons", ()):
            self._set_button_enabled(button, can_control)
        locked = state != RemotePanel._SESSION_IDLE
        for control in RemotePanel._startup_configuration_controls(self):
            control.setEnabled(not locked)

    def _startup_configuration_controls(self):
        names = (
            "preset",
            "maxsize",
            "fps",
            "codec",
            "buffer",
            "bitrate",
            "orientation",
            "chk_record",
            "chk_fullscreen",
            "chk_aot",
            "chk_showtouches",
            "chk_stayawake",
            "chk_turnscreenoff",
            "chk_hw_encoder",
            "chk_noplayback",
            "chk_noaudio",
        )
        return tuple(
            control for name in names if (control := getattr(self, name, None)) is not None
        )

    def _update_action_states(self) -> None:
        self._set_session_state(getattr(self, "_session_state", self._SESSION_IDLE))

    def update_action_states(self) -> None:
        """供设备选择协调层刷新 Remote Start 的可用状态。"""

        self._update_action_states()

    def _set_running(self, running: bool):
        RemotePanel._set_session_state(
            self,
            RemotePanel._SESSION_RUNNING if running else RemotePanel._SESSION_IDLE,
        )

    # ── 状态指示 ────────────────────────────────────────────────────────

    def _update_status(self, text: str, color: str | None):
        self._status_label.setStyleSheet("font-weight: bold;")
        self._status_label.setText(f"Status: {text}")

    # ── 按键与输入事件 ──────────────────────────────────────────────────

    def _selected_remote_device(self) -> str | None:
        try:
            devices = self.selected_devices
        except AttributeError:
            devices = []
        if not devices:
            self._log("WARNING", "No device selected")
            return None
        if len(devices) != 1:
            self._log("WARNING", "Select exactly one device for Remote control")
            return None
        return devices[0]

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
                return self._remote_control.perform_action(device, action)
            except Exception as exc:
                self._log("ERROR", f"remote action failed: {type(exc).__name__}")
                raise

        self._submit_remote_input(_run)

    @classmethod
    def _should_ignore_scrcpy_log_line(cls, line: str) -> bool:
        return any(pattern in line for pattern in cls._IGNORED_SCRCPY_LOG_PATTERNS)

    def _submit_remote_input(self, task):
        """遥控输入放入单线程队列，并把队列状态回写到 UI。"""
        executor = getattr(self, "_remote_executor", None)
        if executor is None:
            self._mark_remote_submitted()
            try:
                result = task()
                state = "sent" if self._remote_input_succeeded(result) else "failed"
            except Exception:
                state = "failed"
            if state == "failed":
                self._log("WARNING", "Remote input was not sent")
            self._mark_remote_completed(state)
            return
        self._mark_remote_submitted()

        def _wrapped():
            try:
                service_result = task()
                result = "sent" if self._remote_input_succeeded(service_result) else "failed"
            except Exception as exc:
                result = "failed"
                self._log("ERROR", f"remote input failed: {type(exc).__name__}")
            if result == "failed":
                self._log("WARNING", "Remote input was not sent")
            self._mark_remote_completed(result)

        try:
            executor.submit(_wrapped)
        except RuntimeError as exc:
            self._remote_submitted = max(
                getattr(self, "_remote_completed", 0),
                getattr(self, "_remote_submitted", 0) - 1,
            )
            self._remote_failed = getattr(self, "_remote_failed", 0) + 1
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
        if result == "sent":
            self._remote_sent = getattr(self, "_remote_sent", 0) + 1
        elif result == "failed":
            self._remote_failed = getattr(self, "_remote_failed", 0) + 1
        self._emit_remote_queue_status(
            getattr(self, "_remote_submitted", 0),
            self._remote_completed,
            result,
        )

    @staticmethod
    def _remote_input_succeeded(result) -> bool:
        if isinstance(result, bool):
            return result
        if result is None:
            return False
        success = getattr(result, "success", None)
        if success is not None:
            return bool(success)
        return True

    def _emit_remote_queue_status(self, submitted: int, completed: int, result: str):
        try:
            self._remote_queue_status_requested.emit(submitted, completed, result)
        except RuntimeError:
            # 兼容尚未完成 QObject 初始化的轻量嵌入场景。
            pass

    def _update_remote_queue_status(self, submitted: int, completed: int, result: str):
        queued = max(0, submitted - completed)
        label = getattr(self, "_remote_queue_label", None)
        if label is not None:
            label.setText(
                f"Queue: {queued} queued · {getattr(self, '_remote_sent', 0)} sent · "
                f"{getattr(self, '_remote_failed', 0)} failed"
            )

    def showEvent(self, event):
        self._update_action_states()
        super().showEvent(event)

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
            try:
                self._request_scrcpy_stop_once()
            except Exception:
                # claim 已由 helper 回滚；注册过的 supervisor 仍可重试停止，
                # 其余 executor 与 ADB 会话清理不能被单个服务异常截断。
                pass
        self._active_device = None
        self._running = False
        try:
            self._stop_launch_worker(wait_ms=0)
        except Exception:
            pass
        executor = getattr(self, "_remote_executor", None)
        if executor is not None:
            self._remote_executor = None
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        adb = getattr(self, "_adb", None)
        if (
            not getattr(self, "_shutdown_task_registered", False)
            and adb is not None
            and hasattr(adb, "close_input_sessions")
        ):
            close_input = adb.close_input_sessions
            try:
                threading.Thread(
                    target=close_input,
                    name="adblab-remote-input-shutdown",
                    daemon=True,
                ).start()
            except Exception:
                try:
                    close_input()
                except Exception:
                    pass

    def register_shutdown_task(self, supervisor, *, owner_id: str, task_id: str) -> bool:
        """在界面断开引用前注册 scrcpy、启动 worker 和输入会话清理任务。"""
        worker = getattr(self, "_launch_worker", None)
        adb = getattr(self, "_adb", None)
        close_input = getattr(adb, "close_input_sessions", None)
        scrcpy_service = getattr(self, "_scrcpy_service", None)
        process_key = getattr(self, "_process_key", "")
        process_terminal = threading.Event()

        def process_running(*, raise_errors: bool = False) -> bool:
            if process_terminal.is_set():
                return False
            if scrcpy_service is None or not process_key:
                process_terminal.set()
                return False
            try:
                running = bool(scrcpy_service.is_active(process_key))
            except Exception:
                if raise_errors:
                    raise
                return True
            if not running:
                process_terminal.set()
            return running

        if worker is None and not callable(close_input) and not process_running():
            return False
        self._shutdown_task_registered = True
        input_finished = threading.Event()
        input_started = threading.Event()
        input_error_lock = threading.Lock()
        input_error_type = [""]

        def record_input_error(exc: Exception) -> None:
            with input_error_lock:
                if not input_error_type[0]:
                    input_error_type[0] = type(exc).__name__

        def completion_error_type() -> str:
            with input_error_lock:
                return input_error_type[0]

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
            request_error = None
            if worker_running():
                try:
                    self._request_launch_worker_interruption_once(worker)
                except Exception as exc:
                    request_error = exc
            try:
                should_request_process_stop = process_running(raise_errors=True)
            except Exception as exc:
                should_request_process_stop = True
                if request_error is None:
                    request_error = exc
            if should_request_process_stop:
                try:
                    self._request_scrcpy_stop_once(scrcpy_service, process_key)
                except Exception as exc:
                    if request_error is None:
                        request_error = exc
            if callable(close_input) and not input_started.is_set():
                input_started.set()

                def close_sessions():
                    try:
                        close_input()
                    except Exception as exc:
                        record_input_error(exc)
                        return exc
                    finally:
                        input_finished.set()
                    return None

                try:
                    threading.Thread(
                        target=close_sessions,
                        name="adblab-remote-input-shutdown",
                        daemon=True,
                    ).start()
                except Exception as exc:
                    close_error = close_sessions()
                    if close_error is not None:
                        request_error = close_error
                    elif request_error is None:
                        request_error = exc
            elif not callable(close_input):
                input_finished.set()
            if request_error is not None:
                raise request_error

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
            forced = bool(scrcpy_service.force_stop(process_key, timeout))
            if forced:
                process_terminal.set()
            return forced

        supervisor.register(
            task_id,
            owner_id=owner_id,
            kind="remote_session",
            request_stop=request_stop,
            wait=wait,
            is_running=is_running,
            force_stop=force_stop,
            error_type=completion_error_type,
        )
        return True

    def _stop_launch_worker(self, wait_ms: int = 3000):
        worker = getattr(self, "_launch_worker", None)
        if worker is None:
            return
        self._launch_worker = None
        self._disconnect_launch_worker(worker)
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
                self._request_launch_worker_interruption_once(worker)
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
                self._defer_launch_worker_delete(worker)
        else:
            try:
                self._defer_launch_worker_delete(worker)
            except Exception as exc:
                remember_error(exc)
                if not any(item is worker for item in self._orphaned_launch_workers):
                    self._orphaned_launch_workers.append(worker)

        if first_error is not None:
            raise first_error

    def _shutdown_lifecycle_lock(self):
        """兼容轻量测试实例，并为直接关闭与 supervisor 提供同一把锁。"""

        lock = getattr(self, "_shutdown_request_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._shutdown_request_lock = lock
        return lock

    def _claim_scrcpy_stop(self) -> object | None:
        """原子取得当前 scrcpy 会话的唯一停止所有权。"""

        lock = self._shutdown_lifecycle_lock()
        with lock:
            if getattr(self, "_scrcpy_stop_claim", None) is not None:
                return None
            claim = object()
            self._scrcpy_stop_claim = claim
            return claim

    def _release_scrcpy_stop_claim(self, claim: object) -> bool:
        """仅允许持有者释放自己的停止 token，避免旧会话污染新会话。"""

        lock = self._shutdown_lifecycle_lock()
        with lock:
            if getattr(self, "_scrcpy_stop_claim", None) is not claim:
                return False
            self._scrcpy_stop_claim = None
            return True

    def _reset_scrcpy_stop_claim(self) -> None:
        """在新 scrcpy 进程成功启动后开放该会话的第一次停止请求。"""

        lock = self._shutdown_lifecycle_lock()
        with lock:
            self._scrcpy_stop_claim = None

    def _request_scrcpy_stop_once(self, service=None, process_key: str | None = None) -> bool:
        """为一个 scrcpy 会话只发送一次异步停止请求。"""

        resolved_service = service or getattr(self, "_scrcpy_service", None)
        resolved_key = process_key or getattr(self, "_process_key", "")
        if resolved_service is None or not resolved_key:
            return False
        stop_claim = self._claim_scrcpy_stop()
        if stop_claim is None:
            return False
        try:
            requested = resolved_service.request_stop(resolved_key)
        except Exception:
            self._release_scrcpy_stop_claim(stop_claim)
            raise
        if requested is False:
            try:
                still_active = bool(resolved_service.is_active(resolved_key))
            except Exception:
                still_active = True
            if still_active:
                self._release_scrcpy_stop_claim(stop_claim)
        return True

    def _request_launch_worker_interruption_once(self, worker) -> bool:
        """同一启动 worker 在多条关闭路径中只接收一次中断请求。"""

        if worker is None:
            return False
        lock = self._shutdown_lifecycle_lock()
        with lock:
            if getattr(self, "_interrupted_launch_worker", None) is worker:
                return False
            self._interrupted_launch_worker = worker
        try:
            worker.requestInterruption()
        except Exception:
            with lock:
                if getattr(self, "_interrupted_launch_worker", None) is worker:
                    self._interrupted_launch_worker = None
            raise
        return True

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
        """持有未回收 worker，并在其 GUI 线程中执行有界删除重试。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.get(worker_key)
            if state is None:
                state = {
                    "attempts": 0,
                    "scheduled": False,
                    "exhausted": False,
                    "known_stopped": False,
                    "finished_seen": False,
                }
                cls._launch_worker_reaper_states[worker_key] = state
                if not any(item is worker for item in cls._orphaned_launch_workers):
                    cls._orphaned_launch_workers.append(worker)
                new_registration = True
            else:
                new_registration = False

        if new_registration:
            try:
                worker.setParent(None)
            except Exception:
                pass

            def release_after_finished():
                with cls._launch_worker_reaper_lock:
                    current = cls._launch_worker_reaper_states.get(worker_key)
                    if current is not state:
                        return
                    current["finished_seen"] = True
                    current["known_stopped"] = True
                cls._schedule_launch_worker_delete(worker, restart_exhausted=True)

            try:
                worker.finished.connect(release_after_finished)
            except Exception:
                pass
            else:
                with cls._launch_worker_reaper_lock:
                    current = cls._launch_worker_reaper_states.get(worker_key)
                    if current is state:
                        current["finished_callback"] = release_after_finished

        try:
            running = bool(worker.isRunning())
        except Exception:
            running = None
        if running is False:
            with cls._launch_worker_reaper_lock:
                current = cls._launch_worker_reaper_states.get(worker_key)
                if current is state:
                    current["known_stopped"] = True
            # finished 可能早于回收器连接；已结束线程必须主动进入事件循环重试。
            cls._schedule_launch_worker_delete(worker, restart_exhausted=True)

    @classmethod
    def _schedule_launch_worker_delete(
        cls,
        worker: ScrcpyLaunchWorker,
        *,
        restart_exhausted: bool,
    ) -> None:
        """幂等安排一次删除尝试；真实 QObject 始终回到自身 GUI 线程执行。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.get(worker_key)
            if state is None:
                return
            if restart_exhausted and bool(state["exhausted"]):
                state["attempts"] = 0
                state["exhausted"] = False
            if bool(state["scheduled"]) or bool(state["exhausted"]):
                return
            state["scheduled"] = True

        def callback():
            cls._retry_launch_worker_delete(worker)

        try:
            application = QCoreApplication.instance()
            if application is not None:
                QTimer.singleShot(cls._LAUNCH_WORKER_DELETE_RETRY_MS, application, callback)
            else:
                QTimer.singleShot(cls._LAUNCH_WORKER_DELETE_RETRY_MS, callback)
        except Exception:
            with cls._launch_worker_reaper_lock:
                current = cls._launch_worker_reaper_states.get(worker_key)
                if current is state:
                    current["scheduled"] = False
                    current["exhausted"] = True
            cls._release_stopped_launch_worker(worker)

    @classmethod
    def _retry_launch_worker_delete(cls, worker: ScrcpyLaunchWorker) -> None:
        """执行一次删除尝试，并在固定次数耗尽后进入明确终态。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.get(worker_key)
            if state is None:
                return
            state["scheduled"] = False

        try:
            worker.deleteLater()
        except Exception:
            with cls._launch_worker_reaper_lock:
                current = cls._launch_worker_reaper_states.get(worker_key)
                if current is not state:
                    return
                current["attempts"] = int(current["attempts"]) + 1
                attempts = int(current["attempts"])
                if attempts >= cls._LAUNCH_WORKER_DELETE_RETRY_LIMIT:
                    current["exhausted"] = True
            if attempts < cls._LAUNCH_WORKER_DELETE_RETRY_LIMIT:
                cls._schedule_launch_worker_delete(worker, restart_exhausted=False)
            else:
                # QObject 删除失败不应让已确认停止的 Python 包装对象永久残留；
                # 仍运行或状态未知时则继续保留，等待真实 finished 再开启一轮有限重试。
                cls._release_stopped_launch_worker(worker)
            return

        cls._forget_launch_worker(worker)

    @classmethod
    def _release_stopped_launch_worker(cls, worker: ScrcpyLaunchWorker) -> bool:
        """仅在线程明确停止时释放残余；运行或未知状态继续强引用。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.get(worker_key)
            if state is None:
                return True
            stopped_by_evidence = bool(state["known_stopped"] or state["finished_seen"])
        if stopped_by_evidence:
            cls._forget_launch_worker(worker)
            return True

        try:
            running = bool(worker.isRunning())
        except Exception:
            return False
        if running:
            return False
        with cls._launch_worker_reaper_lock:
            current = cls._launch_worker_reaper_states.get(worker_key)
            if current is state:
                current["known_stopped"] = True
        cls._forget_launch_worker(worker)
        return True

    @classmethod
    def _forget_launch_worker(cls, worker: ScrcpyLaunchWorker) -> None:
        """原子移除指定 worker 的回收状态和进程级强引用。"""

        worker_key = id(worker)
        with cls._launch_worker_reaper_lock:
            state = cls._launch_worker_reaper_states.pop(worker_key, None)
            for index, item in enumerate(cls._orphaned_launch_workers):
                if item is worker:
                    del cls._orphaned_launch_workers[index]
                    break
        finished_callback = None if state is None else state.get("finished_callback")
        if finished_callback is not None:
            try:
                worker.finished.disconnect(finished_callback)
            except Exception:
                pass

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
