"""提供 Remote 面板的表单构建与 scrcpy 设置持久化。"""

import os
import re
from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, InfoBadge

from core.settings_manager import SCRCPY_SETTING_DEFAULTS, AppSettings
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role
from gui.widgets.responsive_layout import (
    RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY,
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
        self._frame._remote_section_groups = []
        self._build_header(lo)
        mirroring = self._frame._build_mirroring()
        control = self._frame._build_control()
        self._frame._remote_section_groups.extend((mirroring, control))
        self._frame._on_theme_changed_remote("")
        self._frame._set_session_state(self._frame._SESSION_IDLE)
        BaseStyles.theme_changed.connect(self._on_theme_changed_remote)
        lo.addWidget(mirroring)
        lo.addWidget(control)
        lo.addStretch()
        return w

    # ── 卡片化页头与分区视觉 ─────────────────────────────────────────────

    def _build_header(self, lo) -> None:
        """构建页头：标题、副标题与设备可用性状态徽标。"""

        header = QWidget()
        header.setObjectName("remoteHeader")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 4)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._frame.remote_title = apply_label_role(
            BodyLabel("远程控制"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.remote_status_badge = InfoBadge("未选择", self._frame)
        self._frame.remote_status_badge.setObjectName("remoteStatusBadge")
        self._frame.remote_status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.remote_status_badge.setFont(self._frame._font_sm)
        # InfoBadge 默认对鼠标透明，会吞掉 tooltip 的悬停事件，这里恢复接收。
        self._frame.remote_status_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )
        self._frame.remote_status_badge.setToolTip("远程控制的设备选择状态")
        title_row.addWidget(self._frame.remote_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.remote_status_badge)
        self._frame.remote_subtitle = apply_label_role(
            BodyLabel("屏幕镜像、设备按键与手势控制"),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        # 页签字体爆发测试断言面板内不存在 UI_SMALL 角色控件（历史不变式），
        # 副标题用 UI 角色 + 次级文字色维持视觉层级。
        self._frame.remote_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self._frame.remote_subtitle)
        lo.addWidget(header)
        self._frame._apply_remote_header_style()

    def _on_theme_changed_remote(self, _name: str) -> None:
        """主题切换时重建页头与分区卡片样式（委托给面板持有者）。"""

        self._frame._on_theme_changed_remote(_name)

    def _build_mirroring(self) -> QWidget:
        g = self._frame._card("屏幕镜像")
        gl = g.viewLayout
        gl.setSpacing(4)

        preset_label = self._frame._label("预设：")
        preset_label.setMinimumWidth(56)
        preset_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        preset_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._frame.preset = self._frame._combo(self._frame._PRESET_NAMES)
        saved_preset = self._frame._load("preset")
        self._frame.preset.setCurrentText(saved_preset)
        if self._frame.preset.currentText() != saved_preset:
            self._frame.preset.setCurrentIndex(-1)  # 自定义值不对应任何预设。
        self._frame.preset.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
        self._frame._refresh_responsive_widget_minimum(self._frame.preset)

        self._frame._status_label = self._frame._status_text("状态：空闲")
        self._frame._remote_queue_label = self._frame._status_text("队列：0")
        self._frame._status_label.setAccessibleName("远程会话状态")
        initial_status = "状态：空闲"
        self._frame._status_label.setToolTip(initial_status)
        self._frame._status_label.setAccessibleDescription(initial_status)
        self._frame._remote_queue_label.setAccessibleName("远程输入队列状态")
        queue_details = "排队：0 · 已发送：0 · 失败：0"
        self._frame._remote_queue_label.setToolTip(queue_details)
        self._frame._remote_queue_label.setAccessibleDescription(queue_details)
        for label in (self._frame._status_label, self._frame._remote_queue_label):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        settings = [
            ("尺寸：", "maxsize", self._frame._SIZES),
            ("FPS:", "fps", self._frame._FPS),
            ("编码：", "codec", self._frame._CODECS),
            ("缓冲：", "buffer", self._frame._BUFFERS),
            ("码率：", "bitrate", self._frame._BITRATES),
            ("方向：", "orientation", self._frame._ORIENTATIONS),
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
            combo.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
            self._frame._refresh_responsive_widget_minimum(combo)
            setattr(self._frame, attr, combo)
            self._frame._parameter_labels.append(label)
            setting_widgets.extend((label, combo))
        self._frame.orientation.setToolTip("锁定屏幕方向（0 为自动）")

        # Preset、Status、Queue 与六个参数必须共享同一个响应式网格。
        # 分属两个 binding 时，上下两行会各自计算列宽和断点（尤其 medium
        # 宽度下一个是 6 列、另一个是 4 列），导致三组状态与下方选项错位。
        mirroring_widgets = (
            preset_label,
            self._frame.preset,
            *setting_widgets,
            self._frame._status_label,
            self._frame._remote_queue_label,
        )
        mirroring_policies = (
            WidthPolicy.NATURAL,  # Preset 标签
            WidthPolicy.SHRINKABLE,  # Preset 下拉
            *tuple(
                policy
                for _setting in settings
                for policy in (WidthPolicy.NATURAL, WidthPolicy.SHRINKABLE)
            ),
            WidthPolicy.WRAPPING,  # Status
            WidthPolicy.WRAPPING,  # Queue
        )
        # 顺序：0 Preset 标签、1 Preset 下拉、2..13 六组参数、14 Status、15 Queue。
        # 状态标签放在最后可避免 _link_form_labels 把它们误绑到参数下拉框。
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
                    GridPlacement(2, 1, 0),
                    GridPlacement(3, 1, 1),
                    GridPlacement(4, 1, 2),
                    GridPlacement(5, 1, 3),
                    GridPlacement(6, 1, 4),
                    GridPlacement(7, 1, 5),
                    GridPlacement(8, 2, 0),
                    GridPlacement(9, 2, 1),
                    GridPlacement(10, 2, 2),
                    GridPlacement(11, 2, 3),
                    GridPlacement(12, 2, 4),
                    GridPlacement(13, 2, 5),
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
                    GridPlacement(2, 3, 0),
                    GridPlacement(3, 3, 1),
                    GridPlacement(4, 4, 0),
                    GridPlacement(5, 4, 1),
                    GridPlacement(6, 5, 0),
                    GridPlacement(7, 5, 1),
                    GridPlacement(8, 6, 0),
                    GridPlacement(9, 6, 1),
                    GridPlacement(10, 7, 0),
                    GridPlacement(11, 7, 1),
                    GridPlacement(12, 8, 0),
                    GridPlacement(13, 8, 1),
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
        self._frame.chk_record = self._frame._create_checkbox("保存录屏")
        self._frame.chk_record.setToolTip("将镜像画面录制到文件")
        self._frame.chk_record.toggled.connect(self._frame._on_record_toggled)
        self._frame.record_path = self._frame._status_text("")
        self._frame.record_path.setAccessibleName("录屏保存路径")
        # 录制路径保持单行，避免长文件名无限拉高启动选项；
        # 完整内容由 tooltip 与辅助描述提供。
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

        self._frame.chk_fullscreen = self._frame._create_checkbox("全屏")
        self._frame.chk_fullscreen.setToolTip("以全屏模式启动")
        self._frame.chk_aot = self._frame._create_checkbox("窗口置顶")
        self._frame.chk_aot.setToolTip("让镜像窗口保持在其他窗口上方")
        self._frame.chk_showtouches = self._frame._create_checkbox("显示触点")
        self._frame.chk_showtouches.setToolTip("在屏幕上显示触摸位置")
        self._frame.chk_stayawake = self._frame._create_checkbox("保持唤醒")
        self._frame.chk_stayawake.setToolTip("镜像期间保持设备屏幕唤醒")
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

        self._frame.chk_turnscreenoff = self._frame._create_checkbox("关闭设备屏幕")
        self._frame.chk_turnscreenoff.setToolTip("连接后关闭设备屏幕")
        self._frame.chk_hw_encoder = self._frame._create_checkbox("硬件编码")
        self._frame.chk_hw_encoder.setToolTip("强制使用硬件编码器（可能造成卡顿）")
        self._frame.chk_noplayback = self._frame._create_checkbox("仅录制")
        self._frame.chk_noplayback.setToolTip("只录制文件，不显示镜像窗口")
        self._frame.chk_noaudio = self._frame._create_checkbox("禁用音频")
        self._frame.chk_noaudio.setChecked(True)
        self._frame.chk_noaudio.setToolTip("不转发设备音频")
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
            "开始镜像", "monitor-play.svg", "accent", tooltip="开始屏幕镜像（Ctrl+Enter）"
        )
        self._frame.btn_start.setMinimumHeight(32)
        self._frame.btn_start.setIconSize(QSize(16, 16))
        self._frame.btn_stop = self._frame._b(
            "停止镜像",
            "stop-circle.svg",
            "danger",
            tooltip="停止屏幕镜像（Ctrl+Shift+Return）",
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
        g = self._frame._card("远程按键与手势")
        outer = g.viewLayout
        outer.setSpacing(6)
        self._frame._remote_control_buttons = []
        self._frame._remote_key_buttons = []
        self._frame._remote_action_buttons = []

        # RECENTS 已覆盖 APP_SWITCH；通知栏操作由下方手势处理。
        key_specs = [
            ("主页", "HOME"),
            ("返回", "BACK"),
            ("最近", "RECENTS"),
            ("菜单", "MENU"),
            ("电源", "POWER"),
            ("设置", "SETTINGS"),
            ("相机", "CAMERA"),
            ("搜索", "SEARCH"),
            ("确认", "ENTER"),
            ("删除", "DEL"),
        ]
        for label, code in key_specs:
            self._frame._remote_key_button(label, code, f"发送按键事件 {code}")
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
            ("播放", "MEDIA_PLAY"),
            ("上一个", "MEDIA_PREV"),
            ("下一个", "MEDIA_NEXT"),
        ]
        for label, code in media_specs:
            self._frame._remote_key_button(label, code, f"发送按键事件 {code}")
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
            ("上滑", "swipe_up", "发送向上滑动手势"),
            ("下滑", "swipe_down", "发送向下滑动手势"),
            ("左滑", "swipe_left", "发送向左滑动手势"),
            ("右滑", "swipe_right", "发送向右滑动手势"),
            ("展开通知", "notif_expand", "展开通知栏"),
            ("收起通知", "notif_collapse", "收起通知栏"),
            ("竖屏", "rotate_portrait", "切换到竖屏方向"),
            ("横屏", "rotate_landscape", "切换到横屏方向"),
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
            self._frame.record_path.setAccessibleDescription("")
            return
        details = "开始镜像时创建录屏文件"
        self._frame.record_path.setText(details)
        self._frame.record_path.setToolTip(details)
        self._frame.record_path.setAccessibleDescription(details)

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
        self._frame.record_path.setAccessibleDescription(display_path)
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
