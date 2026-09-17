"""提供 Logcat 功能页的表单构建、主题应用与响应式重排。"""

import weakref

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    CommandBar,
    FluentIcon,
    InfoBadge,
    InfoLevel,
    LineEdit,
    PlainTextEdit,
    ProgressRing,
    TransparentPushButton,
)

from gui.dialogs.live_logcat_highlighter import LogcatHighlighter
from gui.dialogs.live_logcat_material import LogcatMaterial
from gui.dialogs.live_logcat_worker import LEVEL_LABELS
from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles.fluent import apply_focus_indicator, apply_label_role
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


class _LogcatStatusLabel(CaptionLabel):
    """顶部状态只占一行，省略仅影响绘制，悬停和辅助描述保留完整信息。"""

    def setText(self, text: str, compact_text: str | None = None) -> None:
        self._compact_text = text if compact_text is None else compact_text
        super().setText(text)
        self.setToolTip(text)
        self.setAccessibleDescription(text)
        self.update()

    def compactText(self) -> str:
        """显示摘要与完整诊断分开，避免在窄工具栏展示整段操作说明。"""
        return getattr(self, "_compact_text", self.text())

    def minimumSizeHint(self) -> QSize:
        return QSize(8, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(BaseStyles.get_color("TEXT_SECONDARY"))
        painter.drawText(
            self.contentsRect(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            self.fontMetrics().elidedText(
                self.compactText().replace("\n", " "), Qt.TextElideMode.ElideRight,
                self.contentsRect().width(),
            ),
        )
        painter.end()


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
        self._frame.btn_get_pkg = TransparentPushButton()
        self._frame.btn_get_pkg.setAutoDefault(False)
        self._frame.btn_get_pkg.setDefault(False)
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
        bar = self._frame._command_bar = CommandBar(self._frame.actions)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.setButtonTight(True)
        bar.setIconSize(QSize(16, 16))
        bar.moreButton.setToolTip(tr("更多"))
        bar.moreButton.setAccessibleName(tr("更多"))
        bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._frame._command_icons = []
        for name, icon, title, short_title, tooltip, callback in (
            ("start", FluentIcon.PLAY, "开始采集", "开始", "开始读取当前设备的日志，已有内容会清空",
             self._frame._start),
            ("stop", FluentIcon.PAUSE, "停止采集", "停止",
             "停止当前日志采集，保留页面与已显示的日志",
             self._frame._stop),
            ("follow", FluentIcon.DOWN, "跟随最新", "跟随",
             "上翻时暂停跟随；点击后回到最新日志，采集始终继续",
             self._frame._stream_controller._toggle_follow),
            ("wrap", FluentIcon.ALIGNMENT, "自动换行", "换行",
             "开启后长日志自动换行；关闭后可横向滚动查看完整行",
             self._frame._toggle_wrap),
            ("export", FluentIcon.SAVE, "导出", "导出", "将当前筛选后显示的日志保存为文本文件",
             self._frame._export),
            ("clear", FluentIcon.BROOM, "清空", "清空",
             "清空已缓冲和显示的日志，正在运行的采集继续",
             self._frame._clear),
        ):
            if name in ("follow", "export"):
                bar.addSeparator()
            action = Action(icon.icon(), tr(short_title), self._frame)
            action.setProperty("accessibleName", tr(title))
            action.setToolTip(tr(tooltip))
            action.setCheckable(name in ("follow", "wrap"))
            action.setChecked(name == "follow")
            action.triggered.connect(callback)
            setattr(self._frame, f"{name}_action", action)
            setattr(self._frame, f"{name}_btn", bar.addAction(action))
            self._frame._command_icons.append((action, icon))
        btn_row.addWidget(bar, 1)

        self._frame._status_group = QWidget(self._frame.actions)
        status_layout = QHBoxLayout(self._frame._status_group)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        layout.addWidget(self._frame.actions)
        self._frame.status_bar = apply_label_role(
            _LogcatStatusLabel(), FontRole.UI_SMALL,
            color_key="TEXT_SECONDARY"
        )
        self._frame.status_bar.setText(tr("点击开始采集，读取当前设备日志"), tr("待采集"))
        self._frame.status_bar.setAccessibleName(tr("日志采集状态"))
        self._frame.status_bar.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )
        status_layout.addWidget(self._frame.status_bar, 1)
        # 缓存占用是确定进度；批次刷新不启动动画，也不额外占用一行。
        ring = self._frame.cache_ring = ProgressRing(self._frame._status_group, useAni=False)
        ring.setFixedSize(28, 28)
        ring.setStrokeWidth(3)
        ring.setTextVisible(False)
        ring.setRange(0, self._frame.MAX_BUFFER)
        ring.setValue(0)
        ring.setAccessibleName(tr("日志缓存"))
        status_layout.addWidget(ring, 0, Qt.AlignmentFlag.AlignVCenter)
        btn_row.addWidget(self._frame._status_group)

        self._frame.output = _LogcatOutput(self._frame)
        self._frame.output.setReadOnly(True)
        self._frame.output.setLineWrapMode(PlainTextEdit.LineWrapMode.NoWrap)
        self._frame.output.setUndoRedoEnabled(False)
        self._frame.output.setAccessibleName(tr("设备日志输出"))
        self._frame.output.setPlaceholderText(tr("日志会显示在这里。可选择应用或日志等级后开始采集。"))
        self._frame.output.document().setDocumentMargin(12)
        self._frame.output.document().setMaximumBlockCount(self._frame.MAX_BUFFER)
        layout.addWidget(self._frame.output, 1)

        self._material = LogcatMaterial(self._frame, self._frame.output)
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
        """命令栏按字体保留自然尺寸，次要命令通过原生溢出菜单保持可达。"""
        bar = getattr(self._frame, "_command_bar", None)
        if bar is None:
            return
        for button in (*bar.commandButtons, bar.moreButton):
            button.setFont(bar.font())
            hint = button.sizeHint()
            button.setFixedSize(
                hint.width(), max(hint.height(), button.fontMetrics().height() + 16),
            )
            if button is not bar.moreButton:
                button.setAccessibleName(button.action().property("accessibleName"))
                button.setAccessibleDescription(button.action().toolTip())
            apply_focus_indicator(button, selector="QToolButton")
        bar.setFixedHeight(max(button.height() for button in (*bar.commandButtons, bar.moreButton)))
        bar.updateGeometry()
        if hasattr(self._frame, "_status_group"):
            status = self._frame.status_bar
            # 预留约六个全宽字符，长错误仅省略绘制，按钮不足时使用原生菜单。
            preferred = status.fontMetrics().horizontalAdvance("\u3000" * 6) + 36
            self._frame._status_group.setFixedWidth(min(preferred, max(100, available_width // 4)))

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
        for label in (self._frame._level_label, self._frame._package_label):
            label.setFont(ui_font)
        self._frame.status_bar.setFont(BS.font_for_role(FontRole.UI_SMALL))
        self._frame.cache_ring.update()
        self._frame._command_bar.setFont(ui_font)
        for action, icon in self._frame._command_icons:
            action.setIcon(icon.icon())
        self._frame.btn_get_pkg.setIcon(FluentIcon.APPLICATION.icon())
        self._frame.output.setFont(log_font)
        self._frame.output.document().setDefaultFont(log_font)
        self._material.refresh(force=True)
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
        button = self._frame.btn_get_pkg
        button.setFont(BaseStyles.font_for_role(FontRole.UI))
        button.setIconSize(QSize(16, 16))
        button.setMaximumHeight(16777215)
        button.setMinimumHeight(button.fontMetrics().height() + 16)
        apply_focus_indicator(button, selector="QPushButton")

    def resizeEvent(self, event):
        self._reflow_filters()
        self._frame._filter_reflow_timer.start(0)

    def _set_running_actions(self, running: bool, *, stopping: bool = False) -> None:
        """统一维护日志采集按钮状态，避免异步路径出现状态分叉。"""

        self._frame._logcat_stopping = stopping
        has_device = self._frame._can_operate_device()
        self._frame.start_action.setEnabled(has_device and not running)
        self._frame.stop_action.setEnabled(running and not stopping)
        package_lookup_active = bool(
            self._frame._pkg_worker is not None and self._frame._pkg_worker.isRunning()
        )
        self._frame.btn_get_pkg.setEnabled(
            has_device and not stopping and not package_lookup_active
        )
        self._apply_action_button_styles()
