"""提供 Remote 面板的表单构建与 scrcpy 设置持久化。"""

import os
import re
from datetime import datetime

from PySide6.QtCore import QObject, QSize, Qt, Slot
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    HorizontalSeparator,
    IndicatorPosition,
    InfoBadge,
    SwitchButton,
    themeColor,
)

from core.settings_manager import SCRCPY_SETTING_DEFAULTS, AppSettings
from gui.feedback import report_feedback
from gui.i18n import tr
from gui.panels.remote_panel_controls import (
    RemoteBitrateEditor,
    RemoteChoiceEditor,
    RemoteSwitchButton,
    RemoteWindowToggle,
    RemoteWorkspace,
)
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    apply_font_role,
    apply_label_role,
    configure_button,
    configure_fluent_control,
    font_qss,
    set_fluent_font_rule,
)
from gui.styles.icon_loader import get_fluent_icon
from gui.widgets.category_stack import AdaptiveCategoryStack
from gui.widgets.responsive_layout import (
    RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY,
    GridMode,
    WidthPolicy,
)


class RemotePanelForm(QObject):
    """随表单根控件销毁的控制器，通过 ``self._frame`` 访问 Remote 面板。"""

    def __init__(self, frame):
        super().__init__()
        self._frame = frame

    def build_ui(self, *, parent: QWidget | None = None) -> QWidget:
        """构建表单；根控件失败时仍由外部所有者释放，正常挂载后归属宿主。"""
        w = QWidget(parent, Qt.WindowType.Window)
        # RemotePanel 是隐藏的协调对象，可能晚于可见表单释放；全局样式信号必须
        # 归属实际视图，Qt 才能在根控件销毁时断连，避免访问已释放的设备与徽标。
        self.setParent(w)
        lo = QVBoxLayout(w)
        lo.setSpacing(10)
        lo.setContentsMargins(0, 0, 0, 0)
        self._frame._remote_section_groups = []
        self._editors = []
        self._fields = []
        self._switches = []
        self._toggle_buttons = []
        self._build_header(lo)
        self._frame._feedback_received.connect(self._show_feedback)
        mirroring = self._frame._build_mirroring()
        control = self._frame._build_control()
        self._frame._remote_section_groups.extend((mirroring, control))
        self._frame.category_stack = AdaptiveCategoryStack("remote", w)
        self._frame.category_stack.setObjectName("remoteCategoryStack")
        workspace = RemoteWorkspace(mirroring, control, w)
        workspace.setObjectName("remoteWorkspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._frame._remote_workspace_binding = self._frame._add_responsive_row(
            workspace_layout, mirroring, control, spacing=56, adaptive_spacing=False,
            policies=(WidthPolicy.SHRINKABLE, WidthPolicy.SHRINKABLE),
            modes=(
                GridMode("two", 2, 0, column_stretches=(1, 1)),
                GridMode("one", 1, 1, column_stretches=(1,)),
            ),
        )
        self._frame._responsive_row_owners[-1][0].setObjectName("remoteWorkspaceRow")
        self._frame.category_stack.add_category("mirroring", tr("远程控制"), (workspace,))
        self._frame.category_stack.set_navigation_visible(False)
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
        # SidePanel 先响应此信号更新后代字体，再重测复合字段；ui_font_changed
        # 在它之前发出，直接订阅会把旧字号的下限保存到新布局中。
        BaseStyles.fonts_changed.connect(self._refresh_controls)
        BaseStyles.accent_color_changed.connect(self._refresh_controls)
        self._refresh_controls()
        lo.addWidget(self._frame.category_stack, 1)
        return w

    # ── 页头与开放分区 ──────────────────────────────────────────────────

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
        self._refresh_controls()

    def _field(self, text: str, control: QWidget) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = self._frame._label(text)
        label.setMinimumWidth(label.fontMetrics().horizontalAdvance(text))
        label.setBuddy(control)
        self._frame._parameter_labels.append(label)
        layout.addWidget(label)
        layout.addWidget(control)
        container.setMinimumWidth(max(control.minimumWidth(), label.minimumSizeHint().width()))
        self._fields.append((container, label, control))
        return container

    def _group_title(self, layout, text: str) -> None:
        layout.addSpacing(8)
        layout.addWidget(HorizontalSeparator())
        layout.addSpacing(4)
        layout.addWidget(apply_label_role(
            BodyLabel(tr(text)), FontRole.UI, color_key="TEXT_SECONDARY", bold=True,
        ))

    def _switch(self, text: str, tooltip: str) -> SwitchButton:
        switch = RemoteSwitchButton(indicatorPos=IndicatorPosition.LEFT)
        switch.setOnText(tr(text))
        switch.setOffText(tr(text))
        switch.setAccessibleName(tr(text))
        switch.setToolTip(tr(tooltip))
        switch.setAccessibleDescription(tr(tooltip))
        switch.indicator.setAccessibleName(tr(text))
        switch.indicator.setToolTip(tr(tooltip))
        switch.hBox.setStretchFactor(switch.label, 1)
        switch.hBox.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        switch.hBox.setAlignment(switch.label, Qt.AlignmentFlag.AlignVCenter)
        switch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        configure_fluent_control(switch.indicator, focus=False, ensure_height=False)
        switch.indicator.installEventFilter(switch)
        self._switches.append(switch)
        return switch

    def _window_toggle(self, text: str, icon: str, tooltip: str):
        button = RemoteWindowToggle()
        configure_button(button, text=tr(text), tooltip=tr(tooltip))
        button.setIcon(get_fluent_icon(icon))
        button.setProperty("iconName", icon)
        button.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        self._toggle_buttons.append(button)
        return button

    def refresh_control_metrics(self) -> None:
        """随宿主字体刷新复合字段的度量，不请求额外布局代次。"""
        # 字段容器承担布局下限，字体变化仍需重测其内部下拉框的选项宽度。
        for name in ("preset", "maxsize", "fps", "buffer", "bitrate", "orientation"):
            self._frame._refresh_responsive_widget_minimum(getattr(self._frame, name))
        for switch in self._switches:
            configure_fluent_control(switch, focus=False)
            apply_font_role(switch.label)
            font = BaseStyles.font_for_role(FontRole.UI)
            switch.setFont(font)
            set_fluent_font_rule(switch.label, (
                f"SwitchButton > QLabel {{ {font_qss(font)} }}"
                "SwitchButton > QLabel[remoteSwitchFocused=true] "
                f"{{ color: {themeColor().name()}; }}"
            ))
            switch.label.setMinimumWidth(switch.label.fontMetrics().horizontalAdvance(
                switch.label.text(),
            ))
            switch.setFixedHeight(max(28, switch.label.sizeHint().height() + 8))
            switch.updateGeometry()
        # 录屏提示显隐不能先挤缩开关再等待滚动内容增高；空文案也保留一行字体高度。
        self._frame.record_path.setFixedHeight(self._frame.record_path.fontMetrics().height())
        for editor in self._editors:
            editor.refresh_metrics()
        for container, label, control in self._fields:
            label.setMinimumWidth(label.fontMetrics().horizontalAdvance(label.text()))
            container.setMinimumWidth(max(
                control.minimumWidth(), label.minimumSizeHint().width(),
            ))
            container.updateGeometry()

    @Slot()
    def _refresh_controls(self) -> None:
        """字体、强调色变化时刷新原生复合控件，保持所有编辑值和会话状态。"""
        self.refresh_control_metrics()
        for button in (
            *self._toggle_buttons, self._frame.btn_start, self._frame.btn_stop,
            *self._frame._remote_control_buttons,
            *(row[2] for row in getattr(self._frame, "_session_rows", {}).values()),
        ):
            self._style_transparent_button(button, accented=button is self._frame.btn_start)
        self._frame.apply_responsive_width(0)

    def _style_transparent_button(self, button, *, accented: bool = False) -> None:
        """本页以文字和底线反馈交互，各状态保留相同边距，避免焦点框挤动内容。"""
        accent = themeColor().name()
        disabled = BaseStyles.color("TEXT_DISABLED")
        normal = accent if accented else BaseStyles.color("TEXT_PRIMARY")
        selector = type(button).__name__
        states = ", ".join(selector + state for state in (
            "", ":hover", ":pressed", ":focus", ":checked", ":checked:hover",
            ":checked:pressed", ":checked:focus", ":disabled", ":checked:disabled",
        ))
        set_fluent_font_rule(button, (
            f"{states} {{ background: transparent; border: 0px solid transparent; "
            f"border-bottom: 2px solid transparent; border-radius: 0px; }}"
            f"{selector} {{ color: {normal}; }}"
            f"{selector}:hover, {selector}:pressed {{ color: {accent}; }}"
            f"{selector}:checked, {selector}:checked:hover, {selector}:checked:pressed, "
            f"{selector}:checked:focus, "
            f"{selector}:focus {{ color: {accent}; border-bottom-color: {accent}; }}"
            f"{selector}:disabled, {selector}:checked:disabled {{ color: {disabled}; "
            f"border-bottom-color: transparent; }}"
        ))
        apply_font_role(button, ensure_height=True)

    @Slot()
    def _update_mirror_hint(self) -> None:
        record_only = self._frame.chk_noplayback.isChecked()
        self._frame._mirror_hint.setText(
            tr("仅录制，不打开镜像窗口") if record_only else tr("镜像将在独立窗口打开")
        )

    def _sync_parameter_editors(self) -> None:
        for editor in getattr(self, "_editors", ()):
            editor.sync_selection()

    def _build_mirroring(self) -> QWidget:
        frame = self._frame
        g = frame._card(tr("屏幕镜像"))
        g.setObjectName("remoteMirroringSection")
        gl = g.viewLayout
        gl.setSpacing(10)
        gl.setAlignment(Qt.AlignmentFlag.AlignTop)
        frame._parameter_labels = []
        for name, items in (
            ("preset", frame._PRESET_NAMES), ("maxsize", frame._SIZES),
            ("fps", frame._FPS), ("buffer", frame._BUFFERS),
            ("bitrate", frame._BITRATES), ("orientation", frame._ORIENTATIONS),
        ):
            combo = frame._combo(items)
            saved_index = combo.findData(frame._load(name))
            if name == "preset" or saved_index >= 0:
                combo.setCurrentIndex(saved_index)
            combo.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
            frame._refresh_responsive_widget_minimum(combo)
            setattr(frame, name, combo)
        frame.preset.setAccessibleName(tr("预设："))
        frame.fps.setAccessibleName("FPS")
        frame.bitrate.setAccessibleName(tr("码率："))
        preset_editor = RemoteChoiceEditor(frame.preset)
        fps_editor = RemoteChoiceEditor(frame.fps)
        bitrate_value = frame._label("")
        bitrate_editor = RemoteBitrateEditor(frame.bitrate, bitrate_value)
        self._editors.extend((preset_editor, fps_editor, bitrate_editor))
        frame.preset_selector = preset_editor.pivot
        frame.fps_selector = fps_editor.pivot
        frame.bitrate_slider = bitrate_editor.slider
        frame.preset_binding = frame._add_responsive_row(
            gl, self._field(tr("预设："), preset_editor), wide_columns=1,
        )
        frame.mirroring_binding = frame._add_responsive_row(
            gl, self._field(tr("尺寸："), frame.maxsize), self._field("FPS", fps_editor),
            spacing=12, compact_columns=1, medium_columns=2, wide_columns=2,
        )
        frame.parameter_binding = frame.mirroring_binding
        frame._add_responsive_row(gl, self._field(tr("码率："), bitrate_editor), wide_columns=1)
        frame.codec = frame._status_text(tr("自动（启动时检测）"))
        frame.codec.setWordWrap(True)
        frame.codec.setAccessibleName(tr("自动视频编码"))
        frame.codec.setMinimumWidth(0)
        frame.codec.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        frame.codec.setToolTip(tr("启动时按设备能力自动选择视频编码与编码器"))
        frame.codec.setAccessibleDescription(frame.codec.toolTip())
        frame._add_responsive_row(
            gl, self._field(tr("编码："), frame.codec),
            self._field(tr("缓冲："), frame.buffer),
            self._field(tr("方向："), frame.orientation),
            spacing=10, compact_columns=1, medium_columns=2, wide_columns=3,
        )
        frame.orientation.setToolTip(tr("锁定屏幕方向（0 为自动）"))
        frame._status_label = frame._status_text(tr("状态：空闲"))
        frame._status_label.setAccessibleName(tr("远程会话状态"))
        frame._status_label.setToolTip(tr("状态：空闲"))
        frame._status_label.setAccessibleDescription(tr("状态：空闲"))
        frame._status_label.setMinimumWidth(0)
        frame._status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        g.headerLayout.addWidget(frame._status_label, 1)
        frame._remote_queue_label = frame._status_text(tr("队列：0"))
        frame._remote_queue_label.setAccessibleName(tr("远程输入队列状态"))
        frame._remote_queue_label.setToolTip(tr("排队：0 · 已发送：0 · 失败：0"))
        frame._remote_queue_label.setAccessibleDescription(frame._remote_queue_label.toolTip())
        self._group_title(gl, tr("窗口与录制"))
        frame.chk_aot = self._window_toggle(
            "窗口置顶", "map-pin.svg", "让镜像窗口保持在其他窗口上方",
        )
        frame.chk_fullscreen = self._window_toggle("全屏", "frame-corners.svg", "以全屏模式启动")
        frame.chk_showtouches = self._window_toggle(
            "显示触点", "radio-button.svg", "在屏幕上显示触摸位置",
        )
        frame._add_responsive_row(
            gl, frame.chk_aot, frame.chk_fullscreen, frame.chk_showtouches,
            spacing=6, compact_columns=1, medium_columns=2, wide_columns=3,
        )
        frame.chk_record = self._switch("保存录屏", "将镜像画面录制到文件")
        frame.chk_record.checkedChanged.connect(frame._on_record_toggled)
        frame.chk_noaudio = self._switch("禁用音频", "不转发设备音频")
        frame.chk_noaudio.setChecked(True)
        frame.chk_stayawake = self._switch("保持唤醒", "镜像期间保持设备屏幕唤醒")
        frame.chk_turnscreenoff = self._switch("关闭设备屏幕", "连接后关闭设备屏幕")
        frame.chk_noplayback = self._switch("仅录制", "只录制文件，不显示镜像窗口")
        frame._add_responsive_row(
            gl, frame.chk_record, frame.chk_noaudio, frame.chk_stayawake,
            frame.chk_turnscreenoff, frame.chk_noplayback,
            spacing=12, compact_columns=1, medium_columns=2, wide_columns=2,
            policies=(WidthPolicy.NATURAL,) * 5,
        )
        frame.record_path = frame._status_text("")
        frame.record_path.setAccessibleName(tr("录屏保存路径"))
        frame.record_path.setWordWrap(False)
        frame.record_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        record_policy = frame.record_path.sizePolicy()
        record_policy.setRetainSizeWhenHidden(True)
        frame.record_path.setSizePolicy(record_policy)
        frame.record_path.setMinimumWidth(0)
        gl.addWidget(frame.record_path)
        frame.record_path.hide()
        frame.btn_start = frame._b(
            tr("开始镜像"), "monitor-play.svg", "ghost", tooltip=tr("开始屏幕镜像（Ctrl+Enter）"),
        )
        frame.btn_stop = frame._b(
            tr("停止镜像"), "stop-circle.svg", "ghost",
            tooltip=tr("停止屏幕镜像（Ctrl+Shift+Return）"),
        )
        frame.btn_stop.setEnabled(False)
        frame._add_responsive_row(
            gl, frame.btn_start, frame.btn_stop, spacing=8,
            compact_columns=1, medium_columns=2, wide_columns=2,
        )
        frame._mirror_hint = apply_label_role(
            BodyLabel(tr("镜像将在独立窗口打开")), FontRole.UI, color_key="TEXT_SECONDARY",
        )
        frame._mirror_hint.setWordWrap(True)
        gl.addWidget(frame._mirror_hint)
        frame.chk_noplayback.checkedChanged.connect(self._update_mirror_hint)
        frame._session_list = QWidget(g)
        frame._session_list.setObjectName("remoteSessionList")
        frame._session_list_layout = QVBoxLayout(frame._session_list)
        frame._session_list_layout.setContentsMargins(0, 4, 0, 0)
        frame._session_list_layout.setSpacing(6)
        # 动态会话行的按钮不可压缩；将列表下限传给嵌套分栏，避免行高小于按钮高度。
        frame._session_list_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        frame._session_rows = {}
        gl.addWidget(frame._session_list)
        frame._session_list.hide()
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
                    tr("停止"), "stop-circle.svg", "ghost", tooltip=tr("停止或重试此设备的镜像"),
                )
                self._style_transparent_button(action)
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
        frame = self._frame
        g = frame._card(tr("远程按键与手势"))
        g.setObjectName("remoteControlSection")
        outer = g.viewLayout
        outer.setSpacing(8)
        outer.setAlignment(Qt.AlignmentFlag.AlignTop)
        frame._remote_control_buttons = []
        frame._remote_key_buttons = []
        frame._remote_action_buttons = []

        def key_group(specs, *, column_counts=(3, 2, 1), equal_columns=True):
            buttons = tuple(frame._remote_key_button(
                tr(label), code, tr("发送按键事件 {code}").format(code=code),
            ) for label, code in specs)
            binding = frame._add_responsive_row(
                outer, *buttons, spacing=6,
                policies=(WidthPolicy.NATURAL,) * len(buttons),
                modes=tuple(GridMode(
                    str(count), count, rank, column_stretches=(1,) * count,
                    equal_column_groups=(
                        (tuple(range(count)),) if equal_columns and count > 1 else ()
                    ),
                ) for rank, count in enumerate(column_counts)),
            )
            return buttons, binding

        navigation, frame._remote_navigation_binding = key_group(
            (("返回", "BACK"), ("主页", "HOME"), ("最近", "RECENTS")),
        )
        for button in navigation:
            button.setIconSize(QSize(20, 20))
            button.setMinimumHeight(48)
        self._group_title(outer, tr("系统按键"))
        system, frame._remote_key_binding = key_group((
            ("菜单", "MENU"), ("回车", "ENTER"), ("退格", "DEL"),
            ("设置", "SETTINGS"), ("相机", "CAMERA"), ("搜索", "SEARCH"),
        ))
        self._group_title(outer, tr("音量与媒体"))
        volume, frame._remote_volume_binding = key_group((
            ("VOL-", "VOL_DOWN"), ("VOL+", "VOL_UP"),
        ), column_counts=(2, 1))
        media, frame._remote_media_binding = key_group((
            ("上一个", "MEDIA_PREV"), ("播放/暂停", "MEDIA_PLAY"), ("下一个", "MEDIA_NEXT"),
        ), column_counts=(3, 1), equal_columns=False)
        frame._remote_media_buttons = (*volume, *media)
        self._group_title(outer, tr("手势与方向"))
        specs = (
            ("上滑", "swipe_up", "发送向上滑动手势"),
            ("下滑", "swipe_down", "发送向下滑动手势"),
            ("左滑", "swipe_left", "发送向左滑动手势"),
            ("右滑", "swipe_right", "发送向右滑动手势"),
            ("展开通知", "notif_expand", "展开通知栏"),
            ("收起通知", "notif_collapse", "收起通知栏"),
            ("竖屏", "rotate_portrait", "切换到竖屏方向"),
            ("横屏", "rotate_landscape", "切换到横屏方向"),
        )
        for label, action, tooltip in specs:
            frame._remote_action_button(tr(label), action, tr(tooltip))
        frame._remote_action_binding = frame._add_responsive_row(
            outer, *frame._remote_action_buttons, spacing=6,
            policies=(WidthPolicy.NATURAL,) * 8,
            modes=tuple(GridMode(
                str(count), count, rank, column_stretches=(1,) * count,
                equal_column_groups=(tuple(range(count)),) if count > 1 else (),
            ) for rank, count in enumerate((2, 1))),
        )
        outer.addWidget(HorizontalSeparator())
        frame._remote_queue_label.setWordWrap(True)
        frame._remote_queue_label.setMinimumWidth(0)
        frame._remote_queue_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        footer = QHBoxLayout()
        footer.setSpacing(12)
        footer.addWidget(frame._remote_queue_label, 1)
        power = frame._remote_key_button(tr("电源"), "POWER", tr("点按电源键，切换屏幕开关"))
        power.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        footer.addWidget(power)
        outer.addLayout(footer)
        frame._remote_primary_key_buttons = (*navigation, *system, power)
        hint = apply_label_role(
            BodyLabel(tr("按键与手势可独立使用，无需启动镜像。")),
            FontRole.UI, color_key="TEXT_SECONDARY",
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)
        frame.remote_control_bindings = (
            frame._remote_navigation_binding, frame._remote_key_binding,
            frame._remote_volume_binding, frame._remote_media_binding, frame._remote_action_binding,
        )
        return g


    def _remote_key_button(self, label: str, code: str, tooltip: str):
        b = self._frame._b(
            label, self._frame._KEY_ICONS.get(code, "keyboard.svg"), "ghost", tooltip=tooltip,
        )
        b.setProperty("remoteKey", code)
        b.setFont(self._frame._font_sm)
        b.setIconSize(QSize(16, 16))
        b.setMinimumHeight(28)
        b.setMinimumWidth(56)
        b.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        b.clicked.connect(lambda _, cd=code: self._frame._send_keyevent(cd))
        self._frame._remote_control_buttons.append(b)
        self._frame._remote_key_buttons.append(b)
        return b

    def _remote_action_button(self, label: str, action: str, tooltip: str):
        b = self._frame._b(
            label, self._frame._ACTION_ICONS.get(action, "keyboard.svg"), "ghost", tooltip=tooltip
        )
        b.setProperty("remoteAction", action)
        b.setFont(self._frame._font_sm)
        b.setIconSize(QSize(16, 16))
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
        self._sync_parameter_editors()
        self._frame._save_all()

    def _save(self, key: str, value: str):
        if getattr(self._frame, "_loading", False):
            return
        self._frame._settings.set(f"scrcpy_{key}", value)

    def _save_all(self):
        p = self._frame.preset.currentData()
        self._frame._settings.set("scrcpy_preset", p if p else "Custom")
        for k in ("maxsize", "fps", "buffer", "bitrate", "orientation"):
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
            for key in ("maxsize", "fps", "buffer", "bitrate", "orientation"):
                combo = getattr(self._frame, key)
                saved_index = combo.findData(self._frame._load(key))
                if saved_index >= 0:
                    combo.setCurrentIndex(saved_index)
        finally:
            self._frame._loading = was_loading
        self._sync_parameter_editors()
        self._frame._update_action_states()
        return True

    # ── scrcpy 预设 ─────────────────────────────────────────────────────

    def _on_preset_changed(self, idx: int):
        if idx in self._frame._PRESETS:
            was_loading = getattr(self._frame, "_loading", False)
            self._frame._loading = True
            p = self._frame._PRESETS[idx]
            for key in ("maxsize", "fps", "bitrate", "buffer"):
                combo = getattr(self._frame, key)
                combo.setCurrentIndex(combo.findData(p[key]))
            self._frame._loading = was_loading
            self._sync_parameter_editors()
            if not was_loading:
                self._frame._save_all()

    # ── 录制开关 ────────────────────────────────────────────────────────

    def _on_record_toggled(self, checked: bool):
        if not checked:
            self._frame.record_path.setText("")
            self._frame.record_path.setToolTip("")
            self._frame.record_path.setAccessibleDescription("")
            self._frame.record_path.hide()
            return
        details = tr("开始镜像时创建录屏文件")
        self._frame.record_path.setText(details)
        self._frame.record_path.setToolTip(details)
        self._frame.record_path.setAccessibleDescription(details)
        self._frame.record_path.show()

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
            "buffer",
            "bitrate",
            "orientation",
            "chk_record",
            "chk_fullscreen",
            "chk_aot",
            "chk_showtouches",
            "chk_stayawake",
            "chk_turnscreenoff",
            "chk_noplayback",
            "chk_noaudio",
        )
        return tuple(getattr(self, "_editors", ())) + tuple(
            control for name in names if (control := getattr(self._frame, name, None)) is not None
        )
