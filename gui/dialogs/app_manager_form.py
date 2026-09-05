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
    TreeItemDelegate,
    TreeView,
    setCustomStyleSheet,
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


class AppManagerItemDelegate(TreeItemDelegate):
    """保留 Fluent 复选绘制，并使用页面字号展示应用名与包名。"""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.font = cast(QWidget, self.parent()).font()
        option.fontMetrics = QFontMetrics(option.font)


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
        layout.setSpacing(8)
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
            BodyLabel("应用管理"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.status_badge = InfoBadge.info("未选择设备", header_card)
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip("当前设备的连接状态与操作资格")
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = apply_label_role(
            BodyLabel("查看应用信息、管理启用状态与备份"),
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
        self._frame._search_label = apply_label_role(BodyLabel("搜索"), FontRole.UI)
        self._frame.search_input = LineEdit()
        self._frame.search_input.setPlaceholderText("搜索应用名称或包名")
        self._frame._search_label.setBuddy(self._frame.search_input)
        self._frame.search_input.setAccessibleName("搜索应用")
        self._frame.search_input.textChanged.connect(self._frame._filter)
        self._frame._type_label = apply_label_role(BodyLabel("类型"), FontRole.UI)
        self._frame.type_filter = ComboBox()
        for label, key in (
            ("全部应用", "All"), ("用户应用", "User Apps"), ("系统应用", "System Apps")
        ):
            self._frame.type_filter.addItem(label, userData=key)
        self._frame._type_label.setBuddy(self._frame.type_filter)
        self._frame.type_filter.setAccessibleName("筛选应用类型")
        self._frame.type_filter.currentIndexChanged.connect(self._frame._filter)
        self._frame.selection_label = apply_label_role(BodyLabel("已选 0 项"), FontRole.UI)
        self._frame.selection_label.setMinimumWidth(82)
        self._frame.view_toggle = PushButton()
        self._frame.view_toggle.setFixedSize(28, 28)
        self._frame.view_toggle.setToolTip("切换图标或列表视图")
        self._frame.view_toggle.setAccessibleName("切换图标或列表视图")
        self._frame.view_toggle.clicked.connect(self._frame._toggle_view)
        self._frame.view_toggle.setIcon(get_themed_icon("list-bullets.svg"))
        self._frame.view_toggle.setIconSize(QSize(16, 16))
        self._frame.refresh_btn = PushButton()
        self._frame.refresh_btn.setText("刷新")
        self._frame.refresh_btn.setToolTip("重新加载已安装应用")
        self._frame.refresh_btn.setIcon(get_themed_icon("arrows-clockwise.svg"))
        self._frame.refresh_btn.setIconSize(QSize(14, 14))
        self._frame.refresh_btn.clicked.connect(self._frame._load_apps)
        self._frame.refresh_btn.setProperty("adaptiveBaseHeight", 28)
        self._frame._search_control = self._frame.search_input
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
            CaptionLabel("无法加载应用列表。"),
            FontRole.UI_SMALL,
            color_key="ERROR_COLOR",
        )
        self._frame.load_error_label.setWordWrap(True)
        self._frame.load_error_label.setAccessibleName("应用加载错误")
        self._frame.retry_btn = PushButton("重试")
        self._frame.retry_btn.setToolTip("重新尝试加载应用列表")
        self._frame.retry_btn.setAccessibleName("重试加载应用")
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
            ["", "应用名称", "包名", "版本", "状态", "类型"]
        )
        self._frame.model.itemChanged.connect(self._frame._on_table_item_changed)
        self._frame.proxy = _app_manager.AppSortProxy()
        self._frame.proxy.setSourceModel(self._frame.model)
        self._frame.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._frame.proxy.setFilterKeyColumn(-1)
        self._frame.tree = TreeView()
        self._frame.tree.setObjectName("appManagerTable")
        self._frame.tree.setItemDelegate(AppManagerItemDelegate(self._frame.tree))
        self._frame.tree.setBorderVisible(True)
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
        # Fluent 复选框从列内 23px 绘制到 42px，需留出完整边框与右侧净空。
        self._frame.tree.setColumnWidth(0, 48)
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
                "卸载所选",
                "uninstall",
                "trash.svg",
                "卸载已选择的应用",
            ),
            (
                "停用所选",
                "disable",
                "prohibit.svg",
                "停用已选择的应用",
            ),
            (
                "启用所选",
                "enable",
                "check-circle.svg",
                "启用已选择的应用",
            ),
            ("取消全选", None, "square.svg", "清除当前应用选择"),
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
                "创建预设",
                self._frame._create_preset,
                "floppy-disk.svg",
                "将所选应用列表保存为预设",
            ),
            (
                "加载预设",
                self._frame._load_preset,
                "folder-open.svg",
                "根据已保存的预设选择应用",
            ),
            (
                "备份所选",
                self._frame._backup_selected,
                "archive.svg",
                "备份已选择的应用",
            ),
            (
                "恢复备份",
                self._frame._restore_apps,
                "cloud-arrow-down.svg",
                "从备份文件恢复应用",
            ),
            (
                "应用详情",
                self._frame._show_details,
                "info.svg",
                "查看所选应用的详情",
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
                t in {"备份所选", "恢复备份", "应用详情"},
            )
            b.setProperty(
                "requiresSelection",
                t in {"创建预设", "备份所选", "应用详情"},
            )
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            b.clicked.connect(fn)
            if t in {"创建预设", "备份所选", "应用详情"}:
                self._frame._selection_action_buttons.append(b)
            self._frame._preset_action_buttons.append(b)
        layout.addLayout(self._frame._preset_action_layout)

        self._frame.log_output = TextEdit()
        self._frame.log_output.setReadOnly(True)
        self._frame.log_output.setMaximumHeight(96)
        self._frame.log_output.setPlaceholderText("操作过程将在此显示")
        log_header = QHBoxLayout()
        log_header.addWidget(apply_label_role(BodyLabel("操作记录"), FontRole.UI))
        log_header.addStretch(1)
        self._frame.log_toggle = PushButton("展开记录")
        self._frame.log_toggle.setCheckable(True)
        self._frame.log_toggle.setChecked(False)
        self._frame.log_toggle.setAccessibleName("显示或收起操作记录")
        self._frame.log_toggle.setToolTip("查看或收起本页操作过程，收起后保留记录内容")
        self._frame.log_toggle.setAccessibleDescription(self._frame.log_toggle.toolTip())
        self._frame.log_toggle.toggled.connect(self._toggle_log)
        log_header.addWidget(self._frame.log_toggle)
        layout.addLayout(log_header)
        layout.addWidget(self._frame.log_output)
        self._frame.log_output.hide()

        self._frame.status_bar = apply_label_role(
            CaptionLabel("就绪"), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self._frame.status_bar.setAccessibleName("应用管理状态")
        self._frame.status_bar.setWordWrap(True)
        layout.addWidget(self._frame.status_bar)
        self._frame._update_selection_ui()
        self._frame._reflow_action_buttons()

    def prepare_for_workspace(self) -> None:
        """工作区已有页头，保留同一状态控件并避免重复创建工具栏容器。"""
        if getattr(self._frame, "_workspace_prepared", False):
            return
        self._frame._workspace_prepared = True
        self._frame.header_card.hide()
        search_control = QWidget(self._frame._master_panel)
        search_layout = QHBoxLayout(search_control)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(8)
        search_layout.addWidget(self._frame.search_input, 1)
        search_layout.addWidget(self._frame.status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self._frame.status_badge.show()
        self._frame._search_control = search_control
        controls = self._frame._top_controls
        self._frame._top_controls = (controls[0], search_control, *controls[2:])
        self._frame._reflow_top_controls()
        self._frame._master_panel.updateGeometry()
        self._frame.updateGeometry()

    def _apply_theme(self, _value=None):
        bs = BaseStyles
        ui_font = bs.font_for_role(FontRole.UI)
        log_font = bs.font_for_role(FontRole.LOG)
        self._frame.setFont(ui_font)
        # 工作区滚动容器可能保留创建时的调色板，页面表面自行提交当前主题底色。
        self._frame._master_panel.setStyleSheet(
            "QWidget#appManagerMasterPanel {"
            f"background-color: {bs.color('WINDOW_BG')};"
            "}"
        )
        bg = bs.color("INPUT_BG")
        fg = bs.color("TEXT_PRIMARY")
        border = bs.color("BORDER_COLOR")
        # 日志输出框样式由 qfluentwidgets TextEdit 自维护，这里仅同步等宽字体。
        self._frame.log_output.setFont(log_font)
        self._frame.log_output.document().setDefaultFont(log_font)
        self._frame.load_error_label.setFont(bs.font_for_role(FontRole.UI_SMALL))
        self._frame.retry_btn.setFont(ui_font)
        # 上游树控件的透明普通行与 Qt AlternateBase 在切换主题后可能反色。
        # 同时声明两套局部实色，并保留 Fluent 的表头、选中态和复选委托。
        self._frame.tree.setFont(ui_font)
        self._frame.tree.header().setFont(ui_font)
        for column in range(self._frame.model.columnCount()):
            self._frame.model.setHeaderData(
                column, Qt.Orientation.Horizontal, ui_font, Qt.ItemDataRole.FontRole
            )
        metrics = QFontMetrics(ui_font)
        self._frame.tree.setColumnWidth(4, max(96, metrics.horizontalAdvance("已停用") + 40))
        self._frame.tree.setColumnWidth(5, max(80, metrics.horizontalAdvance("厂商") + 40))
        row_height = max(36, QFontMetrics(ui_font).height() + 12)
        header_font_size = (
            f"{ui_font.pointSizeF()}pt" if ui_font.pointSizeF() > 0 else f"{ui_font.pixelSize()}px"
        )
        styles = []
        for theme in ("Light", "Dark"):
            styles.append(
                "QTreeView#appManagerTable {"
                f"background-color: {bs.color_for(theme, 'INPUT_BG')};"
                f"alternate-background-color: {bs.color_for(theme, 'INPUT_BG_HOVER')};"
                f"border: 1px solid {bs.color_for(theme, 'BORDER_COLOR')};"
                f"border-radius: {bs.RADIUS_MD}px;"
                "} QTreeView#appManagerTable::item {"
                f"height: {row_height}px;"
                "} QHeaderView, QHeaderView::section {"
                f"font-size: {header_font_size};"
                "}"
            )
        setCustomStyleSheet(self._frame.tree, styles[0], styles[1])
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
        # Fluent LineEdit 默认固定为 33px，大字体须重新按实际内容高度留白。
        editor = self._frame.search_input
        editor.setFont(ui_font)
        editor.setMaximumHeight(16777215)
        editor.setMinimumHeight(0)
        editor.setMinimumHeight(max(33, editor.sizeHint().height(), metrics.height() + 12))
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
        self._update_view_geometry()

    def _update_view_geometry(self) -> None:
        """保留可读的列表视口，超出小工作区的动作区域由宿主外层滚动承接。"""
        tree = self._frame.tree
        tree.ensurePolished()
        tree.doItemsLayout()
        row_heights = [
            tree.sizeHintForRow(row) for row in range(min(3, self._frame.proxy.rowCount()))
        ]
        # 空列表也预留同等空间；加载后以包含 Fluent 内边距的真实行高替代估计。
        fallback = max(36, QFontMetrics(tree.font()).height() + 12) + 12
        row_height = max(row_heights, default=fallback)
        tree.setMinimumHeight(
            row_height * 3
            + tree.header().sizeHint().height()
            + 2 * tree.frameWidth()
            + tree.horizontalScrollBar().sizeHint().height()
        )

        icons = self._frame.icon_list
        font = BaseStyles.font_for_role(FontRole.UI)
        icons.setFont(font)
        metrics = QFontMetrics(font)
        spacing = icons.spacing()
        grid = QSize(
            max(128, metrics.horizontalAdvance("应用名称") + 24),
            icons.iconSize().height() + metrics.height() * 2 + 16,
        )
        icons.setGridSize(grid)
        for index in range(icons.count()):
            item = icons.item(index)
            item.setFont(font)
            item.setSizeHint(grid - QSize(spacing * 2, spacing * 2))
        icons.setMinimumHeight(
            grid.height() * 2 + spacing * 2 + 2 * icons.frameWidth()
            + icons.horizontalScrollBar().sizeHint().height()
        )
        self._frame._master_panel.updateGeometry()
        self._frame.updateGeometry()

    def _toggle_log(self, expanded: bool) -> None:
        """收起操作记录只释放布局空间，日志内容与后台写入保持不变。"""
        self._frame.log_output.setVisible(expanded)
        self._frame.log_toggle.setText("收起记录" if expanded else "展开记录")

    # ── 页头与状态徽标视觉 ──────────────────────────────────────────────

    def _apply_header_style(self) -> None:
        """按字体变更刷新直接使用的参考标签与徽标。"""

        bs = BaseStyles
        self._frame.dialog_title.setFont(bs.font_for_role(FontRole.TITLE))
        self._frame.dialog_subtitle.setFont(bs.font_for_role(FontRole.UI))
        self._frame.status_badge.setFont(bs.font_for_role(FontRole.UI))
        self._refresh_status_badge()

    def _refresh_status_badge(self) -> None:
        """在线和操作选择分别呈现，避免把仅连接的会话显示为可操作。"""

        has_device = bool(self._frame.device_ip)
        connected = bool(getattr(self._frame, "_device_connected", has_device))
        if not has_device:
            text, level = "未选择设备", InfoLevel.INFOAMTION
        elif not connected:
            text, level = "离线", InfoLevel.WARNING
        elif not self._frame._device_selected:
            text, level = "未选为操作目标", InfoLevel.INFOAMTION
        else:
            text, level = "就绪", InfoLevel.SUCCESS
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
        # 中文短标签不能让窄窗意外挤回整行；保留批量动作两列与紧凑短动词层次。
        if available_width < 560:
            for button, label in zip(buttons, short_labels):
                button.setText(label)
                button.updateGeometry()
            columns = (
                2 if self._frame._buttons_fit_columns(buttons, 2, available_width, spacing) else 1
            )
        elif available_width >= 860 and self._frame._buttons_fit_columns(
            buttons, wide_columns, available_width, spacing
        ):
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
            ("卸载", "停用", "启用", "清除"),
            4,
        )
        self._frame._reflow_action_group(
            self._frame._preset_action_layout,
            self._frame._preset_action_buttons,
            ("保存", "加载", "备份", "恢复", "详情"),
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

        if self._frame._action_layout_available_width() >= 860 and self._frame._top_controls_fit(7):
            for column, widget in enumerate(self._frame._top_controls):
                self._frame._top_layout.addWidget(widget, 0, column)
            self._frame._top_layout.setColumnStretch(1, 1)
            return

        if self._frame._top_controls_fit(5):
            self._frame._top_layout.addWidget(self._frame._search_label, 0, 0)
            self._frame._top_layout.addWidget(self._frame._search_control, 0, 1, 1, 4)
            self._frame._top_layout.addWidget(self._frame._type_label, 1, 0)
            self._frame._top_layout.addWidget(self._frame.type_filter, 1, 1)
            self._frame._top_layout.addWidget(self._frame.selection_label, 1, 2)
            self._frame._top_layout.addWidget(self._frame.view_toggle, 1, 3)
            self._frame._top_layout.addWidget(self._frame.refresh_btn, 1, 4)
            self._frame._top_layout.setColumnStretch(1, 1)
            return

        self._frame._top_layout.addWidget(self._frame._search_label, 0, 0)
        self._frame._top_layout.addWidget(self._frame._search_control, 0, 1, 1, 2)
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
