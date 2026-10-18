"""提供 Remote 面板的表单构建与 scrcpy 设置持久化。"""

import os
import re
from datetime import datetime
from typing import cast

from PySide6.QtCore import QObject, QSize, Qt, Slot
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)
from qfluentwidgets import (
    BodyLabel,
    IconWidget,
    IndicatorPosition,
    InfoBadge,
    SwitchButton,
    ToolButton,
    TransparentPushButton,
    TransparentToolButton,
    themeColor,
)
from shiboken6 import delete

from core.settings_manager import SCRCPY_SETTING_DEFAULTS, AppSettings
from gui.feedback import report_feedback
from gui.i18n import tr
from gui.panels.remote_panel_controls import (
    RemoteBitrateEditor,
    RemoteChoiceEditor,
    RemoteCommandButton,
    RemoteSection,
    RemoteSessionHint,
    RemoteSwitchButton,
    RemoteToolbarSeparators,
    RemoteWindowToggle,
)
from gui.panels.remote_panel_dock import RemoteControllerWindow, RemotePanelDock
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    apply_focus_indicator,
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
    GridPlacement,
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
        self._root = w
        lo = QVBoxLayout(w)
        lo.setSpacing(20)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._frame._remote_section_groups = []
        self._editors = []
        self._fields = []
        self._switches = []
        self._toggle_buttons = []
        self._toolbar_separators = []
        self._group_titles = []
        self._frame._remote_split_groups = []
        self._build_header(lo)
        self._frame._feedback_received.connect(self._show_feedback)
        session = self._build_session()
        mirroring = self._frame._build_mirroring()
        full_control = self._frame._build_control()
        self._frame._standalone_remote = RemoteControllerWindow(full_control, w)
        self._frame._responsive_coordinator.attach_top_level(self._frame._standalone_remote)
        self._frame._standalone_remote.set_target_count(len(self._frame.selected_devices))
        self._frame._dock_controller = RemotePanelDock(self._frame, w)
        self._frame._remote_section_groups.append(mirroring)
        self._frame.category_stack = AdaptiveCategoryStack("remote", w)
        self._frame.category_stack.setObjectName("remoteCategoryStack")
        # QStackedLayout 不实际缩进页面，但其默认边距会被响应式测量重复计入。
        category_layout = self._frame.category_stack.stack.layout()
        assert category_layout is not None
        category_layout.setContentsMargins(0, 0, 0, 0)
        workspace = QWidget(w)
        workspace.setObjectName("remoteWorkspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(16)
        workspace_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        workspace_layout.addWidget(session, 0, Qt.AlignmentFlag.AlignTop)
        self._frame._remote_bottom_sections = (self._system_section, self._recording_section)
        self._frame._remote_workspace_binding = self._frame._add_responsive_row(
            workspace_layout, mirroring,
            spacing=24, adaptive_spacing=False, wide_columns=1, medium_columns=1,
            compact_columns=1,
            policies=(WidthPolicy.SHRINKABLE,),
        )
        workspace_row = self._frame._responsive_row_owners[-1][0]
        workspace_row.setObjectName("remoteWorkspaceRow")
        workspace_row.setProperty("responsiveLiveHeight", True)
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
        lo.addWidget(self._frame.category_stack, 0, Qt.AlignmentFlag.AlignTop)
        self._use_live_workspace_height(workspace_row, w)
        # 独立窗口各自维护焦点链，主页面先访问顶部操作，再进入参数。
        directions = {button.property("remoteAction"): button
                      for button in self._frame._remote_action_buttons}
        keys = {button.property("remoteKey"): button
                for button in self._frame._remote_key_buttons}
        focus_order = (
            self._frame.btn_start, self._frame.btn_stop,
            *self._frame.preset_selector.items.values(),
            self._frame.preset, self._frame.maxsize, self._frame.fps,
            self._frame.buffer, self._frame.orientation, self._frame.bitrate_slider,
            *(switch.indicator for switch in self._frame.window_options_binding.widgets()),
        )
        for before, after in zip(focus_order, focus_order[1:]):
            QWidget.setTabOrder(before, after)
        remote_focus_order = (
            keys["BACK"], keys["HOME"], keys["RECENTS"], keys["POWER"],
            *(directions[action] for action in (
                "rotate_portrait", "rotate_landscape", "notif_expand", "notif_collapse",
            )),
            *(directions[action] for action in (
                "swipe_up", "swipe_down", "swipe_left", "swipe_right",
            )),
            *(keys[code] for code in ("MENU", "ENTER", "DEL", "SETTINGS", "CAMERA", "SEARCH")),
            *(keys[code] for code in (
                "VOL_DOWN", "MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT", "VOL_UP",
            )),
        )
        for before, after in zip(remote_focus_order, remote_focus_order[1:]):
            QWidget.setTabOrder(before, after)
        return w

    @staticmethod
    def _use_live_workspace_height(row: QWidget, root: QWidget) -> None:
        """让深层分类包装项实时委托高度，宽窄回流不保留旧滚动占位。"""
        widget = row
        while widget is not root and (parent := widget.parentWidget()) is not None:
            layout = parent.layout()
            if isinstance(layout, QBoxLayout) and widget.hasHeightForWidth():
                index = layout.indexOf(widget)
                item = layout.itemAt(index) if index >= 0 else None
                if item is not None:
                    stretch, alignment = layout.stretch(index), item.alignment()
                    removed = layout.takeAt(index)
                    delete(removed)
                    live_item = QWidgetItem(widget)
                    live_item.setAlignment(alignment)
                    layout.insertItem(index, live_item)
                    layout.setStretch(index, stretch)
            widget = parent

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
        # 页面用途由分区说明承接，页头只保留标题与设备状态，避免挤占操作区。
        self._frame.remote_subtitle.setParent(header)
        self._frame.remote_subtitle.hide()
        lo.addWidget(header)
        self._frame._apply_remote_header_style()

    @Slot()
    def _on_theme_changed_remote(self) -> None:
        """主题切换时重建页头与分区卡片样式（委托给面板持有者）。"""

        self._frame._on_theme_changed_remote(BaseStyles.current_theme())
        self._refresh_controls()

    def _field(self, text: str, control: QWidget, unit: str = "") -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        label = self._frame._label(text)
        label.setMinimumWidth(label.fontMetrics().horizontalAdvance(text))
        label.setBuddy(control)
        self._frame._parameter_labels.append(label)
        layout.addWidget(label)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(4)
        layout.addLayout(value_row)
        value_row.addWidget(control, 1)
        if unit:
            suffix = self._frame._label(unit)
            suffix.setWordWrap(False)
            value_row.addWidget(suffix)
            if control in (self._frame.maxsize, self._frame.orientation):
                combo = (
                    self._frame.maxsize if control is self._frame.maxsize
                    else self._frame.orientation
                )
                no_unit = "Default" if control is self._frame.maxsize else "0"
                suffix.setVisible(combo.currentData() != no_unit)
                combo.currentIndexChanged.connect(
                    lambda _index: suffix.setVisible(combo.currentData() != no_unit),
                )
        container.setMinimumWidth(layout.minimumSize().width())
        self._fields.append((container, label, control))
        return container

    def _group_title(self, layout, text: str) -> None:
        label = apply_label_role(
            BodyLabel(tr(text)), FontRole.UI, color_key="TEXT_SECONDARY", bold=True,
        )
        self._group_titles.append(label)
        layout.addWidget(label)

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
        switch.setSpacing(6)
        switch.hBox.setContentsMargins(0, 0, 0, 0)
        switch.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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
        for label in self._group_titles:
            apply_label_role(label, FontRole.UI, color_key="TEXT_SECONDARY", bold=True)
            label.setMinimumHeight(label.fontMetrics().height())
        # 字段容器承担布局下限，字体变化仍需重测其内部下拉框的选项宽度。
        for name in ("preset", "maxsize", "fps", "buffer", "bitrate", "orientation"):
            self._frame._refresh_responsive_widget_minimum(getattr(self._frame, name))
        for switch in self._switches:
            configure_fluent_control(switch, focus=False)
            # 原生 QSS 在每次 polish 时写回 12px 间距，页内紧凑度须在同一层覆盖。
            set_fluent_font_rule(switch, "SwitchButton { qproperty-spacing: 6; }")
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
            switch.setFixedHeight(max(36, switch.label.sizeHint().height() + 12))
            switch.updateGeometry()
        # 录屏提示显示时保持一行高度，未录制时不额外占用布局空间。
        self._frame.record_path.setFixedHeight(self._frame.record_path.fontMetrics().height())
        self._frame._status_label.setMinimumWidth(0)
        for editor in self._editors:
            editor.refresh_metrics()
        for container, label, control in self._fields:
            label.setMinimumWidth(label.fontMetrics().horizontalAdvance(label.text()))
            # 嵌套布局在字体信号返回前仍可能缓存旧宽度；直接按本代字段和单位度量。
            units = [child for child in container.findChildren(
                QLabel, options=Qt.FindChildOption.FindDirectChildrenOnly,
            ) if child is not label and not child.isHidden()]
            value_width = max(control.minimumWidth(), control.minimumSizeHint().width())
            value_width += sum(unit.fontMetrics().horizontalAdvance(unit.text()) + 4
                               for unit in units)
            container.setMinimumWidth(max(label.minimumWidth(), value_width))
            container.updateGeometry()
        self._sync_control_heights()

    def _sync_control_heights(self) -> None:
        """同页控件共享当前字体的自然高度，放大和恢复字号均重新度量。"""
        frame = self._frame
        buttons = (
            *self._toggle_buttons, frame.btn_start, frame.btn_stop,
            *frame._remote_control_buttons,
            *(row[2] for row in getattr(frame, "_session_rows", {}).values()),
        )
        combos = tuple(getattr(frame, name) for name in (
            "preset", "maxsize", "fps", "buffer", "bitrate", "orientation",
        ))
        choices = tuple(item for editor in self._editors
                        if isinstance(editor, RemoteChoiceEditor)
                        for item in editor.pivot.items.values())
        for button in buttons:
            apply_font_role(button)
        height = max(
            36,
            *(button.fontMetrics().height() + 14 for button in buttons),
            *(control.minimumSizeHint().height() for control in (*buttons, *combos, *choices)
              if not isinstance(control, RemoteCommandButton)),
        )
        command_height = max(height, *(button.sizeHint().height() for button in buttons
                                       if isinstance(button, RemoteCommandButton)))
        for control in (*buttons, *combos, *choices, *self._switches):
            control.setFixedHeight(
                command_height if isinstance(control, RemoteCommandButton) else height
            )
            if isinstance(control, ToolButton):
                control.setFixedWidth(height)
        for editor in self._editors:
            if isinstance(editor, RemoteChoiceEditor) and editor._prefer_combo:
                # 隐藏 Pivot 的指示条仍抬高堆叠布局；纯下拉字段须随当前统一高度
                # 同步外壳，避免相邻控件居中后错位，字号恢复时也不能保留旧高度。
                editor.setFixedHeight(height)
        frame._mirror_hint.refresh_height(height)
        frame._status_label.setFixedHeight(height)
        for section in (*frame._remote_section_groups, *frame._remote_bottom_sections,
                        self._gesture_section, self._media_section):
            if section.headerLabel.isHidden() and not section.headerView.isHidden():
                section.headerView.setFixedHeight(frame._remote_queue_label.fontMetrics().height())
            else:
                section.headerView.setMinimumHeight(height)
        frame.codec.setMinimumHeight(height)

    @Slot()
    def _refresh_controls(self) -> None:
        """字体、强调色变化时刷新原生复合控件，保持所有编辑值和会话状态。"""
        self.refresh_control_metrics()
        for separators in self._toolbar_separators:
            separators.update()
        buttons = (
            *self._toggle_buttons, self._frame.btn_start, self._frame.btn_stop,
            *self._frame._remote_control_buttons,
            *(row[2] for row in getattr(self._frame, "_session_rows", {}).values()),
        )
        for button in buttons:
            self._style_transparent_button(button)
        self._sync_control_heights()
        self.refresh_session_summary()
        self._frame.apply_responsive_width(0)

    def refresh_session_summary(self) -> None:
        """固定操作栏保留网格项，避免状态切换时短暂拆装布局。"""
        frame = self._frame
        count = max(99, len(frame.selected_devices), len(getattr(frame, "_device_sessions", {})))
        labels = (
            (frame.btn_start, (
                tr("选择设备"), tr("正在启动…"), tr("已全部启动"), tr("正在停止…"),
                tr("启动 {count} 台").format(count=count),
                tr("追加启动 {count} 台").format(count=count),
                tr("重试 {count} 台").format(count=count),
            )),
            (frame.btn_stop, (tr("停止全部"), tr("取消启动"), tr("正在停止…"))),
        )
        # 为同一按钮的状态文案预留自然宽度，状态切换不挤动相邻操作和参数。
        for button, texts in labels:
            metrics = button.fontMetrics()
            chrome = button.sizeHint().width() - metrics.horizontalAdvance(button.text())
            button.setMinimumWidth(max(metrics.horizontalAdvance(text) for text in texts) + chrome)
        self._session_summary.updateGeometry()

    def _style_transparent_button(self, button) -> None:
        """透明动作仅在键盘聚焦时描边，悬停和图标沿用原生 Fluent 绘制。"""
        selector = type(button).__name__
        if isinstance(button, (TransparentPushButton, TransparentToolButton)):
            padding = "0px" if isinstance(button, ToolButton) else "3px 10px 4px"
            rule = f"{selector} {{ padding: {padding}; border-radius: 6px; }}"
            # 原生悬停/按压样式会撤掉边宽；透明预留需同级覆盖，避免焦点切换跳动。
            rule += (
                f'{selector}[adblabKeyboardFocusOnly="true"] '
                "{ border: 2px solid transparent; }"
            )
            if button is self._frame.btn_start:
                rule += f"{selector}:enabled {{ color: {BaseStyles.color('BORDER_FOCUS')}; }}"
            if isinstance(button, RemoteCommandButton):
                rule += (
                    f"{selector}[hasIcon=true] {{ padding-left: 32px; padding-right: 8px; }}"
                    f"{selector} {{ color: {BaseStyles.color('TEXT_PRIMARY')}; }}"
                    f"{selector}:disabled {{ color: {BaseStyles.color('TEXT_DISABLED')}; }}"
                )
            set_fluent_font_rule(button, rule)
            apply_focus_indicator(button, keyboard_only=True)
            apply_font_role(button)
            button.setFixedHeight(max(36, button.fontMetrics().height() + 14,
                                      button.minimumSizeHint().height()))
            if isinstance(button, ToolButton):
                button.setFixedWidth(button.height())
            return
        # 常态沿用普通按钮的细边框，焦点仅改变颜色，避免转移焦点时改变尺寸。
        rule = (
            f"{selector}:!focus {{ border: 1px solid transparent; }}"
            f"{selector}:focus {{ border-width: 1px; }}"
            f"{selector} {{ padding-top: 3px; padding-bottom: 4px; border-radius: 6px; }}"
        )
        if selector in ("PushButton", "ToolButton"):
            rule += f"{selector}:!focus {{ border-color: {BaseStyles.color('BORDER_COLOR')}; }}"
        if selector == "PushButton":
            rule += f"{selector}[hasIcon=true] {{ padding-left: 32px; padding-right: 8px; }}"
        if selector == "ToolButton":
            rule += f"{selector} {{ padding: 0px; }}"
        if button is self._frame.btn_start:
            # 强调色按钮不能再用同色焦点框，否则浅色主题下键盘焦点不可见。
            rule += f"{selector}:focus {{ border-color: {BaseStyles.color('TEXT_PRIMARY')}; }}"
        set_fluent_font_rule(button, rule)
        apply_font_role(button)
        height = max(36, button.fontMetrics().height() + 14, button.minimumSizeHint().height())
        button.setFixedHeight(height)
        if isinstance(button, ToolButton):
            button.setFixedWidth(height)

    def _toggle_mirror_diagnostics(self) -> None:
        frame = self._frame
        expanded = frame._mirror_diagnostic_label.isHidden()
        frame._mirror_diagnostic_label.setVisible(expanded)
        frame.btn_mirror_diagnostics.setText(tr("收起原因") if expanded else tr("查看原因"))
        frame.apply_responsive_width(0)

    @Slot()
    def _update_mirror_hint(self) -> None:
        record_only = self._frame.chk_noplayback.isChecked()
        if record_only:
            self._frame.chk_record.setChecked(True)
        self._frame._refresh_mirror_presentation()

    def _sync_parameter_editors(self) -> None:
        for editor in getattr(self, "_editors", ()):
            editor.sync_selection()

    def _build_session(self) -> QWidget:
        """会话状态与停止入口独立于设置区，参数锁定不会遮挡原会话资源。"""
        frame = self._frame
        g = RemoteSection(tr("屏幕镜像"))
        g.setObjectName("remoteMirrorSession")
        gl = g.viewLayout
        frame._status_label = frame._status_text(tr("状态：空闲"))
        frame._status_label.setAccessibleName(tr("远程会话状态"))
        frame._status_label.setToolTip(tr("状态：空闲"))
        frame._status_label.setAccessibleDescription(tr("状态：空闲"))
        frame._status_label.setMinimumWidth(0)
        frame._status_label.setWordWrap(False)
        frame._status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        g.headerView.hide()
        summary = QWidget(g)
        self._session_summary = summary
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        mirror_icon = IconWidget(get_fluent_icon("monitor-play.svg"), summary)
        mirror_icon.setFixedSize(20, 20)
        title_row.addWidget(mirror_icon)
        title_row.addWidget(g.headerLabel)
        title_row.addWidget(frame._status_label, 1)
        summary_layout.addLayout(title_row)
        frame._mirror_device_label = apply_label_role(
            BodyLabel(tr("未选择设备")), FontRole.UI, color_key="TEXT_SECONDARY",
        )
        frame._mirror_device_label.setMinimumWidth(0)
        frame._mirror_device_label.setWordWrap(True)
        frame._mirror_device_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        frame._mirror_connection_label = apply_label_role(
            BodyLabel(""), FontRole.UI, color_key="TEXT_SECONDARY",
        )
        frame._mirror_connection_label.setWordWrap(True)
        device_row = QHBoxLayout()
        device_row.setSpacing(8)
        device_row.addWidget(frame._mirror_device_label, 1)
        device_row.addWidget(frame._mirror_connection_label)
        # 设备明细留给独立展示入口，顶部仅承载固定的镜像操作。
        frame._mirror_device_label.hide()
        frame._mirror_connection_label.hide()
        frame._mirror_device_label.setParent(summary)
        frame._mirror_connection_label.setParent(summary)
        frame.btn_start = TransparentPushButton(get_fluent_icon("monitor-play.svg"), tr("选择设备"))
        frame.btn_start.setProperty("iconName", "monitor-play.svg")
        frame.btn_start.setProperty("fontRole", FontRole.UI.value)
        frame.btn_stop = TransparentPushButton(get_fluent_icon("stop-circle.svg"), tr("停止全部"))
        frame.btn_stop.setProperty("iconName", "stop-circle.svg")
        frame.btn_stop.setProperty("fontRole", FontRole.UI.value)
        frame.btn_stop.setEnabled(False)
        frame._mirror_hint = apply_label_role(
            RemoteSessionHint(tr("镜像将在独立窗口打开"), tuple(tr(text) for text in (
                "正在释放镜像资源，请稍候", "部分镜像尚未停止，请再次停止。",
                "正在准备服务；可取消启动，已打开的镜像也将停止",
                "正在建立连接，画面就绪后显示镜像中",
                "已运行的镜像继续保留；停止全部不受勾选影响",
                "请选择操作设备，可同时启动多台", "追加设备沿用当前参数；停止全部后可调整设置",
                "仅录制，不打开镜像窗口", "每台设备将在独立窗口打开镜像",
                "未能建立镜像连接，请重试。",
            )) + (tr("{count} 台连接失败，其余镜像继续运行。").format(count=999),)),
            FontRole.UI, color_key="TEXT_SECONDARY",
        )
        frame._mirror_hint.setWordWrap(True)
        frame._add_responsive_row(
            gl, summary, frame.btn_start, frame.btn_stop,
            spacing=12, adaptive_spacing=False,
            policies=(WidthPolicy.WRAPPING,) + (WidthPolicy.NATURAL,) * 2,
            modes=(
                GridMode("three", 3, 0, column_stretches=(1, 0, 0)),
                GridMode("two", 2, 1, placements=(
                    GridPlacement(0, 0, 0, column_span=2),
                    GridPlacement(1, 1, 0), GridPlacement(2, 1, 1),
                ), column_stretches=(1, 1)),
                GridMode("one", 1, 2, column_stretches=(1,)),
            ),
        )
        gl.setSpacing(4)
        frame._mirror_error_label = apply_label_role(
            BodyLabel(""), FontRole.UI, color_key="TEXT_PRIMARY",
        )
        frame._mirror_error_label.setWordWrap(True)
        gl.addWidget(frame._mirror_error_label)
        frame._mirror_error_label.hide()
        frame.btn_mirror_diagnostics = TransparentPushButton(
            get_fluent_icon("info.svg"), tr("查看原因"),
        )
        frame.btn_mirror_diagnostics.setProperty("iconName", "info.svg")
        frame.btn_mirror_diagnostics.setToolTip(tr("查看原因"))
        frame.btn_mirror_diagnostics.setAccessibleName(tr("查看原因"))
        frame.btn_mirror_diagnostics.clicked.connect(self._toggle_mirror_diagnostics)
        frame.btn_mirror_diagnostics.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed,
        )
        self._toggle_buttons.append(frame.btn_mirror_diagnostics)
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 0, 0)
        hint_row.setSpacing(8)
        hint_row.addWidget(frame._mirror_hint, 1)
        hint_row.addWidget(frame.btn_mirror_diagnostics)
        gl.addLayout(hint_row)
        frame.btn_mirror_diagnostics.hide()
        frame._mirror_diagnostic_label = apply_label_role(
            BodyLabel(""), FontRole.UI, color_key="TEXT_SECONDARY",
        )
        frame._mirror_diagnostic_label.setWordWrap(True)
        frame._mirror_diagnostic_label.setTextFormat(Qt.TextFormat.PlainText)
        frame._mirror_diagnostic_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse,
        )
        gl.addWidget(frame._mirror_diagnostic_label)
        frame._mirror_diagnostic_label.hide()
        frame._session_list = QWidget(g)
        frame._session_list.setObjectName("remoteSessionList")
        frame._session_list_layout = QVBoxLayout(frame._session_list)
        frame._session_list_layout.setContentsMargins(0, 0, 0, 0)
        frame._session_list_layout.setSpacing(4)
        # 多设备行的操作按钮由各自会话持有，始终保持自然高度和原设备目标。
        frame._session_list_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        frame._session_rows = {}
        gl.addWidget(frame._session_list)
        frame._session_list.hide()
        return g

    def _build_mirroring(self) -> QWidget:
        frame = self._frame
        g = RemoteSection(tr("镜像参数"), divider=True)
        g.setObjectName("remoteMirroringSection")
        gl = g.viewLayout
        frame.mirror_settings = g.view
        g.headerView.hide()
        frame._parameter_labels = []
        for name, items in (
            ("preset", frame._PRESET_NAMES), ("maxsize", frame._SIZES),
            ("fps", frame._FPS), ("buffer", frame._BUFFERS),
            ("bitrate", frame._BITRATES), ("orientation", frame._ORIENTATIONS),
        ):
            combo = frame._combo(items)
            if name in ("maxsize", "orientation"):
                for index, value in enumerate(items):
                    label = (
                        value.removesuffix("p") if name == "maxsize" and value != "Default"
                        else tr(value) if name == "maxsize"
                        else tr("自动") if value == "0" else value
                    )
                    combo.setItemText(index, label)
            # 项目焦点框比原生下拉边框多一像素，提前从内边距预留，防止 Tab
            # 焦点使字段 sizeHint 增长并带动整栏位移；颜色和悬停仍沿用原生样式。
            set_fluent_font_rule(combo, (
                "ComboBox, ComboBox:hover, ComboBox:pressed, ComboBox:disabled, "
                "ComboBox:focus { border-width: 2px; padding: 4px 30px 5px 10px; }"
            ))
            combo.setMinimumHeight(max(36, combo.fontMetrics().height() + 14))
            saved_index = combo.findData(frame._load(name))
            if name == "preset" or saved_index >= 0:
                combo.setCurrentIndex(saved_index)
            combo.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
            frame._refresh_responsive_widget_minimum(combo)
            setattr(frame, name, combo)
        frame.preset.setAccessibleName(tr("预设："))
        frame.fps.setAccessibleName("FPS")
        frame.bitrate.setAccessibleName(tr("码率："))
        frame.maxsize.setToolTip(tr("限制镜像画面的最长边，保持设备画面比例"))
        preset_editor = RemoteChoiceEditor(frame.preset)
        fps_editor = RemoteChoiceEditor(frame.fps, prefer_combo=True)
        bitrate_value = frame._label("")
        bitrate_title = frame._label(tr("码率"))
        bitrate_editor = RemoteBitrateEditor(
            frame.bitrate, bitrate_value, title_label=bitrate_title,
        )
        bitrate_title.setBuddy(bitrate_editor.slider)
        self._editors.extend((preset_editor, fps_editor, bitrate_editor))
        frame.preset_selector = preset_editor.pivot
        frame.fps_selector = fps_editor.pivot
        frame.bitrate_slider = bitrate_editor.slider
        frame.preset_binding = frame._add_responsive_row(
            gl, preset_editor, wide_columns=1,
        )
        frame.codec = frame._status_text(tr("自动视频编码"))
        frame.codec.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        frame.codec.setWordWrap(True)
        frame.codec.setAccessibleName(tr("自动视频编码"))
        frame.codec.setMinimumWidth(0)
        frame.codec.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        frame.codec.setToolTip(tr("启动时按设备能力自动选择视频编码与编码器"))
        frame.codec.setAccessibleDescription(frame.codec.toolTip())
        frame.advanced_options = QWidget()
        frame.advanced_options.setObjectName("advanced_options")
        advanced = QVBoxLayout(frame.advanced_options)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setSpacing(8)
        gl.addWidget(frame.advanced_options)
        frame.mirroring_binding = frame._add_responsive_row(
            advanced, self._field(tr("画面尺寸"), frame.maxsize, "px"),
            self._field(tr("帧率"), fps_editor, "FPS"),
            self._field(tr("视频缓冲"), frame.buffer, "ms"),
            self._field(tr("画面方向"), frame.orientation, "°"),
            spacing=12, adaptive_spacing=False, modes=self._parameter_modes(),
        )
        frame.parameter_binding = frame.mirroring_binding
        frame.encoding_binding = frame._add_responsive_row(
            advanced, bitrate_editor, frame.codec, spacing=24, adaptive_spacing=False,
            policies=(WidthPolicy.SHRINKABLE, WidthPolicy.WRAPPING),
            modes=(GridMode("ratio", 2, 0, column_stretches=(3, 1)),
                   GridMode("stacked", 1, 1, column_stretches=(1,))),
        )
        frame.orientation.setToolTip(tr("锁定屏幕方向（0 为自动）"))
        frame._remote_queue_label = frame._status_text(tr("队列：0"))
        frame._remote_queue_label.setAccessibleName(tr("远程输入队列状态"))
        frame._remote_queue_label.setToolTip(tr("排队：0 · 已发送：0 · 失败：0"))
        frame._remote_queue_label.setAccessibleDescription(frame._remote_queue_label.toolTip())
        self._recording_section = RemoteSection(tr("窗口与录制"), divider=True)
        self._recording_section.headerView.hide()
        gl.addWidget(self._recording_section)
        recording = self._recording_section.viewLayout
        frame.chk_aot = self._switch("窗口置顶", "让镜像窗口保持在其他窗口上方")
        frame.chk_fullscreen = self._switch("全屏", "以全屏模式启动")
        frame.chk_showtouches = self._switch(
            "显示触点", "显示手指在设备屏幕上的触点，不显示电脑鼠标点击",
        )
        frame.chk_noaudio = self._switch("禁用音频", "不转发设备音频")
        frame.chk_noaudio.setChecked(True)
        frame.chk_stayawake = self._switch("保持唤醒", "镜像期间保持设备屏幕唤醒")
        # 窄窗按实际文字宽度回流，不改变开关状态和持久化值。
        frame.more_options = QWidget()
        frame.more_options.setObjectName("more_options")
        more = QVBoxLayout(frame.more_options)
        more.setContentsMargins(0, 0, 0, 0)
        more.setSpacing(8)
        recording.addWidget(frame.more_options)
        frame.chk_turnscreenoff = self._switch("关闭屏幕", "连接后关闭设备屏幕")
        frame.chk_record = self._switch("保存录屏", "将镜像画面录制到文件")
        frame.chk_record.checkedChanged.connect(frame._on_record_toggled)
        frame.chk_noplayback = self._switch("仅录制", "只录制文件，不显示镜像窗口")
        controls = (
            frame.chk_aot, frame.chk_fullscreen, frame.chk_showtouches, frame.chk_stayawake,
            frame.chk_turnscreenoff, frame.chk_noaudio, frame.chk_record, frame.chk_noplayback,
        )
        frame.window_options_binding = frame._add_responsive_row(
            more, *controls, spacing=8, adaptive_spacing=False,
            modes=self._parameter_modes(),
            policies=(WidthPolicy.NATURAL,) * len(controls),
        )
        frame.record_path = frame._status_text("")
        frame.record_path.setAccessibleName(tr("录屏保存路径"))
        frame.record_path.setWordWrap(False)
        frame.record_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        record_policy = frame.record_path.sizePolicy()
        record_policy.setRetainSizeWhenHidden(False)
        frame.record_path.setSizePolicy(record_policy)
        frame.record_path.setMinimumWidth(0)
        recording.addWidget(frame.record_path)
        frame.record_path.hide()
        frame.chk_noplayback.checkedChanged.connect(self._update_mirror_hint)
        return g

    @staticmethod
    def _parameter_modes() -> tuple[GridMode, ...]:
        """字段与开关以四、二、一列回流，不缩小用户设置的字体。"""
        return tuple(GridMode(
            str(columns), columns, rank, column_stretches=(1,) * columns,
            equal_column_groups=(tuple(range(columns)),) if columns > 1 else (),
        ) for rank, columns in enumerate((4, 2, 1)))


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
            label = frame._mirror_device_name(device)
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
        frame._session_list.hide()
        frame._refresh_mirror_presentation()

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
        g = RemoteSection(tr("设备操作"), divider=True)
        g.setObjectName("remoteControlSection")
        outer = g.viewLayout
        outer.setSpacing(4)
        g.headerLabel.hide()
        g.vBoxLayout.setSpacing(4)
        frame._remote_control_buttons = []
        frame._remote_key_buttons = []
        frame._remote_action_buttons = []

        hint = tr("按键与手势可独立使用，无需启动镜像。")
        g.headerLabel.setToolTip(hint)
        g.setAccessibleDescription(hint)
        self._system_section = RemoteSection(tr("系统按键"), divider=True)
        self._system_section.headerView.hide()
        self._system_section.headerLabel.setToolTip(hint)
        self._system_section.setAccessibleDescription(hint)
        system_layout = self._system_section.viewLayout
        system_layout.setSpacing(4)

        self._gesture_section = self._system_section

        def toolbar(layout, buttons, columns):
            binding = frame._add_responsive_row(
                layout, *buttons, spacing=6, adaptive_spacing=False,
                policies=(WidthPolicy.NATURAL,) * len(buttons),
                modes=tuple(GridMode(
                    str(count), count, rank,
                    column_stretches=(1,) * count,
                    equal_column_groups=(
                        (tuple(range(count)),) if count > 1 else ()
                    ),
                ) for rank, count in enumerate(columns)),
            )
            # 回流后按当前行数同步自然下限，避免父布局挤压固定高度的按钮。
            row = binding.widgets()[0].parentWidget()
            grid = row.layout()
            grid.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            self._toolbar_separators.append(RemoteToolbarSeparators(buttons, row))
            return binding

        def keys(specs):
            return tuple(self._remote_key_button(
                tr(label), code, tr("{action}（作用于已选设备）").format(action=tr(label)),
            ) for label, code in specs)

        navigation = keys((("返回", "BACK"), ("主页", "HOME"),
                           ("最近", "RECENTS"), ("电源", "POWER")))
        navigation[-1].setToolTip(tr("点按电源键，切换屏幕开关"))
        navigation[-1].setAccessibleDescription(navigation[-1].toolTip())

        gestures = tuple(frame._remote_action_button(tr(label), action, tr(tooltip))
                         for label, action, tooltip in (
            ("上滑", "swipe_up", "发送向上滑动手势"),
            ("下滑", "swipe_down", "发送向下滑动手势"),
            ("左滑", "swipe_left", "发送向左滑动手势"),
            ("右滑", "swipe_right", "发送向右滑动手势"),
        ))

        # 协议列表保持原有顺序，视觉与焦点顺序由下方工具栏单独声明。
        notifications = tuple(frame._remote_action_button(tr(label), action, tr(tooltip))
                              for label, action, tooltip in (
            ("展开通知", "notif_expand", "展开通知栏"),
            ("收起通知", "notif_collapse", "收起通知栏"),
        ))
        orientation = tuple(frame._remote_action_button(tr(label), action, tr(tooltip))
                            for label, action, tooltip in (
            ("竖屏", "rotate_portrait", "切换到竖屏方向"),
            ("横屏", "rotate_landscape", "切换到横屏方向"),
        ))
        media = keys((("音量 −", "VOL_DOWN"), ("上一个", "MEDIA_PREV"),
                      ("播放/暂停", "MEDIA_PLAY"), ("下一个", "MEDIA_NEXT"), ("音量 +", "VOL_UP")))
        frame._remote_media_buttons = media
        # 媒体传输保持连续顺序；极窄工作区回退单列，不把两类操作拆成混杂的半行。
        self._media_section = RemoteSection(tr("音量与媒体"), divider=True)
        self._media_section.headerView.hide()
        self._media_section.vBoxLayout.setSpacing(4)
        self._media_section.viewLayout.setSpacing(4)
        self._media_section.headerLabel.setToolTip(hint)
        frame._remote_media_binding = toolbar(
            self._media_section.viewLayout, media, (5, 1),
        )
        system = keys((("菜单", "MENU"), ("回车", "ENTER"), ("退格", "DEL"),
                       ("设置", "SETTINGS"), ("相机", "CAMERA"), ("搜索", "SEARCH")))
        frame._remote_navigation_binding = toolbar(
            outer, (*navigation, *orientation, *notifications), (8, 4, 2, 1),
        )
        frame._remote_action_binding = toolbar(
            system_layout, (*gestures, *system), (10, 5, 2, 1),
        )
        # 合并后的网格继续提供既有度量入口，操作参数和按钮对象保持原样。
        frame._remote_screen_binding = frame._remote_navigation_binding
        frame._remote_key_binding = frame._remote_action_binding
        frame._remote_queue_label.setWordWrap(False)
        frame._remote_queue_label.setMinimumWidth(0)
        frame._remote_queue_label.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred,
        )
        apply_label_role(frame._remote_queue_label, FontRole.UI, color_key="TEXT_SECONDARY")
        g.headerLayout.addWidget(frame._remote_queue_label)
        outer.addWidget(self._system_section)
        outer.addWidget(self._media_section)
        frame._remote_primary_key_buttons = (*navigation, *system)
        frame.remote_control_bindings = (
            frame._remote_navigation_binding, frame._remote_action_binding,
            frame._remote_media_binding,
        )
        return g

    def _remote_key_button(self, label: str, code: str, tooltip: str):
        icon = self._frame._KEY_ICONS.get(code, "keyboard.svg")
        b = self._command_button(label, icon, tooltip)
        b.setAccessibleName(label)
        b.setProperty("remoteKey", code)
        b.setFont(self._frame._font_sm)
        b.setIconSize(QSize(20, 20))
        b.setMinimumWidth(56)
        b.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        b.clicked.connect(lambda _, cd=code: self._frame._send_keyevent(cd))
        self._frame._remote_control_buttons.append(b)
        self._frame._remote_key_buttons.append(b)
        return b

    def _remote_action_button(self, label: str, action: str, tooltip: str):
        icon = self._frame._ACTION_ICONS.get(action, "keyboard.svg")
        b = self._command_button(label, icon, tooltip)
        b.setProperty("remoteAction", action)
        b.setFont(self._frame._font_sm)
        b.setIconSize(QSize(20, 20))
        b.setMinimumWidth(56)
        b.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        b.clicked.connect(lambda _, act=action: self._frame._send_remote_action(act))
        self._frame._remote_control_buttons.append(b)
        self._frame._remote_action_buttons.append(b)
        return b

    def _command_button(self, label: str, icon: str, tooltip: str) -> RemoteCommandButton:
        button = RemoteCommandButton()
        configure_button(button, text=label, tooltip=tooltip)
        button.setIcon(get_fluent_icon(icon))
        button.setProperty("iconName", icon)
        button.setAccessibleName(label)
        return button

    def _icon_button(self, label: str, icon: str, tooltip: str) -> ToolButton:
        """无可见文字的动作仍保留名称与提示，图标交由 Fluent 原生控件绘制。"""
        button = ToolButton()
        configure_button(button, text="", tooltip=tooltip)
        button.setAccessibleName(label)
        button.setIcon(get_fluent_icon(icon))
        button.setProperty("iconName", icon)
        button.setIconSize(QSize(20, 20))
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return button

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
            self._frame.chk_noplayback.setChecked(False)
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
