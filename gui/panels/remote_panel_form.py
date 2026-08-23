"""提供 Remote 面板的表单构建与 scrcpy 设置持久化。"""

import os
import re
from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QVBoxLayout, QWidget

from core.settings_manager import SCRCPY_SETTING_DEFAULTS, AppSettings
from gui.widgets.responsive_layout import (
    GridMode,
    GridPlacement,
    WidthPolicy,
    span_tail_mode,
)


class RemotePanelForm:
    """组合进 RemotePanel 的表单控制器，通过 ``self._frame`` 访问面板。"""

    def __init__(self, frame):
        self._frame = frame

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addWidget(self._frame._build_mirroring())
        lo.addWidget(self._frame._build_control())
        self._frame._set_session_state(self._frame._SESSION_IDLE)
        lo.addStretch()
        return w

    def _build_mirroring(self) -> QWidget:
        g = self._frame._g("Screen Mirroring")
        gl = QVBoxLayout(g)
        gl.setSpacing(4)

        preset_label = self._frame._label("Preset:")
        preset_label.setMinimumWidth(56)
        preset_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        preset_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._frame.preset = self._frame._combo(self._frame._PRESET_NAMES)
        saved_preset = self._frame._load("preset")
        self._frame.preset.setCurrentText(saved_preset)
        if self._frame.preset.currentText() != saved_preset:
            self._frame.preset.setCurrentIndex(-1)  # 自定义值不对应任何预设。

        self._frame._status_label = self._frame._status_text("Status: Idle")
        self._frame._remote_queue_label = self._frame._status_text(
            "Queue: 0 queued · 0 sent · 0 failed"
        )
        self._frame._remote_queue_label.setAccessibleName("Remote input queue status")
        self._frame._device_info = self._frame._status_text("")

        settings = [
            ("Size:", "maxsize", self._frame._SIZES),
            ("FPS:", "fps", self._frame._FPS),
            ("Codec:", "codec", self._frame._CODECS),
            ("Buffer:", "buffer", self._frame._BUFFERS),
            ("Bitrate:", "bitrate", self._frame._BITRATES),
            ("Orient:", "orientation", self._frame._ORIENTATIONS),
        ]
        setting_widgets = []
        self._frame._parameter_labels = []
        for lbl, attr, items in settings:
            label = self._frame._label(lbl)
            label.setMinimumWidth(56)
            label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            combo = self._frame._combo(items)
            combo.setCurrentText(self._frame._load(attr))
            setattr(self._frame, attr, combo)
            self._frame._parameter_labels.append(label)
            setting_widgets.extend((label, combo))
        self._frame.orientation.setToolTip("Lock orientation (0=auto)")

        # Preset、Status、Queue 与六个参数必须共享同一个响应式网格。
        # 分属两个 binding 时，上下两行会各自计算列宽和断点（尤其 medium
        # 宽度下一个是 6 列、另一个是 4 列），导致三组状态与下方选项错位。
        mirroring_widgets = (
            preset_label,
            self._frame.preset,
            *setting_widgets,
            self._frame._status_label,
            self._frame._remote_queue_label,
            self._frame._device_info,
        )
        mirroring_policies = (
            WidthPolicy.NATURAL,      # Preset 标签
            WidthPolicy.SHRINKABLE,   # Preset 下拉
            *tuple(
                policy
                for _setting in settings
                for policy in (WidthPolicy.NATURAL, WidthPolicy.SHRINKABLE)
            ),
            WidthPolicy.WRAPPING,     # Status
            WidthPolicy.WRAPPING,     # Queue
            WidthPolicy.WRAPPING,     # Device info
        )
        # 顺序：0 Preset 标签、1 Preset 下拉、2..13 六组参数、14 Status、
        # 15 Queue、16 Device info。状态标签放在最后可避免 _link_form_labels
        # 把 Status/Queue 误绑到参数下拉框。
        mirroring_modes = (
            GridMode(
                "three",
                6,
                0,
                placements=(
                    GridPlacement(0, 0, 0),
                    GridPlacement(1, 0, 1),
                    GridPlacement(14, 0, 2, column_span=2),
                    GridPlacement(15, 0, 4, column_span=2),
                    GridPlacement(16, 1, 0, column_span=6),
                    GridPlacement(2, 2, 0),
                    GridPlacement(3, 2, 1),
                    GridPlacement(4, 2, 2),
                    GridPlacement(5, 2, 3),
                    GridPlacement(6, 2, 4),
                    GridPlacement(7, 2, 5),
                    GridPlacement(8, 3, 0),
                    GridPlacement(9, 3, 1),
                    GridPlacement(10, 3, 2),
                    GridPlacement(11, 3, 3),
                    GridPlacement(12, 3, 4),
                    GridPlacement(13, 3, 5),
                ),
                column_stretches=(0, 1, 0, 1, 0, 1),
            ),
            GridMode(
                "two",
                4,
                1,
                placements=(
                    GridPlacement(0, 0, 0),
                    GridPlacement(1, 0, 1),
                    GridPlacement(14, 0, 2, column_span=2),
                    GridPlacement(15, 1, 0, column_span=2),
                    GridPlacement(16, 1, 2, column_span=2),
                    GridPlacement(2, 2, 0),
                    GridPlacement(3, 2, 1),
                    GridPlacement(4, 2, 2),
                    GridPlacement(5, 2, 3),
                    GridPlacement(6, 3, 0),
                    GridPlacement(7, 3, 1),
                    GridPlacement(8, 3, 2),
                    GridPlacement(9, 3, 3),
                    GridPlacement(10, 4, 0),
                    GridPlacement(11, 4, 1),
                    GridPlacement(12, 4, 2),
                    GridPlacement(13, 4, 3),
                ),
                column_stretches=(0, 1, 0, 1),
            ),
            GridMode(
                "one",
                2,
                2,
                placements=(
                    GridPlacement(0, 0, 0),
                    GridPlacement(1, 0, 1),
                    GridPlacement(14, 1, 0, column_span=2),
                    GridPlacement(15, 2, 0, column_span=2),
                    GridPlacement(16, 3, 0, column_span=2),
                    GridPlacement(2, 4, 0),
                    GridPlacement(3, 4, 1),
                    GridPlacement(4, 5, 0),
                    GridPlacement(5, 5, 1),
                    GridPlacement(6, 6, 0),
                    GridPlacement(7, 6, 1),
                    GridPlacement(8, 7, 0),
                    GridPlacement(9, 7, 1),
                    GridPlacement(10, 8, 0),
                    GridPlacement(11, 8, 1),
                    GridPlacement(12, 9, 0),
                    GridPlacement(13, 9, 1),
                ),
                column_stretches=(0, 1),
            ),
        )
        self._frame.mirroring_binding = self._frame._add_responsive_row(
            gl,
            *mirroring_widgets,
            spacing=6,
            policies=mirroring_policies,
            modes=mirroring_modes,
        )
        # 保留旧属性名，让表单状态与参数绑定指向同一份布局计划。
        self._frame.status_binding = self._frame.mirroring_binding
        self._frame.parameter_binding = self._frame.mirroring_binding
        self._frame.preset_binding = self._frame.mirroring_binding
        self._frame.chk_record = self._frame._create_checkbox("Record")
        self._frame.chk_record.setToolTip("Record mirroring to file")
        self._frame.chk_record.toggled.connect(self._frame._on_record_toggled)
        self._frame.record_path = self._frame._status_text("")
        # 记录路径是状态提示，禁止换行且不参与最小宽度计算，避免文本出现时挤压其它按钮。
        self._frame.record_path.setWordWrap(False)
        self._frame.record_path.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._frame.record_path.setMinimumWidth(0)
        self._frame._add_responsive_row(
            gl,
            (self._frame.chk_record, 1),
            (self._frame.record_path, 3),
            spacing=8,
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )

        self._frame.chk_fullscreen = self._frame._create_checkbox("Fullscreen")
        self._frame.chk_fullscreen.setToolTip("Launch in fullscreen mode")
        self._frame.chk_aot = self._frame._create_checkbox("Pin Top")
        self._frame.chk_aot.setToolTip("Keep window above all others")
        self._frame.chk_showtouches = self._frame._create_checkbox("Touches")
        self._frame.chk_showtouches.setToolTip("Visualize touch points on screen")
        self._frame.chk_stayawake = self._frame._create_checkbox("Awake")
        self._frame.chk_stayawake.setToolTip("Keep device screen on while mirroring")
        self._frame._add_responsive_row(
            gl,
            self._frame.chk_fullscreen,
            self._frame.chk_aot,
            self._frame.chk_showtouches,
            self._frame.chk_stayawake,
            spacing=8,
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )

        self._frame.chk_turnscreenoff = self._frame._create_checkbox("Screen Off")
        self._frame.chk_turnscreenoff.setToolTip("Turn off device screen on connect")
        self._frame.chk_hw_encoder = self._frame._create_checkbox("HW Enc")
        self._frame.chk_hw_encoder.setToolTip("Force hardware encoder (may cause stutter)")
        self._frame.chk_noplayback = self._frame._create_checkbox("No Window")
        self._frame.chk_noplayback.setToolTip("Record only, no display window")
        self._frame.chk_noaudio = self._frame._create_checkbox("No Audio")
        self._frame.chk_noaudio.setChecked(True)
        self._frame.chk_noaudio.setToolTip("Disable audio forwarding")
        self._frame._add_responsive_row(
            gl,
            self._frame.chk_turnscreenoff,
            self._frame.chk_hw_encoder,
            self._frame.chk_noplayback,
            self._frame.chk_noaudio,
            spacing=8,
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )

        self._frame.btn_start = self._frame._b(
            "Start", "monitor-play.svg", "accent", tooltip="Start mirroring (Ctrl+Enter)"
        )
        self._frame.btn_start.setMinimumHeight(32)
        self._frame.btn_start.setIconSize(QSize(16, 16))
        self._frame.btn_stop = self._frame._b(
            "Stop",
            "stop-circle.svg",
            "danger",
            tooltip="Stop mirroring (Ctrl+Shift+Return)",
        )
        self._frame.btn_stop.setMinimumHeight(32)
        self._frame.btn_stop.setIconSize(QSize(16, 16))
        self._frame.btn_stop.setEnabled(False)
        self._frame._add_responsive_row(
            gl,
            self._frame.btn_start,
            self._frame.btn_stop,
            spacing=6,
            compact_columns=2,
            medium_columns=2,
            wide_columns=2,
        )

        return g

    def _create_checkbox(self, text: str) -> QCheckBox:
        return self._frame._checkbox(text)

    def _build_control(self) -> QWidget:
        g = self._frame._g("Remote Control")
        outer = QVBoxLayout(g)
        outer.setSpacing(6)
        self._frame._remote_control_buttons = []
        self._frame._remote_key_buttons = []
        self._frame._remote_action_buttons = []

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
            self._frame._remote_key_button(label, code, f"Send keyevent {code}")
        self._frame._remote_primary_key_buttons = tuple(self._frame._remote_key_buttons)
        control_modes = (
            span_tail_mode("four", 4, 0, column_stretches=(1, 1, 1, 1)),
            span_tail_mode("two", 2, 1, column_stretches=(1, 1)),
        )
        self._frame._remote_key_binding = self._frame._add_responsive_row(
            outer,
            *self._frame._remote_primary_key_buttons,
            spacing=2,
            policies=(WidthPolicy.NATURAL,) * len(self._frame._remote_primary_key_buttons),
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
            self._frame._remote_key_button(label, code, f"Send keyevent {code}")
        self._frame._remote_media_buttons = tuple(
            self._frame._remote_key_buttons[len(self._frame._remote_primary_key_buttons) :]
        )
        self._frame._remote_media_binding = self._frame._add_responsive_row(
            outer,
            *self._frame._remote_media_buttons,
            spacing=2,
            policies=(WidthPolicy.NATURAL,) * len(self._frame._remote_media_buttons),
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
            self._frame._remote_action_button(label, action, tooltip)
        self._frame._remote_action_binding = self._frame._add_responsive_row(
            outer,
            *self._frame._remote_action_buttons,
            spacing=2,
            policies=(WidthPolicy.NATURAL,) * len(self._frame._remote_action_buttons),
            modes=control_modes,
        )
        self._frame.remote_control_bindings = (
            self._frame._remote_key_binding,
            self._frame._remote_media_binding,
            self._frame._remote_action_binding,
        )

        return g

    def _remote_key_button(self, label: str, code: str, tooltip: str):
        b = self._frame._b(label, self._frame._KEY_ICONS.get(code, "keyboard.svg"), tooltip=tooltip)
        b.setProperty("remoteKey", code)
        b.setFont(self._frame._font_sm)
        b.setIconSize(QSize(13, 13))
        b.setMinimumHeight(28)
        b.setMinimumWidth(56)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.clicked.connect(lambda _, cd=code: self._frame._send_keyevent(cd))
        self._frame._remote_control_buttons.append(b)
        self._frame._remote_key_buttons.append(b)
        return b

    def _remote_action_button(self, label: str, action: str, tooltip: str):
        b = self._frame._b(
            label, self._frame._ACTION_ICONS.get(action, "keyboard.svg"), tooltip=tooltip
        )
        b.setProperty("remoteAction", action)
        b.setFont(self._frame._font_sm)
        b.setIconSize(QSize(13, 13))
        b.setMinimumHeight(28)
        b.setMinimumWidth(76)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.clicked.connect(lambda _, act=action: self._frame._send_remote_action(act))
        self._frame._remote_control_buttons.append(b)
        self._frame._remote_action_buttons.append(b)
        return b

    # ── 设置持久化 ──────────────────────────────────────────────────────

    def _on_custom_setting_changed(self, _value):
        """任一独立参数变化后取消预设选择并保存为自定义配置。"""
        if getattr(self._frame, "_loading", False):
            return
        self._frame.preset.blockSignals(True)
        self._frame.preset.setCurrentIndex(-1)
        self._frame.preset.blockSignals(False)
        self._frame._save_all()

    def _save(self, key: str, value: str):
        if getattr(self._frame, "_loading", False):
            return
        self._frame._settings.set(f"scrcpy_{key}", value)

    def _save_all(self):
        p = self._frame.preset.currentText()
        self._frame._settings.set("scrcpy_preset", p if p else "Custom")
        for k in ("maxsize", "fps", "codec", "buffer", "bitrate", "orientation"):
            self._frame._settings.set(f"scrcpy_{k}", getattr(self._frame, k).currentText())

    def _load(self, key: str) -> str:
        setting_key = f"scrcpy_{key}"
        return str(
            self._frame._settings.get(
                setting_key,
                SCRCPY_SETTING_DEFAULTS[setting_key],
            )
        )

    def reload_from_settings(self) -> bool:
        """Idle 时幂等重载 scrcpy 设置；活动会话继续使用冻结快照。"""

        if (
            getattr(self._frame, "_session_state", self._frame._SESSION_IDLE)
            != self._frame._SESSION_IDLE
        ):
            return False
        self._frame._settings = AppSettings.instance()
        was_loading = getattr(self._frame, "_loading", False)
        self._frame._loading = True
        try:
            saved_preset = self._frame._load("preset")
            preset_index = self._frame.preset.findText(saved_preset)
            self._frame.preset.setCurrentIndex(preset_index)
            for key in ("maxsize", "fps", "codec", "buffer", "bitrate", "orientation"):
                getattr(self._frame, key).setCurrentText(self._frame._load(key))
        finally:
            self._frame._loading = was_loading
        self._frame._update_action_states()
        return True

    # ── scrcpy 预设 ─────────────────────────────────────────────────────

    def _on_preset_changed(self, idx: int):
        if idx in self._frame._PRESETS:
            was_loading = getattr(self._frame, "_loading", False)
            self._frame._loading = True
            p = self._frame._PRESETS[idx]
            self._frame.maxsize.setCurrentText(p["maxsize"])
            self._frame.fps.setCurrentText(p["fps"])
            self._frame.bitrate.setCurrentText(p["bitrate"])
            self._frame.codec.setCurrentText(p["codec"])
            self._frame.buffer.setCurrentText(p["buffer"])
            self._frame._loading = was_loading
            if not was_loading:
                self._frame._save_all()

    # ── 录制开关 ────────────────────────────────────────────────────────

    def _on_record_toggled(self, checked: bool):
        if not checked:
            self._frame.record_path.setText("")
            self._frame.record_path.setToolTip("")
            return
        self._frame.record_path.setText("Recording path will be created on Start")
        self._frame.record_path.setToolTip("")

    def _allocate_record_path(self, device: str) -> str:
        """为一次 Start 分配不会与本进程既有会话冲突的录制路径。"""

        save_dir = self._frame._settings.save_directory
        os.makedirs(save_dir, exist_ok=True)
        device_tag = re.sub(r"[^A-Za-z0-9_-]+", "_", device).strip("_") or "device"
        stem = f"scrcpy_{device_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        sequence = 1
        while True:
            suffix = "" if sequence == 1 else f"_{sequence}"
            path = os.path.normpath(os.path.join(save_dir, f"{stem}{suffix}.mp4"))
            key = os.path.normcase(os.path.abspath(path))
            if key not in self._frame._allocated_record_paths and not os.path.exists(path):
                self._frame._allocated_record_paths.add(key)
                return path
            sequence += 1

    def _display_record_path(self, path: str) -> None:
        display_path = path.replace("\\", "/")
        self._frame.record_path.setToolTip(display_path)
        if len(display_path) > 72:
            display_path = f"…/{os.path.basename(display_path)}"
        self._frame.record_path.setText(display_path)

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
            control for name in names if (control := getattr(self._frame, name, None)) is not None
        )
