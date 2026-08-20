"""应用管理器对话框 — 列出、筛选、管理、备份/恢复设备上的应用。"""

import json
import weakref

from PySide6.QtCore import QSize, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QPainter,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from core.settings_manager import AppSettings
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    alive_callback,
    alive_forwarding_callback,
    fit_secondary_window_to_owner_screen,
    is_qobject_alive,
    safe_disconnect,
    wait_for_threads_later,
)
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from gui.widgets.responsive_layout import reflow_widgets
from models.app_manager_worker import AppManagerWorker


def _apply_adaptive_text_heights(widget: QWidget) -> None:
    """按当前界面字体更新曾使用固定高度的文字按钮。"""
    for button in widget.findChildren(QPushButton):
        baseline = button.property("adaptiveBaseHeight")
        if baseline is None:
            continue
        button.setMinimumHeight(int(baseline))
        metrics_height = QFontMetrics(button.font()).height() + 10
        button.setMinimumHeight(max(int(baseline), button.sizeHint().height(), metrics_height))


# ── 排序代理模型 ──────────────────────────────────────────────────────────


class AppSortProxy(QSortFilterProxyModel):
    STATUS_ORDER = {"Enabled": 0, "Disabled": 1}
    TYPE_ORDER = {"User": 0, "System": 1, "Vendor": 2, "Other": 3}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ""
        self._app_type = "All"

    def set_filters(self, search_text: str, app_type: str) -> None:
        self._search_text = search_text.strip().lower()
        self._app_type = app_type
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if model is None:
            return False
        name = str(model.index(source_row, 1, source_parent).data() or "").lower()
        package = str(model.index(source_row, 2, source_parent).data() or "").lower()
        app_type = str(model.index(source_row, 5, source_parent).data() or "")
        type_match = (
            self._app_type == "All"
            or (self._app_type == "User Apps" and app_type == "User")
            or (self._app_type == "System Apps" and app_type == "System")
        )
        text_match = (
            not self._search_text or self._search_text in name or self._search_text in package
        )
        return type_match and text_match

    def lessThan(self, left, right):
        col = left.column()
        ld = self.sourceModel().data(left)
        rd = self.sourceModel().data(right)
        if col == 2 and ld in self.STATUS_ORDER:
            return self.STATUS_ORDER[ld] < self.STATUS_ORDER[rd]
        if col == 3 and ld in self.TYPE_ORDER:
            return self.TYPE_ORDER[ld] < self.TYPE_ORDER[rd]
        return super().lessThan(left, right)


# ── 应用详情对话框 ─────────────────────────────────────────────────────────


