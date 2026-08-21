"""提供 Logcat 对话框的表单构建、主题应用与响应式重排。"""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
)

from gui.dialogs.live_logcat_highlighter import LogcatHighlighter
from gui.dialogs.live_logcat_worker import LEVEL_LABELS
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole


class LiveLogcatForm:
    """组合进 LiveLogcatDialog 的表单控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    def _init_ui(self):
        layout = QVBoxLayout(self._frame)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        filters = QGridLayout()
        filters.setHorizontalSpacing(6)
        filters.setVerticalSpacing(4)
        self._frame._filters_layout = filters
        self._frame._level_label = QLabel("Level:")
        self._frame.level_combo = QComboBox()
        self._frame.level_combo.addItem("All", None)
        for code in ("V", "D", "I", "W", "E", "F"):
            self._frame.level_combo.addItem(LEVEL_LABELS[code], code)
        self._frame.level_combo.currentIndexChanged.connect(self._frame._rebuild)
        self._frame.level_combo.setMinimumWidth(120)
        self._frame._level_label.setBuddy(self._frame.level_combo)
        self._frame.level_combo.setAccessibleName("Log level")
        self._frame._package_label = QLabel("Package:")
        self._frame.pkg_input = QLineEdit()
        self._frame.pkg_input.setPlaceholderText("com.example.app")
        self._frame._package_label.setBuddy(self._frame.pkg_input)
        self._frame.pkg_input.setAccessibleName("Package filter")
        self._frame.btn_get_pkg = QPushButton("Current Package")
        self._frame.btn_get_pkg.setIcon(get_themed_icon("target.svg"))
        self._frame.btn_get_pkg.setIconSize(QSize(14, 14))
        self._frame.btn_get_pkg.setToolTip("Fetch current foreground app package")
        self._frame.btn_get_pkg.setMinimumWidth(120)
        self._frame.btn_get_pkg.clicked.connect(self._frame._fetch_current_pkg)
        self._frame._tag_label = QLabel("Tag:")
        self._frame.tag_input = QLineEdit()
        self._frame.tag_input.setPlaceholderText("ActivityManager")
        self._frame.tag_input.textChanged.connect(self._frame._schedule_filter_rebuild)
        self._frame._tag_label.setBuddy(self._frame.tag_input)
        self._frame.tag_input.setAccessibleName("Tag filter")
        self._frame._filter_controls = (
            self._frame._level_label,
            self._frame.level_combo,
            self._frame._package_label,
            self._frame.pkg_input,
            self._frame.btn_get_pkg,
            self._frame._tag_label,
            self._frame.tag_input,
        )
        self._reflow_filters()
        layout.addLayout(filters)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._frame.start_btn = QPushButton("Start")
        self._frame.start_btn.setToolTip("Start streaming device log messages")
        self._frame.start_btn.setIcon(get_themed_icon("play.svg"))
        self._frame.start_btn.setIconSize(QSize(14, 14))
        self._frame.stop_btn = QPushButton("Stop")
        self._frame.stop_btn.setToolTip("Stop the active log stream")
        self._frame.stop_btn.setIcon(get_themed_icon("stop-circle.svg"))
        self._frame.stop_btn.setIconSize(QSize(14, 14))
        self._frame.clear_btn = QPushButton("Clear")
        self._frame.clear_btn.setToolTip("Remove all displayed log messages")
        self._frame.clear_btn.setIcon(get_themed_icon("broom.svg"))
        self._frame.clear_btn.setIconSize(QSize(14, 14))
        self._frame.export_btn = QPushButton("Export")
        self._frame.export_btn.setToolTip("Save the displayed log messages to a file")
        self._frame.export_btn.setIcon(get_themed_icon("file-arrow-down.svg"))
        self._frame.export_btn.setIconSize(QSize(14, 14))
        self._frame.wrap_btn = QPushButton("Wrap")
        self._frame.wrap_btn.setIcon(get_themed_icon("arrows-left-right.svg"))
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
        for button in action_buttons:
            btn_row.addWidget(button)

        self._frame.status_bar = QStatusBar()
        self._frame.status_bar.setSizeGripEnabled(False)
        self._frame.status_bar.showMessage("Ready")
        btn_row.addWidget(self._frame.status_bar, 1)
        layout.addLayout(btn_row)

        self._frame.output = QPlainTextEdit()
        self._frame.output.setReadOnly(True)
        self._frame.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
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
        for column in range(7):
            layout.setColumnStretch(column, 0)
        for row in range(5):
            layout.setRowStretch(row, 0)

        if wide:
            for column, control in enumerate(controls):
                layout.addWidget(control, 0, column)
            layout.setColumnStretch(3, 2)
            layout.setColumnStretch(6, 2)
            self._frame.layout().activate()
            self._frame._reflowing_filters = False
            return

        layout.addWidget(self._frame._level_label, 0, 0)
        layout.addWidget(self._frame.level_combo, 1, 0, 1, 2)
        layout.addWidget(self._frame._package_label, 2, 0)
        layout.addWidget(self._frame.pkg_input, 2, 1)
        layout.addWidget(self._frame.btn_get_pkg, 3, 0, 1, 2)
        layout.addWidget(self._frame._tag_label, 4, 0)
        layout.addWidget(self._frame.tag_input, 4, 1)
        layout.setColumnStretch(1, 1)
        self._frame.layout().activate()
        self._frame._reflowing_filters = False

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self._frame)
        BS = BaseStyles
        ui_font = BS.font_for_role(FontRole.UI)
        mono_font = BS.font_for_role(FontRole.MONO)
        log_font = BS.font_for_role(FontRole.LOG)
        self._frame.setStyleSheet(BS.PANEL_BASE_STYLE())
        self._frame.setFont(ui_font)
        for field in (self._frame.pkg_input, self._frame.tag_input):
            field.setFont(mono_font)
        fg = BS.color("TEXT_PRIMARY")
        border = BS.color("BORDER_COLOR")
        self._frame.output.setStyleSheet(
            f"background-color: {BS.color('LOG_BACKGROUND')}; "
            f"color: {BS.color('LOG_TEXT_COLOR')}; "
            f"border: 1px solid {border}; border-radius: {BS.RADIUS_MD}px;"
        )
        self._frame.output.setFont(log_font)
        self._frame.output.document().setDefaultFont(log_font)
        self._frame.status_bar.setStyleSheet(BS.STATUS_BAR_STYLE())
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
            "U": fg,
        }
        self._frame.highlighter.set_theme(hl_colors)

    def _apply_action_button_styles(self) -> None:
        """按当前主题刷新启动和停止按钮的语义色。"""

        bs = BaseStyles
        self._frame.start_btn.setStyleSheet(f"""
            QPushButton {{
                {bs.BUTTON_BASE()}
                background-color: {bs.color("LOG_SUCCESS")}; color: #ffffff;
                border: 1px solid {bs.color("LOG_SUCCESS")};
            }}
            QPushButton:hover {{ border-color: {bs.color("TEXT_PRIMARY")}; }}
            QPushButton:pressed {{ border-color: {bs.color("BORDER_FOCUS")}; }}
            QPushButton:focus {{ border: 2px solid {bs.color("TEXT_PRIMARY")}; }}
            QPushButton:disabled {{
                background-color: {bs.color("INPUT_BG")};
                color: {bs.color("TEXT_DISABLED")};
                border-color: {bs.color("BORDER_COLOR")};
            }}
            """)
        self._frame.stop_btn.setObjectName("danger")
        self._frame.stop_btn.setProperty("buttonVariant", "danger")
        self._frame.stop_btn.setStyleSheet(bs.BUTTON_QSS())
        for button in (self._frame.start_btn, self._frame.stop_btn):
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def resizeEvent(self, event):
        self._reflow_filters()
        self._frame._filter_reflow_timer.start(0)

    def _set_running_actions(self, running: bool, *, stopping: bool = False) -> None:
        """统一维护日志采集按钮状态，避免异步路径出现状态分叉。"""

        self._frame.start_btn.setEnabled(not running)
        self._frame.stop_btn.setEnabled(running and not stopping)
        self._apply_action_button_styles()
