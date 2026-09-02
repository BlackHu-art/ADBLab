"""提供截图查看器对话框的主题与界面构建控制器。"""

from typing import cast

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QFrame,
    QGraphicsScene,
    QGridLayout,
    QHBoxLayout,
    QListView,
    QListWidget,
    QSizePolicy,
    QVBoxLayout,
)
from qfluentwidgets import (
    CardWidget,
    InfoBadge,
    InfoLevel,
    SmoothScrollDelegate,
    TransparentToolButton,
)

from gui.dialogs.screenshot_viewer_widgets import ScreenshotBottomBar, ScreenshotGraphicsView
from gui.styles import BaseStyles
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from gui.widgets.fluent.label import FluentLabel


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

        # 视觉重设计：页头卡片由 CardWidget 自绘制随主题切换，徽标按已加载截图数量刷新。
        if hasattr(self._frame, "header_card"):
            self._frame.dialog_title.setFont(BaseStyles.font_for_role(FontRole.TITLE))
            self._frame.dialog_subtitle.setFont(ui_font)
            self._frame.status_badge.setFont(ui_font)
            count = len(getattr(self._frame, "_image_paths", ()))
            self._frame.status_badge.setText(
                f"{count} images" if count else "Empty"
            )
            self._frame.status_badge.setLevel(
                InfoLevel.SUCCESS if count else InfoLevel.INFOAMTION
            )

        self._frame.setStyleSheet(
            f"""
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
            """
        )
        # 图标按钮已收敛为 TransparentToolButton：其 widget 级 QSS 会覆盖父级边框，
        # 因此键盘焦点指示器（BORDER_FOCUS 边框）需逐按钮以 widget 级 QSS 注入；
        # 危险删除按钮额外用 ID 选择器覆盖 hover/pressed 背景。
        focus_qss = f"QToolButton:focus {{ border: 2px solid {c('BORDER_FOCUS')}; }}"
        danger_qss = (
            f"QToolButton#danger:hover {{"
            f" background-color: {c('BUTTON_DANGER')}; color: #ffffff; }}"
            f"QToolButton#danger:pressed {{"
            f" background-color: {c('BUTTON_DANGER_HOVER')}; color: #ffffff; }}"
        )
        for button in getattr(self._frame, "_icon_buttons", []):
            qss = focus_qss + (danger_qss if button.objectName() == "danger" else "")
            button.setStyleSheet(qss)
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

        # ── 页头卡片：标题、副标题与截图数量状态徽标 ─────────────────────
        # 视觉重设计：对话框内容顶部统一为 Fluent CardWidget 卡片页头。
        # 副标题保持 UI 字体角色并以 TEXT_SECONDARY 次级文字色维持视觉层级。
        self._frame.header_card = CardWidget()
        self._frame.header_card.setObjectName("dialogHeaderCard")
        self._frame.header_card.setBorderRadius(BaseStyles.RADIUS_LG)
        hl = QVBoxLayout(self._frame.header_card)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._frame.dialog_title = FluentLabel(
            "Screenshot Viewer", role=FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.status_badge = InfoBadge.info("Empty", self._frame.header_card)
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip("Number of loaded screenshots")
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = FluentLabel(
            "Inspect captured device screenshots",
            role=FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        self._frame.dialog_subtitle.setObjectName("dialogSubtitle")
        self._frame.dialog_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self._frame.dialog_subtitle)
        root.addWidget(self._frame.header_card)

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
        self._frame._thumb_list.setViewMode(QListView.ViewMode.IconMode)
        self._frame._thumb_list.setFlow(QListView.Flow.LeftToRight)
        self._frame._thumb_list.setMovement(QListView.Movement.Static)
        self._frame._thumb_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._frame._thumb_list.setWrapping(False)
        self._frame._thumb_list.setUniformItemSizes(True)
        self._frame._thumb_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._frame._thumb_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._frame._thumb_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frame._thumb_list.setIconSize(QSize(86, 58))
        self._frame._thumb_list.setFixedHeight(92)
        # 缩略图横向条保留原生 QListWidget（IconMode 网格），仅承接 Fluent 平滑滚动条。
        SmoothScrollDelegate(self._frame._thumb_list)
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

        self._frame._path_label = FluentLabel(
            "", role=FontRole.MONO, color_key="TEXT_SECONDARY"
        )
        self._frame._path_label.setObjectName("pathLabel")
        self._frame._path_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._frame._path_label.setMinimumWidth(120)
        self._frame._path_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._frame._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._frame._path_label.setToolTip("Screenshot file path")
        self._frame._path_label.setAccessibleName("Screenshot file path")
        self._frame._path_label.setProperty("screenshotFullFileName", "")
        self._frame._path_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        self._frame._info_label = FluentLabel(
            "", role=FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self._frame._info_label.setObjectName("metaLabel")
        self._frame._info_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._frame._info_label.setMinimumWidth(150)
        self._frame._info_label.setToolTip("Image size, file size, and modified time")
        self._frame._info_label.setAccessibleName("Screenshot metadata")
        self._frame._info_label.setWordWrap(True)
        self._frame._info_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        self._frame._prev_btn = self._tool_button("caret-left.svg", "Previous screenshot (Left)")
        self._frame._prev_btn.clicked.connect(self._frame.navigate_prev)

        self._frame._nav_label = FluentLabel(
            "0 / 0", role=FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self._frame._nav_label.setObjectName("navLabel")
        self._frame._nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame._nav_label.setMinimumWidth(52)
        self._frame._nav_label.setToolTip("Current screenshot index")

        self._frame._next_btn = self._tool_button("caret-right.svg", "Next screenshot (Right)")
        self._frame._next_btn.clicked.connect(self._frame.navigate_next)

        self._frame._zoom_out_btn = self._tool_button(
            "magnifying-glass-minus.svg", "Zoom out (Ctrl+-)"
        )
        self._frame._zoom_out_btn.clicked.connect(self._frame.zoom_out)

        self._frame._zoom_label = FluentLabel(
            "Fit", role=FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self._frame._zoom_label.setObjectName("zoomLabel")
        self._frame._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame._zoom_label.setMinimumWidth(56)
        self._frame._zoom_label.setToolTip("Current zoom")

        self._frame._zoom_in_btn = self._tool_button(
            "magnifying-glass-plus.svg", "Zoom in (Ctrl+=)"
        )
        self._frame._zoom_in_btn.clicked.connect(self._frame.zoom_in)

        self._frame._fit_btn = self._tool_button("frame-corners.svg", "Fit to window (Ctrl+0)")
        self._frame._fit_btn.clicked.connect(self._frame._reset_zoom)

        self._frame._actual_btn = self._tool_button("number-square-one.svg", "Actual size (Ctrl+1)")
        self._frame._actual_btn.clicked.connect(self._frame._actual_size)

        self._frame._copy_btn = self._tool_button("copy.svg", "Copy image to clipboard (Ctrl+C)")
        self._frame._copy_btn.clicked.connect(self._frame.copy_to_clipboard)

        self._frame._folder_btn = self._tool_button("folder-open.svg", "Open file location")
        self._frame._folder_btn.clicked.connect(self._frame._open_file_location)

        self._frame._delete_btn = self._tool_button("trash.svg", "Delete screenshot")
        self._frame._delete_btn.setObjectName("danger")
        self._frame._delete_btn.clicked.connect(self._frame._delete_file)

        self._frame._metadata_group = self._bottom_bar_group("screenshotMetadataGroup")
        metadata_layout = cast(QBoxLayout, self._frame._metadata_group.layout())
        metadata_layout.addWidget(self._frame._path_label)
        metadata_layout.addWidget(self._frame._info_label, 1)
        metadata_layout.setDirection(QBoxLayout.Direction.TopToBottom)
        self._frame._metadata_layout = metadata_layout
        self._frame._metadata_layout_mode = "stacked"

        self._frame._navigation_group = self._bottom_bar_group("screenshotNavigationGroup")
        navigation_layout = cast(QHBoxLayout, self._frame._navigation_group.layout())
        for control in (self._frame._prev_btn, self._frame._nav_label, self._frame._next_btn):
            navigation_layout.addWidget(control)

        self._frame._actions_group = self._bottom_bar_group("screenshotActionsGroup")
        actions_layout = cast(QHBoxLayout, self._frame._actions_group.layout())
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

    def _metadata_required_width(self) -> int:
        """返回元数据两项保持单行横排所需的组内宽度。"""

        path_label = self._frame._path_label
        info_label = self._frame._info_label
        full_name = str(path_label.property("screenshotFullFileName") or path_label.text())
        path_width = max(
            path_label.minimumWidth(),
            path_label.fontMetrics().horizontalAdvance(full_name),
        )
        info_width = max(
            info_label.minimumWidth(),
            info_label.fontMetrics().horizontalAdvance(info_label.text()),
        )
        return path_width + info_width + max(0, self._frame._metadata_layout.spacing())

    def _reflow_metadata_group(self) -> str:
        """按元数据组的真实宽度在横排和纵排之间切换。"""

        layout = self._frame._metadata_layout
        available_width = self._frame._metadata_group.contentsRect().width()
        mode = (
            "inline"
            if available_width > 0 and available_width >= self._metadata_required_width()
            else "stacked"
        )
        if mode == self._frame._metadata_layout_mode:
            return mode
        layout.setDirection(
            QBoxLayout.Direction.LeftToRight
            if mode == "inline"
            else QBoxLayout.Direction.TopToBottom
        )
        layout.setStretch(0, 0)
        layout.setStretch(1, 1 if mode == "inline" else 0)
        self._frame._metadata_layout_mode = mode
        self._frame._metadata_group.updateGeometry()
        return mode

    def _refresh_path_label_elision(self) -> None:
        """显式省略超长文件名，完整内容由 tooltip 与无障碍文本保留。"""

        label = self._frame._path_label
        full_name = str(label.property("screenshotFullFileName") or "")
        available_width = label.contentsRect().width()
        visible_text = (
            label.fontMetrics().elidedText(
                full_name,
                Qt.TextElideMode.ElideMiddle,
                available_width,
            )
            if full_name and available_width > 0
            else full_name
        )
        if label.text() != visible_text:
            label.setText(visible_text)

    def _reflow_bottom_bar(self) -> None:
        if self._frame._reflowing_bottom_bar:
            return
        self._frame._reflowing_bottom_bar = True
        try:
            layout = self._frame._bottom_bar_layout
            spacing = max(0, layout.spacing())
            metadata_mode = self._reflow_metadata_group()
            self._refresh_path_label_elision()
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
                metadata_mode,
                available_width,
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
            final_metadata_mode = self._reflow_metadata_group()
            if final_metadata_mode != metadata_mode:
                layout.activate()
            self._refresh_path_label_elision()
            minimum_height = layout.minimumSize().height()
            if layout.hasHeightForWidth() and available_width > 0:
                minimum_height = max(minimum_height, layout.heightForWidth(available_width))
            self._frame._bottom_bar.setMinimumHeight(minimum_height)
            final_group_sizes = tuple(
                self._group_minimum_size(group) for group in self._frame._bottom_bar_groups
            )
            fingerprint = (
                mode,
                final_metadata_mode,
                available_width,
                spacing,
                tuple((size.width(), size.height()) for size in final_group_sizes),
            )
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

    def _tool_button(self, icon_name: str, tooltip: str) -> TransparentToolButton:
        from gui.dialogs import screenshot_viewer as _sv

        button = TransparentToolButton()
        button.setIcon(_sv.get_themed_icon(icon_name))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(28, 28)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("iconName", icon_name)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._frame._icon_buttons.append(button)
        return button

    def _refresh_button_icons(self):
        from gui.dialogs import screenshot_viewer as _sv

        self._frame.setWindowIcon(_sv.get_themed_icon(self._frame._window_icon_name))
        for button in getattr(self._frame, "_icon_buttons", []):
            icon_name = button.property("iconName")
            if icon_name:
                button.setIcon(_sv.get_themed_icon(icon_name))
