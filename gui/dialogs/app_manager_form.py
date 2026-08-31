"""应用管理器表单控制器 — 构建界面、应用主题并处理响应式重排。"""

from typing import cast

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
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
        button.setMinimumHeight(max(int(baseline), button.sizeHint().height(), metrics_height))


class AppManagerForm:
    """组合进 AppManagerDialog 的表单控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    def _init_ui(self):
        from gui.dialogs import app_manager as _app_manager

        layout = QVBoxLayout(self._frame)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 6)

        # ── 页头卡片：标题、副标题与设备连接状态徽标 ─────────────────────
        # 视觉重设计：对话框内容顶部统一为卡片页头（面板底色+细边框+大圆角）。
        # 副标题保持 UI 字体角色并以 TEXT_SECONDARY 次级文字色维持视觉层级；
        # 不用 UI_SMALL，遵守对话框字体爆发测试不存在小型字角色控件的不变式。
        header_card = QFrame()
        header_card.setObjectName("dialogHeaderCard")
        hl = QVBoxLayout(header_card)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._frame.dialog_title = QLabel("App Manager")
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.dialog_title.setProperty("fontRole", FontRole.TITLE.value)
        self._frame.dialog_title.setFont(BaseStyles.font_for_role(FontRole.TITLE))
        self._frame.status_badge = QLabel("No device")
        self._frame.status_badge.setObjectName("dialogStatusBadge")
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip("Device availability for app actions")
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = QLabel("Install, inspect and control device packages")
        self._frame.dialog_subtitle.setObjectName("dialogSubtitle")
        self._frame.dialog_subtitle.setProperty("fontRole", FontRole.UI.value)
        self._frame.dialog_subtitle.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.dialog_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self._frame.dialog_subtitle)
        self._frame.header_card = header_card
        layout.addWidget(header_card)

        self._frame._top_layout = QGridLayout()
        self._frame._top_layout.setSpacing(6)
        self._frame._search_label = QLabel("Search:")
        self._frame.search_input = QLineEdit()
        self._frame.search_input.setPlaceholderText("Filter...")
        self._frame._search_label.setBuddy(self._frame.search_input)
        self._frame.search_input.setAccessibleName("Application search")
        self._frame.search_input.textChanged.connect(self._frame._filter)
        self._frame._type_label = QLabel("Type:")
        self._frame.type_filter = QComboBox()
        self._frame.type_filter.addItems(["All", "User Apps", "System Apps"])
        self._frame._type_label.setBuddy(self._frame.type_filter)
        self._frame.type_filter.setAccessibleName("Application type")
        self._frame.type_filter.currentIndexChanged.connect(self._frame._filter)
        self._frame.selection_label = QLabel("Selected: 0")
        self._frame.selection_label.setMinimumWidth(82)
        self._frame.view_toggle = QPushButton()
        self._frame.view_toggle.setFixedSize(28, 28)
        self._frame.view_toggle.setToolTip("Toggle Icon / List view")
        self._frame.view_toggle.setAccessibleName("Toggle Icon / List view")
        self._frame.view_toggle.clicked.connect(self._frame._toggle_view)
        self._frame.view_toggle.setIcon(get_themed_icon("list-bullets.svg"))
        self._frame.view_toggle.setIconSize(QSize(16, 16))
        self._frame.refresh_btn = QPushButton("Refresh")
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
        self._frame.tree = QTreeView()
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

        self._frame.icon_list = QListWidget()
        self._frame.icon_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._frame.icon_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._frame.icon_list.setIconSize(QSize(48, 48))
        self._frame.icon_list.setSpacing(4)
        self._frame.icon_list.setGridSize(QSize(110, 80))
        self._frame.icon_list.setWordWrap(True)
        self._frame.icon_list.setMovement(QListWidget.Movement.Static)
        self._frame.icon_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._frame.icon_list.customContextMenuRequested.connect(self._frame._icon_context_menu)
        self._frame.icon_list.itemDoubleClicked.connect(self._frame._icon_double_click)
        self._frame.icon_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
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
            b = QPushButton(t)
            b.setIcon(get_themed_icon(icon))
            b.setIconSize(QSize(14, 14))
            b.setProperty("adaptiveBaseHeight", btn_h)
            b.setToolTip(tooltip)
            b.setAccessibleName(t)
            b.setAccessibleDescription(tooltip)
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
            b = QPushButton(t)
            b.setIcon(get_themed_icon(icon))
            b.setIconSize(QSize(14, 14))
            b.setProperty("adaptiveBaseHeight", btn_h)
            b.setToolTip(tooltip)
            b.setAccessibleName(t)
            b.setAccessibleDescription(tooltip)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            b.clicked.connect(fn)
            if t in {"Create Preset", "Backup Selected", "App Details"}:
                self._frame._selection_action_buttons.append(b)
            self._frame._preset_action_buttons.append(b)
        layout.addLayout(self._frame._preset_action_layout)

        self._frame.log_output = QTextEdit()
        self._frame.log_output.setReadOnly(True)
        self._frame.log_output.setMaximumHeight(100)
        self._frame.log_output.setPlaceholderText("Operation log...")
        layout.addWidget(self._frame.log_output, 1)

        self._frame.status_bar = QStatusBar()
        self._frame.status_bar.showMessage("Ready")
        layout.addWidget(self._frame.status_bar)
        self._frame._update_selection_ui()
        self._frame._reflow_action_buttons()

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self._frame)
        bs = BaseStyles
        ui_font = bs.font_for_role(FontRole.UI)
        log_font = bs.font_for_role(FontRole.LOG)
        self._frame.setStyleSheet(bs.PANEL_BASE_STYLE())
        self._frame.setFont(ui_font)
        bg = bs.color("INPUT_BG")
        fg = bs.color("TEXT_PRIMARY")
        border = bs.color("BORDER_COLOR")
        self._frame.log_output.setStyleSheet(
            f"background-color:{bs.color('LOG_BACKGROUND')}; "
            f"color:{bs.color('LOG_TEXT_COLOR')}; border:1px solid {border}; "
            f"border-radius:{bs.RADIUS_MD}px;"
        )
        self._frame.log_output.setFont(log_font)
        self._frame.log_output.document().setDefaultFont(log_font)
        self._frame.tree.setStyleSheet(
            "QTreeView { background-color:"
            f"{bg}; color:{fg}; border:1px solid {border}; border-radius:{bs.RADIUS_MD}px; "
            "alternate-background-color:"
            f"{bs.color('INPUT_BG_HOVER')}; "
            "} QTreeView::item:selected { background-color:"
            f"{bs.color('SELECTION_BG')}; color:{bs.color('SELECTION_TEXT')}; "
            "} QHeaderView::section { background-color:"
            f"{bs.color('BUTTON_BG')}; color:{fg}; padding:4px; border:1px solid {border}"
            "; }"
        )
        self._frame.icon_list.setStyleSheet(
            "QListWidget { background-color:"
            f"{bg}; color:{fg}; border:1px solid {border}; border-radius:{bs.RADIUS_MD}px; "
            "} QListWidget::item:selected { background-color:"
            f"{bs.color('SELECTION_BG')}; color:{bs.color('SELECTION_TEXT')}; border-radius:4px"
            "; }"
        )
        self._frame.status_bar.setStyleSheet(bs.STATUS_BAR_STYLE())
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
        """视觉重设计：按当前主题重建页头卡片样式，并刷新各标签字体。"""

        bs = BaseStyles
        self._frame.header_card.setStyleSheet(
            f"QFrame#dialogHeaderCard {{ background-color: {bs.color('PANEL_BG')};"
            f" border: 1px solid {bs.color('BORDER_COLOR')};"
            f" border-radius: {bs.RADIUS_LG}px; }}"
        )
        self._frame.dialog_title.setFont(bs.font_for_role(FontRole.TITLE))
        self._frame.dialog_title.setStyleSheet(f"color: {bs.color('TITLE_COLOR')};")
        self._frame.dialog_subtitle.setFont(bs.font_for_role(FontRole.UI))
        self._frame.dialog_subtitle.setStyleSheet(f"color: {bs.color('TEXT_SECONDARY')};")
        self._frame.status_badge.setFont(bs.font_for_role(FontRole.UI))
        self._refresh_status_badge()

    def _refresh_status_badge(self) -> None:
        """视觉重设计：按设备连接状态刷新徽标；绿=已连接设备，灰=未选择设备。"""

        bs = BaseStyles
        has_device = bool(self._frame.device_ip)
        self._frame.status_badge.setText("Ready" if has_device else "No device")
        background = (
            bs.color("LOG_SUCCESS") if has_device else bs.color("TEXT_SECONDARY")
        )
        self._frame.status_badge.setStyleSheet(
            f"QLabel#dialogStatusBadge {{ background-color: {background};"
            f" color: {bs.color('PANEL_BG')};"
            f" border-radius: 7px; padding: 1px 8px; }}"
        )

    def _action_layout_available_width(self) -> int:
        margins = self._frame.layout().contentsMargins()
        return max(1, self._frame.contentsRect().width() - margins.left() - margins.right())

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

    def _create_context_menu(self) -> QMenu:
        """创建使用共享深浅主题样式的上下文菜单。"""

        menu = QMenu(self._frame)
        menu.setStyleSheet(BaseStyles.MENU_STYLE())
        return menu
