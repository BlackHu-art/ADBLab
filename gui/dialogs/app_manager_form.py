"""应用管理器表单控制器 — 构建界面、应用主题并处理响应式重排。"""

from typing import cast

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QStandardItemModel
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLayout,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBadge,
    InfoLevel,
    LineEdit,
    ListWidget,
    PushButton,
    RoundMenu,
    TextEdit,
    TreeView,
)

from gui.styles import BaseStyles
from gui.styles.fluent import apply_label_role
from gui.styles.icon_loader import get_themed_icon
from gui.styles.typography import FontRole
from gui.widgets.responsive_layout import reflow_widgets


def _apply_adaptive_text_heights(widget: QWidget) -> None:
    """按当前界面字体更新曾使用固定高度的文字按钮。"""
    for button in widget.findChildren(QPushButton):
        baseline = button.property("adaptiveBaseHeight")
        if baseline is None:
            continue
        button.setMinimumHeight(int(baseline))
        metrics_height = QFontMetrics(button.font()).height() + 10
        # qfluentwidgets PushButton 的最小行高由 minimumSizeHint 按点字号给出，
        # 像素字体的 sizeHint 比它低 2px；以 minimumSizeHint 为下限避免按钮被裁切。
        button.setMinimumHeight(
            max(
                int(baseline),
                button.sizeHint().height(),
                button.minimumSizeHint().height(),
                metrics_height,
            )
        )


