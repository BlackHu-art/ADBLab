"""Screen Mirroring & Remote Control tab -- scrcpy launcher, D-Pad, quick keys."""

import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base_panel import BasePanel
from utils.resource_path import resource_path


def _bundled_scrcpy() -> str:
    return resource_path(os.path.join("scrcpy-win64-v3.3.1", "scrcpy.exe"))


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

    def __init__(self, panel, parent=None):
        super().__init__(panel, parent)
        self._process = None

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

        # row 1: preset + start/stop
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        r1.addWidget(QLabel("Preset"))
        self.preset = self._combo(["Smooth", "Balanced", "High Quality", "Custom"])
        r1.addWidget(self.preset, 1)
        r1.addSpacing(12)
        r1.addWidget(QLabel("Size"))
        self.maxsize = self._combo(["Default", "480p", "720p", "1080p"])
        r1.addWidget(self.maxsize, 1)
        r1.addWidget(QLabel("FPS"))
        self.fps = self._combo(["30", "60", "120"])
        r1.addWidget(self.fps, 1)
        gl.addLayout(r1)

        # row 2: bitrate
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        r2.addWidget(QLabel("Bitrate"))
        self.bitrate = QSlider(Qt.Horizontal)
        self.bitrate.setRange(1, 50)
        self.bitrate.setValue(8)
        self.bitrate_label = QLabel("8 Mbps")
        self.bitrate_label.setFont(self._font_sm)
        self.bitrate_label.setFixedWidth(52)
        self.bitrate.valueChanged.connect(lambda v: self.bitrate_label.setText(f"{v} Mbps"))
        r2.addWidget(self.bitrate, 3)
        r2.addWidget(self.bitrate_label)
        gl.addLayout(r2)

        # row 3: checkboxes
        r3 = QHBoxLayout()
        r3.setSpacing(10)
        self.chk_fullscreen = QCheckBox("Fullscreen")
        self.chk_aot = QCheckBox("Always on Top")
        self.chk_noaudio = QCheckBox("No Audio")
        self.chk_noaudio.setChecked(True)
        self.chk_showtouches = QCheckBox("Show Touches")
        for cb in (self.chk_fullscreen, self.chk_aot, self.chk_noaudio, self.chk_showtouches):
            cb.setFont(self._font_sm)
            r3.addWidget(cb)
        r3.addStretch()
        gl.addLayout(r3)

        # row 4: start / stop
        r4 = QHBoxLayout()
        r4.setSpacing(4)
        self.btn_start = self._b("Start", "Restart.svg")
        self.btn_stop = self._b("Stop", "Kill_monkey.svg")
        r4.addWidget(self.btn_start)
        r4.addWidget(self.btn_stop)
        r4.addStretch()
        gl.addLayout(r4)

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

    # -- signals ----------------------------------------------------------

    def connect_signals(self):
        self.btn_start.clicked.connect(self._start_scrcpy)
        self.btn_stop.clicked.connect(self._stop_scrcpy)
        self.preset.currentIndexChanged.connect(self._on_preset_changed)

    # -- scrcpy -----------------------------------------------------------

    def _on_preset_changed(self, idx: int):
        presets = {
            0: {"maxsize": "Default", "fps": "60", "bitrate": 4, "extra": "--max-fps 60"},
            1: {"maxsize": "720p", "fps": "60", "bitrate": 8, "extra": ""},
            2: {"maxsize": "1080p", "fps": "120", "bitrate": 16, "extra": ""},
        }
        if idx in presets:
            p = presets[idx]
            self.maxsize.setCurrentText(p["maxsize"])
            self.fps.setCurrentText(p["fps"])
            self.bitrate.setValue(p["bitrate"])

    def _start_scrcpy(self):
        exe = _bundled_scrcpy()
        if not os.path.isfile(exe):
            self._log("WARNING", f"scrcpy not found: {exe}")
            return
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return

        args = [exe, "-s", devices[0]]
        size = self.maxsize.currentText()
        if size != "Default":
            args.extend(["-m", size.replace("p", "")])
        args.extend(["--max-fps", self.fps.currentText()])
        args.append(f"--video-bit-rate={self.bitrate.value()}M")
        if self.chk_fullscreen.isChecked():
            args.append("-f")
        if self.chk_aot.isChecked():
            args.append("--always-on-top")
        if self.chk_noaudio.isChecked():
            args.append("--no-audio")
        if self.chk_showtouches.isChecked():
            args.append("--show-touches")

        try:
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._process = subprocess.Popen(args, creationflags=cf)
            self._log("INFO", f"scrcpy started on {devices[0]}")
        except Exception as e:
            self._log("ERROR", f"scrcpy start failed: {e}")

    def _stop_scrcpy(self):
        if not self._process:
            return
        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            self._log("INFO", "scrcpy stopped")
        except Exception as e:
            self._log("ERROR", f"stop failed: {e}")

    # -- key events -------------------------------------------------------

    def _send_keyevent(self, key_name: str):
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        code = self._KEYCODE_MAP.get(key_name, "")
        if not code:
            return
        from utils.adb_resolver import adb_path
        subprocess.run(
            [adb_path(), "-s", devices[0], "shell", "input", "keyevent", code],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._log("INFO", f"Key: {key_name}")

    # -- helpers ----------------------------------------------------------

    def _log(self, level: str, msg: str):
        self.signals.log_message.emit(level, msg)
