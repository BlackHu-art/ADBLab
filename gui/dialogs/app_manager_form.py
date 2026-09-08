"""应用管理器表单控制器 — 构建界面、应用主题并处理响应式重排。"""

from typing import cast

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QFontMetrics, QStandardItemModel
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
    CommandBar,
    InfoBadge,
    InfoLevel,
    LineEdit,
    ListWidget,
    PushButton,
    RoundMenu,
    TransparentToolButton,
    TreeItemDelegate,
    TreeView,
    setCustomStyleSheet,
)

from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles.fluent import apply_focus_indicator, apply_label_role
from gui.styles.icon_loader import get_themed_icon
from gui.styles.typography import FontRole


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
            BodyLabel(tr("应用管理")), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.status_badge = InfoBadge.info(tr("未选择设备"), header_card)
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip(tr("当前设备的连接状态与操作资格"))
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = apply_label_role(
            BodyLabel(tr("查看应用信息、管理启用状态与备份")),
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
        self._frame._search_label = apply_label_role(BodyLabel(tr("搜索")), FontRole.UI)
        self._frame.search_input = LineEdit()
        self._frame.search_input.setPlaceholderText(tr("搜索应用名称或包名"))
        self._frame._search_label.setBuddy(self._frame.search_input)
        self._frame.search_input.setAccessibleName(tr("搜索应用"))
        self._frame.search_input.textChanged.connect(self._frame._filter)
        self._frame._type_label = apply_label_role(BodyLabel(tr("类型")), FontRole.UI)
        self._frame.type_filter = ComboBox()
        for label, key in (
            (tr("全部应用"), "All"), (tr("用户应用"), "User Apps"), (tr("系统应用"), "System Apps")
        ):
            self._frame.type_filter.addItem(label, userData=key)
        self._frame._type_label.setBuddy(self._frame.type_filter)
        self._frame.type_filter.setAccessibleName(tr("筛选应用类型"))
        self._frame.type_filter.currentIndexChanged.connect(self._frame._filter)
        self._frame.selection_label = apply_label_role(BodyLabel(tr("已选 0 项")), FontRole.UI)
        self._frame.selection_label.setMinimumWidth(82)
        self._frame.view_toggle = TransparentToolButton()
        self._frame.view_toggle.setFixedSize(28, 28)
        self._frame.view_toggle.setToolTip(tr("切换图标或列表视图"))
        self._frame.view_toggle.setAccessibleName(tr("切换图标或列表视图"))
        self._frame.view_toggle.clicked.connect(self._frame._toggle_view)
        self._frame.view_toggle.setIcon(get_themed_icon("list-bullets.svg"))
        self._frame.view_toggle.setIconSize(QSize(16, 16))
        self._frame.refresh_btn = PushButton()
        self._frame.refresh_btn.setText(tr("刷新"))
        self._frame.refresh_btn.setToolTip(tr("重新加载已安装应用"))
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
        for control in self._frame._top_controls:
            if control is not self._frame.search_input:
                control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout.addLayout(self._frame._top_layout)
        self._frame._reflow_top_controls()

        self._frame.load_error_panel = QFrame()
        self._frame.load_error_panel.setObjectName("appManagerLoadError")
        error_layout = QHBoxLayout(self._frame.load_error_panel)
        error_layout.setContentsMargins(8, 4, 8, 4)
        error_layout.setSpacing(8)
        self._frame.load_error_label = apply_label_role(
            CaptionLabel(tr("无法加载应用列表。")),
            FontRole.UI_SMALL,
            color_key="ERROR_COLOR",
        )
        self._frame.load_error_label.setWordWrap(True)
        self._frame.load_error_label.setAccessibleName(tr("应用加载错误"))
        self._frame.retry_btn = PushButton(tr("重试"))
        self._frame.retry_btn.setToolTip(tr("重新尝试加载应用列表"))
        self._frame.retry_btn.setAccessibleName(tr("重试加载应用"))
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
            ["", tr("应用名称"), tr("包名"), tr("版本"), tr("状态"), tr("类型")]
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

        bar = CommandBar(self._frame._master_panel)
        self._frame._command_bar = bar
        bar.setObjectName("appManagerCommandBar")
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.setButtonTight(True)
        bar.setSpaing(0)
        bar.setIconSize(QSize(16, 16))
        bar.setMenuDropDown(False)
        bar.moreButton.setAccessibleName(tr("更多应用操作"))
        bar.moreButton.setToolTip(tr("显示未展开的应用操作"))
        self._frame._command_icons = []
        for index, (t, fn, icon, tooltip, requires_device, requires_selection) in enumerate([
            (
                tr("卸载所选"),
                lambda: self._frame._modify_selected("uninstall"),
                "trash.svg", tr("卸载已选择的应用"), True, True,
            ),
            (
                tr("停用所选"),
                lambda: self._frame._modify_selected("disable"),
                "prohibit.svg", tr("停用已选择的应用"), True, True,
            ),
            (
                tr("启用所选"),
                lambda: self._frame._modify_selected("enable"),
                "check-circle.svg", tr("启用已选择的应用"), True, True,
            ),
            (
                tr("取消全选"), self._frame._deselect_all,
                "square.svg", tr("清除当前应用选择"), False, True,
            ),
            (
                tr("创建预设"),
                self._frame._create_preset,
                "floppy-disk.svg",
                tr("将所选应用列表保存为预设"),
                False, True,
            ),
            (
                tr("加载预设"),
                self._frame._load_preset,
                "folder-open.svg",
                tr("根据已保存的预设选择应用"),
                False, False,
            ),
            (
                tr("备份所选"),
                self._frame._backup_selected,
                "archive.svg",
                tr("备份已选择的应用"),
                True, True,
            ),
            (
                tr("恢复备份"),
                self._frame._restore_apps,
                "cloud-arrow-down.svg",
                tr("从备份文件恢复应用"),
                True, False,
            ),
            (
                tr("应用详情"),
                self._frame._show_details,
                "info.svg",
                tr("查看所选应用的详情"),
                True, True,
            ),
        ]):
            if index in (4, 6):
                bar.addSeparator()
            action = QAction(get_themed_icon(icon), t, bar)
            action.setToolTip(tooltip)
            action.setProperty("requiresDevice", requires_device)
            action.setProperty("requiresSelection", requires_selection)
            action.triggered.connect(fn)
            # 按钮与溢出菜单必须共享动作状态，不能以隐藏按钮作为准入代理。
            bar.addAction(action)
            self._frame._command_icons.append((action, icon))
        layout.addWidget(bar)

        self._frame.status_bar = apply_label_role(
            CaptionLabel(tr("就绪")), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self._frame.status_bar.setAccessibleName(tr("应用管理状态"))
        self._frame.status_bar.setWordWrap(True)
        layout.addWidget(self._frame.status_bar)
        self._frame._update_selection_ui()
        self._frame._reflow_action_buttons()

    def prepare_for_workspace(self) -> None:
        """嵌入时由宿主页头呈现设备状态，筛选行只保留应用筛选与刷新。"""
        if getattr(self._frame, "_workspace_prepared", False):
            return
        self._frame._workspace_prepared = True
        # 窗口留白移入整组主从内容，保留列表和详情原有的内部边距。
        self._frame._page_layout.setContentsMargins(24, 0, 24, 24)
        self._frame.header_card.hide()
        self._frame.status_badge.hide()
        self._frame._reflow_top_controls()
        self._frame._master_panel.updateGeometry()
        self._frame.updateGeometry()

    def _apply_theme(self, _value=None):
        bs = BaseStyles
        ui_font = bs.font_for_role(FontRole.UI)
        self._frame.setFont(ui_font)
        # 布局面板透出宿主材质，表格与日志仍分别维护自己的可读底色。
        self._frame._master_panel.setStyleSheet(
            "QWidget#appManagerMasterPanel {"
            "background-color: transparent;"
            "}"
        )
        bg = bs.color("INPUT_BG")
        fg = bs.color("TEXT_PRIMARY")
        border = bs.color("BORDER_COLOR")
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
        self._frame.tree.setColumnWidth(4, max(96, metrics.horizontalAdvance(tr("已停用")) + 40))
        self._frame.tree.setColumnWidth(5, max(80, metrics.horizontalAdvance(tr("厂商")) + 40))
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
        self._frame._command_bar.setFont(ui_font)
        for action, icon in self._frame._command_icons:
            action.setIcon(get_themed_icon(icon))
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
            max(128, metrics.horizontalAdvance(tr("应用名称")) + 24),
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
            text, level = tr("未选择设备"), InfoLevel.INFOAMTION
        elif not connected:
            text, level = tr("离线"), InfoLevel.WARNING
        elif not self._frame._device_selected:
            text, level = tr("未选为操作目标"), InfoLevel.INFOAMTION
        else:
            text, level = tr("就绪"), InfoLevel.SUCCESS
        self._frame.status_badge.setText(text)
        self._frame.status_badge.setLevel(level)
        reason = (
            tr("可执行应用操作。") if self._frame._can_operate()
            else tr("勾选当前在线设备后可执行应用操作，已加载内容仍可查看。")
        )
        description = tr("当前设备状态：{value0}。{value1}").format(value0=text, value1=reason)
        self._frame.search_input.setToolTip(description)
        self._frame.search_input.setAccessibleDescription(description)
        if self._frame._can_operate() and self._frame.status_bar.text() in (
            tr("请在顶部设备栏勾选当前设备后执行应用操作；已加载内容仍可查看。"),
            tr("请在顶部设备栏勾选当前在线设备后刷新。"),
        ):
            # 资格恢复只替换过期准入提示，保留随后到达的业务进度与错误文案。
            if self._frame._batch_workers:
                message = tr("正在执行批量操作，请等待完成。")
            elif self._frame._load_in_progress:
                message = tr("正在加载已安装应用…")
            elif self._frame.load_state == "error":
                message = self._frame.load_error_label.text()
            else:
                message = tr("就绪")
            self._frame.status_bar.setText(message)

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

    def _reflow_action_buttons(self) -> None:
        """按当前字体更新原生命令按钮尺寸，宽度不足由命令栏提供溢出菜单。"""
        bar = getattr(self._frame, "_command_bar", None)
        if bar is None:
            return
        for button in (*bar.commandButtons, bar.moreButton):
            button.setFont(bar.font())
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

    def _top_controls_fit(self, columns: int) -> bool:
        """按筛选控件的真实最小宽度选择行数，设备状态不参与内容布局。"""

        controls = self._frame._top_controls
        row_groups = {
            7: (controls,),
            5: (controls[:2], controls[2:]),
            3: (controls[:2], controls[2:4], controls[4:]),
        }
        rows = row_groups[columns]
        spacing = self._frame._top_layout.spacing()
        available_width = self._frame._action_layout_available_width()
        minimum_widths = {
            widget: max(widget.minimumWidth(), widget.minimumSizeHint().width())
            for widget in controls
        }
        return all(
            sum(minimum_widths[widget] for widget in row) + spacing * max(0, len(row) - 1)
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
            self._frame._top_layout.addWidget(self._frame._search_control, 0, 1, 1, 4)
            self._frame._top_layout.addWidget(self._frame._type_label, 1, 0)
            self._frame._top_layout.addWidget(self._frame.type_filter, 1, 1)
            self._frame._top_layout.addWidget(self._frame.selection_label, 1, 2)
            self._frame._top_layout.addWidget(self._frame.view_toggle, 1, 3)
            self._frame._top_layout.addWidget(self._frame.refresh_btn, 1, 4)
            self._frame._top_layout.setColumnStretch(2, 1)
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
