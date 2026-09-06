"""提供 Logcat 功能页的表单构建、主题应用与响应式重排。"""

import weakref

from PySide6.QtCore import QEvent, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
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
from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles.fluent import apply_label_role, configure_button
from gui.styles.typography import FontRole


class _LogcatOutput(PlainTextEdit):
    """尺寸和字体重排可能压缩滚动范围，但不能替用户恢复日志跟随。"""

    def __init__(self, frame):
        self._frame_ref = weakref.ref(frame)
        super().__init__(frame)

    def event(self, event):
        frame = self._frame_ref()
        if frame is None or event.type() not in (QEvent.Type.Resize, QEvent.Type.FontChange):
            return super().event(event)
        was_updating = frame._updating_output
        frame._updating_output = True
        try:
            return super().event(event)
        finally:
            frame._updating_output = was_updating


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
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
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
            BodyLabel(tr("实时 Logcat")), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.status_badge = InfoBadge.info(tr("未连接设备"), self._frame.header_card)
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip(tr("当前日志会话设备的连接状态"))
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = apply_label_role(
            BodyLabel(tr("读取当前设备日志，按应用和等级筛选")),
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
        self._frame._level_label = apply_label_role(BodyLabel(tr("等级")), FontRole.UI)
        self._frame.level_combo = ComboBox()
        self._frame.level_combo.addItem(tr("全部等级"), userData=None)
        for code in ("V", "D", "I", "W", "E", "F"):
            self._frame.level_combo.addItem(tr(LEVEL_LABELS[code]), userData=code)
        self._frame.level_combo.currentIndexChanged.connect(self._frame._rebuild)
        self._frame.level_combo.setMinimumWidth(120)
        self._frame._level_label.setBuddy(self._frame.level_combo)
        self._frame.level_combo.setAccessibleName(tr("最低日志等级"))
        self._frame.level_combo.setToolTip(tr("显示所选等级及更严重的日志"))
        self._frame._package_label = apply_label_role(BodyLabel(tr("应用")), FontRole.UI)
        self._frame.pkg_input = LineEdit()
        self._frame.pkg_input.setPlaceholderText(tr("包名；留空显示全部日志"))
        self._frame._package_label.setBuddy(self._frame.pkg_input)
        self._frame.pkg_input.setAccessibleName(tr("应用包名过滤"))
        self._frame.pkg_input.setToolTip(
            tr("输入包名后按 Enter 应用；清空后按 Enter 查看全部设备日志")
        )
        self._frame.pkg_input.returnPressed.connect(self._frame._submit_package_filter)
        self._frame.btn_get_pkg = PushButton()
        self._frame.btn_get_pkg.setText(tr("当前应用"))
        self._frame.btn_get_pkg.setIcon(FluentIcon.APPLICATION)
        self._frame.btn_get_pkg.setToolTip(tr("获取设备前台应用的包名，并应用到日志过滤"))
        self._frame.btn_get_pkg.setAccessibleName(tr("当前应用"))
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
        btn_row = QHBoxLayout(self._frame.actions)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        self._frame.start_btn = PrimaryPushButton()
        self._frame.start_btn.setText(tr("开始采集"))
        self._frame.start_btn.setToolTip(tr("开始读取当前设备的日志，已有内容会清空"))
        self._frame.start_btn.setIcon(FluentIcon.PLAY)
        self._frame.stop_btn = PrimaryPushButton()
        configure_button(
            self._frame.stop_btn,
            text=tr("停止采集"),
            tooltip=tr("停止当前日志采集，保留页面与已显示的日志"))
        self._frame.stop_btn.setIcon(FluentIcon.PAUSE)
        self._frame.clear_btn = PushButton()
        self._frame.clear_btn.setText(tr("清空"))
        self._frame.clear_btn.setToolTip(tr("清空已缓冲和显示的日志，正在运行的采集继续"))
        self._frame.clear_btn.setIcon(FluentIcon.BROOM)
        self._frame.export_btn = PushButton()
        self._frame.export_btn.setText(tr("导出"))
        self._frame.export_btn.setToolTip(tr("将当前筛选后显示的日志保存为文本文件"))
        self._frame.export_btn.setIcon(FluentIcon.SAVE)
        self._frame.wrap_btn = TogglePushButton()
        self._frame.wrap_btn.setText(tr("自动换行"))
        self._frame.wrap_btn.setIcon(FluentIcon.ALIGNMENT)
        self._frame.wrap_btn.setCheckable(True)
        self._frame.wrap_btn.setChecked(False)
        self._frame.wrap_btn.setToolTip(tr("开启后长日志自动换行；关闭后可横向滚动查看完整行"))
        self._frame.start_btn.clicked.connect(self._frame._start)
        self._frame.stop_btn.clicked.connect(self._frame._stop)
        self._frame.clear_btn.clicked.connect(self._frame._clear)
        self._frame.export_btn.clicked.connect(self._frame._export)
        self._frame.wrap_btn.clicked.connect(self._frame._toggle_wrap)
        self._frame.follow_btn = TogglePushButton(tr("跟随最新"))
        self._frame.follow_btn.setIcon(FluentIcon.DOWN)
        self._frame.follow_btn.setChecked(True)
        self._frame.follow_btn.setToolTip(tr("上翻时暂停跟随；点击后回到最新日志，采集始终继续"))
        self._frame.follow_btn.clicked.connect(self._frame._stream_controller._toggle_follow)
        action_buttons = (
            self._frame.start_btn,
            self._frame.stop_btn,
            self._frame.clear_btn,
            self._frame.export_btn,
            self._frame.wrap_btn,
            self._frame.follow_btn,
        )
        # 顶层窗口默认会让动作按钮响应 Enter；包名输入框已独占 Enter 提交，
        # 所有动作按钮必须关闭默认按钮语义，避免随后再次触发 Current Package 等操作。
        for button in (self._frame.btn_get_pkg, *action_buttons):
            button.setAutoDefault(False)
            button.setDefault(False)
        for button in (self._frame.start_btn, self._frame.stop_btn):
            btn_row.addWidget(button)
        btn_row.addStretch(1)
        self._frame._action_specs = tuple((button, button.text()) for button in action_buttons)
        for button, text in self._frame._action_specs:
            button.setAccessibleName(text)

        layout.addWidget(self._frame.actions)
        self._frame.status_bar = apply_label_role(
            CaptionLabel(tr("点击开始采集，读取当前设备日志")), FontRole.UI,
            color_key="TEXT_SECONDARY"
        )
        self._frame.status_bar.setAccessibleName(tr("日志采集状态"))
        self._frame.status_bar.setWordWrap(True)

        self._frame.reading_tools = QWidget(self._frame)
        reading_row = QHBoxLayout(self._frame.reading_tools)
        reading_row.setContentsMargins(0, 0, 0, 0)
        reading_row.setSpacing(8)
        for button in (self._frame.follow_btn, self._frame.wrap_btn,
                       self._frame.export_btn, self._frame.clear_btn):
            reading_row.addWidget(button)
        btn_row.addWidget(self._frame.reading_tools)
        self._frame.wrap_btn.clicked.connect(self._reflow_filters)

        self._frame.output = _LogcatOutput(self._frame)
        self._frame.output.setReadOnly(True)
        self._frame.output.setLineWrapMode(PlainTextEdit.LineWrapMode.NoWrap)
        self._frame.output.setUndoRedoEnabled(False)
        self._frame.output.setAccessibleName(tr("设备日志输出"))
        self._frame.output.setPlaceholderText(tr("日志会显示在这里。可选择应用或日志等级后开始采集。"))
        self._frame.output.document().setDocumentMargin(12)
        self._frame.output.document().setMaximumBlockCount(self._frame.MAX_BUFFER)
        layout.addWidget(self._frame.output, 1)

        self._frame.reading_status = apply_label_role(
            CaptionLabel(), FontRole.UI, color_key="TEXT_SECONDARY"
        )
        self._frame.reading_status.setWordWrap(True)
        self._frame.reading_status.setToolTip(
            tr("仅保留最近 {limit} 行原始日志，超出后移除最旧记录；导出保存当前筛选结果").format(
                limit=self._frame.MAX_BUFFER
            )
        )
        footer = QHBoxLayout()
        footer.setSpacing(16)
        footer.addWidget(self._frame.status_bar, 1)
        footer.addWidget(self._frame.reading_status, 1)
        layout.addLayout(footer)
        self._frame.output.verticalScrollBar().valueChanged.connect(
            self._frame._stream_controller._on_output_scroll
        )

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
        spacing = layout.horizontalSpacing()
        root_layout = self._frame.layout()
        root_margins = root_layout.contentsMargins() if root_layout is not None else None
        available_width = self._frame.contentsRect().width()
        if root_margins is not None:
            available_width -= root_margins.left() + root_margins.right()
        level = self._frame.level_combo
        preferred_level = max(120, max(
            level.fontMetrics().horizontalAdvance(level.itemText(index))
            for index in range(level.count())
        ) + 48)
        package_button = self._frame.btn_get_pkg
        package_button.setText(tr("当前应用"))
        package_button.setMinimumWidth(0)
        package_button.setMaximumWidth(16777215)
        full_package_width = package_button.sizeHint().width()
        labels = (self._frame._level_label, self._frame._package_label)
        required = (preferred_level + full_package_width + 120 + spacing * 4
                    + sum(label.sizeHint().width() for label in labels))
        compact = available_width < required
        for label in labels:
            label.setVisible(not compact)
        if compact:
            package_button.setText("")
        package_button.setFixedWidth(
            max(32, package_button.fontMetrics().height() + 16)
            if compact else full_package_width
        )
        level.setFixedWidth(
            min(preferred_level, max(120, int(available_width * .45)))
            if compact else preferred_level
        )
        self._frame.pkg_input.setMinimumWidth(80)
        self._frame.pkg_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        while layout.count():
            layout.takeAt(0)
        for column in range(5):
            layout.setColumnStretch(column, 0)
        for column, control in enumerate(self._frame._filter_controls):
            layout.addWidget(control, 0, column)
        layout.setColumnStretch(3, 1)
        self._reflow_action_buttons(available_width)
        self._frame.layout().activate()
        self._frame._reflowing_filters = False

    def _reflow_action_buttons(self, available_width: int) -> None:
        """操作保持在同一行；窄屏先收起阅读按钮文字，再收起采集按钮文字。"""
        specs = getattr(self._frame, "_action_specs", ())
        if not specs:
            return
        for button, text in specs:
            button.setText(text)
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
        widths = [button.sizeHint().width() for button, _text in specs]
        sides = [max(32, button.fontMetrics().height() + 16) for button, _text in specs]
        compact_reading = sum(widths) + 6 * 8 > available_width
        compact_capture = sum(widths[:2]) + sum(sides[2:]) + 6 * 8 > available_width
        for index, (button, _text) in enumerate(specs):
            compact = compact_capture if index < 2 else compact_reading
            if compact:
                button.setText("")
            button.setFixedWidth(sides[index] if compact else widths[index])

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
            self._frame.status_badge.setText(tr("设备已连接") if has_device else tr("未连接设备"))
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
        for label in (self._frame._level_label, self._frame._package_label,
                      self._frame.status_bar, self._frame.reading_status):
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
        self._frame.output.setMinimumHeight(
            max(180, self._frame.output.fontMetrics().lineSpacing() * 6 + 26)
        )
        # 状态信息直接使用 qfluentwidgets CaptionLabel，并同步语义字体。
        self._apply_action_button_styles()
        self._reflow_filters()
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
                       self._frame.clear_btn, self._frame.export_btn, self._frame.wrap_btn,
                       self._frame.follow_btn):
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
