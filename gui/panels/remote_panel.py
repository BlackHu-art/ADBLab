"""Screen Mirroring & Remote Control tab -- scrcpy launcher, D-Pad, quick keys."""

import os
import re
import subprocess
import threading

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.adb_bridge import ADBBridge
from core.settings_manager import AppSettings
from gui.panels.base_panel import BasePanel
from utils.adb_resolver import CF
from utils.resource_path import resource_path


def _bundled_scrcpy() -> str:
    import platform
    system = platform.system()
    if system == "Windows":
        return resource_path(os.path.join("scrcpy-win64-v3.3.1", "scrcpy.exe"))
    # macOS/Linux: use system scrcpy from PATH
    import shutil
    found = shutil.which("scrcpy")
    return found if found else "scrcpy"


class RemotePanel(BasePanel):
    """Screen mirroring + remote key input."""

    _KEYCODE_MAP: dict[str, str] = {
        "HOME": "3", "BACK": "4", "POWER": "26", "RECENTS": "187", "MENU": "82",
        "VOL_UP": "24", "VOL_DOWN": "25",
        "DPAD_UP": "19", "DPAD_DOWN": "20", "DPAD_LEFT": "21",
        "DPAD_RIGHT": "22", "DPAD_CENTER": "23",
        "ENTER": "66", "DEL": "67", "APP_SWITCH": "187",
        "NOTIFICATION": "83", "SETTINGS": "176", "CAMERA": "27", "SEARCH": "84",
        "MEDIA_PLAY": "85", "MEDIA_NEXT": "87", "MEDIA_PREV": "88",
        "CH_UP": "166", "CH_DOWN": "167",
    }

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
    _AUDIO_SOURCES = ["playback", "mic"]

    def __init__(self, panel, parent=None):
        super().__init__(panel, parent)
        self._process = None
        self._running = False
        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._poll_process)
        self._settings = AppSettings.instance()
        self._adb = ADBBridge()

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
        gl.setSpacing(2)

        # Row 0: Preset + status (B8)
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        r1.addWidget(QLabel("Preset"))
        self.preset = self._combo(self._PRESET_NAMES)
        self.preset.setCurrentText(self._load("preset", "Smooth"))
        self._status_label = QLabel("● Idle")
        self._status_label.setFont(self._font_sm)
        r1.addWidget(self.preset, 1)
        r1.addWidget(self._status_label)
        gl.addLayout(r1)

        # Row 2: Size | FPS
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        r2.addWidget(QLabel("Size"))
        self.maxsize = self._combo(self._SIZES)
        self.maxsize.setCurrentText(self._load("maxsize", "1024"))
        r2.addWidget(self.maxsize, 1)
        r2.addWidget(QLabel("FPS"))
        self.fps = self._combo(self._FPS)
        self.fps.setCurrentText(self._load("fps", "30"))
        r2.addWidget(self.fps, 1)
        gl.addLayout(r2)

        # Row 3: Codec | Buffer
        r3 = QHBoxLayout()
        r3.setSpacing(6)
        r3.addWidget(QLabel("Codec"))
        self.codec = self._combo(self._CODECS)
        self.codec.setCurrentText(self._load("codec", "h264"))
        r3.addWidget(self.codec, 1)
        r3.addWidget(QLabel("Buffer"))
        self.buffer = self._combo(self._BUFFERS)
        self.buffer.setCurrentText(self._load("buffer", "30"))
        r3.addWidget(self.buffer, 1)
        gl.addLayout(r3)

        # Row 4: Bitrate | Orientation (A5)
        r4 = QHBoxLayout()
        r4.setSpacing(6)
        r4.addWidget(QLabel("Bitrate"))
        self.bitrate = self._combo(self._BITRATES)
        self.bitrate.setCurrentText(self._load("bitrate", "4"))
        r4.addWidget(self.bitrate, 1)
        r4.addWidget(QLabel("Orient"))
        self.orientation = self._combo(self._ORIENTATIONS)
        self.orientation.setToolTip("Lock video orientation (0=auto)")
        r4.addWidget(self.orientation, 1)
        gl.addLayout(r4)

        # Row 5: Audio source (B10) + device info (B7)
        r5 = QHBoxLayout()
        r5.setSpacing(6)
        r5.addWidget(QLabel("Audio"))
        self.audio_source = self._combo(self._AUDIO_SOURCES)
        self.audio_source.setToolTip("Audio capture source")
        r5.addWidget(self.audio_source, 1)
        self._device_info = QLabel("")
        self._device_info.setFont(self._font_sm)
        r5.addWidget(self._device_info, 3)
        gl.addLayout(r5)

        # Row 6: Record path (A3/A4)
        r6 = QHBoxLayout()
        r6.setSpacing(6)
        self.chk_record = QCheckBox("Record")
        self.chk_record.setFont(self._font_sm)
        self.chk_record.setToolTip("Record mirroring to file")
        self.chk_record.toggled.connect(self._on_record_toggled)
        r6.addWidget(self.chk_record)
        self.record_path = QLabel("")
        self.record_path.setFont(self._font_sm)
        r6.addWidget(self.record_path, 1)
        self.chk_noplayback = QCheckBox("No Playback")
        self.chk_noplayback.setFont(self._font_sm)
        self.chk_noplayback.setToolTip("Record only, no display window")
        r6.addWidget(self.chk_noplayback)
        gl.addLayout(r6)

        # Row 7: Checkboxes - distributed rows
        r7a = QHBoxLayout()
        r7a.setSpacing(16)
        col1 = QVBoxLayout()
        col1.setSpacing(4)
        col2 = QVBoxLayout()
        col2.setSpacing(4)
        col3 = QVBoxLayout()
        col3.setSpacing(4)
        self.chk_fullscreen = QCheckBox("Fullscreen")
        self.chk_aot = QCheckBox("Always on Top")
        self.chk_stayawake = QCheckBox("Stay Awake")           # A1
        self.chk_turnscreenoff = QCheckBox("Turn Screen Off")  # A2
        self.chk_noaudio = QCheckBox("No Audio")
        self.chk_noaudio.setChecked(True)
        self.chk_showtouches = QCheckBox("Show Touches")
        self.chk_hw_encoder = QCheckBox("HW Encoder")
        self.chk_hw_encoder.setToolTip("Force hardware encoder (may cause stutter on some devices)")
        for cb, col in [(self.chk_fullscreen, col1), (self.chk_aot, col2),
                        (self.chk_stayawake, col1), (self.chk_turnscreenoff, col2),
                        (self.chk_noaudio, col3), (self.chk_showtouches, col3),
                        (self.chk_hw_encoder, col3)]:
            cb.setFont(self._font_sm)
            col.addWidget(cb)
        r7a.addLayout(col1)
        r7a.addLayout(col2)
        r7a.addLayout(col3)
        r7a.addStretch()
        gl.addLayout(r7a)

        # Row 8: Start / Stop
        r8 = QHBoxLayout()
        r8.setSpacing(4)
        self.btn_start = self._b("Start (Ctrl+Enter)", "Restart.svg")
        self.btn_stop = self._b("Stop (Ctrl+Q)", "Kill_monkey.svg")
        self.btn_stop.setEnabled(False)
        r8.addWidget(self.btn_start, 1)
        r8.addWidget(self.btn_stop, 1)
        gl.addLayout(r8)

        return g

    def _build_control(self) -> QWidget:
        g = self._g("Remote Control")
        gl = QHBoxLayout(g)
        gl.setSpacing(8)

        # D-Pad
        dpad = QWidget()
        dg = QGridLayout(dpad)
        dg.setSpacing(2)

        def _dk(label, code):
            b = QPushButton(label)
            b.setFont(self._font_base)
            b.setFixedSize(32, 32)
            b.clicked.connect(lambda _, c=code: self._send_keyevent(c))
            return b

        dg.addWidget(_dk("▲", "DPAD_UP"), 0, 1)
        dg.addWidget(_dk("◀", "DPAD_LEFT"), 1, 0)
        dg.addWidget(_dk("●", "DPAD_CENTER"), 1, 1)
        dg.addWidget(_dk("▶", "DPAD_RIGHT"), 1, 2)
        dg.addWidget(_dk("▼", "DPAD_DOWN"), 2, 1)
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
                b = QPushButton(label)
                b.setFont(self._font_sm)
                b.setFixedHeight(28)
                b.setMinimumWidth(56)
                b.clicked.connect(lambda _, cd=code: self._send_keyevent(cd))
                kg.addWidget(b, r, c)
        gl.addWidget(qk, 1)

        return g

    # -- signals + shortcuts (B9) ----------------------------------------

    def connect_signals(self):
        self.btn_start.clicked.connect(self._start_scrcpy)
        self.btn_stop.clicked.connect(self._stop_scrcpy)
        self.preset.currentIndexChanged.connect(self._on_preset_changed)
        # Save on any change (B6)
        for combo, key in [(self.preset, "preset"), (self.maxsize, "maxsize"),
                           (self.fps, "fps"), (self.codec, "codec"),
                           (self.buffer, "buffer"), (self.bitrate, "bitrate")]:
            combo.currentTextChanged.connect(lambda v, k=key: self._save(k, v))
        # B9: Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._start_scrcpy)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self._stop_scrcpy)

    # -- B6: settings persistence ----------------------------------------

    def _save(self, key: str, value: str):
        self._settings.set(f"scrcpy_{key}", value)

    def _load(self, key: str, default: str) -> str:
        return self._settings.get(f"scrcpy_{key}", default)

    # -- scrcpy presets ---------------------------------------------------

    def _on_preset_changed(self, idx: int):
        if idx in self._PRESETS:
            p = self._PRESETS[idx]
            self.maxsize.setCurrentText(p["maxsize"])
            self.fps.setCurrentText(p["fps"])
            self.bitrate.setCurrentText(p["bitrate"])
            self.codec.setCurrentText(p["codec"])
            self.buffer.setCurrentText(p["buffer"])

    # -- C12: scrcpy version ----------------------------------------------

    def _get_scrcpy_version(self) -> str:
        exe = _bundled_scrcpy()
        if not os.path.isfile(exe):
            return "unknown"
        try:
            r = subprocess.run(
                [exe, "--version"], capture_output=True, text=True,
                creationflags=CF,
                timeout=3,
            )
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", r.stdout)
            return m.group(1) if m else "unknown"
        except Exception:
            return "unknown"

    # -- B7: device screen info -------------------------------------------

    def _fetch_device_info(self, device: str):
        try:
            dims = self._adb.get_dimensions(device_id=device)
            if dims and len(dims) == 2:
                self._device_info.setText(f"{dims[0]}x{dims[1]}")
            else:
                self._device_info.setText("")
        except Exception:
            self._device_info.setText("")

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

    # -- pre-flight check -------------------------------------------------

    def _preflight_check(self, device: str) -> bool:
        import time
        try:
            proc = self._adb.shell("echo ok", device_id=device)
            if proc.stdout.read().decode().strip() != "ok":
                self._log("WARNING", f"Device {device} not responding")
                return False
            # USB speed test: push 1KB of zeros and measure time
            t0 = time.monotonic()
            _sp = subprocess.run(
                [self._adb.path, "-s", device, "shell", "dd if=/dev/zero bs=1024 count=1 2>/dev/null"],
                capture_output=True, text=True, creationflags=CF, timeout=5,
            )
            elapsed = time.monotonic() - t0
            if elapsed > 1.0:
                self._log("WARNING",
                    f"USB speed: {elapsed:.1f}s (slow). Try a different cable or USB 3.0 port")
            else:
                self._log("INFO", f"USB speed: {elapsed*1000:.0f}ms (OK)")
            return True
        except Exception as e:
            self._log("WARNING", f"Pre-flight failed: {e}")
            return False

    def _detect_encoder(self, device: str) -> str | None:
        try:
            proc = self._adb.shell("dumpsys media.codec", device_id=device)
            output = proc.stdout.read().decode(errors="ignore")
            for line in output.splitlines():
                if "OMX" in line and "h264" in line.lower() and "encoder" in line.lower():
                    return line.strip().split()[0]
            for line in output.splitlines():
                if "c2." in line and "h264" in line.lower() and "encoder" in line.lower():
                    return line.strip().split()[0]
        except Exception:
            pass
        return None

    # -- scrcpy start / stop ----------------------------------------------

    def _start_scrcpy(self):
        exe = _bundled_scrcpy()
        if not os.path.isfile(exe):
            self._log("WARNING", f"scrcpy not found: {exe}")
            return
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        device = devices[0]

        # C12: log version
        ver = self._get_scrcpy_version()
        self._log("INFO", f"scrcpy v{ver}")

        # B7: fetch device info
        self._fetch_device_info(device)

        if not self._preflight_check(device):
            self._log("WARNING", "Pre-flight check failed — launching anyway...")

        self._set_running(True)
        self._update_status("Running", "#28A745")

        args = [exe, "-s", device]

        size = self.maxsize.currentText()
        if size != "Default":
            args.extend(["-m", size.replace("p", "")])

        args.extend(["--max-fps", self.fps.currentText()])
        args.append(f"--video-bit-rate={self.bitrate.currentText()}M")

        codec = self.codec.currentText()
        if codec != "h264":
            args.extend(["--video-codec", codec])

        buf = self.buffer.currentText()
        if buf != "0":
            args.append(f"--video-buffer={buf}")

        # A5: Lock orientation
        orient = self.orientation.currentText()
        if orient != "0":
            args.append(f"--lock-video-orientation={orient}")

        # B10: Audio source
        if not self.chk_noaudio.isChecked():
            args.extend(["--audio-source", self.audio_source.currentText()])

        if self.chk_hw_encoder.isChecked():
            encoder = self._detect_encoder(device)
            if encoder:
                args.extend(["--video-encoder", encoder])
                self._log("INFO", f"Using encoder: {encoder}")
            else:
                self._log("WARNING", "No hardware encoder found, using default")

        # Checkbox flags
        if self.chk_fullscreen.isChecked():
            args.append("-f")
        if self.chk_aot.isChecked():
            args.append("--always-on-top")
        if self.chk_noaudio.isChecked():
            args.append("--no-audio")
        if self.chk_showtouches.isChecked():
            args.append("--show-touches")
        if self.chk_stayawake.isChecked():                     # A1
            args.append("--stay-awake")
        if self.chk_turnscreenoff.isChecked():                 # A2
            args.append("--turn-screen-off")

        # A3/A4: Record / No Playback
        if self.chk_record.isChecked() and hasattr(self, "_record_path"):
            args.extend(["--record", self._record_path])
        if self.chk_noplayback.isChecked():
            args.append("--no-playback")
            args.append("--no-window")

        # C13: Print FPS
        args.append("--print-fps")

        self._log("INFO", f"Launching: scrcpy {' '.join(args[2:])}")

        try:
            cf = CF
            self._process = subprocess.Popen(
                args, stderr=subprocess.PIPE, text=True, creationflags=cf,
            )
            threading.Thread(target=self._read_stderr, daemon=True).start()
            self._watchdog.start(500)
        except Exception as e:
            self._log("ERROR", f"scrcpy start failed: {e}")
            self._set_running(False)
            self._update_status("Error", "#DC3545")

    def _read_stderr(self):
        if self._process and self._process.stderr:
            for line in self._process.stderr:
                line = line.strip()
                if not line:
                    continue
                # C13: extract FPS from scrcpy stderr
                m = re.search(r"\[(\d+\.?\d*)\s*fps\]", line)
                if m:
                    self._update_status(f"{m.group(1)} fps", None)
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
        if not self._process:
            return
        self._watchdog.stop()
        proc = self._process
        self._process = None
        self._set_running(False)
        self._update_status("Idle", None)
        def _do_stop():
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
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
        if color:
            self._status_label.setStyleSheet(
                f"color: {color}; font-size: 10px; font-weight: bold;"
            )
        self._status_label.setText(f"● {text}")

    # -- key events -------------------------------------------------------

    def _send_keyevent(self, key_name: str):
        devices = self.selected_devices
        if not devices:
            return
        code = self._KEYCODE_MAP.get(key_name, "")
        if not code:
            return
        self._adb.shell_input(f"keyevent {code}", device_id=devices[0])

    # -- helpers ----------------------------------------------------------

    def _log(self, level: str, msg: str):
        self.signals.log_message.emit(level, msg)
