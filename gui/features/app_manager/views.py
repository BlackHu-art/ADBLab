"""应用管理器视图控制器 — 加载/填充应用列表、筛选与选择同步、详情懒加载。"""

import weakref
from collections.abc import Generator, Iterator
from functools import lru_cache
from time import perf_counter

from PySide6.QtCore import QModelIndex, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QStandardItem
from PySide6.QtWidgets import QTreeView, QTreeWidgetItem

from gui.dialogs.lifecycle import (
    alive_callback,
    alive_forwarding_callback,
    is_qobject_alive,
)
from gui.i18n import tr
from gui.styles import BaseStyles
from gui.styles.fluent import add_menu_action
from gui.styles.icon_loader import get_fluent_icon
from gui.styles.typography import FontRole

from .rows import STATUS_ROLE, VERSION_ROLE, refresh_row_description


def _visible_row_indexes(view: QTreeView) -> Iterator[QModelIndex]:
    """仅遍历当前视口的行，排序、隐藏和横向滚动的映射交给 Qt。

    可见区补全会在连续滚动期间反复触发，不能逐个检查整份应用列表。
    保持命中列不变，避免横滚后的第零列已离开视口而漏掉后续行。
    """
    viewport = view.viewport().rect()
    if viewport.isEmpty():
        return
    index = QModelIndex()
    for x in (viewport.left(), viewport.center().x(), viewport.right()):
        index = view.indexAt(QPoint(x, viewport.top()))
        if index.isValid():
            break
    if not index.isValid():
        return
    column = index.column()
    while index.isValid():
        rect = view.visualRect(index)
        if rect.top() > viewport.bottom():
            break
        if rect.isValid() and viewport.intersects(rect):
            yield index
        index = view.indexBelow(index).siblingAtColumn(column)


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
        self._filter_timer = QTimer(frame if isinstance(frame, QObject) else None)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(180)
        self._filter_timer.timeout.connect(self._flush_filter)
        self._last_filter_text = ""
        self._population: Generator[None, None, None] | None = None
        self._population_timer: QTimer | None = None
        self._population_paused = False
        self._population_request = None
        self._population_device = ""
        self._population_worker_finished = False

    @property
    def populating(self) -> bool:
        """列表快照尚未完整交付时，详情补全和刷新继续遵守加载忙碌边界。"""
        return self._population is not None

    def pause_population(self) -> None:
        """离页只暂停展示批次，保留原设备快照供再次激活时继续。"""
        self._population_paused = True
        if self._population_timer is not None:
            self._population_timer.stop()

    def resume_population(self) -> None:
        """恢复尚未失效的展示快照；设备和请求身份仍在每个批次复核。"""
        self._population_paused = False
        if self.populating:
            self._schedule_population()

    def cancel_population(self) -> None:
        """关闭或替换快照时丢弃尚未建行的数据，停止页面拥有的计时器。"""
        if self._population_timer is not None:
            self._population_timer.stop()
        if self._population is not None:
            self._population.close()
        self._population = None
        self._population_worker_finished = False

    def defer_load_finished(self, request_id) -> bool:
        """worker 退出不能提前结束仍在 GUI 中分批交付的加载。"""
        if self.populating and request_id == self._population_request:
            self._population_worker_finished = True
            return True
        return False

    def _schedule_population(self) -> None:
        if self._population_paused:
            return
        if self._population_timer is None:
            self._population_timer = QTimer(self._frame)
            self._population_timer.setSingleShot(True)
            self._population_timer.timeout.connect(self._continue_population)
        self._population_timer.start(0)

    def _continue_population(self) -> None:
        """每次只消费一个有行数及时间预算的批次，不嵌套处理 Qt 事件。"""
        if self._population is None or self._population_paused:
            return
        if self._frame._closing or self._frame.device_ip != self._population_device or (
            self._population_request is not None
            and self._population_request != self._frame._active_load_request
        ):
            self.cancel_population()
            return
        try:
            next(self._population)
        except StopIteration:
            self._population = None
            self._finish_population()
        else:
            self._schedule_population()

    def _load_apps(self):
        from . import page as _app_manager

        if self._frame._closing:
            return False
        if not self._frame._can_operate():
            # 未通过设备准入时没有执行加载，保留原加载结果及真实错误提示。
            self._frame.status_bar.setText(tr("请在顶部设备栏勾选当前在线设备后刷新。"))
            return False
        if getattr(self._frame, "_load_in_progress", False) or self.populating:
            self._frame._load_refresh_pending = True
            self._frame.status_bar.setText(tr("刷新已排队，将在当前加载完成后执行。"))
            return False
        self._frame._load_request_id += 1
        request_id = self._frame._load_request_id
        self._frame._active_load_request = request_id
        self._frame._load_in_progress = True
        self._frame._android_user_ready = False
        self._frame.details_page.set_android_user(self._frame._android_user_id, ready=False)
        self._frame._load_result_received = False
        self._frame._last_load_error = ""
        self._cancel_detail_worker()
        self._frame._icons_controller.reset(preserve_cache=True)
        self._frame._loaded_detail_packages.clear()
        self._frame._pending_detail_packages.clear()
        self._frame._failed_detail_packages.clear()
        if is_qobject_alive(self._frame._detail_timer):
            self._frame._detail_timer.stop()
        set_state = getattr(self._frame, "_set_load_state", None)
        if callable(set_state):
            set_state("loading", tr("正在加载已安装应用…"))
        w = _app_manager.AppManagerWorker(self._frame.device_ip, "load_apps")
        w.log_message.connect(
            lambda message: self._frame._on_load_log(request_id, message),
            Qt.ConnectionType.QueuedConnection,
        )
        dialog_ref = weakref.ref(self._frame)
        pending_user = None

        def receive_user(user_id):
            nonlocal pending_user
            if type(user_id) is int and user_id >= 0:
                pending_user = user_id

        w.user_context_loaded.connect(receive_user, Qt.ConnectionType.QueuedConnection)

        def populate_current(apps):
            dialog = dialog_ref()
            if (
                dialog is not None and is_qobject_alive(dialog) and not dialog._closing
                and request_id == dialog._active_load_request and pending_user is not None
            ):
                dialog._accept_android_user(pending_user)
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
        self.cancel_population()
        # GUI 分批消费期间，调用方不再拥有可改变待交付内容的列表引用。
        apps = list(apps)
        self._frame._detail_filter_timer.stop()
        self._cancel_detail_worker()
        self._frame._icons_controller.reset(preserve_cache=True)
        self._frame._apps_data = apps
        available_packages = {pkg for _name, pkg, _status, _app_type in apps}
        self._frame._detail_cache = {
            pkg: detail for pkg, detail in self._frame._detail_cache.items()
            if pkg in available_packages
        }
        self._frame._app_labels = {
            pkg: detail[0] for pkg, detail in self._frame._detail_cache.items()
        }
        self._frame._app_versions = {
            pkg: detail[1] for pkg, detail in self._frame._detail_cache.items()
        }
        self._frame._icons_controller.retain_packages(available_packages)
        self._frame._loaded_detail_packages.clear()
        self._frame._failed_detail_packages.clear()
        self._frame._pending_detail_packages.clear()
        self._frame._detail_row_by_pkg = {}
        self._frame._detail_icon_by_pkg = {}
        if not hasattr(self._frame, "selected_packages"):
            self._frame.selected_packages = set()
        self._frame.selected_packages.clear()
        self._frame.selected_packages.update(previous_selection & available_packages)
        self._frame._syncing_selection = True
        try:
            self._frame.tree.setSortingEnabled(False)
            self._frame.model.removeRows(0, self._frame.model.rowCount())
            self._frame.icon_list.clear()
        finally:
            self._frame._syncing_selection = False
        self._population_request = request_id
        self._population_device = self._frame.device_ip
        if request_id is not None:
            self._frame._load_result_received = True
        self._population = self._populate_rows(apps)
        self._frame._update_selection_ui()
        self._continue_population()

    def _populate_rows(self, apps):
        """成对增量构造两种视图，按行同步选择，允许批次之间切换和筛选。"""
        sorted_apps = sorted(apps, key=lambda x: (0 if x[3] == "User" else 1, x[0].lower()))
        immediate = len(apps) <= 128
        started = perf_counter()
        for row, ((name, pkg, st, at), icon_app) in enumerate(zip(apps, sorted_apps)):
            name, version, _installed = self._frame._detail_cache.get(pkg, (name, "", ""))
            cb = QStandardItem()
            cb.setCheckable(True)
            cb.setCheckState(
                Qt.CheckState.Checked if pkg in self._frame.selected_packages
                else Qt.CheckState.Unchecked
            )
            self._frame.model.appendRow(
                [
                    cb,
                    QStandardItem(name),
                    QStandardItem(pkg),
                    QStandardItem(version),
                    QStandardItem(st),
                    QStandardItem(at),
                ]
            )
            for column in (1, 2):
                item = self._frame.model.item(row, column)
                item.setToolTip(item.text())
            self._frame._detail_row_by_pkg[pkg] = row
            name, pkg, st, at = icon_app
            name, version, _installed = self._frame._detail_cache.get(pkg, (name, "", ""))
            item = QTreeWidgetItem(["", name, pkg, ""])
            item.setIcon(0, self._frame._gen_icon(name, at, 48))
            item.setData(0, Qt.ItemDataRole.UserRole, pkg)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, at)
            item.setData(0, STATUS_ROLE, st)
            item.setData(0, VERSION_ROLE, version)
            refresh_row_description(item)
            color = "TEXT_DISABLED" if st == "Disabled" else "TEXT_PRIMARY"
            item.setForeground(1, BaseStyles.get_color(color))
            self._frame.icon_list.addTopLevelItem(item)
            self._frame._detail_icon_by_pkg[pkg] = item
            self._filter_icon(item)
            self._frame._syncing_selection = True
            try:
                item.setSelected(pkg in self._frame.selected_packages)
            finally:
                self._frame._syncing_selection = False
            if not immediate and ((row + 1) % 64 == 0 or perf_counter() - started >= 0.006):
                yield
                started = perf_counter()

    def _finish_population(self):
        """两种视图交付完整后才发布成功并放行详情、图标及排队的刷新。"""
        self._frame.tree.setSortingEnabled(True)
        self._frame._form_controller._update_view_geometry()
        record_success = getattr(self._frame, "_record_load_success", None)
        if callable(record_success) and self._population_request is not None:
            record_success(self._population_request, len(self._frame._apps_data))
        else:
            self._frame.status_bar.setText(
                tr("已加载 {value0} 个应用，正在读取详情…").format(
                    value0=len(self._frame._apps_data),
                )
            )
        details_page = getattr(self._frame, "details_page", None)
        if (
            getattr(self._frame, "_details_open", False)
            and details_page is not None
            and details_page.package_name not in self._frame._detail_row_by_pkg
        ):
            self._frame.close_details()
        self._frame._schedule_visible_detail_load()
        self._frame._icons_controller.schedule()
        if self._population_worker_finished:
            self._population_worker_finished = False
            self._frame._on_load_worker_finished(self._population_request)
        else:
            self._frame._update_selection_ui()

    def _on_metadata(self, metadata):
        """只接收 worker 的当前代次元数据，指纹用于验证候选图标缓存。"""
        self._on_detail(
            metadata["package"], metadata["label"], metadata["version"],
            metadata["installed"], fingerprint=metadata["fingerprint"],
        )

    def _on_detail(self, pkg, label, version, itime, *, fingerprint=""):
        sender = getattr(self._frame, "sender", None)
        source = sender() if callable(sender) else None
        source_request_id = getattr(source, "_app_load_request_id", None)
        if self._frame._closing or (
            source_request_id is not None
            and source_request_id != getattr(self._frame, "_active_load_request", 0)
        ) or (source is not None and getattr(source, "_app_detail_cancelled", False)):
            return
        self._frame._pending_detail_packages.discard(pkg)
        self._frame._loaded_detail_packages.add(pkg)
        self._frame._app_labels[pkg] = label
        self._frame._app_versions[pkg] = version
        self._frame._detail_cache[pkg] = (label, version, itime)
        self._frame._failed_detail_packages.discard(pkg)
        self._frame._icons_controller.validate_metadata(pkg, fingerprint)
        item = self._frame._detail_icon_by_pkg.get(pkg)
        if item:
            if label:
                item.setText(1, label)
            item.setData(0, VERSION_ROLE, version)
            refresh_row_description(item)
            self._frame._icons_controller.decorate(pkg)
        row = self._frame._detail_row_by_pkg.get(pkg)
        if row is not None:
            name_item = self._frame.model.item(row, 1)
            version_item = self._frame.model.item(row, 3)
            if label and name_item:
                name_item.setText(label)
                name_item.setToolTip(label)
            if version_item:
                version_item.setText(version)
                version_item.setToolTip(version)
        # 单条详情只更新对应模型行，全列表筛选合并到本轮事件交付之后。
        if not self._frame._detail_filter_timer.isActive():
            self._frame._detail_filter_timer.start(0)

    def _cancel_detail_worker(self):
        """取消只读补全但保留 worker 占位，直到 finished 确认设备清理完成。"""
        worker = self._frame._detail_worker
        if worker is not None and not getattr(worker, "_app_detail_cancelled", False):
            setattr(worker, "_app_detail_cancelled", True)
            worker.abort()

    def _on_detail_worker_finished(self, packages=None, request_id=None, worker=None):
        """未发布成功详情的包留待刷新重试，避免失败批次在定时器中不断重发。"""
        if worker is not None and worker is not self._frame._detail_worker:
            return
        if request_id is not None and request_id != getattr(self._frame, "_active_load_request", 0):
            if worker is not None:
                self._frame._detail_worker = None
                self._frame._detail_worker_running = False
                self._frame._schedule_visible_detail_load()
            return
        cancelled = worker is not None and getattr(worker, "_app_detail_cancelled", False)
        if packages:
            self._frame._pending_detail_packages.difference_update(packages)
            if not cancelled:
                failed = set(packages) - self._frame._loaded_detail_packages
                self._frame._failed_detail_packages.update(failed)
                for package in failed:
                    self._frame._icons_controller.validate_metadata(package, "")
        self._frame._detail_worker = None
        self._frame._detail_worker_running = False
        if self._frame._closing or not is_qobject_alive(self._frame._detail_timer):
            return
        if not self._frame._can_operate():
            return
        self._frame._icons_controller.schedule()
        if self._frame._has_unloaded_details():
            if not self._frame._detail_timer.isActive():
                self._frame._schedule_visible_detail_load(delay_ms=80)
            return
        # 滚动或切视图可能已排队定时器；没有剩余工作时仍必须发布本批终态。
        self._frame._detail_timer.stop()
        if self._frame._failed_detail_packages:
            self._frame.status_bar.setText(tr("部分应用详情未读取，点击刷新重试。"))
            return
        self._frame.status_bar.setText(
            tr("已加载 {value0} 个应用").format(value0=len(self._frame._apps_data))
        )

    def _schedule_visible_detail_load(self, delay_ms: int = 120):
        if (
            self._frame._closing
            or not getattr(self._frame, "_active", True)
            or not self._frame._can_operate()
            or not is_qobject_alive(self._frame._detail_timer)
        ):
            return
        if self._frame._detail_timer.isActive():
            return
        self._frame._detail_timer.start(delay_ms)

    def _has_unloaded_details(self) -> bool:
        return any(
            pkg
            for _name, pkg, _status, _app_type in self._frame._apps_data
            if pkg not in self._frame._loaded_detail_packages
            and pkg not in self._frame._pending_detail_packages
            and pkg not in self._frame._failed_detail_packages
        )

    def _next_unloaded_detail_packages(self, limit: int = 30) -> list[str]:
        packages = []
        for _name, pkg, _status, _app_type in self._frame._apps_data:
            if (
                pkg in self._frame._loaded_detail_packages
                or pkg in self._frame._pending_detail_packages
                or pkg in self._frame._failed_detail_packages
            ):
                continue
            packages.append(pkg)
            if len(packages) >= limit:
                break
        return packages

    def _visible_detail_packages(self, limit: int = 30) -> list[str]:
        packages: list[str] = []
        if self._frame._view_mode:
            for index in _visible_row_indexes(self._frame.icon_list):
                pkg = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole)
                if (
                    pkg
                    and pkg not in self._frame._loaded_detail_packages
                    and pkg not in self._frame._failed_detail_packages
                ):
                    packages.append(pkg)
                    if len(packages) >= limit:
                        break
            return packages

        seen = set()
        for index in _visible_row_indexes(self._frame.tree):
            proxy_index = index.siblingAtColumn(2)
            source_index = self._frame.proxy.mapToSource(proxy_index)
            source_row = source_index.row()
            item = self._frame.model.item(source_row, 2)
            pkg = item.text() if item else ""
            if (
                pkg and pkg not in seen and pkg not in self._frame._loaded_detail_packages
                and pkg not in self._frame._failed_detail_packages
            ):
                seen.add(pkg)
                packages.append(pkg)
                if len(packages) >= limit:
                    break
        if packages:
            return packages

        for row in range(min(self._frame.model.rowCount(), limit)):
            item = self._frame.model.item(row, 2)
            pkg = item.text() if item else ""
            if (
                pkg and pkg not in self._frame._loaded_detail_packages
                and pkg not in self._frame._failed_detail_packages
            ):
                packages.append(pkg)
        return packages

    def _load_visible_details(self):
        from . import page as _app_manager

        if (
            self._frame._closing
            or not getattr(self._frame, "_active", True)
            or not self._frame._can_operate()
            or self._frame._load_in_progress
            or self.populating
            or self._frame.load_state == "error"
        ):
            return
        visible = self._frame._visible_detail_packages()
        if self._frame._detail_worker_running:
            worker = self._frame._detail_worker
            if (
                visible and set(visible).isdisjoint(self._frame._pending_detail_packages)
            ) or (
                worker is not None and getattr(worker, "_app_background_details", False)
                and self._frame._icons_controller.prioritize_visible()
            ):
                self._cancel_detail_worker()
            return
        if self._frame._icons_controller.busy:
            self._frame._icons_controller.schedule()
            return
        packages = [
            pkg
            for pkg in visible
            if pkg not in self._frame._pending_detail_packages
            and pkg not in self._frame._failed_detail_packages
        ]
        if not packages:
            if self._frame._view_mode and self._frame._icons_controller.prioritize_visible():
                return
            packages = self._frame._next_unloaded_detail_packages()
        if not packages:
            return
        self._frame._pending_detail_packages.update(packages)
        self._frame._detail_worker_running = True
        self._frame.status_bar.setText(
            tr("正在读取详情 {value0}/{value1}").format(
                value0=len(self._frame._loaded_detail_packages), value1=len(self._frame._apps_data)
            )
        )
        w = _app_manager.AppManagerWorker(
            self._frame.device_ip, "load_metadata_batch", packages=packages,
            user_id=self._frame._android_user_id,
        )
        self._frame._detail_worker = w
        setattr(w, "_app_detail_cancelled", False)
        setattr(w, "_app_background_details", not bool(visible))
        request_id = getattr(self._frame, "_active_load_request", 0)
        setattr(w, "_app_load_request_id", request_id)
        w.app_detail_batch.connect(self._frame._on_detail)
        w.app_metadata_loaded.connect(self._frame._on_metadata)
        w.log_message.connect(
            alive_forwarding_callback(self._frame, "log"), Qt.ConnectionType.QueuedConnection
        )
        w.finished.connect(
            alive_callback(
                self._frame,
                "_on_detail_worker_finished",
                packages,
                request_id,
                w,
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
            get_fluent_icon("list-bullets.svg" if self._frame._view_mode else "squares-four.svg")
        )
        tooltip = tr("切换为列表视图") if self._frame._view_mode else tr("切换为图标视图")
        self._frame.view_toggle.setToolTip(tooltip)
        self._frame.view_toggle.setAccessibleName(tooltip)
        self._frame.refresh_btn.setToolTip(tr("刷新应用列表并重试未读取的图标"))
        if self._frame._view_mode:
            self._frame._icons_controller.schedule()
        else:
            self._frame._icons_controller.pause()
        self._frame._schedule_visible_detail_load()

    def _icon_context_menu(self, pos):
        item = self._frame.icon_list.itemAt(pos)
        if not item:
            return
        pkg = item.data(0, Qt.ItemDataRole.UserRole)
        if not pkg:
            return
        menu = self._frame._create_context_menu()
        bind = self._frame._user_bound_action
        add_menu_action(menu, tr("应用详情"), callback=bind("_show_details_for", pkg))
        menu.addSeparator()
        add_menu_action(menu, tr("启动应用"), callback=bind("_launch", pkg))
        add_menu_action(
            menu, tr("强制停止"), callback=bind("_modify_one", "force_stop", pkg)
        )
        add_menu_action(
            menu, tr("清除数据"), callback=bind("_modify_one", "clear", pkg)
        )
        menu.addSeparator()
        add_menu_action(
            menu, tr("卸载"), callback=bind("_modify_one", "uninstall", pkg)
        )
        add_menu_action(menu, tr("停用"), callback=bind("_modify_one", "disable", pkg))
        add_menu_action(menu, tr("启用"), callback=bind("_modify_one", "enable", pkg))
        menu.addSeparator()
        add_menu_action(menu, tr("备份"), callback=bind("_backup_one", pkg))
        if self._frame._batch_workers or not self._frame._can_modify_apps():
            for action in menu.actions():
                if not action.isSeparator():
                    action.setEnabled(False)
        menu.exec(self._frame.icon_list.viewport().mapToGlobal(pos))

    def _icon_double_click(self, item):
        pkg = item.data(0, Qt.ItemDataRole.UserRole)
        if pkg:
            self._frame._show_details_for(pkg)

    def _flush_filter(self):
        self._filter()

    def _filter(self):
        self._frame._detail_filter_timer.stop()
        self._last_filter_text = self._frame.search_input.text()
        text = self._last_filter_text.strip().lower()
        ft = self._frame.type_filter.currentData()
        self._frame.proxy.set_filters(text, ft)
        # 表格筛选条件也必须同步应用到图标视图，避免两种视图展示不同结果。
        for i in range(self._frame.icon_list.topLevelItemCount()):
            item = self._frame.icon_list.topLevelItem(i)
            self._filter_icon(item, text, ft)
        self._frame._schedule_visible_detail_load()
        icons = getattr(self._frame, "_icons_controller", None)
        if icons is not None:
            icons.schedule()

    def _filter_icon(self, item, text=None, app_type=None):
        """新交付的行直接采用最新筛选条件，无需每个批次重新扫描旧行。"""
        if text is None:
            text = self._frame.search_input.text().strip().lower()
            app_type = self._frame.type_filter.currentData()
        pkg = (item.data(0, Qt.ItemDataRole.UserRole) or "").lower()
        name = (item.text(1) or "").lower()
        type_match = (
            app_type == "All"
            or (app_type == "User Apps" and item.data(0, Qt.ItemDataRole.UserRole + 1) == "User")
            or (app_type == "System Apps"
                and item.data(0, Qt.ItemDataRole.UserRole + 1) == "System")
        )
        item.setHidden(not (type_match and (not text or text in name or text in pkg)))

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
        self._sync_selection_packages({package})

    def _on_icon_selection_changed(self):
        """将图标选择写回唯一选择集，再同步到表格复选框。"""

        if self._frame._syncing_selection:
            return
        # selectionModel 保留隐藏行的选择；selectedItems 会遗漏筛选后隐藏的项目。
        selected_icons = {
            package for index in self._frame.icon_list.selectionModel().selectedRows(0)
            if (package := index.data(Qt.ItemDataRole.UserRole))
        }
        if self.populating:
            # 未交付到图标视图的选择不能被一次前台选择动作误认为取消。
            selected_icons.update(
                self._frame.selected_packages - self._frame._detail_icon_by_pkg.keys(),
            )
        changed = self._frame.selected_packages ^ selected_icons
        self._frame.selected_packages.clear()
        self._frame.selected_packages.update(selected_icons)
        self._sync_selection_packages(changed)

    def _sync_selection_packages(self, packages):
        """单项或选择差量只触达包名映射中的行，不扫描两份完整列表。"""
        self._frame._syncing_selection = True
        try:
            for package in packages:
                selected = package in self._frame.selected_packages
                row = self._frame._detail_row_by_pkg.get(package)
                if row is not None:
                    checkbox = self._frame.model.item(row, 0)
                    state = Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
                    if checkbox is not None and checkbox.checkState() != state:
                        checkbox.setCheckState(state)
                item = self._frame._detail_icon_by_pkg.get(package)
                if item is not None and item.isSelected() != selected:
                    item.setSelected(selected)
        finally:
            self._frame._syncing_selection = False
        self._frame._update_selection_ui()

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
        for index in range(self._frame.icon_list.topLevelItemCount()):
            item = self._frame.icon_list.topLevelItem(index)
            package = item.data(0, Qt.ItemDataRole.UserRole) if item else ""
            if package:
                icon_items.append((item, package))
                available_packages.add(package)

        if not self.populating:
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
        load_running = bool(getattr(self._frame, "_load_in_progress", False)) or self.populating
        device_connected = self._frame._can_operate()
        user_ready = self._frame._can_modify_apps()
        previous_width = self._frame.selection_label.minimumSizeHint().width()
        self._frame.selection_label.setText(tr('已选 {value0} 项').format(value0=count))
        if self._frame.selection_label.minimumSizeHint().width() != previous_width:
            # 位数变化会改变摘要的最小宽度，窄窗须立即重判共享列预算。
            self._frame._reflow_top_controls()
        for action in self._frame._command_bar.actions():
            requires_device = bool(action.property("requiresDevice"))
            requires_selection = bool(action.property("requiresSelection"))
            action.setEnabled(
                not batch_running
                and (user_ready or not requires_device)
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
