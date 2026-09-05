"""应用管理器视图控制器 — 加载/填充应用列表、筛选与选择同步、详情懒加载。"""

import weakref
from functools import lru_cache

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QStandardItem
from PySide6.QtWidgets import QListWidgetItem

from gui.dialogs.lifecycle import (
    alive_callback,
    alive_forwarding_callback,
    is_qobject_alive,
)
from gui.styles import BaseStyles
from gui.styles.fluent import add_menu_action
from gui.styles.icon_loader import get_themed_icon
from gui.styles.typography import FontRole


@lru_cache(maxsize=16)
def _icon_font(size: int) -> QFont:
    font = BaseStyles.font_for_role(FontRole.UI, size=size // 3 + 1)
    font.setBold(True)
    return font


@lru_cache(maxsize=4096)
def _painted_icon(name: str, atype: str, size: int) -> QIcon:
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
    p.setFont(_icon_font(size))
    p.drawText(margin, margin, rsize, rsize, Qt.AlignmentFlag.AlignCenter, abbreviation)
    p.end()
    return QIcon(pix)


class AppManagerViews:
    """组合进 AppManagerPage 的视图控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        self._frame = frame

    def _load_apps(self):
        from gui.dialogs import app_manager as _app_manager

        if self._frame._closing:
            return False
        if not self._frame._can_operate():
            set_state = getattr(self._frame, "_set_load_state", None)
            if callable(set_state):
                set_state("error", "请在顶部设备栏勾选当前在线设备后刷新。")
            return False
        if getattr(self._frame, "_load_in_progress", False):
            self._frame._load_refresh_pending = True
            self._frame.status_bar.setText("刷新已排队，将在当前加载完成后执行。")
            return False
        self._frame._load_request_id += 1
        request_id = self._frame._load_request_id
        self._frame._active_load_request = request_id
        self._frame._load_in_progress = True
        self._frame._load_result_received = False
        self._frame._last_load_error = ""
        if is_qobject_alive(self._frame._detail_timer):
            self._frame._detail_timer.stop()
        set_state = getattr(self._frame, "_set_load_state", None)
        if callable(set_state):
            set_state("loading", "正在加载已安装应用…")
        w = _app_manager.AppManagerWorker(self._frame.device_ip, "load_apps")
        w.log_message.connect(
            lambda message: self._frame._on_load_log(request_id, message),
            Qt.ConnectionType.QueuedConnection,
        )
        dialog_ref = weakref.ref(self._frame)

        def populate_current(apps):
            dialog = dialog_ref()
            if dialog is not None and is_qobject_alive(dialog):
                dialog._populate(apps, request_id=request_id)

        w.apps_loaded.connect(populate_current, Qt.ConnectionType.QueuedConnection)
        w.finished.connect(
            alive_callback(self._frame, "_on_load_worker_finished", request_id),
            Qt.ConnectionType.QueuedConnection,
        )
        self._frame._track_worker(w)
        w.start()
        return True

    def _populate(self, apps, *, request_id=None):
        if self._frame._closing or (
            request_id is not None and request_id != self._frame._active_load_request
        ):
            return
        previous_selection = set(getattr(self._frame, "selected_packages", set()))
        self._frame._icons_controller.reset()
        self._frame._apps_data = apps
        self._frame._app_labels = {}
        self._frame._app_versions = {}
        self._frame._detail_cache.clear()
        self._frame._pending_detail_packages.clear()
        self._frame._detail_worker_running = False
        self._frame._detail_row_by_pkg = {}
        self._frame._detail_icon_by_pkg = {}
        self._frame._syncing_selection = True
        self._frame.tree.setSortingEnabled(False)
        self._frame.model.removeRows(0, self._frame.model.rowCount())
        for row, (name, pkg, st, at) in enumerate(apps):
            cb = QStandardItem()
            cb.setCheckable(True)
            self._frame.model.appendRow(
                [
                    cb,
                    QStandardItem(name),
                    QStandardItem(pkg),
                    QStandardItem(""),
                    QStandardItem(st),
                    QStandardItem(at),
                ]
            )
            for column in (1, 2):
                item = self._frame.model.item(row, column)
                item.setToolTip(item.text())
            self._frame._detail_row_by_pkg[pkg] = row
        self._frame.tree.setSortingEnabled(True)
        self._frame.icon_list.clear()
        self._frame.icon_list.setUpdatesEnabled(False)
        try:
            sorted_apps = sorted(apps, key=lambda x: (0 if x[3] == "User" else 1, x[0].lower()))
            for name, pkg, st, at in sorted_apps:
                short_name = name[:18] + (".." if len(name) > 18 else "")
                icon = self._frame._gen_icon(name, at, 48)
                item = QListWidgetItem(icon, short_name)
                item.setData(Qt.ItemDataRole.UserRole, pkg)
                item.setData(Qt.ItemDataRole.UserRole + 1, at)
                type_text = {
                    "User": "用户", "System": "系统", "Vendor": "厂商", "Other": "其他"
                }.get(at, at)
                state_text = "已停用" if st == "Disabled" else "已启用"
                item.setToolTip(f"{pkg}\n类型：{type_text} | 状态：{state_text}")
                item.setSizeHint(QSize(106, 72))
                if st == "Disabled":
                    item.setForeground(BaseStyles.get_color("TEXT_DISABLED"))
                self._frame.icon_list.addItem(item)
                self._frame._detail_icon_by_pkg[pkg] = item
        finally:
            self._frame.icon_list.setUpdatesEnabled(True)
        available_packages = {pkg for _name, pkg, _status, _app_type in apps}
        if not hasattr(self._frame, "selected_packages"):
            self._frame.selected_packages = set()
        self._frame.selected_packages.clear()
        self._frame.selected_packages.update(previous_selection & available_packages)
        self._frame._syncing_selection = False
        self._frame._sync_selection_views()
        self._frame._filter()
        self._frame._form_controller._update_view_geometry()
        record_success = getattr(self._frame, "_record_load_success", None)
        if callable(record_success) and request_id is not None:
            record_success(request_id, len(apps))
        else:
            self._frame.status_bar.setText(f"已加载 {len(apps)} 个应用，正在读取详情…")
        details_page = getattr(self._frame, "details_page", None)
        if (
            getattr(self._frame, "_details_open", False)
            and details_page is not None
            and details_page.package_name not in available_packages
        ):
            self._frame.close_details()
        self._frame._schedule_visible_detail_load()
        self._frame._icons_controller.schedule()

    def _on_detail(self, pkg, label, version, itime):
        sender = getattr(self._frame, "sender", None)
        source = sender() if callable(sender) else None
        source_request_id = getattr(source, "_app_load_request_id", None)
        if self._frame._closing or (
            source_request_id is not None
            and source_request_id != getattr(self._frame, "_active_load_request", 0)
        ):
            return
        self._frame._pending_detail_packages.discard(pkg)
        self._frame._app_labels[pkg] = label
        self._frame._app_versions[pkg] = version
        self._frame._detail_cache[pkg] = (label, version, itime)
        item = self._frame._detail_icon_by_pkg.get(pkg)
        if item:
            item.setToolTip(f"{label}\n{pkg}\n{version}")
            item.setText(label[:18] + (".." if len(label) > 18 else ""))
            self._frame._icons_controller.decorate(pkg)
        row = self._frame._detail_row_by_pkg.get(pkg)
        if row is not None:
            name_item = self._frame.model.item(row, 1)
            version_item = self._frame.model.item(row, 3)
            if label and name_item:
                name_item.setText(label)
                name_item.setToolTip(label)
            if version and version_item:
                version_item.setText(version)
                version_item.setToolTip(version)

    def _on_detail_worker_finished(self, packages=None, request_id=None):
        if request_id is not None and request_id != getattr(self._frame, "_active_load_request", 0):
            return
        if packages:
            self._frame._pending_detail_packages.difference_update(packages)
        self._frame._detail_worker_running = False
        if self._frame._closing or not is_qobject_alive(self._frame._detail_timer):
            return
        if not self._frame._can_operate():
            return
        if self._frame._detail_timer.isActive():
            return
        if self._frame._has_unloaded_details():
            self._frame._schedule_visible_detail_load(delay_ms=80)
            return
        self._frame.status_bar.setText(f"已加载 {len(self._frame._apps_data)} 个应用")

    def _schedule_visible_detail_load(self, delay_ms: int = 120):
        if (
            self._frame._closing
            or not getattr(self._frame, "_active", True)
            or not self._frame._can_operate()
            or not is_qobject_alive(self._frame._detail_timer)
        ):
            return
        if self._frame._detail_timer.isActive():
            self._frame._detail_timer.stop()
        self._frame._detail_timer.start(delay_ms)

    def _has_unloaded_details(self) -> bool:
        return any(
            pkg
            for _name, pkg, _status, _app_type in self._frame._apps_data
            if pkg not in self._frame._detail_cache
            and pkg not in self._frame._pending_detail_packages
        )

    def _next_unloaded_detail_packages(self, limit: int = 30) -> list[str]:
        packages = []
        for _name, pkg, _status, _app_type in self._frame._apps_data:
            if pkg in self._frame._detail_cache or pkg in self._frame._pending_detail_packages:
                continue
            packages.append(pkg)
            if len(packages) >= limit:
                break
        return packages

    def _visible_detail_packages(self, limit: int = 30) -> list[str]:
        packages: list[str] = []
        if self._frame._view_mode:
            for i in range(self._frame.icon_list.count()):
                item = self._frame.icon_list.item(i)
                pkg = item.data(Qt.ItemDataRole.UserRole) if item else ""
                if item and not item.isHidden() and pkg and pkg not in self._frame._detail_cache:
                    packages.append(pkg)
                    if len(packages) >= limit:
                        break
            return packages

        root = self._frame.tree.rootIndex()
        viewport = self._frame.tree.viewport().rect()
        seen = set()
        for row in range(self._frame.proxy.rowCount(root)):
            proxy_index = self._frame.proxy.index(row, 2, root)
            if not proxy_index.isValid():
                continue
            rect = self._frame.tree.visualRect(proxy_index)
            if rect.isValid() and not viewport.intersects(rect):
                continue
            source_index = self._frame.proxy.mapToSource(proxy_index)
            source_row = source_index.row()
            item = self._frame.model.item(source_row, 2)
            pkg = item.text() if item else ""
            if pkg and pkg not in seen and pkg not in self._frame._detail_cache:
                seen.add(pkg)
                packages.append(pkg)
                if len(packages) >= limit:
                    break
        if packages:
            return packages

        for row in range(min(self._frame.model.rowCount(), limit)):
            item = self._frame.model.item(row, 2)
            pkg = item.text() if item else ""
            if pkg and pkg not in self._frame._detail_cache:
                packages.append(pkg)
        return packages

    def _load_visible_details(self):
        from gui.dialogs import app_manager as _app_manager

        if (
            self._frame._closing
            or not getattr(self._frame, "_active", True)
            or not self._frame._can_operate()
            or self._frame._detail_worker_running
        ):
            return
        packages = [
            pkg
            for pkg in self._frame._visible_detail_packages()
            if pkg not in self._frame._pending_detail_packages
        ]
        if not packages:
            packages = self._frame._next_unloaded_detail_packages()
        if not packages:
            return
        self._frame._pending_detail_packages.update(packages)
        self._frame._detail_worker_running = True
        self._frame.status_bar.setText(
            f"正在读取详情 {len(self._frame._detail_cache)}/{len(self._frame._apps_data)}"
        )
        w = _app_manager.AppManagerWorker(
            self._frame.device_ip, "load_detail_batch", packages=packages
        )
        request_id = getattr(self._frame, "_active_load_request", 0)
        setattr(w, "_app_load_request_id", request_id)
        w.app_detail_batch.connect(self._frame._on_detail)
        w.log_message.connect(
            alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
        )
        w.finished.connect(
            alive_callback(
                self._frame,
                "_on_detail_worker_finished",
                packages,
                request_id,
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        self._frame._track_worker(w)
        w.start()

    @staticmethod
    def _gen_icon(name, atype, size=48):
        return _painted_icon(name, atype, size)

    def _toggle_view(self):
        self._frame._sync_selection_views()
        self._frame._view_mode = not self._frame._view_mode
        self._frame.stack.setCurrentIndex(1 if self._frame._view_mode else 0)
        self._frame.view_toggle.setIcon(
            get_themed_icon("list-bullets.svg" if self._frame._view_mode else "squares-four.svg")
        )
        tooltip = "切换为列表视图" if self._frame._view_mode else "切换为图标视图"
        self._frame.view_toggle.setToolTip(tooltip)
        self._frame.view_toggle.setAccessibleName(tooltip)
        self._frame.refresh_btn.setToolTip("刷新应用列表并重试未读取的图标")
        self._frame._icons_controller.schedule()
        self._frame._schedule_visible_detail_load()

    def _icon_context_menu(self, pos):
        item = self._frame.icon_list.itemAt(pos)
        if not item:
            return
        pkg = item.data(Qt.ItemDataRole.UserRole)
        if not pkg:
            return
        menu = self._frame._create_context_menu()
        add_menu_action(menu, "应用详情", callback=lambda: self._frame._show_details_for(pkg))
        menu.addSeparator()
        add_menu_action(menu, "启动应用", callback=lambda: self._frame._launch(pkg))
        add_menu_action(
            menu, "强制停止", callback=lambda: self._frame._modify_one("force_stop", pkg)
        )
        add_menu_action(menu, "清除数据", callback=lambda: self._frame._modify_one("clear", pkg))
        menu.addSeparator()
        add_menu_action(
            menu, "卸载", callback=lambda: self._frame._modify_one("uninstall", pkg)
        )
        add_menu_action(menu, "停用", callback=lambda: self._frame._modify_one("disable", pkg))
        add_menu_action(menu, "启用", callback=lambda: self._frame._modify_one("enable", pkg))
        menu.addSeparator()
        add_menu_action(menu, "备份", callback=lambda: self._frame._backup_one(pkg))
        if self._frame._batch_workers or not self._frame._can_operate():
            for action in menu.actions():
                if not action.isSeparator():
                    action.setEnabled(False)
        menu.exec(self._frame.icon_list.mapToGlobal(pos))

    def _icon_double_click(self, item):
        pkg = item.data(Qt.ItemDataRole.UserRole)
        if pkg:
            self._frame._show_details_for(pkg)

    def _filter(self):
        text = self._frame.search_input.text().strip().lower()
        ft = self._frame.type_filter.currentData()
        self._frame.proxy.set_filters(text, ft)
        # 表格筛选条件也必须同步应用到图标视图，避免两种视图展示不同结果。
        for i in range(self._frame.icon_list.count()):
            item = self._frame.icon_list.item(i)
            pkg = (item.data(Qt.ItemDataRole.UserRole) or "").lower()
            name = (item.text().split("\n")[0] or "").lower()
            type_match = (
                ft == "All"
                or (ft == "User Apps" and item.data(Qt.ItemDataRole.UserRole + 1) == "User")
                or (ft == "System Apps" and item.data(Qt.ItemDataRole.UserRole + 1) == "System")
            )
            text_match = not text or text in name or text in pkg
            item.setHidden(not (type_match and text_match))
        self._frame._schedule_visible_detail_load()
        icons = getattr(self._frame, "_icons_controller", None)
        if icons is not None:
            icons.schedule()

    def _on_table_item_changed(self, item):
        """将表格复选状态写回唯一选择集，再同步到图标视图。"""

        if self._frame._syncing_selection or item.column() != 0:
            return
        package_item = self._frame.model.item(item.row(), 2)
        package = package_item.text() if package_item else ""
        if not package:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._frame.selected_packages.add(package)
        else:
            self._frame.selected_packages.discard(package)
        self._frame._sync_selection_views()

    def _on_icon_selection_changed(self):
        """将图标选择写回唯一选择集，再同步到表格复选框。"""

        if self._frame._syncing_selection:
            return
        icon_packages = {
            item.data(Qt.ItemDataRole.UserRole)
            for index in range(self._frame.icon_list.count())
            if (item := self._frame.icon_list.item(index)) is not None
            and item.data(Qt.ItemDataRole.UserRole)
        }
        selected_icons = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._frame.icon_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        }
        self._frame.selected_packages.difference_update(icon_packages)
        self._frame.selected_packages.update(selected_icons)
        self._frame._sync_selection_views()

    def _sync_selection_views(self):
        """以 selected_packages 为真源同步表格、图标和操作按钮。"""

        if self._frame._syncing_selection:
            return
        table_rows = []
        icon_items = []
        available_packages = set()
        for row in range(self._frame.model.rowCount()):
            package_item = self._frame.model.item(row, 2)
            checkbox_item = self._frame.model.item(row, 0)
            package = package_item.text() if package_item else ""
            if package and checkbox_item:
                table_rows.append((checkbox_item, package))
                available_packages.add(package)
        for index in range(self._frame.icon_list.count()):
            item = self._frame.icon_list.item(index)
            package = item.data(Qt.ItemDataRole.UserRole) if item else ""
            if package:
                icon_items.append((item, package))
                available_packages.add(package)

        self._frame.selected_packages.intersection_update(available_packages)
        self._frame._syncing_selection = True
        try:
            for checkbox_item, package in table_rows:
                expected = (
                    Qt.CheckState.Checked
                    if package in self._frame.selected_packages
                    else Qt.CheckState.Unchecked
                )
                if checkbox_item.checkState() != expected:
                    checkbox_item.setCheckState(expected)
            for item, package in icon_items:
                selected = package in self._frame.selected_packages
                if item.isSelected() != selected:
                    item.setSelected(selected)
        finally:
            self._frame._syncing_selection = False
        self._frame._update_selection_ui()

    def _update_selection_ui(self):
        """更新选择计数，并在无选择或批处理期间禁用相关动作。"""

        count = len(self._frame.selected_packages)
        batch_running = bool(self._frame._batch_workers)
        load_running = bool(getattr(self._frame, "_load_in_progress", False))
        device_connected = self._frame._can_operate()
        self._frame.selection_label.setText(f"已选 {count} 项")
        for button in self._frame._selection_action_buttons:
            requires_device = bool(button.property("requiresDevice"))
            button.setEnabled(
                count > 0
                and not batch_running
                and (device_connected or not requires_device)
            )
        for button in self._frame._preset_action_buttons:
            requires_device = bool(button.property("requiresDevice"))
            requires_selection = bool(button.property("requiresSelection"))
            button.setEnabled(
                not batch_running
                and (device_connected or not requires_device)
                and (count > 0 or not requires_selection)
            )
        self._frame.refresh_btn.setEnabled(
            device_connected and not batch_running and not load_running
        )
        retry_btn = getattr(self._frame, "retry_btn", None)
        if retry_btn is not None:
            retry_btn.setEnabled(device_connected and not batch_running and not load_running)

    def _on_row_clicked(self, index):
        src = self._frame.proxy.mapToSource(index)
        row = src.row()
        if row < 0:
            return
        cb = self._frame.model.item(row, 0)
        if index.column() > 0:
            ns = (
                Qt.CheckState.Unchecked
                if cb.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            cb.setCheckState(ns)
