"""使用官方 Fluent 图片翻页、命令栏和圆点分页构建截图页面。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    CommandBar,
    FluentIcon,
    InfoBadge,
    InfoLevel,
)

from gui.dialogs.screenshot_viewer_widgets import (
    ScreenshotDetailsBar,
    ScreenshotFlipView,
    ScreenshotPipsPager,
)
from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles.fluent import apply_focus_indicator, apply_label_role
from gui.styles.typography import FontRole


class ScreenshotViewerUI:
    """管理页内展示与命令入口；图片状态、文件操作和生命周期由页面统一协调。"""

    def __init__(self, frame):
        self._frame = frame

    def _init_page(self):
        self._frame.setObjectName("screenshotPage")
        self._frame.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.setMinimumSize(0, 0)
        self._frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def prepare_for_workspace(self) -> None:
        """工作区拥有统一页头，嵌入时归还整组重复标题占用的空间。"""

        self._frame.header_card.hide()

    def _init_shortcuts(self):
        frame = self._frame
        for key, callback in (
            ("Esc", frame.back_requested.emit),
            ("Ctrl+O", frame._add_images),
            ("Ctrl+R", frame._rotate_image),
            ("Ctrl+C", frame.copy_to_clipboard),
            ("Ctrl+=", frame.zoom_in),
            ("Ctrl++", frame.zoom_in),
            ("Ctrl+-", frame.zoom_out),
            ("Ctrl+0", frame._reset_zoom),
            ("Ctrl+1", frame._actual_size),
            ("Alt+Left", frame.navigate_prev),
            ("Alt+Right", frame.navigate_next),
        ):
            QShortcut(QKeySequence(key), frame, callback)

    @staticmethod
    def _theme_color(key: str) -> str:
        return BaseStyles.color(key)

    def _apply_theme(self, _value=None):
        """同步项目字体和可访问性，保留 Fluent 控件自身的主题及溢出菜单绘制。"""

        frame = self._frame
        ui_font = BaseStyles.font_for_role(FontRole.UI)
        small_font = BaseStyles.font_for_role(FontRole.UI_SMALL)
        frame.setFont(ui_font)
        frame.dialog_title.setFont(BaseStyles.font_for_role(FontRole.TITLE))
        frame.dialog_subtitle.setFont(ui_font)
        frame.status_badge.setFont(ui_font)
        count = len(frame._image_paths)
        frame.status_badge.setText(
            tr("{value0} images").format(value0=count) if count else tr("Empty")
        )
        frame.status_badge.setLevel(InfoLevel.SUCCESS if count else InfoLevel.INFOAMTION)
        frame._empty_label.setFont(ui_font)
        frame._path_label.setFont(BaseStyles.font_for_role(FontRole.MONO))
        for label in (frame._info_label, frame._nav_label, frame._zoom_label):
            label.setFont(small_font)

        bar = frame._command_bar
        bar.setFont(ui_font)
        for action, icon in frame._command_icons:
            action.setIcon(icon.icon())
        for button in (*bar.commandButtons, bar.moreButton):
            button.setFont(ui_font)
            hint = button.sizeHint()
            button.setFixedSize(
                hint.width(), max(hint.height(), button.fontMetrics().height() + 16)
            )
            if button is not bar.moreButton:
                button.setAccessibleName(button.action().text())
                button.setAccessibleDescription(button.action().toolTip())
            apply_focus_indicator(button, selector="QToolButton")
        bar.setFixedHeight(max(button.height() for button in (*bar.commandButtons, bar.moreButton)))
        bar.updateGeometry()
        apply_focus_indicator(frame._view, selector="QListWidget")
        apply_focus_indicator(frame._pager, selector="QListWidget")
        self._refresh_metadata()

    def _init_ui(self):
        frame = self._frame
        root = QVBoxLayout(frame)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)
        frame.header_card = CardWidget(frame)
        frame.header_card.setObjectName("dialogHeaderCard")
        frame.header_card.setBorderRadius(BaseStyles.RADIUS_LG)
        header = QVBoxLayout(frame.header_card)
        header.setContentsMargins(12, 8, 12, 8)
        header.setSpacing(2)
        title_row = QHBoxLayout()
        frame.dialog_title = apply_label_role(
            BodyLabel(tr("Screenshot Viewer")), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        frame.dialog_title.setObjectName("dialogTitle")
        frame.status_badge = InfoBadge.info(tr("Empty"), frame.header_card)
        frame.status_badge.setToolTip(tr("Number of loaded screenshots"))
        frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        title_row.addWidget(frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(frame.status_badge)
        header.addLayout(title_row)
        frame.dialog_subtitle = apply_label_role(
            BodyLabel(tr("Inspect captured device screenshots")),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        frame.dialog_subtitle.setObjectName("dialogSubtitle")
        frame.dialog_subtitle.setWordWrap(True)
        header.addWidget(frame.dialog_subtitle)
        root.addWidget(frame.header_card)
        root.addWidget(self._build_command_bar())

        frame._canvas_frame = QFrame(frame)
        frame._canvas_frame.setObjectName("canvasFrame")
        canvas = QVBoxLayout(frame._canvas_frame)
        canvas.setContentsMargins(0, 0, 0, 0)
        frame._image_stack = QStackedWidget(frame._canvas_frame)
        frame._image_stack.setMinimumHeight(160)
        frame._empty_label = apply_label_role(
            BodyLabel(tr("No screenshot available")), FontRole.UI, color_key="TEXT_SECONDARY"
        )
        frame._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame._empty_label.setWordWrap(True)
        frame._view = ScreenshotFlipView(frame)
        frame._view.setObjectName("imageView")
        frame._view.setAccessibleName(tr("Screenshot Viewer"))
        frame._view.currentIndexChanged.connect(frame._navigate_to)
        frame._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        frame._view.customContextMenuRequested.connect(frame._on_context_menu)
        frame._image_stack.addWidget(frame._empty_label)
        frame._image_stack.addWidget(frame._view)
        canvas.addWidget(frame._image_stack)
        root.addWidget(frame._canvas_frame, 1)

        frame._pager_bar = QWidget(frame)
        pager_row = QHBoxLayout(frame._pager_bar)
        pager_row.setContentsMargins(0, 0, 0, 0)
        pager_row.addStretch(1)
        frame._pager = ScreenshotPipsPager(frame)
        frame._pager.setAccessibleName(tr("Choose screenshot"))
        frame._pager.currentIndexChanged.connect(frame._navigate_to)
        pager_row.addWidget(frame._pager)
        frame._nav_label = apply_label_role(
            BodyLabel("0 / 0"), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        frame._nav_label.setObjectName("navLabel")
        frame._nav_label.setToolTip(tr("Current screenshot index"))
        pager_row.addWidget(frame._nav_label)
        pager_row.addStretch(1)
        root.addWidget(frame._pager_bar)
        root.addWidget(self._build_details())

    def _build_command_bar(self) -> CommandBar:
        """按钮和窄屏更多菜单共享同一 Action，确保禁用、确认和图标状态一致。"""

        frame = self._frame
        bar = CommandBar(frame)
        frame._command_bar = bar
        bar.setObjectName("screenshotCommandBar")
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.setButtonTight(True)
        bar.setIconSize(QSize(16, 16))
        frame._command_icons = []
        specifications = (
            ("add", FluentIcon.ADD, "Add images", "Add local images (Ctrl+O)", frame._add_images),
            ("rotate", FluentIcon.ROTATE, "Rotate", "Rotate preview clockwise (Ctrl+R)",
             frame._rotate_image),
            ("zoom_in", FluentIcon.ZOOM_IN, "Zoom in", "Zoom in (Ctrl+=)", frame.zoom_in),
            ("zoom_out", FluentIcon.ZOOM_OUT, "Zoom out", "Zoom out (Ctrl+-)", frame.zoom_out),
            ("fit", FluentIcon.FIT_PAGE, "Fit", "Fit to window (Ctrl+0)", frame._reset_zoom),
            ("actual", FluentIcon.FULL_SCREEN, "Actual size", "Actual size (Ctrl+1)",
             frame._actual_size),
            ("info", FluentIcon.INFO, "Info", "Show image details", frame._show_image_info),
            ("copy", FluentIcon.COPY, "Copy", "Copy image to clipboard (Ctrl+C)",
             frame.copy_to_clipboard),
            ("folder", FluentIcon.FOLDER, "Open folder", "Open file location",
             frame._open_file_location),
            ("delete", FluentIcon.DELETE, "Delete", "Delete screenshot", frame._delete_file),
        )
        for name, icon, title, tooltip, callback in specifications:
            if name in {"fit", "copy"}:
                bar.addSeparator()
            action = Action(icon.icon(), tr(title), frame)
            action.setObjectName(f"screenshot_{name}")
            action.setToolTip(tr(tooltip))
            action.setCheckable(name == "info")
            action.triggered.connect(callback)
            setattr(frame, f"_{name}_action", action)
            frame._command_icons.append((action, icon))
            button = bar.addAction(action)
            assert button is not None
            button.setAccessibleName(action.text())
            button.setAccessibleDescription(action.toolTip())
            action.changed.connect(
                lambda action=action, button=button: self._sync_command_button(action, button)
            )
        bar.moreButton.setToolTip(tr("More image actions"))
        bar.moreButton.setAccessibleName(tr("More image actions"))
        return bar

    @staticmethod
    def _sync_command_button(action, button) -> None:
        """确认提示与禁用状态变化时，可访问描述跟随同一 Action 更新。"""

        button.setAccessibleName(action.text())
        button.setAccessibleDescription(action.toolTip())

    def _build_details(self) -> ScreenshotDetailsBar:
        frame = self._frame
        frame._details_bar = ScreenshotDetailsBar(frame)
        frame._details_bar.setObjectName("screenshotDetails")
        layout = QVBoxLayout(frame._details_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        frame._metadata_row = QHBoxLayout()
        frame._metadata_row.setSpacing(8)
        frame._path_label = apply_label_role(BodyLabel(), FontRole.MONO, color_key="TEXT_SECONDARY")
        frame._path_label.setObjectName("pathLabel")
        frame._path_label.setMinimumWidth(0)
        frame._path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        frame._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        frame._path_label.setAccessibleName(tr("Screenshot file path"))
        frame._path_label.setProperty("screenshotFullFileName", "")
        frame._zoom_label = apply_label_role(
            BodyLabel(tr("Fit")), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        frame._zoom_label.setObjectName("zoomLabel")
        frame._zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        frame._zoom_label.setAccessibleName(tr("Image zoom"))
        frame._metadata_row.addWidget(frame._path_label, 1)
        frame._metadata_row.addWidget(frame._zoom_label)
        layout.addLayout(frame._metadata_row)
        frame._info_label = apply_label_role(
            BodyLabel(), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        frame._info_label.setObjectName("metaLabel")
        frame._info_label.setMinimumWidth(0)
        frame._info_label.setWordWrap(True)
        frame._info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        frame._info_label.setAccessibleName(tr("Screenshot metadata"))
        frame._info_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        frame._info_label.hide()
        layout.addWidget(frame._info_label)
        return frame._details_bar

    def _refresh_metadata(self) -> None:
        """长文件名只在显示层省略，完整路径及可访问描述由当前图片状态保留。"""

        frame = self._frame
        available = frame._details_bar.contentsRect().width()
        stacked = available < frame._zoom_label.sizeHint().width() + 100
        direction = (
            QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight
        )
        if frame._metadata_row.direction() != direction:
            frame._metadata_row.setDirection(direction)
        label = frame._path_label
        name = str(label.property("screenshotFullFileName") or "")
        width = max(
            0, available if stacked else available - frame._zoom_label.sizeHint().width() - 8
        )
        label.setText(label.fontMetrics().elidedText(name, Qt.TextElideMode.ElideMiddle, width))
        frame._info_label.setVisible(frame._info_action.isChecked())

    def _schedule_metadata_reflow(self) -> None:
        """合并尺寸回调；页面释放后不再启动刷新计时器。"""

        if not self._frame._disposed:
            self._frame._metadata_reflow_timer.start(0)
