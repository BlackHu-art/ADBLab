"""提供 Logcat 功能页的表单构建、主题应用与响应式重排。"""

import weakref

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBadge,
    InfoLevel,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    TogglePushButton,
)

from gui.dialogs.live_logcat_highlighter import LogcatHighlighter
from gui.dialogs.live_logcat_worker import LEVEL_LABELS
from gui.styles import BaseStyles
from gui.styles.fluent import apply_label_role, configure_button
from gui.styles.icon_loader import get_themed_icon
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
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        # ── 页头卡片：标题、副标题与设备连接状态徽标 ─────────────────────
        # 视觉重设计：页面内容顶部统一为 Fluent CardWidget 卡片页头。
        # 副标题保持 UI 字体角色并以 TEXT_SECONDARY 次级文字色维持视觉层级。
        self._frame.header_card = CardWidget()
        self._frame.header_card.setObjectName("dialogHeaderCard")
        self._frame.header_card.setBorderRadius(BaseStyles.RADIUS_LG)
        hl = QVBoxLayout(self._frame.header_card)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._frame.dialog_title = apply_label_role(
            BodyLabel("Live Logcat"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.status_badge = InfoBadge.info("No device", self._frame.header_card)
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip("Device availability for log streaming")
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = apply_label_role(
            BodyLabel("Stream and filter device log messages"),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        self._frame.dialog_subtitle.setObjectName("dialogSubtitle")
        self._frame.dialog_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self._frame.dialog_subtitle)
        layout.addWidget(self._frame.header_card)

        filters = QGridLayout()
        filters.setHorizontalSpacing(6)
        filters.setVerticalSpacing(4)
        self._frame._filters_layout = filters
        self._frame._level_label = apply_label_role(BodyLabel("Level:"), FontRole.UI)
        self._frame.level_combo = ComboBox()
        self._frame.level_combo.addItem("All", userData=None)
        for code in ("V", "D", "I", "W", "E", "F"):
            self._frame.level_combo.addItem(LEVEL_LABELS[code], code)
        self._frame.level_combo.currentIndexChanged.connect(self._frame._rebuild)
        self._frame.level_combo.setMinimumWidth(120)
        self._frame._level_label.setBuddy(self._frame.level_combo)
        self._frame.level_combo.setAccessibleName("Log level")
        self._frame._package_label = apply_label_role(BodyLabel("Package:"), FontRole.UI)
        self._frame.pkg_input = LineEdit()
        self._frame.pkg_input.setPlaceholderText("com.example.app")
        self._frame._package_label.setBuddy(self._frame.pkg_input)
        self._frame.pkg_input.setAccessibleName("Package filter")
        self._frame.pkg_input.setToolTip("Enter a package name, then press Enter to apply")
        self._frame.pkg_input.returnPressed.connect(self._frame._submit_package_filter)
        self._frame.btn_get_pkg = PushButton()
        self._frame.btn_get_pkg.setText("Current Package")
        self._frame.btn_get_pkg.setIcon(get_themed_icon("target.svg"))
        self._frame.btn_get_pkg.setProperty("iconName", "target.svg")
        self._frame.btn_get_pkg.setIconSize(QSize(14, 14))
        self._frame.btn_get_pkg.setToolTip("Fetch current foreground app package")
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

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._frame.start_btn = PrimaryPushButton()
        self._frame.start_btn.setText("Start")
        self._frame.start_btn.setToolTip("Start streaming device log messages")
        self._frame.start_btn.setIcon(get_themed_icon("play.svg"))
        self._frame.start_btn.setProperty("iconName", "play.svg")
        self._frame.start_btn.setIconSize(QSize(14, 14))
        self._frame.stop_btn = PrimaryPushButton()
        configure_button(
            self._frame.stop_btn,
            text="Stop",
            tooltip="Stop the active log stream",
            danger=True,
        )
        self._frame.stop_btn.setIcon(get_themed_icon("stop-circle.svg"))
        self._frame.stop_btn.setProperty("iconName", "stop-circle.svg")
        self._frame.stop_btn.setIconSize(QSize(14, 14))
        self._frame.clear_btn = PushButton()
        self._frame.clear_btn.setText("Clear")
        self._frame.clear_btn.setToolTip("Remove all displayed log messages")
        self._frame.clear_btn.setIcon(get_themed_icon("broom.svg"))
        self._frame.clear_btn.setProperty("iconName", "broom.svg")
        self._frame.clear_btn.setIconSize(QSize(14, 14))
        self._frame.export_btn = PushButton()
        self._frame.export_btn.setText("Export")
        self._frame.export_btn.setToolTip("Save the displayed log messages to a file")
        self._frame.export_btn.setIcon(get_themed_icon("file-arrow-down.svg"))
        self._frame.export_btn.setProperty("iconName", "file-arrow-down.svg")
        self._frame.export_btn.setIconSize(QSize(14, 14))
        self._frame.wrap_btn = TogglePushButton()
        self._frame.wrap_btn.setText("Wrap")
        self._frame.wrap_btn.setIcon(get_themed_icon("arrows-left-right.svg"))
        self._frame.wrap_btn.setProperty("iconName", "arrows-left-right.svg")
        self._frame.wrap_btn.setIconSize(QSize(14, 14))
        self._frame.wrap_btn.setCheckable(True)
        self._frame.wrap_btn.setChecked(True)
        self._frame.wrap_btn.setToolTip("Wrap long log lines within the view")
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

        self._frame.status_bar = apply_label_role(
            CaptionLabel("Ready"), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self._frame.status_bar.setAccessibleName("Logcat status")
        btn_row.addWidget(self._frame.status_bar, 1)
        layout.addLayout(btn_row)

        self._frame.output = PlainTextEdit()
        self._frame.output.setReadOnly(True)
        self._frame.output.setLineWrapMode(PlainTextEdit.LineWrapMode.WidgetWidth)
        self._frame.output.setUndoRedoEnabled(False)
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
        wide = max(0, available_width) >= required_width

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
        layout.addWidget(self._frame.level_combo, 1, 0, 1, 2)
        layout.addWidget(self._frame._package_label, 2, 0)
        layout.addWidget(self._frame.pkg_input, 2, 1)
        layout.addWidget(self._frame.btn_get_pkg, 3, 0, 1, 2)
        layout.setColumnStretch(1, 1)
        self._frame.layout().activate()
        self._frame._reflowing_filters = False

    def _apply_theme(self, _value=None):
        BS = BaseStyles
        self._frame.setWindowIcon(get_themed_icon(self._frame._window_icon_name))
        # 视觉重设计：页头卡片由 CardWidget 自绘制随主题切换，徽标按 device_ip 刷新。
        if hasattr(self._frame, "header_card"):
            self._frame.dialog_title.setFont(BS.font_for_role(FontRole.TITLE))
            self._frame.dialog_subtitle.setFont(BS.font_for_role(FontRole.UI))
            self._frame.status_badge.setFont(BS.font_for_role(FontRole.UI))
            has_device = bool(
                self._frame.device_ip
                and getattr(self._frame, "_device_connected", True)
            )
            self._frame.status_badge.setText("Ready" if has_device else "No device")
            self._frame.status_badge.setLevel(
                InfoLevel.SUCCESS if has_device else InfoLevel.INFOAMTION
            )
        for button in (
            self._frame.btn_get_pkg,
            self._frame.start_btn,
            self._frame.stop_btn,
            self._frame.clear_btn,
            self._frame.export_btn,
            self._frame.wrap_btn,
        ):
            icon_name = button.property("iconName")
            if icon_name:
                button.setIcon(get_themed_icon(str(icon_name)))
        ui_font = BS.font_for_role(FontRole.UI)
        mono_font = BS.font_for_role(FontRole.MONO)
        log_font = BS.font_for_role(FontRole.LOG)
        self._frame.setFont(ui_font)
        # qfluentwidgets ComboBox/LineEdit 默认像素字号，这里显式覆盖为点位角色字体。
        self._frame.level_combo.setFont(ui_font)
        self._frame.pkg_input.setFont(mono_font)
        # 输出框样式由 qfluentwidgets PlainTextEdit 自维护（随主题切换），仅同步等宽字体。
        self._frame.output.setFont(log_font)
        self._frame.output.document().setDefaultFont(log_font)
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
        hl_colors = {
            "V": BS.color("LOG_DEBUG"),
            "D": BS.color("LOG_DEBUG"),
            "I": BS.color("LOG_INFO"),
            "W": BS.color("LOG_WARNING"),
            "E": BS.color("LOG_ERROR"),
            "F": BS.color("LOG_CRITICAL"),
            "S": BS.color("TEXT_SECONDARY"),
            "U": BS.color("TEXT_PRIMARY"),
        }
        self._frame.highlighter.set_theme(hl_colors)

    def _apply_action_button_styles(self) -> None:
        """动作按钮直接使用 qfluentwidgets，危险色由项目配置函数补充。"""

    def resizeEvent(self, event):
        self._reflow_filters()
        self._frame._filter_reflow_timer.start(0)

    def _set_running_actions(self, running: bool, *, stopping: bool = False) -> None:
        """统一维护日志采集按钮状态，避免异步路径出现状态分叉。"""

        self._frame._logcat_stopping = stopping
        has_device = bool(
            self._frame.device_ip
            and getattr(self._frame, "_device_connected", True)
        )
        self._frame.start_btn.setEnabled(has_device and not running)
        self._frame.stop_btn.setEnabled(running and not stopping)
        package_lookup_active = bool(
            self._frame._pkg_worker is not None and self._frame._pkg_worker.isRunning()
        )
        self._frame.btn_get_pkg.setEnabled(
            has_device and not stopping and not package_lookup_active
        )
        self._apply_action_button_styles()