class AppManagerForm:
    """组合进 AppManagerPage 的表单控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        self._frame = frame

    def _init_ui(self):
        from gui.dialogs import app_manager as _app_manager

        self._frame._page_layout = QVBoxLayout(self._frame)
        self._frame._page_layout.setContentsMargins(0, 0, 0, 0)
        self._frame._page_layout.setSpacing(0)
        self._frame._master_panel = QWidget(self._frame)
        self._frame._master_panel.setObjectName("appManagerMasterPanel")
        layout = QVBoxLayout(self._frame._master_panel)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 6)

        # ── 页头卡片：标题、副标题与设备连接状态徽标 ─────────────────────
        # 视觉重设计：页面内容顶部统一为 Fluent CardWidget 卡片页头（圆角由
        # CardWidget 自绘制并随主题切换，不再依赖 QFrame 页头 QSS）。
        # 副标题保持 UI 字体角色并以 TEXT_SECONDARY 次级文字色维持视觉层级；
        # 不用 UI_SMALL，遵守功能页字体测试不存在小型字角色控件的不变式。
        header_card = CardWidget()
        header_card.setObjectName("dialogHeaderCard")
        header_card.setBorderRadius(BaseStyles.RADIUS_LG)
        hl = QVBoxLayout(header_card)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._frame.dialog_title = apply_label_role(
            BodyLabel("App Manager"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.status_badge = InfoBadge.info("No device", header_card)
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip("Device availability for app actions")
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = apply_label_role(
            BodyLabel("Install, inspect and control device packages"),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        self._frame.dialog_subtitle.setObjectName("dialogSubtitle")
        self._frame.dialog_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self._frame.dialog_subtitle)
        self._frame.header_card = header_card
        layout.addWidget(header_card)

        self._frame._top_layout = QGridLayout()
        self._frame._top_layout.setSpacing(6)
        self._frame._search_label = apply_label_role(BodyLabel("Search:"), FontRole.UI)
        self._frame.search_input = LineEdit()
        self._frame.search_input.setPlaceholderText("Filter...")
        self._frame._search_label.setBuddy(self._frame.search_input)
        self._frame.search_input.setAccessibleName("Application search")
        self._frame.search_input.textChanged.connect(self._frame._filter)
        self._frame._type_label = apply_label_role(BodyLabel("Type:"), FontRole.UI)
        self._frame.type_filter = ComboBox()
        self._frame.type_filter.addItems(["All", "User Apps", "System Apps"])
        self._frame._type_label.setBuddy(self._frame.type_filter)
        self._frame.type_filter.setAccessibleName("Application type")
        self._frame.type_filter.currentIndexChanged.connect(self._frame._filter)
        self._frame.selection_label = apply_label_role(BodyLabel("Selected: 0"), FontRole.UI)
        self._frame.selection_label.setMinimumWidth(82)
        self._frame.view_toggle = PushButton()
        self._frame.view_toggle.setFixedSize(28, 28)
        self._frame.view_toggle.setToolTip("Toggle Icon / List view")
        self._frame.view_toggle.setAccessibleName("Toggle Icon / List view")
        self._frame.view_toggle.clicked.connect(self._frame._toggle_view)
        self._frame.view_toggle.setIcon(get_themed_icon("list-bullets.svg"))
        self._frame.view_toggle.setIconSize(QSize(16, 16))
        self._frame.refresh_btn = PushButton()
        self._frame.refresh_btn.setText("Refresh")
        self._frame.refresh_btn.setToolTip("Reload the installed application list")
        self._frame.refresh_btn.setIcon(get_themed_icon("arrows-clockwise.svg"))
        self._frame.refresh_btn.setIconSize(QSize(14, 14))
        self._frame.refresh_btn.clicked.connect(self._frame._load_apps)
        self._frame.refresh_btn.setProperty("adaptiveBaseHeight", 28)
        self._frame._top_controls = (
            self._frame._search_label,
            self._frame.search_input,
            self._frame._type_label,
            self._frame.type_filter,
            self._frame.selection_label,
            self._frame.view_toggle,
            self._frame.refresh_btn,
        )
        layout.addLayout(self._frame._top_layout)
        self._frame._reflow_top_controls()

        self._frame.load_error_panel = QFrame()
        self._frame.load_error_panel.setObjectName("appManagerLoadError")
        error_layout = QHBoxLayout(self._frame.load_error_panel)
        error_layout.setContentsMargins(8, 4, 8, 4)
        error_layout.setSpacing(8)
        self._frame.load_error_label = apply_label_role(
            CaptionLabel("Unable to load applications."),
            FontRole.UI_SMALL,
            color_key="ERROR_COLOR",
        )
        self._frame.load_error_label.setWordWrap(True)
        self._frame.load_error_label.setAccessibleName("Application load error")
        self._frame.retry_btn = PushButton("Retry")
        self._frame.retry_btn.setToolTip("Retry loading the installed application list")
        self._frame.retry_btn.setAccessibleName("Retry application loading")
        self._frame.retry_btn.setIcon(get_themed_icon("arrows-clockwise.svg"))
        self._frame.retry_btn.setIconSize(QSize(14, 14))
        self._frame.retry_btn.setProperty("adaptiveBaseHeight", 28)
        self._frame.retry_btn.clicked.connect(self._frame.retry_load)
        error_layout.addWidget(self._frame.load_error_label, 1)
        error_layout.addWidget(self._frame.retry_btn)
        self._frame.load_error_panel.hide()
        layout.addWidget(self._frame.load_error_panel)

        self._frame.stack = QStackedWidget()

        self._frame.model = QStandardItemModel(0, 6)
        self._frame.model.setHorizontalHeaderLabels(
            ["", "App Name", "Package Name", "Version", "Status", "Type"]
        )
        self._frame.model.itemChanged.connect(self._frame._on_table_item_changed)
        self._frame.proxy = _app_manager.AppSortProxy()
        self._frame.proxy.setSourceModel(self._frame.model)
        self._frame.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._frame.proxy.setFilterKeyColumn(-1)
        self._frame.tree = TreeView()
        self._frame.tree.setFrameShape(QFrame.Shape.NoFrame)
        self._frame.tree.setModel(self._frame.proxy)
        self._frame.tree.setSortingEnabled(True)
        self._frame.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._frame.tree.setAlternatingRowColors(True)
        self._frame.tree.setRootIsDecorated(False)
        self._frame.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._frame.tree.customContextMenuRequested.connect(self._frame._context_menu)
        self._frame.tree.clicked.connect(self._frame._on_row_clicked)
        h = self._frame.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for i in range(1, 6):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self._frame.tree.setColumnWidth(0, 40)
        self._frame.tree.setColumnWidth(1, 160)
        self._frame.tree.setColumnWidth(2, 320)
        self._frame.tree.setColumnWidth(3, 100)
        self._frame.tree.setColumnWidth(4, 70)
        self._frame.tree.setColumnWidth(5, 60)
        self._frame.tree.verticalScrollBar().valueChanged.connect(
            lambda _value: self._frame._schedule_visible_detail_load()
        )
        self._frame.stack.addWidget(self._frame.tree)

        self._frame.icon_list = ListWidget()
        self._frame.icon_list.setViewMode(ListWidget.ViewMode.IconMode)
        self._frame.icon_list.setResizeMode(ListWidget.ResizeMode.Adjust)
        self._frame.icon_list.setIconSize(QSize(48, 48))
        self._frame.icon_list.setSpacing(4)
        self._frame.icon_list.setGridSize(QSize(110, 80))
        self._frame.icon_list.setWordWrap(True)
        self._frame.icon_list.setMovement(ListWidget.Movement.Static)
        self._frame.icon_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._frame.icon_list.customContextMenuRequested.connect(self._frame._icon_context_menu)
        self._frame.icon_list.itemDoubleClicked.connect(self._frame._icon_double_click)
        self._frame.icon_list.setSelectionMode(ListWidget.SelectionMode.ExtendedSelection)
        self._frame.icon_list.itemSelectionChanged.connect(self._frame._on_icon_selection_changed)
        self._frame.icon_list.verticalScrollBar().valueChanged.connect(
            lambda _value: self._frame._schedule_visible_detail_load()
        )
        self._frame.stack.addWidget(self._frame.icon_list)

        self._frame._view_mode = False  # False 表示表格视图，True 表示图标视图
        layout.addWidget(self._frame.stack, 2)

        btn_h = 30
        self._frame._selection_action_layout = QGridLayout()
        self._frame._selection_action_layout.setSpacing(4)
        self._frame._selection_action_buttons = []
        labels_actions = [
            (
                "Uninstall Selected",
                "uninstall",
                "trash.svg",
                "Remove the selected applications",
            ),
            (
                "Disable Selected",
                "disable",
                "prohibit.svg",
                "Disable the selected applications",
            ),
            (
                "Enable Selected",
                "enable",
                "check-circle.svg",
                "Enable the selected applications",
            ),
            ("Deselect All", None, "square.svg", "Clear the application selection"),
        ]
        for t, a, icon, tooltip in labels_actions:
            b = PushButton()
            b.setText(t)
            b.setIcon(get_themed_icon(icon))
            b.setIconSize(QSize(14, 14))
            b.setProperty("adaptiveBaseHeight", btn_h)
            b.setToolTip(tooltip)
            b.setAccessibleName(t)
            b.setAccessibleDescription(tooltip)
            b.setProperty("requiresDevice", a is not None)
            b.setProperty("requiresSelection", True)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            if a:
                b.clicked.connect(lambda _, act=a: self._frame._modify_selected(act))
            else:
                b.clicked.connect(self._frame._deselect_all)
            self._frame._selection_action_buttons.append(b)
        layout.addLayout(self._frame._selection_action_layout)

        self._frame._preset_action_layout = QGridLayout()
        self._frame._preset_action_layout.setSpacing(4)
        self._frame._preset_action_buttons = []
        for t, fn, icon, tooltip in [
            (
                "Create Preset",
                self._frame._create_preset,
                "floppy-disk.svg",
                "Save the selected package list as a preset",
            ),
            (
                "Load Preset",
                self._frame._load_preset,
                "folder-open.svg",
                "Select applications from a saved preset",
            ),
            (
                "Backup Selected",
                self._frame._backup_selected,
                "archive.svg",
                "Back up the selected applications",
            ),
            (
                "Restore Backup",
                self._frame._restore_apps,
                "cloud-arrow-down.svg",
                "Restore applications from a backup",
            ),
            (
                "App Details",
                self._frame._show_details,
                "info.svg",
                "Show details for the selected application",
            ),
        ]:
            b = PushButton()
            b.setText(t)
            b.setIcon(get_themed_icon(icon))
            b.setIconSize(QSize(14, 14))
            b.setProperty("adaptiveBaseHeight", btn_h)
            b.setToolTip(tooltip)
            b.setAccessibleName(t)
            b.setAccessibleDescription(tooltip)
            b.setProperty(
                "requiresDevice",
                t in {"Backup Selected", "Restore Backup", "App Details"},
            )
            b.setProperty(
                "requiresSelection",
                t in {"Create Preset", "Backup Selected", "App Details"},
            )
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            b.clicked.connect(fn)
            if t in {"Create Preset", "Backup Selected", "App Details"}:
                self._frame._selection_action_buttons.append(b)
            self._frame._preset_action_buttons.append(b)
        layout.addLayout(self._frame._preset_action_layout)

        self._frame.log_output = TextEdit()
        self._frame.log_output.setReadOnly(True)
        self._frame.log_output.setMaximumHeight(100)
        self._frame.log_output.setPlaceholderText("Operation log...")
        layout.addWidget(self._frame.log_output, 1)

        self._frame.status_bar = apply_label_role(
            CaptionLabel("Ready"), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self._frame.status_bar.setAccessibleName("Application manager status")
        layout.addWidget(self._frame.status_bar)
        self._frame._update_selection_ui()
        self._frame._reflow_action_buttons()

    def _apply_theme(self, _value=None):
        bs = BaseStyles
        ui_font = bs.font_for_role(FontRole.UI)
        log_font = bs.font_for_role(FontRole.LOG)
        self._frame.setFont(ui_font)
        bg = bs.color("INPUT_BG")
        fg = bs.color("TEXT_PRIMARY")
        border = bs.color("BORDER_COLOR")
        # 日志输出框样式由 qfluentwidgets TextEdit 自维护，这里仅同步等宽字体。
        self._frame.log_output.setFont(log_font)
        self._frame.log_output.document().setDefaultFont(log_font)
        self._frame.load_error_label.setFont(bs.font_for_role(FontRole.UI_SMALL))
        self._frame.retry_btn.setFont(ui_font)
        # 应用树样式由 qfluentwidgets TreeView 自维护（随主题切换）。
        self._frame.icon_list.setStyleSheet(
            "QListWidget { background-color:"
            f"{bg}; color:{fg}; border:1px solid {border}; border-radius:{bs.RADIUS_MD}px; "
            "} QListWidget::item:selected { background-color:"
            f"{bs.color('SELECTION_BG')}; color:{bs.color('SELECTION_TEXT')}; border-radius:4px"
            "; }"
        )
        # 状态信息直接使用 qfluentwidgets CaptionLabel。
        for control in self._frame._top_controls:
            control.setFont(ui_font)
            control.updateGeometry()
        for button in (*self._frame._selection_action_buttons, *self._frame._preset_action_buttons):
            button.setFont(ui_font)
            button.updateGeometry()
        view_hint = self._frame.view_toggle.minimumSizeHint()
        self._frame.view_toggle.setFixedSize(
            max(28, view_hint.width()), max(28, view_hint.height())
        )
        _apply_adaptive_text_heights(self._frame)
        self._frame._reflow_top_controls()
        self._frame._reflow_action_buttons()
        self._apply_header_style()

    # ── 页头与状态徽标视觉 ──────────────────────────────────────────────

    def _apply_header_style(self) -> None:
        """按字体变更刷新直接使用的参考标签与徽标。"""

        bs = BaseStyles
        self._frame.dialog_title.setFont(bs.font_for_role(FontRole.TITLE))
        self._frame.dialog_subtitle.setFont(bs.font_for_role(FontRole.UI))
        self._frame.status_badge.setFont(bs.font_for_role(FontRole.UI))
        self._refresh_status_badge()

    def _refresh_status_badge(self) -> None:
        """按设备连接状态刷新徽标；绿=已连接设备，蓝=未选择设备。"""

        has_device = bool(self._frame.device_ip)
        connected = bool(getattr(self._frame, "_device_connected", has_device))
        if not has_device:
            text, level = "No device", InfoLevel.INFOAMTION
        elif connected:
            text, level = "Ready", InfoLevel.SUCCESS
        else:
            text, level = "Offline", InfoLevel.WARNING
        self._frame.status_badge.setText(text)
        self._frame.status_badge.setLevel(level)

    def _action_layout_available_width(self) -> int:
        surface = getattr(self._frame, "_master_panel", None)
        if not isinstance(surface, QWidget):
            surface = self._frame
        layout = surface.layout()
        if layout is None:
            return max(1, surface.contentsRect().width())
        margins = layout.contentsMargins()
        if not getattr(self._frame, "_details_open", False):
            surface_width = self._frame.contentsRect().width()
        else:
            surface_width = surface.contentsRect().width()
        return max(1, surface_width - margins.left() - margins.right())

    @staticmethod
    def _buttons_fit_columns(buttons, columns: int, available_width: int, spacing: int) -> bool:
        rows = [buttons[index : index + columns] for index in range(0, len(buttons), columns)]
        return all(
            sum(button.minimumSizeHint().width() for button in row) + spacing * max(0, len(row) - 1)
            <= available_width
            for row in rows
        )

    def _reflow_action_group(
        self,
        layout: QGridLayout,
        buttons: list[QPushButton],
        short_labels: tuple[str, ...],
        wide_columns: int,
        *,
        span_last_in_two_columns: bool = False,
    ) -> None:
        available_width = self._frame._action_layout_available_width()
        full_labels = tuple(button.accessibleName() for button in buttons)
        spacing = layout.spacing()
        for button, label in zip(buttons, full_labels):
            if button.text() != label:
                button.setText(label)
                button.updateGeometry()
        if self._frame._buttons_fit_columns(buttons, wide_columns, available_width, spacing):
            columns = wide_columns
        elif self._frame._buttons_fit_columns(buttons, 2, available_width, spacing):
            columns = 2
        else:
            for button, label in zip(buttons, short_labels):
                button.setText(label)
                button.updateGeometry()
            if self._frame._buttons_fit_columns(buttons, 2, available_width, spacing):
                columns = 2
            else:
                columns = 1

        reflow_widgets(layout, buttons, columns)
        if span_last_in_two_columns and columns == 2:
            last_button = buttons[-1]
            last_index = layout.indexOf(last_button)
            row, _column, _row_span, _column_span = cast(
                tuple[int, int, int, int], layout.getItemPosition(last_index)
            )
            layout.removeWidget(last_button)
            layout.addWidget(last_button, row, 0, 1, 2)

    def _reflow_action_buttons(self) -> None:
        if not hasattr(self._frame, "_selection_action_layout"):
            return
        self._frame._reflow_action_group(
            self._frame._selection_action_layout,
            self._frame._selection_action_buttons[:4],
            ("Uninstall", "Disable", "Enable", "Clear"),
            4,
        )
        self._frame._reflow_action_group(
            self._frame._preset_action_layout,
            self._frame._preset_action_buttons,
            ("Save", "Load", "Backup", "Restore", "Details"),
            5,
            span_last_in_two_columns=True,
        )

    def _top_controls_fit(self, columns: int) -> bool:
        """检查指定顶部布局的每一行能否容纳控件真实最小宽度。"""

        controls = self._frame._top_controls
        row_groups = {
            7: (controls,),
            5: (controls[:2], controls[2:]),
            3: (controls[:2], controls[2:4], controls[4:]),
        }
        rows = row_groups[columns]
        spacing = self._frame._top_layout.spacing()
        available_width = self._frame._action_layout_available_width()
        return all(
            sum(widget.minimumSizeHint().width() for widget in row) + spacing * max(0, len(row) - 1)
            <= available_width
            for row in rows
        )

    def _reflow_top_controls(self) -> None:
        """按字体感知的真实最小宽度重排搜索、筛选和刷新入口。"""

        if not hasattr(self._frame, "_top_layout"):
            return
        for widget in self._frame._top_controls:
            self._frame._top_layout.removeWidget(widget)
        for column in range(max(7, self._frame._top_layout.columnCount())):
            self._frame._top_layout.setColumnStretch(column, 0)

        if self._frame._top_controls_fit(7):
            for column, widget in enumerate(self._frame._top_controls):
                self._frame._top_layout.addWidget(widget, 0, column)
            self._frame._top_layout.setColumnStretch(1, 1)
            return

        if self._frame._top_controls_fit(5):
            self._frame._top_layout.addWidget(self._frame._search_label, 0, 0)
            self._frame._top_layout.addWidget(self._frame.search_input, 0, 1, 1, 4)
            self._frame._top_layout.addWidget(self._frame._type_label, 1, 0)
            self._frame._top_layout.addWidget(self._frame.type_filter, 1, 1)
            self._frame._top_layout.addWidget(self._frame.selection_label, 1, 2)
            self._frame._top_layout.addWidget(self._frame.view_toggle, 1, 3)
            self._frame._top_layout.addWidget(self._frame.refresh_btn, 1, 4)
            self._frame._top_layout.setColumnStretch(1, 1)
            return

        self._frame._top_layout.addWidget(self._frame._search_label, 0, 0)
        self._frame._top_layout.addWidget(self._frame.search_input, 0, 1, 1, 2)
        self._frame._top_layout.addWidget(self._frame._type_label, 1, 0)
        self._frame._top_layout.addWidget(self._frame.type_filter, 1, 1, 1, 2)
        self._frame._top_layout.addWidget(self._frame.selection_label, 2, 0)
        self._frame._top_layout.addWidget(self._frame.view_toggle, 2, 1)
        self._frame._top_layout.addWidget(self._frame.refresh_btn, 2, 2)
        self._frame._top_layout.setColumnStretch(2, 1)

    def _create_context_menu(self) -> RoundMenu:
        """创建跟随 qfluentwidgets 主题的上下文菜单。"""

        menu = RoundMenu(parent=self._frame)
        menu.setFont(BaseStyles.font_for_role(FontRole.UI))
        return menu
