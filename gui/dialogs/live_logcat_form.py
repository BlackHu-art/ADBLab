"""提供 Logcat 功能页的表单构建、主题应用与响应式重排。"""

import weakref

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FlowLayout,
    FluentIcon,
    InfoBadge,
    InfoLevel,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    TogglePushButton,
    setCustomStyleSheet,
)

from gui.dialogs.live_logcat_highlighter import LogcatHighlighter
from gui.dialogs.live_logcat_worker import LEVEL_LABELS
from gui.styles import BaseStyles
from gui.styles.fluent import apply_label_role, configure_button
from gui.styles.typography import FontRole


class LiveLogcatForm:
    """组合进 LiveLogcatPage 的表单控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        # 控制器由页面持有，反向使用弱引用，避免 Qt 包装对象进入 Python 引用环。
        self._frame_ref = weakref.ref(frame)

    @property
    def _frame(self):
        frame = self._frame_ref()
        if frame is None:
            raise RuntimeError("LiveLogcatPage has been released")
        return frame

    def _init_ui(self):
        layout = QVBoxLayout(self._frame)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 8, 8, 8)

        # 独立页保留标题，工作区经公开嵌入钩子隐藏这张卡片。
        self._frame.header_card = CardWidget()
        self._frame.header_card.setObjectName("dialogHeaderCard")
        self._frame.header_card.setBorderRadius(BaseStyles.RADIUS_LG)
        hl = QVBoxLayout(self._frame.header_card)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._frame.dialog_title = apply_label_role(
            BodyLabel("实时 Logcat"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.status_badge = InfoBadge.info("未连接设备", self._frame.header_card)
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip("当前日志会话设备的连接状态")
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = apply_label_role(
            BodyLabel("读取当前设备日志，按应用和等级筛选"),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        self._frame.dialog_subtitle.setObjectName("dialogSubtitle")
        self._frame.dialog_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self._frame.dialog_subtitle)
        layout.addWidget(self._frame.header_card)

        filters = QGridLayout()
        filters.setHorizontalSpacing(8)
        filters.setVerticalSpacing(8)
        self._frame._filters_layout = filters
        self._frame._level_label = apply_label_role(BodyLabel("等级"), FontRole.UI)
        self._frame.level_combo = ComboBox()
        self._frame.level_combo.addItem("全部等级", userData=None)
        for code in ("V", "D", "I", "W", "E", "F"):
            self._frame.level_combo.addItem(LEVEL_LABELS[code], code)
        self._frame.level_combo.currentIndexChanged.connect(self._frame._rebuild)
        self._frame.level_combo.setMinimumWidth(120)
        self._frame._level_label.setBuddy(self._frame.level_combo)
        self._frame.level_combo.setAccessibleName("最低日志等级")
        self._frame.level_combo.setToolTip("显示所选等级及更严重的日志")
        self._frame._package_label = apply_label_role(BodyLabel("应用"), FontRole.UI)
        self._frame.pkg_input = LineEdit()
        self._frame.pkg_input.setPlaceholderText("包名；留空显示全部日志")
        self._frame._package_label.setBuddy(self._frame.pkg_input)
        self._frame.pkg_input.setAccessibleName("应用包名过滤")
        self._frame.pkg_input.setToolTip("输入包名后按 Enter 应用；清空后按 Enter 查看全部设备日志")
        self._frame.pkg_input.returnPressed.connect(self._frame._submit_package_filter)
        self._frame.btn_get_pkg = PushButton()
        self._frame.btn_get_pkg.setText("当前应用")
        self._frame.btn_get_pkg.setIcon(FluentIcon.APPLICATION)
        self._frame.btn_get_pkg.setToolTip("获取设备前台应用的包名，并应用到日志过滤")
        self._frame.btn_get_pkg.setMinimumWidth(120)
        self._frame.btn_get_pkg.clicked.connect(self._frame._fetch_current_pkg)
        self._frame._filter_controls = (
            self._frame._level_label,
            self._frame.level_combo,
            self._frame._package_label,
            self._frame.pkg_input,
            self._frame.btn_get_pkg,
        )
        self._reflow_filters()
        layout.addLayout(filters)

        self._frame.actions = QWidget(self._frame)
        btn_row = FlowLayout(self._frame.actions, needAni=False)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setHorizontalSpacing(8)
        btn_row.setVerticalSpacing(8)
        self._frame.start_btn = PrimaryPushButton()
        self._frame.start_btn.setText("开始采集")
        self._frame.start_btn.setToolTip("开始读取当前设备的日志，已有内容会清空")
        self._frame.start_btn.setIcon(FluentIcon.PLAY)
        self._frame.stop_btn = PrimaryPushButton()
        configure_button(
            self._frame.stop_btn,
            text="停止采集",
            tooltip="停止当前日志采集，保留页面与已显示的日志")
        self._frame.stop_btn.setIcon(FluentIcon.PAUSE)
        self._frame.clear_btn = PushButton()
        self._frame.clear_btn.setText("清空")
        self._frame.clear_btn.setToolTip("清空已缓冲和显示的日志，正在运行的采集继续")
        self._frame.clear_btn.setIcon(FluentIcon.BROOM)
        self._frame.export_btn = PushButton()
        self._frame.export_btn.setText("导出")
        self._frame.export_btn.setToolTip("将当前筛选后显示的日志保存为文本文件")
        self._frame.export_btn.setIcon(FluentIcon.SAVE)
        self._frame.wrap_btn = TogglePushButton()
        self._frame.wrap_btn.setText("自动换行")
        self._frame.wrap_btn.setIcon(FluentIcon.ALIGNMENT)
        self._frame.wrap_btn.setCheckable(True)
        self._frame.wrap_btn.setChecked(True)
        self._frame.wrap_btn.setToolTip("开启后长日志自动换行；关闭后可横向滚动查看完整行")
        self._frame.start_btn.clicked.connect(self._frame._start)
        self._frame.stop_btn.clicked.connect(self._frame._stop)
        self._frame.clear_btn.clicked.connect(self._frame._clear)
        self._frame.export_btn.clicked.connect(self._frame._export)
        self._frame.wrap_btn.clicked.connect(self._frame._toggle_wrap)
        action_buttons = (
            self._frame.start_btn,
            self._frame.stop_btn,
            self._frame.clear_btn,
            self._frame.export_btn,
            self._frame.wrap_btn,
        )
        # 顶层窗口默认会让动作按钮响应 Enter；包名输入框已独占 Enter 提交，
        # 所有动作按钮必须关闭默认按钮语义，避免随后再次触发 Current Package 等操作。
        for button in (self._frame.btn_get_pkg, *action_buttons):
            button.setAutoDefault(False)
            button.setDefault(False)
        for button in action_buttons:
            btn_row.addWidget(button)

        layout.addWidget(self._frame.actions)
        self._frame.status_bar = apply_label_role(
            CaptionLabel("点击开始采集，读取当前设备日志"), FontRole.UI,
            color_key="TEXT_SECONDARY"
        )
        self._frame.status_bar.setAccessibleName("日志采集状态")
        self._frame.status_bar.setWordWrap(True)
        layout.addWidget(self._frame.status_bar)

        self._frame.output = PlainTextEdit()
        self._frame.output.setReadOnly(True)
        self._frame.output.setLineWrapMode(PlainTextEdit.LineWrapMode.WidgetWidth)
        self._frame.output.setUndoRedoEnabled(False)
        self._frame.output.setAccessibleName("设备日志输出")
        self._frame.output.setPlaceholderText("日志会显示在这里。可选择应用或日志等级后开始采集。")
        self._frame.output.document().setDocumentMargin(12)
        self._frame.output.document().setMaximumBlockCount(self._frame.MAX_BUFFER)
        layout.addWidget(self._frame.output, 1)

        self._frame.highlighter = LogcatHighlighter(self._frame.output.document())
        self._set_running_actions(False)
        self._frame._update_content_actions()

    @staticmethod
    def _filter_minimum_width(widget) -> int:
        return max(widget.minimumSize().width(), widget.minimumSizeHint().width())

    def _reflow_filters(self) -> None:
        if self._frame._reflowing_filters:
            return
        self._frame._reflowing_filters = True
        layout = self._frame._filters_layout
        controls = self._frame._filter_controls
        spacing = layout.horizontalSpacing()
        required_width = sum(self._filter_minimum_width(control) for control in controls)
        required_width += spacing * (len(controls) - 1)
        root_layout = self._frame.layout()
        root_margins = root_layout.contentsMargins() if root_layout is not None else None
        available_width = self._frame.contentsRect().width()
        if root_margins is not None:
            available_width -= root_margins.left() + root_margins.right()
        # 未嵌入父布局前 QWidget 的默认宽度并非可用视口，先用可换行下限。
        wide = self._frame.isVisible() and max(0, available_width) >= required_width

        while layout.count():
            layout.takeAt(0)
        for column in range(5):
            layout.setColumnStretch(column, 0)
        for row in range(4):
            layout.setRowStretch(row, 0)

        if wide:
            for column, control in enumerate(controls):
                layout.addWidget(control, 0, column)
            layout.setColumnStretch(3, 2)
            self._frame.layout().activate()
            self._frame._reflowing_filters = False
            return

        layout.addWidget(self._frame._level_label, 0, 0)
        layout.addWidget(self._frame.level_combo, 0, 1)
        layout.addWidget(self._frame._package_label, 1, 0)
        layout.addWidget(self._frame.pkg_input, 1, 1)
        layout.addWidget(self._frame.btn_get_pkg, 2, 1)
        layout.setColumnStretch(1, 1)
        self._frame.layout().activate()
        self._frame._reflowing_filters = False

    def _apply_theme(self, _value=None):
        BS = BaseStyles
        self._frame.setWindowIcon(FluentIcon.SCROLL.icon())
        if hasattr(self._frame, "header_card"):
            self._frame.dialog_title.setFont(BS.font_for_role(FontRole.TITLE))
            self._frame.dialog_subtitle.setFont(BS.font_for_role(FontRole.UI))
            self._frame.status_badge.setFont(BS.font_for_role(FontRole.UI))
            has_device = bool(
                self._frame.device_ip
                and getattr(self._frame, "_device_connected", True)
            )
            self._frame.status_badge.setText("设备已连接" if has_device else "未连接设备")
            self._frame.status_badge.setLevel(
                InfoLevel.SUCCESS if has_device else InfoLevel.INFOAMTION
            )
        ui_font = BS.font_for_role(FontRole.UI)
        mono_font = BS.font_for_role(FontRole.MONO)
        log_font = BS.font_for_role(FontRole.LOG)
        self._frame.setFont(ui_font)
        # qfluentwidgets ComboBox/LineEdit 默认像素字号，这里显式覆盖为点位角色字体。
        self._frame.level_combo.setFont(ui_font)
        self._frame.pkg_input.setFont(mono_font)
        for widget in (self._frame.level_combo, self._frame.pkg_input):
            widget.setMaximumHeight(16777215)
            widget.setMinimumHeight(widget.fontMetrics().height() + 16)
        for label in (self._frame._level_label, self._frame._package_label, self._frame.status_bar):
            label.setFont(ui_font)
        # 使用日志专用表面，避免透明输入背景降低小字号日志的等级颜色对比度。
        styles = []
        for theme in ("Light", "Dark"):
            styles.append(
                "PlainTextEdit {"
                f"background: {BS.color_for(theme, 'LOG_BACKGROUND')};"
                f"color: {BS.color_for(theme, 'LOG_TEXT_COLOR')};"
                f"border: 1px solid {BS.color_for(theme, 'BORDER_COLOR')};"
                "border-radius: 6px;}"
            )
        setCustomStyleSheet(self._frame.output, *styles)
        self._frame.output.setFont(log_font)
        self._frame.output.document().setDefaultFont(log_font)
        self._frame.output.setMinimumHeight(self._frame.output.fontMetrics().lineSpacing() * 6 + 26)
        # 状态信息直接使用 qfluentwidgets CaptionLabel，并同步语义字体。
        self._apply_action_button_styles()
        self._frame.level_combo.setMinimumWidth(120)
        self._frame.level_combo.setMinimumWidth(
            max(120, self._frame.level_combo.sizeHint().width())
        )
        self._frame.btn_get_pkg.setMinimumWidth(120)
        self._frame.btn_get_pkg.setMinimumWidth(
            max(120, self._frame.btn_get_pkg.sizeHint().width())
        )
        self._reflow_filters()

        # Logcat 等级颜色跟随当前主题更新。
        debug_color = BS.color("TEXT_SECONDARY" if BS.resolved_theme() == "Light" else "LOG_DEBUG")
        hl_colors = {
            "V": debug_color,
            "D": debug_color,
            "I": BS.color("LOG_INFO"),
            "W": BS.color("LOG_WARNING"),
            "E": QColor(BS.color("LOG_ERROR")).darker(110).name()
            if BS.resolved_theme() == "Light" else BS.color("LOG_ERROR"),
            "F": BS.color("LOG_CRITICAL"),
            "S": BS.color("TEXT_SECONDARY"),
            "U": BS.color("TEXT_PRIMARY"),
        }
        self._frame.highlighter.set_theme(hl_colors)
        self._frame.updateGeometry()

    def _apply_action_button_styles(self) -> None:
        """保留 Fluent 原生状态绘制，并使动作高度随真实字号增长。"""
        for button in (self._frame.btn_get_pkg, self._frame.start_btn, self._frame.stop_btn,
                       self._frame.clear_btn, self._frame.export_btn, self._frame.wrap_btn):
            button.setFont(BaseStyles.font_for_role(FontRole.UI))
            button.setIconSize(QSize(18, 18))
            button.setMaximumHeight(16777215)
            button.setMinimumHeight(button.fontMetrics().height() + 16)

    def resizeEvent(self, event):
        self._reflow_filters()
        self._frame._filter_reflow_timer.start(0)

    def _set_running_actions(self, running: bool, *, stopping: bool = False) -> None:
        """统一维护日志采集按钮状态，避免异步路径出现状态分叉。"""

        self._frame._logcat_stopping = stopping
        has_device = self._frame._can_operate_device()
        self._frame.start_btn.setEnabled(has_device and not running)
        self._frame.stop_btn.setEnabled(running and not stopping)
        package_lookup_active = bool(
            self._frame._pkg_worker is not None and self._frame._pkg_worker.isRunning()
        )
        self._frame.btn_get_pkg.setEnabled(
            has_device and not stopping and not package_lookup_active
        )
        self._apply_action_button_styles()
