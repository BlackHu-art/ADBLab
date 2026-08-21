"""提供截图查看器对话框的主题与界面构建控制器。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsScene,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from gui.dialogs.screenshot_viewer_widgets import ScreenshotBottomBar, ScreenshotGraphicsView
from gui.styles import BaseStyles
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole


class ScreenshotViewerUI:
    """组合进 ScreenshotViewer 的主题与界面控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    def _init_window(self):
        from gui.dialogs import screenshot_viewer as _sv

        self._frame.setWindowTitle("Screenshot Viewer")
        self._frame.setWindowIcon(_sv.get_themed_icon(self._frame._window_icon_name))
        self._frame.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.setMinimumSize(760, 520)
        self._frame.resize(1100, 760)

    def _init_shortcuts(self):
        QShortcut(QKeySequence("Esc"), self._frame, self._frame.close)
        QShortcut(QKeySequence("Ctrl+C"), self._frame, self._frame.copy_to_clipboard)
        QShortcut(QKeySequence("Ctrl+="), self._frame, self._frame.zoom_in)
        QShortcut(QKeySequence("Ctrl++"), self._frame, self._frame.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self._frame, self._frame.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self._frame, self._frame._reset_zoom)
        QShortcut(QKeySequence("Ctrl+1"), self._frame, self._frame._actual_size)
        QShortcut(QKeySequence("Alt+Left"), self._frame, self._frame.navigate_prev)
        QShortcut(QKeySequence("Alt+Right"), self._frame, self._frame.navigate_next)

    @staticmethod
    def _theme_color(key: str) -> str:
        return BaseStyles.color(key)

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self._frame)
        ui_font = BaseStyles.font_for_role(FontRole.UI)
        small_font = BaseStyles.font_for_role(FontRole.UI_SMALL)
        mono_font = BaseStyles.font_for_role(FontRole.MONO)
        self._frame.setFont(ui_font)
        c = self._theme_color
        r = BaseStyles

        self._frame.setStyleSheet(
            BaseStyles.SCROLLBAR_STYLE()
            + f"""
            QDialog {{
                background-color: {c("WINDOW_BG")};
                color: {c("TEXT_PRIMARY")};
            }}
            QFrame#canvasFrame {{
                background-color: {c("INPUT_BG")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {r.RADIUS_LG}px;
            }}
            QGraphicsView#imageView {{
                background-color: {c("INPUT_BG")};
                border: none;
            }}
            QGraphicsView#imageView:focus {{
                border: 2px solid {c("BORDER_FOCUS")};
            }}
            QFrame#bottomDock {{
                background-color: {c("TOOLBAR_BG")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {r.RADIUS_MD}px;
            }}
            QFrame#bottomBar {{
                background-color: transparent;
                border: none;
            }}
            QListWidget#thumbnailStrip {{
                background-color: {c("INPUT_BG")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {r.RADIUS_SM}px;
                color: {c("TEXT_PRIMARY")};
                padding: 4px;
                outline: none;
            }}
            QListWidget#thumbnailStrip:focus {{
                border: 2px solid {c("BORDER_FOCUS")};
            }}
            QListWidget#thumbnailStrip::item {{
                border: 1px solid transparent;
                border-radius: {r.RADIUS_SM}px;
                padding: 3px;
                margin: 1px;
            }}
            QListWidget#thumbnailStrip::item:selected {{
                background-color: {c("SELECTION_BG")};
                border-color: {c("BORDER_FOCUS")};
                color: {c("SELECTION_TEXT")};
            }}
            QLabel {{
                color: {c("TEXT_PRIMARY")};
                background: transparent;
            }}
            QLabel#metaLabel,
            QLabel#navLabel,
            QLabel#zoomLabel {{
                color: {c("TEXT_SECONDARY")};
            }}
            QLabel#pathLabel {{
                color: {c("TEXT_SECONDARY")};
            }}
            QPushButton {{
                background-color: {c("BUTTON_BG")};
                color: {c("TEXT_PRIMARY")};
                border: 1px solid {c("BORDER_COLOR")};
                border-radius: {r.RADIUS_SM}px;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {c("BUTTON_HOVER")};
                border-color: {c("BORDER_FOCUS")};
            }}
            QPushButton:pressed {{
                background-color: {c("BUTTON_PRESSED")};
            }}
            QPushButton:focus {{
                border: 2px solid {c("BORDER_FOCUS")};
            }}
            QPushButton:disabled {{
                color: {c("TEXT_DISABLED")};
                background-color: {c("INPUT_BG")};
                border-color: {c("BORDER_COLOR")};
            }}
            QPushButton#danger:hover {{
                background-color: {c("BUTTON_DANGER")};
                border-color: {c("BUTTON_DANGER")};
                color: #ffffff;
            }}
            QPushButton#danger:pressed {{
                background-color: {c("BUTTON_DANGER_HOVER")};
                border-color: {c("BUTTON_DANGER_HOVER")};
                color: #ffffff;
            }}
            """
        )
        self._frame._path_label.setFont(mono_font)
        for label in (self._frame._info_label, self._frame._nav_label, self._frame._zoom_label):
            label.setFont(small_font)
        self._frame._nav_label.setMinimumWidth(0)
        self._frame._nav_label.setMinimumWidth(52)
        self._frame._nav_label.setMinimumWidth(max(52, self._frame._nav_label.sizeHint().width()))
        self._frame._zoom_label.setMinimumWidth(0)
        self._frame._zoom_label.setMinimumWidth(56)
        self._frame._zoom_label.setMinimumWidth(max(56, self._frame._zoom_label.sizeHint().width()))
        self._refresh_button_icons()
        if hasattr(self._frame, "_bottom_bar"):
            self._reflow_bottom_bar()
        if hasattr(self._frame, "_placeholder_text"):
            if self._frame._placeholder_text is not None:
                self._frame._placeholder_text.setFont(
                    BaseStyles.font_for_role(
                        FontRole.UI, size=max(12, BaseStyles.DEFAULT_FONT_SIZE + 1)
                    )
                )
            self._frame._refresh_placeholder_color()

    def _init_ui(self):
        root = QVBoxLayout(self._frame)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_canvas(), stretch=1)
        root.addWidget(self._build_bottom_dock())

    def _build_canvas(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("canvasFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        self._frame._scene = QGraphicsScene(self._frame)
        self._frame._view = ScreenshotGraphicsView(self._frame)
        self._frame._view.setScene(self._frame._scene)
        self._frame._view.customContextMenuRequested.connect(self._frame._on_context_menu)
        layout.addWidget(self._frame._view)
        return frame

    def _build_bottom_dock(self) -> QFrame:
        dock = QFrame()
        dock.setObjectName("bottomDock")
        layout = QVBoxLayout(dock)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._frame._thumb_list = QListWidget()
        self._frame._thumb_list.setObjectName("thumbnailStrip")
        self._frame._thumb_list.setViewMode(QListView.IconMode)
        self._frame._thumb_list.setFlow(QListView.LeftToRight)
        self._frame._thumb_list.setMovement(QListView.Static)
        self._frame._thumb_list.setResizeMode(QListView.Adjust)
        self._frame._thumb_list.setWrapping(False)
        self._frame._thumb_list.setUniformItemSizes(True)
        self._frame._thumb_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._frame._thumb_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._frame._thumb_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._frame._thumb_list.setIconSize(QSize(86, 58))
        self._frame._thumb_list.setFixedHeight(92)
        self._frame._thumb_list.itemClicked.connect(self._frame._on_thumbnail_clicked)
        layout.addWidget(self._frame._thumb_list)

        layout.addWidget(self._build_bottom_bar())
        self._frame._bottom_dock = dock
        return dock

    def _build_bottom_bar(self) -> QFrame:
        bar = ScreenshotBottomBar(self._frame)
        bar.setObjectName("bottomBar")
        layout = QGridLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._frame._path_label = QLabel("")
        self._frame._path_label.setObjectName("pathLabel")
        self._frame._path_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._frame._path_label.setMinimumWidth(120)
        self._frame._path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._frame._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._frame._path_label.setToolTip("Screenshot file path")
        self._frame._path_label.setAccessibleName("Screenshot file path")
        self._frame._path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self._frame._info_label = QLabel("")
        self._frame._info_label.setObjectName("metaLabel")
        self._frame._info_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._frame._info_label.setMinimumWidth(150)
        self._frame._info_label.setToolTip("Image size, file size, and modified time")
        self._frame._info_label.setAccessibleName("Screenshot metadata")
        self._frame._info_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self._frame._prev_btn = self._tool_button("caret-left.svg", "Previous screenshot (Left)")
        self._frame._prev_btn.clicked.connect(self._frame.navigate_prev)

        self._frame._nav_label = QLabel("0 / 0")
        self._frame._nav_label.setObjectName("navLabel")
        self._frame._nav_label.setAlignment(Qt.AlignCenter)
        self._frame._nav_label.setMinimumWidth(52)
        self._frame._nav_label.setToolTip("Current screenshot index")

        self._frame._next_btn = self._tool_button("caret-right.svg", "Next screenshot (Right)")
        self._frame._next_btn.clicked.connect(self._frame.navigate_next)

        self._frame._zoom_out_btn = self._tool_button(
            "magnifying-glass-minus.svg", "Zoom out (Ctrl+-)"
        )
        self._frame._zoom_out_btn.clicked.connect(self._frame.zoom_out)

        self._frame._zoom_label = QLabel("Fit")
        self._frame._zoom_label.setObjectName("zoomLabel")
        self._frame._zoom_label.setAlignment(Qt.AlignCenter)
        self._frame._zoom_label.setMinimumWidth(56)
        self._frame._zoom_label.setToolTip("Current zoom")

        self._frame._zoom_in_btn = self._tool_button(
            "magnifying-glass-plus.svg", "Zoom in (Ctrl+=)"
        )
        self._frame._zoom_in_btn.clicked.connect(self._frame.zoom_in)

        self._frame._fit_btn = self._tool_button("frame-corners.svg", "Fit to window (Ctrl+0)")
        self._frame._fit_btn.clicked.connect(self._frame._reset_zoom)

        self._frame._actual_btn = self._tool_button(
            "number-square-one.svg", "Actual size (Ctrl+1)"
        )
        self._frame._actual_btn.clicked.connect(self._frame._actual_size)

        self._frame._copy_btn = self._tool_button(
            "copy.svg", "Copy image to clipboard (Ctrl+C)"
        )
        self._frame._copy_btn.clicked.connect(self._frame.copy_to_clipboard)

        self._frame._folder_btn = self._tool_button("folder-open.svg", "Open file location")
        self._frame._folder_btn.clicked.connect(self._frame._open_file_location)

        self._frame._delete_btn = self._tool_button("trash.svg", "Delete screenshot")
        self._frame._delete_btn.setObjectName("danger")
        self._frame._delete_btn.clicked.connect(self._frame._delete_file)

        self._frame._metadata_group = self._bottom_bar_group("screenshotMetadataGroup")
        metadata_layout = self._frame._metadata_group.layout()
        metadata_layout.addWidget(self._frame._path_label, 1)
        metadata_layout.addWidget(self._frame._info_label, 1)

        self._frame._navigation_group = self._bottom_bar_group("screenshotNavigationGroup")
        navigation_layout = self._frame._navigation_group.layout()
        for control in (self._frame._prev_btn, self._frame._nav_label, self._frame._next_btn):
            navigation_layout.addWidget(control)

        self._frame._actions_group = self._bottom_bar_group("screenshotActionsGroup")
        actions_layout = self._frame._actions_group.layout()
        for control in (
            self._frame._zoom_out_btn,
            self._frame._zoom_label,
            self._frame._zoom_in_btn,
            self._frame._fit_btn,
            self._frame._actual_btn,
            self._frame._copy_btn,
            self._frame._folder_btn,
            self._frame._delete_btn,
        ):
            actions_layout.addWidget(control)

        self._frame._bottom_bar = bar
        self._frame._bottom_bar_layout = layout
        self._frame._bottom_bar_groups = (
            self._frame._metadata_group,
            self._frame._navigation_group,
            self._frame._actions_group,
        )
        self._frame._bottom_bar_controls = (
            self._frame._path_label,
            self._frame._info_label,
            self._frame._prev_btn,
            self._frame._nav_label,
            self._frame._next_btn,
            self._frame._zoom_out_btn,
            self._frame._zoom_label,
            self._frame._zoom_in_btn,
            self._frame._fit_btn,
            self._frame._actual_btn,
            self._frame._copy_btn,
            self._frame._folder_btn,
            self._frame._delete_btn,
        )
        self._reflow_bottom_bar()
        return bar

    @staticmethod
    def _bottom_bar_group(object_name: str) -> QFrame:
        group = QFrame()
        group.setObjectName(object_name)
        group.setFrameShape(QFrame.Shape.NoFrame)
        group.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        return group

    @staticmethod
    def _group_minimum_size(group: QFrame) -> QSize:
        layout = group.layout()
        layout_minimum = layout.minimumSize() if layout is not None else QSize()
        return group.minimumSizeHint().expandedTo(layout_minimum)

    def _reflow_bottom_bar(self) -> None:
        if self._frame._reflowing_bottom_bar:
            return
        self._frame._reflowing_bottom_bar = True
        try:
            layout = self._frame._bottom_bar_layout
            spacing = max(0, layout.spacing())
            group_sizes = tuple(
                self._group_minimum_size(group) for group in self._frame._bottom_bar_groups
            )
            metadata_size, navigation_size, actions_size = group_sizes
            available_width = self._frame._bottom_bar.contentsRect().width()
            if hasattr(self._frame, "_bottom_dock"):
                root_margins = self._frame.layout().contentsMargins()
                dock_margins = self._frame._bottom_dock.layout().contentsMargins()
                available_width = self._frame.contentsRect().width()
                available_width -= root_margins.left() + root_margins.right()
                available_width -= dock_margins.left() + dock_margins.right()
                available_width -= 2 * self._frame._bottom_dock.frameWidth()
            available_width = max(0, available_width)

            wide_required = sum(size.width() for size in group_sizes) + (2 * spacing)
            split_required = max(
                metadata_size.width(),
                navigation_size.width() + actions_size.width() + spacing,
            )
            if available_width >= wide_required:
                mode = "wide"
            elif available_width >= split_required:
                mode = "split"
            else:
                mode = "stacked"
            fingerprint = (
                mode,
                spacing,
                tuple((size.width(), size.height()) for size in group_sizes),
            )
            if fingerprint == self._frame._bottom_bar_plan_fingerprint:
                return

            while layout.count():
                layout.takeAt(0)
            for column in range(3):
                layout.setColumnStretch(column, 0)
                layout.setColumnMinimumWidth(column, 0)
            for row in range(3):
                layout.setRowStretch(row, 0)
                layout.setRowMinimumHeight(row, 0)

            if mode == "wide":
                layout.addWidget(self._frame._metadata_group, 0, 0)
                layout.addWidget(
                    self._frame._navigation_group,
                    0,
                    1,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
                layout.addWidget(
                    self._frame._actions_group,
                    0,
                    2,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                )
                layout.setColumnStretch(0, 1)
            elif mode == "split":
                layout.addWidget(self._frame._metadata_group, 0, 0, 1, 2)
                layout.addWidget(
                    self._frame._navigation_group,
                    1,
                    0,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
                layout.addWidget(
                    self._frame._actions_group,
                    1,
                    1,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                )
                layout.setColumnStretch(0, 1)
            else:
                layout.addWidget(self._frame._metadata_group, 0, 0)
                layout.addWidget(
                    self._frame._navigation_group,
                    1,
                    0,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
                layout.addWidget(
                    self._frame._actions_group,
                    2,
                    0,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
                layout.setColumnStretch(0, 1)

            self._frame._bottom_bar.setMinimumHeight(0)
            layout.activate()
            self._frame._bottom_bar.setMinimumHeight(layout.minimumSize().height())
            self._frame._bottom_bar_plan_fingerprint = fingerprint
            self._frame._bottom_bar.updateGeometry()
            if hasattr(self._frame, "_bottom_dock"):
                self._frame._bottom_dock.updateGeometry()
                self._frame._bottom_dock.layout().activate()
            root_layout = self._frame.layout()
            if root_layout is not None:
                root_layout.activate()
        finally:
            self._frame._reflowing_bottom_bar = False

    def _schedule_bottom_bar_reflow(self) -> None:
        """合并顶层和底栏 resize，只在最终几何上重排一次。"""

        self._frame._bottom_bar_reflow_timer.start(0)

    def _tool_button(self, icon_name: str, tooltip: str) -> QPushButton:
        from gui.dialogs import screenshot_viewer as _sv

        button = QPushButton()
        button.setIcon(_sv.get_themed_icon(icon_name))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(28, 28)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        button.setProperty("iconName", icon_name)
        self._frame._icon_buttons.append(button)
        return button

    def _refresh_button_icons(self):
        from gui.dialogs import screenshot_viewer as _sv

        self._frame.setWindowIcon(_sv.get_themed_icon(self._frame._window_icon_name))
        for button in getattr(self._frame, "_icon_buttons", []):
            icon_name = button.property("iconName")
            if icon_name:
                button.setIcon(_sv.get_themed_icon(icon_name))