class AppDetailsDialog(QDialog):
    def __init__(self, parent, device_ip: str, package_name: str):
        super().__init__(parent)
        self.device_ip = device_ip
        self.package_name = package_name
        self._workers = []
        self._closing = False
        self.setWindowTitle(f"Details: {package_name}")
        self.setWindowIcon(get_themed_icon("info.svg"))
        self.setMinimumSize(750, 560)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        dw = QWidget()
        dl = QVBoxLayout(dw)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        dl.addWidget(self.detail_text)
        self.tabs.addTab(dw, "App Details")

        pw = QWidget()
        pl = QVBoxLayout(pw)
        self.declared_list = self._ps(pl, "Declared Permissions (Read-Only)", checkable=False)
        self.requested_list = self._ps(pl, "Requested Permissions")
        self.runtime_list = self._ps(pl, "Runtime Permissions (Grant/Revoke)")
        pb = QHBoxLayout()
        self.grant_btn = QPushButton("Grant Selected")
        self.grant_btn.setToolTip("Grant the selected runtime permissions")
        self.grant_btn.setIcon(get_themed_icon("check-circle.svg"))
        self.grant_btn.setIconSize(QSize(14, 14))
        self.revoke_btn = QPushButton("Revoke Selected")
        self.revoke_btn.setToolTip("Revoke the selected runtime permissions")
        self.revoke_btn.setIcon(get_themed_icon("x-circle.svg"))
        self.revoke_btn.setIconSize(QSize(14, 14))
        self.grant_btn.clicked.connect(lambda: self._mp("grant"))
        self.revoke_btn.clicked.connect(lambda: self._mp("revoke"))
        pb.addWidget(self.grant_btn)
        pb.addWidget(self.revoke_btn)
        pl.addLayout(pb)
        self.tabs.addTab(pw, "Permissions")
        layout.addWidget(self.tabs)
        close_btn = QPushButton("Close")
        close_btn.setToolTip("Close the application details window")
        close_btn.setIcon(get_themed_icon("x.svg"))
        close_btn.setIconSize(QSize(14, 14))
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self)
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE())
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        mono_font = BaseStyles.font_for_role(FontRole.MONO)
        self.detail_text.setFont(mono_font)
        self.detail_text.document().setDefaultFont(mono_font)
        _apply_adaptive_text_heights(self)

    def _ps(self, parent, title, *, checkable=True):
        hl = QHBoxLayout()
        hl.addWidget(QLabel(title))
        if checkable:
            sb = QPushButton("Select All/None")
            sb.setToolTip("Toggle every permission in this list")
            sb.setIcon(get_themed_icon("check-square.svg"))
            sb.setIconSize(QSize(14, 14))
            sb.setMinimumWidth(130)
            sb.setProperty("adaptiveBaseHeight", 28)
            hl.addWidget(sb)
        parent.addLayout(hl)
        lw = QListWidget()
        lw.setMinimumHeight(100)
        lw.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection
            if checkable
            else QListWidget.SelectionMode.NoSelection
        )
        parent.addWidget(lw)
        if checkable:
            sb.clicked.connect(lambda: self._ta(lw))
        return lw

    @staticmethod
    def _ta(lw):
        any_u = any(lw.item(i).checkState() != Qt.CheckState.Checked for i in range(lw.count()))
        st = Qt.CheckState.Checked if any_u else Qt.CheckState.Unchecked
        for i in range(lw.count()):
            lw.item(i).setCheckState(st)

    def _load_data(self):
        if self._closing:
            return
        self._rw("app_details", package_name=self.package_name, app_details_loaded=self._od)
        self._rp()

    def _rp(self):
        if self._closing:
            return
        self._rw("permissions", package_name=self.package_name, permissions_loaded=self._op)

    def _od(self, d):
        self.detail_text.clear()
        for k, v in d.items():
            self.detail_text.append(f"<b>{k}:</b> {v}")

    def _op(self, declared, requested, runtime):
        def fill(lw, items, fmt=lambda x: x, *, checkable=True):
            lw.clear()
            for item in items:
                i = QListWidgetItem(fmt(item))
                if checkable:
                    i.setFlags(i.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    i.setCheckState(Qt.CheckState.Unchecked)
                else:
                    i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                lw.addItem(i)

        fill(self.declared_list, declared, checkable=False)
        fill(self.requested_list, requested)
        fill(self.runtime_list, runtime, lambda r: f"{r[0]} (Granted: {r[1]})")

    def _mp(self, action):
        rc = [
            self.runtime_list.item(i).text().split(" (")[0]
            for i in range(self.runtime_list.count())
            if self.runtime_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        rq = [
            self.requested_list.item(i).text()
            for i in range(self.requested_list.count())
            if self.requested_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        sel = rc + rq
        if not sel:
            QMessageBox.warning(self, "No Selection", f"No permissions selected to {action}.")
            return
        for perm in sel:
            self._rw(
                "modify_permission",
                package_name=self.package_name,
                permission=perm,
                action=action,
                operation_done=alive_callback(self, "_rp"),
            )

    def _rw(self, op, **kw):
        if self._closing:
            return None
        w = AppManagerWorker(self.device_ip, op, **kw)
        w.setParent(self)
        for s in ["log_message", "app_details_loaded", "permissions_loaded", "operation_done"]:
            if s in kw:
                getattr(w, s).connect(kw[s])
        owner = self.parent()
        if hasattr(owner, "log"):
            w.log_message.connect(alive_forwarding_callback(owner, "log"))
        w.finished.connect(alive_callback(self, "_prune_worker", w))
        self._workers.append(w)
        w.start()
        return w

    def _prune_worker(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
        if is_qobject_alive(worker) and hasattr(worker, "deleteLater"):
            worker.deleteLater()

    def closeEvent(self, event):
        """中止详情 worker，并把等待操作移交后台，避免阻塞关闭事件。"""
        self._closing = True
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
        workers = self._workers
        self._workers = []
        for w in workers:
            w.abort()
            w.setParent(None)
        wait_for_threads_later(workers, 5000)
        super().closeEvent(event)


# ── 主应用管理器对话框 ────────────────────────────────────────────────────


class AppManagerDialog(QDialog):
    def __init__(self, parent=None, device_ip: str = ""):
        super().__init__(parent, Qt.Window)
        self.device_ip = device_ip
        self.selected_packages = set()
        self._syncing_selection = False
        self._batch_workers = set()
        self._batch_total = 0
        self._batch_action = ""
        self._workers = []
        self._detail_dialogs = {}
        self._load_request_id = 0
        self._active_load_request = 0
        self._apps_data = []
        self._detail_cache = {}
        self._pending_detail_packages = set()
        self._detail_worker_running = False
        self._closing = False
        self._detail_row_by_pkg = {}
        self._detail_icon_by_pkg = {}
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.timeout.connect(self._load_visible_details)
        self.setWindowTitle(f"App Manager - {device_ip}")
        self.setWindowIcon(get_themed_icon("squares-four.svg"))
        self.setMinimumSize(760, 600)
        self.resize(1000, 660)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._load_apps()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 6)

        self._top_layout = QGridLayout()
        self._top_layout.setSpacing(6)
        self._search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter...")
        self._search_label.setBuddy(self.search_input)
        self.search_input.setAccessibleName("Application search")
        self.search_input.textChanged.connect(self._filter)
        self._type_label = QLabel("Type:")
        self.type_filter = QComboBox()
        self.type_filter.addItems(["All", "User Apps", "System Apps"])
        self._type_label.setBuddy(self.type_filter)
        self.type_filter.setAccessibleName("Application type")
        self.type_filter.currentIndexChanged.connect(self._filter)
        self.selection_label = QLabel("Selected: 0")
        self.selection_label.setMinimumWidth(82)
        self.view_toggle = QPushButton()
        self.view_toggle.setFixedSize(28, 28)
        self.view_toggle.setToolTip("Toggle Icon / List view")
        self.view_toggle.setAccessibleName("Toggle Icon / List view")
        self.view_toggle.clicked.connect(self._toggle_view)
        self.view_toggle.setIcon(get_themed_icon("list-bullets.svg"))
        self.view_toggle.setIconSize(QSize(16, 16))
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Reload the installed application list")
        self.refresh_btn.setIcon(get_themed_icon("arrows-clockwise.svg"))
        self.refresh_btn.setIconSize(QSize(14, 14))
        self.refresh_btn.clicked.connect(self._load_apps)
        self.refresh_btn.setProperty("adaptiveBaseHeight", 28)
        self._top_controls = (
            self._search_label,
            self.search_input,
            self._type_label,
            self.type_filter,
            self.selection_label,
            self.view_toggle,
            self.refresh_btn,
        )
        layout.addLayout(self._top_layout)
        self._reflow_top_controls()

        self.stack = QStackedWidget()

        self.model = QStandardItemModel(0, 6)
        self.model.setHorizontalHeaderLabels(
            ["", "App Name", "Package Name", "Version", "Status", "Type"]
        )
        self.model.itemChanged.connect(self._on_table_item_changed)
        self.proxy = AppSortProxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setSortingEnabled(True)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.clicked.connect(self._on_row_clicked)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for i in range(1, 6):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 40)
        self.tree.setColumnWidth(1, 160)
        self.tree.setColumnWidth(2, 320)
        self.tree.setColumnWidth(3, 100)
        self.tree.setColumnWidth(4, 70)
        self.tree.setColumnWidth(5, 60)
        self.tree.verticalScrollBar().valueChanged.connect(
            lambda _value: self._schedule_visible_detail_load()
        )
        self.stack.addWidget(self.tree)

        self.icon_list = QListWidget()
        self.icon_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.icon_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.icon_list.setIconSize(QSize(48, 48))
        self.icon_list.setSpacing(4)
        self.icon_list.setGridSize(QSize(110, 80))
        self.icon_list.setWordWrap(True)
        self.icon_list.setMovement(QListWidget.Movement.Static)
        self.icon_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.icon_list.customContextMenuRequested.connect(self._icon_context_menu)
        self.icon_list.itemDoubleClicked.connect(self._icon_double_click)
        self.icon_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.icon_list.itemSelectionChanged.connect(self._on_icon_selection_changed)
        self.icon_list.verticalScrollBar().valueChanged.connect(
            lambda _value: self._schedule_visible_detail_load()
        )
        self.stack.addWidget(self.icon_list)

        self._view_mode = False  # False 表示表格视图，True 表示图标视图
        layout.addWidget(self.stack, 2)

        btn_h = 30
        self._selection_action_layout = QGridLayout()
        self._selection_action_layout.setSpacing(4)
        self._selection_action_buttons = []
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
                b.clicked.connect(lambda _, act=a: self._modify_selected(act))
            else:
                b.clicked.connect(self._deselect_all)
            self._selection_action_buttons.append(b)
        layout.addLayout(self._selection_action_layout)

        self._preset_action_layout = QGridLayout()
        self._preset_action_layout.setSpacing(4)
        self._preset_action_buttons = []
        for t, fn, icon, tooltip in [
            (
                "Create Preset",
                self._create_preset,
                "floppy-disk.svg",
                "Save the selected package list as a preset",
            ),
            (
                "Load Preset",
                self._load_preset,
                "folder-open.svg",
                "Select applications from a saved preset",
            ),
            (
                "Backup Selected",
                self._backup_selected,
                "archive.svg",
                "Back up the selected applications",
            ),
            (
                "Restore Backup",
                self._restore_apps,
                "cloud-arrow-down.svg",
                "Restore applications from a backup",
            ),
            (
                "App Details",
                self._show_details,
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
                self._selection_action_buttons.append(b)
            self._preset_action_buttons.append(b)
        layout.addLayout(self._preset_action_layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(100)
        self.log_output.setPlaceholderText("Operation log...")
        layout.addWidget(self.log_output, 1)

        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        layout.addWidget(self.status_bar)
        self._update_selection_ui()
        self._reflow_action_buttons()

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self)
        bs = BaseStyles
        ui_font = bs.font_for_role(FontRole.UI)
        log_font = bs.font_for_role(FontRole.LOG)
        self.setStyleSheet(bs.PANEL_BASE_STYLE())
        self.setFont(ui_font)
        bg = bs.color("INPUT_BG")
        fg = bs.color("TEXT_PRIMARY")
        border = bs.color("BORDER_COLOR")
        self.log_output.setStyleSheet(
            f"background-color:{bs.color('LOG_BACKGROUND')}; "
            f"color:{bs.color('LOG_TEXT_COLOR')}; border:1px solid {border}; "
            f"border-radius:{bs.RADIUS_MD}px;"
        )
        self.log_output.setFont(log_font)
        self.log_output.document().setDefaultFont(log_font)
        self.tree.setStyleSheet(
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
        self.icon_list.setStyleSheet(
            "QListWidget { background-color:"
            f"{bg}; color:{fg}; border:1px solid {border}; border-radius:{bs.RADIUS_MD}px; "
            "} QListWidget::item:selected { background-color:"
            f"{bs.color('SELECTION_BG')}; color:{bs.color('SELECTION_TEXT')}; border-radius:4px"
            "; }"
        )
        self.status_bar.setStyleSheet(bs.STATUS_BAR_STYLE())
        for control in self._top_controls:
            control.setFont(ui_font)
            control.updateGeometry()
        for button in (*self._selection_action_buttons, *self._preset_action_buttons):
            button.setFont(ui_font)
            button.updateGeometry()
        view_hint = self.view_toggle.minimumSizeHint()
        self.view_toggle.setFixedSize(max(28, view_hint.width()), max(28, view_hint.height()))
        _apply_adaptive_text_heights(self)
        self._reflow_top_controls()
        self._reflow_action_buttons()

    def _action_layout_available_width(self) -> int:
        margins = self.layout().contentsMargins()
        return max(1, self.contentsRect().width() - margins.left() - margins.right())

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
        available_width = self._action_layout_available_width()
        full_labels = tuple(button.accessibleName() for button in buttons)
        spacing = layout.spacing()
        for button, label in zip(buttons, full_labels):
            if button.text() != label:
                button.setText(label)
                button.updateGeometry()
        if self._buttons_fit_columns(buttons, wide_columns, available_width, spacing):
            columns = wide_columns
        elif self._buttons_fit_columns(buttons, 2, available_width, spacing):
            columns = 2
        else:
            for button, label in zip(buttons, short_labels):
                button.setText(label)
                button.updateGeometry()
            if self._buttons_fit_columns(buttons, 2, available_width, spacing):
                columns = 2
            else:
                columns = 1

        reflow_widgets(layout, buttons, columns)
        if span_last_in_two_columns and columns == 2:
            last_button = buttons[-1]
            last_index = layout.indexOf(last_button)
            row, _column, _row_span, _column_span = layout.getItemPosition(last_index)
            layout.removeWidget(last_button)
            layout.addWidget(last_button, row, 0, 1, 2)

    def _reflow_action_buttons(self) -> None:
        if not hasattr(self, "_selection_action_layout"):
            return
        self._reflow_action_group(
            self._selection_action_layout,
            self._selection_action_buttons[:4],
            ("Uninstall", "Disable", "Enable", "Clear"),
            4,
        )
        self._reflow_action_group(
            self._preset_action_layout,
            self._preset_action_buttons,
            ("Save", "Load", "Backup", "Restore", "Details"),
            5,
            span_last_in_two_columns=True,
        )

    def _top_controls_fit(self, columns: int) -> bool:
        """检查指定顶部布局的每一行能否容纳控件真实最小宽度。"""

        controls = self._top_controls
        row_groups = {
            7: (controls,),
            5: (controls[:2], controls[2:]),
            3: (controls[:2], controls[2:4], controls[4:]),
        }
        rows = row_groups[columns]
        spacing = self._top_layout.spacing()
        available_width = self._action_layout_available_width()
        return all(
            sum(widget.minimumSizeHint().width() for widget in row) + spacing * max(0, len(row) - 1)
            <= available_width
            for row in rows
        )

    def _reflow_top_controls(self) -> None:
        """按字体感知的真实最小宽度重排搜索、筛选和刷新入口。"""

        if not hasattr(self, "_top_layout"):
            return
        for widget in self._top_controls:
            self._top_layout.removeWidget(widget)
        for column in range(max(7, self._top_layout.columnCount())):
            self._top_layout.setColumnStretch(column, 0)

        if self._top_controls_fit(7):
            for column, widget in enumerate(self._top_controls):
                self._top_layout.addWidget(widget, 0, column)
            self._top_layout.setColumnStretch(1, 1)
            return

        if self._top_controls_fit(5):
            self._top_layout.addWidget(self._search_label, 0, 0)
            self._top_layout.addWidget(self.search_input, 0, 1, 1, 4)
            self._top_layout.addWidget(self._type_label, 1, 0)
            self._top_layout.addWidget(self.type_filter, 1, 1)
            self._top_layout.addWidget(self.selection_label, 1, 2)
            self._top_layout.addWidget(self.view_toggle, 1, 3)
            self._top_layout.addWidget(self.refresh_btn, 1, 4)
            self._top_layout.setColumnStretch(1, 1)
            return

        self._top_layout.addWidget(self._search_label, 0, 0)
        self._top_layout.addWidget(self.search_input, 0, 1, 1, 2)
        self._top_layout.addWidget(self._type_label, 1, 0)
        self._top_layout.addWidget(self.type_filter, 1, 1, 1, 2)
        self._top_layout.addWidget(self.selection_label, 2, 0)
        self._top_layout.addWidget(self.view_toggle, 2, 1)
        self._top_layout.addWidget(self.refresh_btn, 2, 2)
        self._top_layout.setColumnStretch(2, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_top_controls()
        self._reflow_action_buttons()

    def _create_context_menu(self) -> QMenu:
        """创建使用共享深浅主题样式的上下文菜单。"""

        menu = QMenu(self)
        menu.setStyleSheet(BaseStyles.MENU_STYLE())
        return menu

    def log(self, msg):
        if self._closing or not is_qobject_alive(self.log_output):
            return
        self.log_output.append(msg)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    # ── 加载 / 筛选 ────────────────────────────────────────────────────────

    def _load_apps(self):
        if self._closing:
            return
        self._load_request_id += 1
        request_id = self._load_request_id
        self._active_load_request = request_id
        self._syncing_selection = True
        self.model.removeRows(0, self.model.rowCount())
        self.icon_list.clear()
        self._syncing_selection = False
        self.selected_packages.clear()
        self._update_selection_ui()
        self._detail_cache.clear()
        self._pending_detail_packages.clear()
        self._detail_worker_running = False
        self._detail_row_by_pkg = {}
        self._detail_icon_by_pkg = {}
        if is_qobject_alive(self._detail_timer):
            self._detail_timer.stop()
        w = AppManagerWorker(self.device_ip, "load_apps")
        w.log_message.connect(alive_forwarding_callback(self, "log"))
        dialog_ref = weakref.ref(self)

        def populate_current(apps):
            dialog = dialog_ref()
            if is_qobject_alive(dialog):
                dialog._populate(apps, request_id=request_id)

        w.apps_loaded.connect(populate_current)
        self._track_worker(w)
        w.start()

    def _populate(self, apps, *, request_id=None):
        if self._closing or (request_id is not None and request_id != self._active_load_request):
            return
        self._apps_data = apps
        self._app_labels = {}
        self._app_versions = {}
        self._detail_row_by_pkg = {}
        self._detail_icon_by_pkg = {}
        self._syncing_selection = True
        self.tree.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        for row, (name, pkg, st, at) in enumerate(apps):
            cb = QStandardItem()
            cb.setCheckable(True)
            self.model.appendRow(
                [
                    cb,
                    QStandardItem(name),
                    QStandardItem(pkg),
                    QStandardItem(""),
                    QStandardItem(st),
                    QStandardItem(at),
                ]
            )
            self._detail_row_by_pkg[pkg] = row
        self.tree.setSortingEnabled(True)
        self.icon_list.clear()
        sorted_apps = sorted(apps, key=lambda x: (0 if x[3] == "User" else 1, x[0].lower()))
        for name, pkg, st, at in sorted_apps:
            short_name = name[:18] + (".." if len(name) > 18 else "")
            icon = self._gen_icon(name, at, 48)
            item = QListWidgetItem(icon, short_name)
            item.setData(Qt.UserRole, pkg)
            item.setToolTip(f"{pkg}\nType: {at} | Status: {st}")
            item.setSizeHint(QSize(106, 72))
            if st == "Disabled":
                item.setForeground(QColor("#999999"))
            self.icon_list.addItem(item)
            self._detail_icon_by_pkg[pkg] = item
        self._syncing_selection = False
        self._sync_selection_views()
        self._filter()
        self.status_bar.showMessage(f"Loaded {len(apps)} apps — loading details...")
        self._schedule_visible_detail_load()

    def _on_detail(self, pkg, label, version, itime):
        sender = getattr(self, "sender", None)
        source = sender() if callable(sender) else None
        source_request_id = getattr(source, "_app_load_request_id", None)
        if self._closing or (
            source_request_id is not None
            and source_request_id != getattr(self, "_active_load_request", 0)
        ):
            return
        self._pending_detail_packages.discard(pkg)
        self._app_labels[pkg] = label
        self._app_versions[pkg] = version
        self._detail_cache[pkg] = (label, version, itime)
        item = self._detail_icon_by_pkg.get(pkg)
        if item:
            item.setToolTip(f"{label}\n{pkg}\n{version}")
        row = self._detail_row_by_pkg.get(pkg)
        if row is not None:
            name_item = self.model.item(row, 1)
            version_item = self.model.item(row, 3)
            if label and name_item:
                name_item.setText(label)
            if version and version_item:
                version_item.setText(version)

    def _on_detail_worker_finished(self, packages=None, request_id=None):
        if request_id is not None and request_id != getattr(self, "_active_load_request", 0):
            return
        if packages:
            self._pending_detail_packages.difference_update(packages)
        self._detail_worker_running = False
        if self._closing or not is_qobject_alive(self._detail_timer):
            return
        if self._detail_timer.isActive():
            return
        if self._has_unloaded_details():
            self._schedule_visible_detail_load(delay_ms=80)
            return
        self.status_bar.showMessage(f"Loaded {len(self._apps_data)} apps")

    def _schedule_visible_detail_load(self, delay_ms: int = 120):
        if self._closing or not is_qobject_alive(self._detail_timer):
            return
        if self._detail_timer.isActive():
            self._detail_timer.stop()
        self._detail_timer.start(delay_ms)

    def _has_unloaded_details(self) -> bool:
        return any(
            pkg
            for _name, pkg, _status, _app_type in self._apps_data
            if pkg not in self._detail_cache and pkg not in self._pending_detail_packages
        )

    def _next_unloaded_detail_packages(self, limit: int = 30) -> list[str]:
        packages = []
        for _name, pkg, _status, _app_type in self._apps_data:
            if pkg in self._detail_cache or pkg in self._pending_detail_packages:
                continue
            packages.append(pkg)
            if len(packages) >= limit:
                break
        return packages

    def _visible_detail_packages(self, limit: int = 30) -> list[str]:
        packages: list[str] = []
        if self._view_mode:
            for i in range(self.icon_list.count()):
                item = self.icon_list.item(i)
                pkg = item.data(Qt.UserRole) if item else ""
                if item and not item.isHidden() and pkg and pkg not in self._detail_cache:
                    packages.append(pkg)
                    if len(packages) >= limit:
                        break
            return packages

        root = self.tree.rootIndex()
        viewport = self.tree.viewport().rect()
        seen = set()
        for row in range(self.proxy.rowCount(root)):
            proxy_index = self.proxy.index(row, 2, root)
            if not proxy_index.isValid():
                continue
            rect = self.tree.visualRect(proxy_index)
            if rect.isValid() and not viewport.intersects(rect):
                continue
            source_index = self.proxy.mapToSource(proxy_index)
            source_row = source_index.row()
            item = self.model.item(source_row, 2)
            pkg = item.text() if item else ""
            if pkg and pkg not in seen and pkg not in self._detail_cache:
                seen.add(pkg)
                packages.append(pkg)
                if len(packages) >= limit:
                    break
        if packages:
            return packages

        for row in range(min(self.model.rowCount(), limit)):
            item = self.model.item(row, 2)
            pkg = item.text() if item else ""
            if pkg and pkg not in self._detail_cache:
                packages.append(pkg)
        return packages

    def _load_visible_details(self):
        if self._closing or self._detail_worker_running:
            return
        packages = [
            pkg
            for pkg in self._visible_detail_packages()
            if pkg not in self._pending_detail_packages
        ]
        if not packages:
            packages = self._next_unloaded_detail_packages()
        if not packages:
            return
        self._pending_detail_packages.update(packages)
        self._detail_worker_running = True
        self.status_bar.showMessage(
            f"Loading details {len(self._detail_cache)}/{len(self._apps_data)}"
        )
        w = AppManagerWorker(self.device_ip, "load_detail_batch", packages=packages)
        request_id = getattr(self, "_active_load_request", 0)
        w._app_load_request_id = request_id
        w.app_detail_batch.connect(self._on_detail)
        w.log_message.connect(alive_forwarding_callback(self, "log"))
        w.finished.connect(
            alive_callback(
                self,
                "_on_detail_worker_finished",
                packages,
                request_id,
            )
        )
        self._track_worker(w)
        w.start()

    @staticmethod
    def _gen_icon(name, atype, size=48):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = {"User": "#4CAF50", "System": "#F44336", "Vendor": "#FF9800", "Other": "#9E9E9E"}
        c = QColor(colors.get(atype, "#9E9E9E"))
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        margin = size // 12
        rsize = size - margin * 2
        radius = size // 5
        p.drawRoundedRect(margin, margin, rsize, rsize, radius, radius)
        p.setPen(QColor("#ffffff"))
        abbreviation = name[:2].upper() if len(name) >= 2 else name.upper()
        font = BaseStyles.font_for_role(FontRole.UI, size=size // 3 + 1)
        font.setBold(True)
        p.setFont(font)
        p.drawText(margin, margin, rsize, rsize, Qt.AlignmentFlag.AlignCenter, abbreviation)
        p.end()
        return QIcon(pix)

    def _toggle_view(self):
        self._sync_selection_views()
        self._view_mode = not self._view_mode
        self.stack.setCurrentIndex(1 if self._view_mode else 0)
        self.view_toggle.setIcon(
            get_themed_icon("list-bullets.svg" if self._view_mode else "squares-four.svg")
        )
        tooltip = "Switch to List view" if self._view_mode else "Switch to Icon view"
        self.view_toggle.setToolTip(tooltip)
        self.view_toggle.setAccessibleName(tooltip)
        self._schedule_visible_detail_load()

    def _icon_context_menu(self, pos):
        item = self.icon_list.itemAt(pos)
        if not item:
            return
        pkg = item.data(Qt.UserRole)
        if not pkg:
            return
        self._icon_selected_pkg = pkg
        menu = self._create_context_menu()
        menu.addAction("App Details", lambda: self._show_details_for(pkg))
        menu.addSeparator()
        menu.addAction("Launch App", lambda: self._launch(pkg))
        menu.addAction("Force Stop", lambda: self._modify_one("force_stop", pkg))
        menu.addAction("Clear Data", lambda: self._modify_one("clear", pkg))
        menu.addSeparator()
        menu.addAction("Uninstall", lambda: self._modify_one("uninstall", pkg))
        menu.addAction("Disable", lambda: self._modify_one("disable", pkg))
        menu.addAction("Enable", lambda: self._modify_one("enable", pkg))
        menu.addSeparator()
        menu.addAction("Backup", lambda: self._backup_one(pkg))
        if self._batch_workers:
            for action in menu.actions():
                if not action.isSeparator():
                    action.setEnabled(False)
        menu.exec(self.icon_list.mapToGlobal(pos))

    def _icon_double_click(self, item):
        pkg = item.data(Qt.UserRole)
        if pkg:
            self._show_details_for(pkg)

    def _filter(self):
        text = self.search_input.text().strip().lower()
        ft = self.type_filter.currentText()
        self.proxy.set_filters(text, ft)
        # 表格筛选条件也必须同步应用到图标视图，避免两种视图展示不同结果。
        for i in range(self.icon_list.count()):
            item = self.icon_list.item(i)
            pkg = (item.data(Qt.UserRole) or "").lower()
            name = (item.text().split("\n")[0] or "").lower()
            type_match = (
                ft == "All"
                or (ft == "User Apps" and "User" in (item.toolTip() or ""))
                or (ft == "System Apps" and "System" in (item.toolTip() or ""))
            )
            text_match = not text or text in name or text in pkg
            item.setHidden(not (type_match and text_match))
        self._schedule_visible_detail_load()

    def _on_table_item_changed(self, item):
        """将表格复选状态写回唯一选择集，再同步到图标视图。"""

        if self._syncing_selection or item.column() != 0:
            return
        package_item = self.model.item(item.row(), 2)
        package = package_item.text() if package_item else ""
        if not package:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self.selected_packages.add(package)
        else:
            self.selected_packages.discard(package)
        self._sync_selection_views()

    def _on_icon_selection_changed(self):
        """将图标选择写回唯一选择集，再同步到表格复选框。"""

        if self._syncing_selection:
            return
        icon_packages = {
            item.data(Qt.UserRole)
            for index in range(self.icon_list.count())
            if (item := self.icon_list.item(index)) is not None and item.data(Qt.UserRole)
        }
        selected_icons = {
            item.data(Qt.UserRole)
            for item in self.icon_list.selectedItems()
            if item.data(Qt.UserRole)
        }
        self.selected_packages.difference_update(icon_packages)
        self.selected_packages.update(selected_icons)
        self._sync_selection_views()

    def _sync_selection_views(self):
        """以 selected_packages 为真源同步表格、图标和操作按钮。"""

        if self._syncing_selection:
            return
        table_rows = []
        icon_items = []
        available_packages = set()
        for row in range(self.model.rowCount()):
            package_item = self.model.item(row, 2)
            checkbox_item = self.model.item(row, 0)
            package = package_item.text() if package_item else ""
            if package and checkbox_item:
                table_rows.append((checkbox_item, package))
                available_packages.add(package)
        for index in range(self.icon_list.count()):
            item = self.icon_list.item(index)
            package = item.data(Qt.UserRole) if item else ""
            if package:
                icon_items.append((item, package))
                available_packages.add(package)

        self.selected_packages.intersection_update(available_packages)
        self._syncing_selection = True
        try:
            for checkbox_item, package in table_rows:
                expected = (
                    Qt.CheckState.Checked
                    if package in self.selected_packages
                    else Qt.CheckState.Unchecked
                )
                if checkbox_item.checkState() != expected:
                    checkbox_item.setCheckState(expected)
            for item, package in icon_items:
                selected = package in self.selected_packages
                if item.isSelected() != selected:
                    item.setSelected(selected)
        finally:
            self._syncing_selection = False
        self._update_selection_ui()

    def _update_selection_ui(self):
        """更新选择计数，并在无选择或批处理期间禁用相关动作。"""

        count = len(self.selected_packages)
        batch_running = bool(self._batch_workers)
        self.selection_label.setText(f"Selected: {count}")
        for button in self._selection_action_buttons:
            button.setEnabled(count > 0 and not batch_running)
        self.refresh_btn.setEnabled(not batch_running)

    # ── 点击 / 右键菜单 ────────────────────────────────────────────────────

    def _on_row_clicked(self, index):
        src = self.proxy.mapToSource(index)
        row = src.row()
        if row < 0:
            return
        cb = self.model.item(row, 0)
        if index.column() > 0:
            ns = (
                Qt.CheckState.Unchecked
                if cb.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            cb.setCheckState(ns)

    def _context_menu(self, pos):
        idx = self.tree.indexAt(pos)
        if not idx.isValid():
            return
        src = self.proxy.mapToSource(idx)
        row = src.row()
        pkg = self.model.item(row, 2).text()
        atype = self.model.item(row, 5).text()
        menu = self._create_context_menu()
        menu.addAction("App Details", lambda: self._show_details_for(pkg))
        menu.addSeparator()
        menu.addAction("Launch App", lambda: self._launch(pkg))
        menu.addAction("Force Stop", lambda: self._modify_one("force_stop", pkg))
        menu.addAction("Clear Data", lambda: self._modify_one("clear", pkg))
        menu.addSeparator()
        menu.addAction("Uninstall", lambda: self._modify_one("uninstall", pkg))
        if atype in ("System", "Vendor"):
            menu.addAction("Disable", lambda: self._modify_one("disable", pkg))
            menu.addAction("Enable", lambda: self._modify_one("enable", pkg))
        menu.addSeparator()
        menu.addAction("Backup", lambda: self._backup_one(pkg))
        if self._batch_workers:
            for action in menu.actions():
                if not action.isSeparator():
                    action.setEnabled(False)
        menu.exec(self.tree.mapToGlobal(pos))

    def _show_details_for(self, pkg):
        if AppManagerDialog._batch_action_blocked(self):
            return None
        existing = self._detail_dialogs.get(pkg)
        if is_qobject_alive(existing):
            fit_secondary_window_to_owner_screen(existing, self)
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing
        dlg = AppDetailsDialog(self, self.device_ip, pkg)
        fit_secondary_window_to_owner_screen(dlg, self)
        self._detail_dialogs[pkg] = dlg
        dlg.finished.connect(alive_callback(self, "_forget_detail_dialog", pkg, dlg))
        dlg.destroyed.connect(alive_callback(self, "_forget_detail_dialog", pkg, dlg))
        dlg.show()
        return dlg

    def _forget_detail_dialog(self, pkg, dialog):
        if self._detail_dialogs.get(pkg) is dialog:
            self._detail_dialogs.pop(pkg, None)

    def _batch_action_blocked(self) -> bool:
        if not self._batch_workers:
            return False
        self.status_bar.showMessage("A batch operation is in progress; wait for it to finish.")
        return True

    def _launch(self, pkg):
        if AppManagerDialog._batch_action_blocked(self):
            return
        w = AppManagerWorker(self.device_ip, "launch_app", package_name=pkg)
        w.log_message.connect(alive_forwarding_callback(self, "log"))
        self._track_worker(w)
        w.start()

    def _modify_one(self, action, pkg):
        if AppManagerDialog._batch_action_blocked(self):
            return
        if not self._confirm_dangerous_action(action, 1):
            return
        if action == "force_stop":
            w = AppManagerWorker(
                self.device_ip, "modify_app", action="force_stop", package_name=pkg
            )
            w.log_message.connect(alive_forwarding_callback(self, "log"))
            self._track_worker(w)
            w.start()
        elif action == "clear":
            w = AppManagerWorker(self.device_ip, "clear_app", package_name=pkg)
            w.log_message.connect(alive_forwarding_callback(self, "log"))
            self._track_worker(w)
            w.start()
        else:
            w = AppManagerWorker(self.device_ip, "modify_app", action=action, package_name=pkg)
            w.log_message.connect(alive_forwarding_callback(self, "log"))
            w.operation_done.connect(alive_callback(self, "_load_apps"))
            self._track_worker(w)
            w.start()

    @staticmethod
    def _global_save_dir() -> str:

        return AppSettings.instance().save_directory

    def _backup_one(self, pkg):
        if AppManagerDialog._batch_action_blocked(self):
            return
        sd = QFileDialog.getExistingDirectory(
            self, "Select Backup Directory", self._global_save_dir()
        )
        if not sd:
            return
        w = AppManagerWorker(self.device_ip, "backup_app", package_name=pkg, save_dir=sd)
        w.log_message.connect(alive_forwarding_callback(self, "log"))
        w.backup_progress.connect(alive_forwarding_callback(self, "_log_backup_progress"))
        self._track_worker(w)
        w.start()

    def _deselect_all(self):
        self.selected_packages.clear()
        self._sync_selection_views()
        self.log("Deselected all.")

    def _log_backup_progress(self, progress, message) -> None:
        self.log(f"[{progress}] {message}")

    # ── 批量操作 ───────────────────────────────────────────────────────────

    def _get_selected_pkgs(self):
        return sorted(self.selected_packages)

    def _modify_selected(self, action):
        if AppManagerDialog._batch_action_blocked(self):
            return
        pkgs = self._get_selected_pkgs()
        if not pkgs:
            QMessageBox.warning(self, "No Selection", "No apps selected.")
            return
        if not self._confirm_dangerous_action(action, len(pkgs)):
            return
        workers = []
        for pkg in pkgs:
            w = AppManagerWorker(self.device_ip, "modify_app", action=action, package_name=pkg)
            w.log_message.connect(alive_forwarding_callback(self, "log"))
            w.finished.connect(alive_callback(self, "_on_batch_worker_finished", w))
            self._track_worker(w)
            workers.append(w)

        self._batch_workers.update(workers)
        self._batch_total = len(workers)
        self._batch_action = action
        self.status_bar.showMessage(f"{action.title()}: 0/{self._batch_total} completed")
        self._update_selection_ui()
        for w in workers:
            w.start()

    def _on_batch_worker_finished(self, worker):
        """等待当前批次全部结束后统一刷新一次应用列表。"""

        if worker not in self._batch_workers:
            return
        self._batch_workers.discard(worker)
        if self._closing:
            return
        remaining = len(self._batch_workers)
        completed = self._batch_total - remaining
        if remaining:
            self.status_bar.showMessage(
                f"{self._batch_action.title()}: {completed}/{self._batch_total} completed"
            )
            self._update_selection_ui()
            return

        action = self._batch_action
        total = self._batch_total
        self._batch_action = ""
        self._batch_total = 0
        self.status_bar.showMessage(f"{action.title()} completed for {total} apps; refreshing...")
        self._update_selection_ui()
        self._load_apps()

    def _confirm_dangerous_action(self, action: str, target_count: int) -> bool:
        """兼容占位：危险操作不再弹窗确认，直接放行。"""

        del action, target_count
        return True

    def _backup_selected(self):
        pkgs = self._get_selected_pkgs()
        if not pkgs:
            QMessageBox.warning(self, "No Selection", "No apps selected.")
            return
        sd = QFileDialog.getExistingDirectory(self, "Backup Directory", self._global_save_dir())
        if not sd:
            return
        for pkg in pkgs:
            w = AppManagerWorker(self.device_ip, "backup_app", package_name=pkg, save_dir=sd)
            w.log_message.connect(alive_forwarding_callback(self, "log"))
            w.backup_progress.connect(alive_forwarding_callback(self, "_log_backup_progress"))
            self._track_worker(w)
            w.start()

    def _restore_apps(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Backup ZIP(s)", "", "ZIP Files (*.zip)"
        )
        if not files:
            return
        w = AppManagerWorker(self.device_ip, "restore_apps", file_paths=files)
        w.log_message.connect(alive_forwarding_callback(self, "log"))
        w.backup_progress.connect(alive_forwarding_callback(self, "_log_backup_progress"))
        w.operation_done.connect(alive_callback(self, "_load_apps"))
        self._track_worker(w)
        w.start()

    def _show_details(self):
        packages = self._get_selected_pkgs()
        if not packages:
            QMessageBox.warning(self, "No Selection", "No app selected.")
            return
        pkg = packages[0]
        if pkg:
            self._show_details_for(pkg)

    # ── 预设操作 ───────────────────────────────────────────────────────────

    def _create_preset(self):
        if not self.selected_packages:
            QMessageBox.warning(self, "No Selection", "Select apps first.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Create Preset")
        dlg.setMinimumSize(380, 280)
        dlg.resize(380, 280)
        dlg.setFont(BaseStyles.font_for_role(FontRole.UI))
        lo = QVBoxLayout(dlg)
        lo.addWidget(QLabel("Preset Name:"))
        ni = QLineEdit()
        lo.addWidget(ni)
        lo.addWidget(QLabel("Author (optional):"))
        ai = QLineEdit()
        lo.addWidget(ai)
        lo.addWidget(QLabel("Description (optional):"))
        di = QTextEdit()
        di.setMaximumHeight(60)
        lo.addWidget(di)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setToolTip("Create this application preset")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
            "Close without creating a preset"
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lo.addWidget(btns)
        fit_secondary_window_to_owner_screen(
            dlg,
            self,
            minimum_floor=dlg.minimumSize(),
        )
        if not dlg.exec():
            return
        name = ni.text().strip() or "New Preset"
        data = {
            "name": name,
            "author": ai.text().strip(),
            "description": di.toPlainText().strip(),
            "selected_packages": sorted(list(self.selected_packages)),
        }
        fp, _ = QFileDialog.getSaveFileName(self, "Save Preset", name + ".json", "JSON (*.json)")
        if fp:
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except (OSError, TypeError, ValueError) as exc:
                self._report_preset_error("save", exc)
                return
            self.log(f"Preset '{name}' saved ({len(data['selected_packages'])} apps).")

    def _load_preset(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Load Preset", "", "JSON (*.json)")
        if not fp:
            return
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            self._validate_preset(data)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            self._report_preset_error("load", exc)
            return
        pkgs = set(data.get("selected_packages", []))
        if not pkgs:
            self.log("Preset empty.")
            return
        available_packages = set()
        for r in range(self.model.rowCount()):
            p = self.model.item(r, 2).text()
            if p:
                available_packages.add(p)
        self.selected_packages.clear()
        self.selected_packages.update(pkgs & available_packages)
        self._sync_selection_views()
        self.log(f"Loaded preset '{data.get('name', '?')}' ({len(self.selected_packages)} apps).")

    @staticmethod
    def _validate_preset(data) -> None:
        if not isinstance(data, dict):
            raise ValueError("Preset root must be a JSON object.")
        packages = data.get("selected_packages")
        if not isinstance(packages, list) or any(
            not isinstance(package, str) or not package.strip() for package in packages
        ):
            raise ValueError("Preset selected_packages must be a list of package names.")
        for field in ("name", "author", "description"):
            if field in data and not isinstance(data[field], str):
                raise ValueError(f"Preset {field} must be text.")

    def _report_preset_error(self, action: str, error: Exception) -> None:
        message = f"Unable to {action} preset: {error}"
        QMessageBox.critical(self, "Preset Error", message)
        self.status_bar.showMessage(message)
        self.log(message)

    # ── 应用生命周期操作 ───────────────────────────────────────────────────

    def _track_worker(self, w):
        w.setParent(self)
        w.finished.connect(alive_callback(self, "_prune_worker", w))
        self._workers.append(w)

    def _prune_worker(self, w):
        if self._closing:
            return
        if w in self._workers:
            self._workers.remove(w)
        if is_qobject_alive(w) and hasattr(w, "deleteLater"):
            w.deleteLater()

    def register_shutdown_tasks(self, supervisor, *, owner_id: str, task_prefix: str):
        """将仍在运行的应用管理 worker 作为一组资源注册到监督器。"""
        workers = [
            worker
            for worker in (
                *self._workers,
                *(
                    worker
                    for dialog in self._detail_dialogs.values()
                    if is_qobject_alive(dialog)
                    for worker in dialog._workers
                ),
            )
            if QThreadGroupShutdownTask._running(worker)
        ]
        if not workers:
            return ()
        handle = QThreadGroupShutdownTask(workers)
        supervisor.register(
            f"{task_prefix}-workers",
            owner_id=owner_id,
            kind="app_manager_workers",
            request_stop=handle.request_stop,
            wait=handle.wait,
            is_running=handle.is_running,
        )
        self._shutdown_registered = True
        return (f"{task_prefix}-workers",)

    def closeEvent(self, event):
        """断开晚到信号并中止 worker；已注册时由统一监督器负责等待。"""
        self._closing = True
        if is_qobject_alive(self._detail_timer):
            self._detail_timer.stop()
            safe_disconnect(self._detail_timer.timeout, self._load_visible_details)
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
        detail_dialogs = list(self._detail_dialogs.values())
        self._detail_dialogs.clear()
        for detail_dialog in detail_dialogs:
            if is_qobject_alive(detail_dialog):
                detail_dialog.close()
        workers = self._workers
        self._workers = []
        for w in workers:
            w.abort()
            w.setParent(None)
        if not getattr(self, "_shutdown_registered", False):
            wait_for_threads_later(workers, 5000)
        super().closeEvent(event)
