"""提供 Remote 面板的表单构建与 scrcpy 设置持久化。"""

import os
import re
from datetime import datetime

from PySide6.QtCore import QObject, QSize, Qt, Slot
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, InfoBadge

from core.settings_manager import SCRCPY_SETTING_DEFAULTS, AppSettings
from gui.feedback import report_feedback
from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role
from gui.widgets.category_stack import AdaptiveCategoryStack
from gui.widgets.responsive_layout import (
    RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY,
    GridMode,
    GridPlacement,
    WidthPolicy,
)


class RemotePanelForm(QObject):
    """随表单根控件销毁的控制器，通过 ``self._frame`` 访问 Remote 面板。"""

    def __init__(self, frame):
        super().__init__()
        self._frame = frame

    def build_ui(self) -> QWidget:
        w = QWidget()
        # RemotePanel 是隐藏的协调对象，可能晚于可见表单释放；全局样式信号必须
        # 归属实际视图，Qt 才能在根控件销毁时断连，避免访问已释放的设备与徽标。
        self.setParent(w)
        lo = QVBoxLayout(w)
        lo.setSpacing(10)
        lo.setContentsMargins(0, 0, 0, 0)
        self._frame._remote_section_groups = []
        self._build_header(lo)
        self._frame._feedback_received.connect(self._show_feedback)
        mirroring = self._frame._build_mirroring()
        control = self._frame._build_control()
        self._frame._remote_section_groups.extend((mirroring, control))
        self._frame.category_stack = AdaptiveCategoryStack("remote", w)
        self._frame.category_stack.setObjectName("remoteCategoryStack")
        self._frame.category_stack.add_category(
            "mirroring", tr("远程控制"), (mirroring, control)
        )
        self._frame.category_stack.add_alias("control", "mirroring")
        self._frame.category_stack.current_changed.connect(
            lambda _key: self._frame.apply_responsive_width(0)
        )
        self._frame._on_theme_changed_remote("")
        self._frame._set_session_state(self._frame._SESSION_IDLE)
        BaseStyles.theme_changed.connect(
            self._on_theme_changed_remote,
            Qt.ConnectionType.UniqueConnection,
        )
        lo.addWidget(self._frame.category_stack, 1)
        return w

    # ── 卡片化页头与分区视觉 ─────────────────────────────────────────────

    def _build_header(self, lo) -> None:
        """构建页头：标题、副标题与设备可用性状态徽标。"""

        header = QWidget()
        header.setObjectName("remoteHeader")
        self._frame.panel_header = header
        hl = QVBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 4)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._frame.remote_title = apply_label_role(
            BodyLabel(tr("远程控制")), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.remote_status_badge = InfoBadge(tr("未选择"), self._frame)
        self._frame.remote_status_badge.setObjectName("remoteStatusBadge")
        self._frame.remote_status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.remote_status_badge.setFont(self._frame._font_sm)
        # InfoBadge 默认对鼠标透明，会吞掉 tooltip 的悬停事件，这里恢复接收。
        self._frame.remote_status_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False
        )
        self._frame.remote_status_badge.setToolTip(tr("远程控制的设备选择状态"))
        title_row.addWidget(self._frame.remote_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.remote_status_badge)
        self._frame.remote_subtitle = apply_label_role(
            BodyLabel(tr("屏幕镜像、设备按键与手势控制")),
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

    @Slot()
    def _on_theme_changed_remote(self) -> None:
        """主题切换时重建页头与分区卡片样式（委托给面板持有者）。"""

        self._frame._on_theme_changed_remote(BaseStyles.current_theme())

    def _build_mirroring(self) -> QWidget:
        g = self._frame._card(tr("屏幕镜像"))
        gl = g.viewLayout
        gl.setSpacing(4)

        preset_label = self._frame._label(tr("预设："))
        preset_label.setWordWrap(False)
        preset_label.setMinimumWidth(56)
        preset_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        preset_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._frame.preset = self._frame._combo(self._frame._PRESET_NAMES)
        saved_preset = self._frame._load("preset")
        self._frame.preset.setCurrentIndex(self._frame.preset.findData(saved_preset))
        self._frame.preset.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
        self._frame._refresh_responsive_widget_minimum(self._frame.preset)

        self._frame._status_label = self._frame._status_text(tr("状态：空闲"))
        self._frame._remote_queue_label = self._frame._status_text(tr("队列：0"))
        self._frame._status_label.setAccessibleName(tr("远程会话状态"))
        initial_status = tr("状态：空闲")
        self._frame._status_label.setToolTip(initial_status)
        self._frame._status_label.setAccessibleDescription(initial_status)
        self._frame._remote_queue_label.setAccessibleName(tr("远程输入队列状态"))
        queue_details = tr("排队：0 · 已发送：0 · 失败：0")
        self._frame._remote_queue_label.setToolTip(queue_details)
        self._frame._remote_queue_label.setAccessibleDescription(queue_details)
        for label in (self._frame._status_label, self._frame._remote_queue_label):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        settings = [
            (tr("尺寸："), "maxsize", self._frame._SIZES),
            ("FPS:", "fps", self._frame._FPS),
            (tr("编码："), "codec", self._frame._CODECS),
            (tr("缓冲："), "buffer", self._frame._BUFFERS),
            (tr("码率："), "bitrate", self._frame._BITRATES),
            (tr("方向："), "orientation", self._frame._ORIENTATIONS),
        ]
        setting_widgets = []
        self._frame._parameter_labels = []
        for lbl, attr, items in settings:
            label = self._frame._label(lbl)
            label.setWordWrap(False)
            label.setMinimumWidth(56)
            label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            combo = self._frame._combo(items)
            saved_index = combo.findData(self._frame._load(attr))
            if saved_index >= 0:
                combo.setCurrentIndex(saved_index)
            combo.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
            self._frame._refresh_responsive_widget_minimum(combo)
            setattr(self._frame, attr, combo)
            self._frame._parameter_labels.append(label)
            setting_widgets.extend((label, combo))
        self._frame.orientation.setToolTip(tr("锁定屏幕方向（0 为自动）"))

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
        self._frame.chk_record = self._frame._create_checkbox(tr("保存录屏"))
        self._frame.chk_record.setToolTip(tr("将镜像画面录制到文件"))
        self._frame.chk_record.toggled.connect(self._frame._on_record_toggled)
        self._frame.record_path = self._frame._status_text("")
        self._frame.record_path.setAccessibleName(tr("录屏保存路径"))
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

        self._frame.chk_fullscreen = self._frame._create_checkbox(tr("全屏"))
        self._frame.chk_fullscreen.setToolTip(tr("以全屏模式启动"))
        self._frame.chk_aot = self._frame._create_checkbox(tr("窗口置顶"))
        self._frame.chk_aot.setToolTip(tr("让镜像窗口保持在其他窗口上方"))
        self._frame.chk_showtouches = self._frame._create_checkbox(tr("显示触点"))
        self._frame.chk_showtouches.setToolTip(tr("在屏幕上显示触摸位置"))
        self._frame.chk_stayawake = self._frame._create_checkbox(tr("保持唤醒"))
        self._frame.chk_stayawake.setToolTip(tr("镜像期间保持设备屏幕唤醒"))
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

        self._frame.chk_turnscreenoff = self._frame._create_checkbox(tr("关闭设备屏幕"))
        self._frame.chk_turnscreenoff.setToolTip(tr("连接后关闭设备屏幕"))
        self._frame.chk_hw_encoder = self._frame._create_checkbox(tr("硬件编码"))
        self._frame.chk_hw_encoder.setToolTip(tr("强制使用硬件编码器（可能造成卡顿）"))
        self._frame.chk_noplayback = self._frame._create_checkbox(tr("仅录制"))
        self._frame.chk_noplayback.setToolTip(tr("只录制文件，不显示镜像窗口"))
        self._frame.chk_noaudio = self._frame._create_checkbox(tr("禁用音频"))
        self._frame.chk_noaudio.setChecked(True)
        self._frame.chk_noaudio.setToolTip(tr("不转发设备音频"))
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
            tr("开始镜像"), "monitor-play.svg", "accent", tooltip=tr("开始屏幕镜像（Ctrl+Enter）")
        )
        self._frame.btn_start.setMinimumHeight(32)
        self._frame.btn_start.setIconSize(QSize(16, 16))
        self._frame.btn_stop = self._frame._b(
            tr("停止镜像"),
            "stop-circle.svg",
            "danger",
            tooltip=tr("停止屏幕镜像（Ctrl+Shift+Return）"),
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

        self._frame._session_list = QWidget(g)
        self._frame._session_list.setObjectName("remoteSessionList")
        self._frame._session_list_layout = QVBoxLayout(self._frame._session_list)
        self._frame._session_list_layout.setContentsMargins(0, 4, 0, 0)
        self._frame._session_list_layout.setSpacing(6)
        self._frame._session_rows = {}
        gl.addWidget(self._frame._session_list)
        self._frame._session_list.hide()

        return g

    def refresh_session_rows(self) -> None:
        """各设备使用稳定展示名称，停止与重试入口绑定原设备而非当前选择。"""
        frame = self._frame
        if not hasattr(frame, "_session_rows"):
            return
        states = {
            "preparing": tr("准备中"), "connecting": tr("连接中"), "ready": tr("就绪"),
            "failed": tr("失败"), "stopped": tr("已停止"), "stopping": tr("正在停止…"),
        }
        sessions = getattr(frame, "_device_sessions", {})
        for device, session in sessions.items():
            row = frame._session_rows.get(device)
            if row is None:
                container = QWidget(frame._session_list)
                layout = QHBoxLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(8)
                name = frame._status_text("")
                name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                status = frame._status_text("")
                action = frame._b(
                    tr("停止"), "stop-circle.svg", "normal", tooltip=tr("停止或重试此设备的镜像"),
                )
                action.clicked.connect(
                    lambda _checked=False, target=device: self._session_action(target)
                )
                layout.addWidget(name, 1)
                layout.addWidget(status)
                layout.addWidget(action)
                frame._session_list_layout.addWidget(container)
                row = frame._session_rows[device] = (name, status, action)
            name, status, action = row
            window = frame.panel.window()
            bar = getattr(window, "_global_device_bar", None)
            label = (
                bar.device_label(device) if bar is not None
                else tr("设备 {number}").format(number=list(sessions).index(device) + 1)
            )
            name.setText(label)
            name.setToolTip(label)
            stop_failed = session.resource_owned and session.error_type == "StopFailed"
            text = tr("停止失败") if stop_failed else states[session.state]
            status.setText(text)
            active = session.resource_owned or session.state == "preparing"
            action.setText(tr("停止") if active else tr("重试"))
            action.setEnabled(
                not getattr(frame, "_closing", False)
                and frame._session_state != frame._SESSION_STOPPING
                and not session.stop_inflight
                and (active or device in frame.selected_devices)
            )
            action.setAccessibleName(
                tr("{device}：{action}").format(device=label, action=action.text())
            )
        frame._session_list.setVisible(bool(sessions))

    def _session_action(self, device: str) -> None:
        session = getattr(self._frame, "_device_sessions", {}).get(device)
        if session is None:
            return
        if session.resource_owned or session.state == "preparing":
            self._frame._stop_device_scrcpy(device)
        else:
            self._frame._retry_device_scrcpy(device)

    @Slot(str, str)  # type: ignore[reportArgumentType]  # PySide6 Slot 的桩类型未包含 self 参数。
    def _show_feedback(self, level: str, message: str) -> None:
        """表单所属线程转交任务记录；显式异常和完成使用 Toast，过程不刷屏。"""
        from typing import cast

        from gui.notifications import ToastLevel

        severity = level.lower()
        if severity not in {"info", "success", "warning", "error"}:
            severity = "error" if severity == "critical" else "info"
        host = self.parent()
        if not isinstance(host, QWidget):
            return
        report_feedback(
            host, "remote", tr("远程控制"), message,
            level=cast(ToastLevel, severity), notify=severity != "info",
            target=str(getattr(self._frame, "_active_device", "") or ""),
        )

    def _create_checkbox(self, text: str) -> QCheckBox:
        return self._frame._checkbox(text)

    def _build_control(self) -> QWidget:
        g = self._frame._card(tr("远程按键与手势"))
        outer = g.viewLayout
        outer.setSpacing(6)
        # 页面有额外高度时仍按自然行高排列，避免空白被分配到按键和媒体组内部。
        outer.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._frame._remote_control_buttons = []
        self._frame._remote_key_buttons = []
        self._frame._remote_action_buttons = []

        # RECENTS 已覆盖 APP_SWITCH；通知栏操作由下方手势处理。
        key_specs = [
            (tr("主页"), "HOME"),
            (tr("返回"), "BACK"),
            (tr("最近"), "RECENTS"),
            (tr("菜单"), "MENU"),
            (tr("电源"), "POWER"),
            (tr("设置"), "SETTINGS"),
            (tr("相机"), "CAMERA"),
            (tr("搜索"), "SEARCH"),
            (tr("确认"), "ENTER"),
            (tr("删除"), "DEL"),
        ]
        for label, code in key_specs:
            self._frame._remote_key_button(label, code, tr("发送按键事件 {code}").format(code=code))
        self._frame._remote_primary_key_buttons = tuple(self._frame._remote_key_buttons)
        # 按键和媒体共用五列节奏；空间不足时依文字自然宽度减列。
        # 末行保持逐格排列，避免确认、删除或媒体尾项因跨列而出现断开的空位。
        key_modes = tuple(
            GridMode(
                name,
                columns,
                rank,
                column_stretches=(1,) * columns,
                equal_column_groups=(tuple(range(columns)),),
            )
            for rank, (name, columns) in enumerate((("five", 5), ("three", 3), ("two", 2)))
        )
        action_modes = tuple(
            GridMode(
                name,
                columns,
                rank,
                column_stretches=(1,) * columns,
                equal_column_groups=(tuple(range(columns)),),
            )
            for rank, (name, columns) in enumerate((("four", 4), ("two", 2)))
        )
        self._frame._remote_key_binding = self._frame._add_responsive_row(
            outer,
            *self._frame._remote_primary_key_buttons,
            spacing=6,
            policies=(WidthPolicy.NATURAL,) * len(self._frame._remote_primary_key_buttons),
            modes=key_modes,
        )

        media_specs = [
            ("VOL-", "VOL_DOWN"),
            ("VOL+", "VOL_UP"),
            (tr("播放"), "MEDIA_PLAY"),
            (tr("上一个"), "MEDIA_PREV"),
            (tr("下一个"), "MEDIA_NEXT"),
        ]
        for label, code in media_specs:
            self._frame._remote_key_button(label, code, tr("发送按键事件 {code}").format(code=code))
        self._frame._remote_media_buttons = tuple(
            self._frame._remote_key_buttons[len(self._frame._remote_primary_key_buttons) :]
        )
        self._frame._remote_media_binding = self._frame._add_responsive_row(
            outer,
            *self._frame._remote_media_buttons,
            spacing=6,
            policies=(WidthPolicy.NATURAL,) * len(self._frame._remote_media_buttons),
            modes=key_modes,
        )

        action_specs = [
            (tr("上滑"), "swipe_up", tr("发送向上滑动手势")),
            (tr("下滑"), "swipe_down", tr("发送向下滑动手势")),
            (tr("左滑"), "swipe_left", tr("发送向左滑动手势")),
            (tr("右滑"), "swipe_right", tr("发送向右滑动手势")),
            (tr("展开通知"), "notif_expand", tr("展开通知栏")),
            (tr("收起通知"), "notif_collapse", tr("收起通知栏")),
            (tr("竖屏"), "rotate_portrait", tr("切换到竖屏方向")),
            (tr("横屏"), "rotate_landscape", tr("切换到横屏方向")),
        ]
        for label, action, tooltip in action_specs:
            self._frame._remote_action_button(label, action, tooltip)
        self._frame._remote_action_binding = self._frame._add_responsive_row(
            outer,
            *self._frame._remote_action_buttons,
            spacing=6,
            policies=(WidthPolicy.NATURAL,) * len(self._frame._remote_action_buttons),
            modes=action_modes,
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
        b.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
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
        b.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
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
        p = self._frame.preset.currentData()
        self._frame._settings.set("scrcpy_preset", p if p else "Custom")
        for k in ("maxsize", "fps", "codec", "buffer", "bitrate", "orientation"):
            self._frame._settings.set(f"scrcpy_{k}", getattr(self._frame, k).currentData())

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
            preset_index = self._frame.preset.findData(saved_preset)
            self._frame.preset.setCurrentIndex(preset_index)
            for key in ("maxsize", "fps", "codec", "buffer", "bitrate", "orientation"):
                combo = getattr(self._frame, key)
                saved_index = combo.findData(self._frame._load(key))
                if saved_index >= 0:
                    combo.setCurrentIndex(saved_index)
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
            for key in ("maxsize", "fps", "bitrate", "codec", "buffer"):
                combo = getattr(self._frame, key)
                combo.setCurrentIndex(combo.findData(p[key]))
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
        details = tr("开始镜像时创建录屏文件")
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
