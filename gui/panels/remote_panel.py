"""Screen Mirroring & Remote Control tab — scrcpy config, D-Pad, keys, gestures, capture."""

import os
import shutil
import subprocess
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base_panel import BasePanel


class RemotePanel(BasePanel):
    """Screen mirroring + full remote control."""

    _KEYCODE_MAP: dict[str, str] = {
        "HOME": "3",
        "BACK": "4",
        "POWER": "26",
        "RECENTS": "187",
        "MENU": "82",
        "VOL_UP": "24",
        "VOL_DOWN": "25",
        "DPAD_UP": "19",
        "DPAD_DOWN": "20",
        "DPAD_LEFT": "21",
        "DPAD_RIGHT": "22",
        "DPAD_CENTER": "23",
        "ENTER": "66",
        "DEL": "67",
        "APP_SWITCH": "187",
        "NOTIFICATION": "83",
        "SETTINGS": "176",
        "CAMERA": "27",
        "SEARCH": "84",
        "MEDIA_PLAY": "85",
        "MEDIA_NEXT": "87",
        "MEDIA_PREV": "88",
        "CH_UP": "166",
        "CH_DOWN": "167",
    }

    def __init__(self, panel, parent=None):
        super().__init__(panel, parent)
        self._process = None
        self._recording = False
        self._record_path = ""

    # ── UI ───────────────────────────────────────────────────────────────

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)

        lo.addWidget(self._build_mirroring_section())
        lo.addWidget(self._build_remote_section())
        lo.addWidget(self._build_gesture_section())
        lo.addWidget(self._build_capture_section())
        lo.addStretch()
        return w

    def _build_mirroring_section(self) -> QWidget:
        g = self._g("Screen Mirroring")
        cols = QHBoxLayout(g)
        cols.setSpacing(12)

        # ── Left: path + start/stop + options ──
        left = QVBoxLayout()
        left.setSpacing(3)

        rp = QHBoxLayout()
        rp.setSpacing(4)
        self.scrcpy_path = self._in("scrcpy executable path…")
        self.scrcpy_path.setText(shutil.which("scrcpy") or "")
        self.btn_browse = self._b("Browse", "Save_alt.svg")
        rp.addWidget(self.scrcpy_path, 3)
        rp.addWidget(self.btn_browse, 1)
        left.addLayout(rp)

        ra = QHBoxLayout()
        ra.setSpacing(4)
        self.btn_start = self._b("▶ Start", "Restart.svg")
        self.btn_stop = self._b("■ Stop", "Kill_monkey.svg")
        ra.addWidget(self.btn_start, 1)
        ra.addWidget(self.btn_stop, 1)
        left.addLayout(ra)

        ro1 = QHBoxLayout()
        ro1.setSpacing(6)
        self.chk_fullscreen = QCheckBox("Fullscreen")
        self.chk_aot = QCheckBox("Always on Top")
        self.chk_fullscreen.setFont(self._font_sm)
        self.chk_aot.setFont(self._font_sm)
        ro1.addWidget(self.chk_fullscreen)
        ro1.addWidget(self.chk_aot)
        left.addLayout(ro1)

        ro2 = QHBoxLayout()
        ro2.setSpacing(6)
        self.chk_noaudio = QCheckBox("No Audio")
        self.chk_noaudio.setChecked(True)
        self.chk_showtouches = QCheckBox("Show Touches")
        self.chk_noaudio.setFont(self._font_sm)
        self.chk_showtouches.setFont(self._font_sm)
        ro2.addWidget(self.chk_noaudio)
        ro2.addWidget(self.chk_showtouches)
        left.addLayout(ro2)

        cols.addLayout(left, 3)

        # ── Right: video params ──
        right = QVBoxLayout()
        right.setSpacing(3)

        rr1 = QHBoxLayout()
        rr1.setSpacing(4)
        self.preset = self._combo(["Smooth", "Balanced", "High Quality", "Custom"])
        rr1.addWidget(QLabel("Preset:"))
        rr1.addWidget(self.preset, 1)
        right.addLayout(rr1)

        rr2 = QHBoxLayout()
        rr2.setSpacing(4)
        self.maxsize = self._combo(["Default", "480p", "720p", "1080p"])
        self.fps = self._combo(["30", "60", "120"])
        rr2.addWidget(QLabel("Size:"))
        rr2.addWidget(self.maxsize, 1)
        rr2.addWidget(QLabel("FPS:"))
        rr2.addWidget(self.fps, 1)
        right.addLayout(rr2)

        rr3 = QHBoxLayout()
        rr3.setSpacing(4)
        rr3.addWidget(QLabel("Bitrate:"))
        self.bitrate = QSlider(Qt.Horizontal)
        self.bitrate.setRange(1, 50)
        self.bitrate.setValue(8)
        self.bitrate_label = QLabel("8 Mbps")
        self.bitrate_label.setFont(self._font_sm)
        self.bitrate_label.setMinimumWidth(52)
        self.bitrate.valueChanged.connect(lambda v: self.bitrate_label.setText(f"{v} Mbps"))
        rr3.addWidget(self.bitrate, 3)
        rr3.addWidget(self.bitrate_label)
        right.addLayout(rr3)

        rr4 = QHBoxLayout()
        rr4.setSpacing(4)
        rr4.addWidget(QLabel("Extra:"))
        self.extra_flags = self._in("Additional flags...")
        rr4.addWidget(self.extra_flags, 1)
        right.addLayout(rr4)

        cols.addLayout(right, 2)

        return g

    def _build_remote_section(self) -> QWidget:
        g = self._g("Remote Control")
        gl = QHBoxLayout(g)
        gl.setSpacing(8)

        # ── D-Pad (left) ──
        dpad = QWidget()
        dg = QGridLayout(dpad)
        dg.setSpacing(2)

        def _dkey(label: str, code: str) -> QPushButton:
            b = QPushButton(label)
            b.setFont(self._font_sm)
            b.setMinimumSize(36, 36)
            b.setMaximumSize(48, 48)
            b.clicked.connect(lambda: self._send_keyevent(code))
            return b

        dg.addWidget(_dkey("▲", "DPAD_UP"), 0, 1)  # ▲
        dg.addWidget(_dkey("◀", "DPAD_LEFT"), 1, 0)  # ◀
        dg.addWidget(_dkey("●", "DPAD_CENTER"), 1, 1)  # ●
        dg.addWidget(_dkey("▶", "DPAD_RIGHT"), 1, 2)  # ▶
        dg.addWidget(_dkey("▼", "DPAD_DOWN"), 2, 1)  # ▼

        gl.addWidget(dpad)

        # ── Quick Keys grid (right) ──
        qk = QWidget()
        kg = QGridLayout(qk)
        kg.setSpacing(2)

        quick_keys = [
            [("HOME", "HOME"), ("BACK", "BACK"), ("POWER", "POWER"), ("RECENTS", "RECENTS")],
            [("MENU", "MENU"), ("VOL+", "VOL_UP"), ("VOL-", "VOL_DOWN"), ("NOTIF", "NOTIFICATION")],
            [
                ("SETTINGS", "SETTINGS"),
                ("APPS", "APP_SWITCH"),
                ("CAMERA", "CAMERA"),
                ("SEARCH", "SEARCH"),
            ],
            [
                ("▶▸ PLAY", "MEDIA_PLAY"),
                ("⏭ NEXT", "MEDIA_NEXT"),
                ("⏮ PREV", "MEDIA_PREV"),
                ("ENTER", "ENTER"),
            ],
        ]

        for r, row in enumerate(quick_keys):
            for c, (label, code) in enumerate(row):
                b = QPushButton(label)
                b.setFont(self._font_sm)
                b.setMinimumHeight(28)
                b.clicked.connect(lambda _, cd=code: self._send_keyevent(cd))
                kg.addWidget(b, r, c)

        gl.addWidget(qk, 1)

        return g

    def _build_gesture_section(self) -> QWidget:
        g = self._g("Touch Gestures")
        gl = QVBoxLayout(g)
        gl.setSpacing(2)

        # Tap row
        rt = QHBoxLayout()
        rt.setSpacing(4)
        self.tap_x = self._in("X", 70)
        self.tap_y = self._in("Y", 70)
        self.btn_tap = self._b("Tap", "Screenshot.svg")
        rt.addWidget(QLabel("Tap"))
        rt.addWidget(self.tap_x, 1)
        rt.addWidget(self.tap_y, 1)
        rt.addWidget(self.btn_tap, 1)
        gl.addLayout(rt)

        # Swipe row
        rs = QHBoxLayout()
        rs.setSpacing(2)
        self.swipe_x1 = self._in("x1", 48)
        self.swipe_y1 = self._in("y1", 48)
        self.swipe_x2 = self._in("x2", 48)
        self.swipe_y2 = self._in("y2", 48)
        self.swipe_dur = self._in("ms", 48)
        self.swipe_dur.setText("300")
        self.btn_swipe = self._b("Swipe", "Screenshot.svg")
        rs.addWidget(QLabel("Swipe"))
        rs.addWidget(self.swipe_x1, 1)
        rs.addWidget(self.swipe_y1, 1)
        rs.addWidget(QLabel("→"))
        rs.addWidget(self.swipe_x2, 1)
        rs.addWidget(self.swipe_y2, 1)
        rs.addWidget(self.swipe_dur, 1)
        rs.addWidget(self.btn_swipe, 1)
        gl.addLayout(rs)

        # Long press + Drag row
        rd = QHBoxLayout()
        rd.setSpacing(4)
        self.long_x = self._in("X", 48)
        self.long_y = self._in("Y", 48)
        self.long_dur = self._in("ms", 48)
        self.long_dur.setText("1000")
        self.btn_longpress = self._qb("Long Press")
        self.drag_x1 = self._in("x1", 48)
        self.drag_y1 = self._in("y1", 48)
        self.drag_x2 = self._in("x2", 48)
        self.drag_y2 = self._in("y2", 48)
        self.drag_dur = self._in("ms", 48)
        self.drag_dur.setText("300")
        self.btn_drag = self._qb("Drag")
        rd.addWidget(QLabel("Long"))
        rd.addWidget(self.long_x, 1)
        rd.addWidget(self.long_y, 1)
        rd.addWidget(self.long_dur, 1)
        rd.addWidget(self.btn_longpress, 1)
        rd.addWidget(QLabel("Drag"))
        rd.addWidget(self.drag_x1, 1)
        rd.addWidget(self.drag_y1, 1)
        rd.addWidget(self.drag_x2, 1)
        rd.addWidget(self.drag_y2, 1)
        rd.addWidget(self.drag_dur, 1)
        rd.addWidget(self.btn_drag, 1)
        gl.addLayout(rd)

        return g

    def _build_capture_section(self) -> QWidget:
        g = self._g("Capture")
        gl = QHBoxLayout(g)
        gl.setSpacing(4)
        self.btn_screenshot = self._b("Screenshot", "Screenshot.svg")
        self.btn_record = self._b("Record", "Screenshot.svg")
        self.btn_record_stop = self._b("Stop Record", "Kill_monkey.svg")
        gl.addWidget(self.btn_screenshot, 1)
        gl.addWidget(self.btn_record, 1)
        gl.addWidget(self.btn_record_stop, 1)
        gl.addStretch(3)
        return g

    # ── Signals ─────────────────────────────────────────────────────────

    def connect_signals(self):
        self.btn_browse.clicked.connect(self._browse_scrcpy)
        self.btn_start.clicked.connect(self._start_scrcpy)
        self.btn_stop.clicked.connect(self._stop_scrcpy)
        self.preset.currentIndexChanged.connect(self._on_preset_changed)
        self.btn_tap.clicked.connect(lambda: self._input_tap())
        self.btn_swipe.clicked.connect(lambda: self._input_swipe())
        self.btn_longpress.clicked.connect(lambda: self._input_longpress())
        self.btn_drag.clicked.connect(lambda: self._input_drag())
        self.btn_screenshot.clicked.connect(self._screenshot)
        self.btn_record.clicked.connect(self._toggle_record)
        self.btn_record_stop.clicked.connect(self._stop_record)

    # ── scrcpy ──────────────────────────────────────────────────────────

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
            self.extra_flags.setText(p["extra"])

    def _browse_scrcpy(self):
        path, _ = QFileDialog.getOpenFileName(None, "Select scrcpy executable")
        if path:
            self.scrcpy_path.setText(path)

    def _start_scrcpy(self):
        exe = self.scrcpy_path.text().strip()
        if not exe:
            self._log("WARNING", "scrcpy path not set")
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
        extra = self.extra_flags.text().strip()
        if extra:
            args += extra.split()

        try:
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._process = subprocess.Popen(args, creationflags=cf)
            self._log("INFO", f"scrcpy started on {devices[0]}")
        except Exception as e:
            self._log("ERROR", f"scrcpy start failed: {e}")

    def _stop_scrcpy(self):
        if self._process:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                self._process = None
                self._log("INFO", "scrcpy stopped")
            except Exception as e:
                self._log("ERROR", f"Failed to stop scrcpy: {e}")

    # ── Key Events ─────────────────────────────────────────────────────

    def _send_keyevent(self, key_name: str):
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        code = self._KEYCODE_MAP.get(key_name, "")
        if code:
            subprocess.run(
                ["adb", "-s", devices[0], "shell", "input", "keyevent", code],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self._log("INFO", f"Key sent: {key_name} ({code})")

    # ── Touch Gestures ─────────────────────────────────────────────────

    def _input_tap(self):
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        x = self.tap_x.text() or "0"
        y = self.tap_y.text() or "0"
        self._run_adb_input(f"tap {x} {y}")
        self._log("INFO", f"Tap ({x},{y})")

    def _input_swipe(self):
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        x1 = self.swipe_x1.text() or "0"
        y1 = self.swipe_y1.text() or "0"
        x2 = self.swipe_x2.text() or "0"
        y2 = self.swipe_y2.text() or "0"
        dur = self.swipe_dur.text() or "300"
        self._run_adb_input(f"swipe {x1} {y1} {x2} {y2} {dur}")
        self._log("INFO", f"Swipe ({x1},{y1}) -> ({x2},{y2})")

    def _input_longpress(self):
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        x = self.long_x.text() or "0"
        y = self.long_y.text() or "0"
        dur = self.long_dur.text() or "1000"
        self._run_adb_input(f"swipe {x} {y} {x} {y} {dur}")
        self._log("INFO", f"Long press ({x},{y}) {dur}ms")

    def _input_drag(self):
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        x1 = self.drag_x1.text() or "0"
        y1 = self.drag_y1.text() or "0"
        x2 = self.drag_x2.text() or "0"
        y2 = self.drag_y2.text() or "0"
        dur = self.drag_dur.text() or "300"
        self._run_adb_input(f"draganddrop {x1} {y1} {x2} {y2} {dur}")
        self._log("INFO", f"Drag ({x1},{y1}) -> ({x2},{y2})")

    def _run_adb_input(self, cmd: str):
        devices = self.selected_devices
        if not devices:
            return
        subprocess.run(
            ["adb", "-s", devices[0], "shell", "input"] + cmd.split(),
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

    # ── Capture ─────────────────────────────────────────────────────────

    def _screenshot(self):
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        ts = int(time.time())
        remote = f"/sdcard/scrcpy_ss_{ts}.png"
        local = os.path.join(self._get_screenshot_dir(), f"scrcpy_ss_{ts}.png")
        subprocess.run(
            ["adb", "-s", devices[0], "shell", "screencap", "-p", remote],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        subprocess.run(
            ["adb", "-s", devices[0], "pull", remote, local],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        subprocess.run(
            ["adb", "-s", devices[0], "shell", "rm", remote],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._log("INFO", f"Screenshot saved: {local}")

    def _toggle_record(self):
        devices = self.selected_devices
        if not devices:
            self._log("WARNING", "No device selected")
            return
        ts = int(time.time())
        remote = f"/sdcard/scrcpy_rec_{ts}.mp4"
        subprocess.run(
            ["adb", "-s", devices[0], "shell", "screenrecord", "--time-limit", "180", remote],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._recording = True
        self._record_path = remote
        self._log("INFO", f"Recording started (background): {remote}")

    def _stop_record(self):
        if not self._recording:
            self._log("WARNING", "Not recording")
            return
        devices = self.selected_devices
        if not devices:
            return
        local = os.path.join(self._get_screenshot_dir(), f"scrcpy_rec_{int(time.time())}.mp4")
        subprocess.run(
            ["adb", "-s", devices[0], "pull", self._record_path, local],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        subprocess.run(
            ["adb", "-s", devices[0], "shell", "rm", self._record_path],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        self._recording = False
        self._log("INFO", f"Recording saved: {local}")

    # ── Helpers ─────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        self.signals.log_message.emit(level, msg)
