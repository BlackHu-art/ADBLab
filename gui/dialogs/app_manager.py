"""应用管理页面，列出、筛选、管理、备份和恢复设备应用。"""

from PySide6.QtCore import QSize, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtWidgets import QSizePolicy, QSplitter, QTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel

from gui.dialogs.app_manager_batch import AppManagerBatch
from gui.dialogs.app_manager_details import AppDetailsPage
from gui.dialogs.app_manager_form import AppManagerForm
from gui.dialogs.app_manager_icons import AppManagerIcons
from gui.dialogs.app_manager_views import AppManagerViews
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    is_qobject_alive,
    safe_disconnect,
)
from gui.styles import BaseStyles
from models.app_manager_worker import AppManagerWorker  # noqa: F401  供测试通过本模块命名空间补丁。

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

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """展示中文状态；源模型继续保存 worker 返回的稳定业务值。"""
        value = super().data(index, role)
        if role == Qt.ItemDataRole.DisplayRole and index.column() in (4, 5):
            return {
                "Enabled": "已启用", "Disabled": "已停用", "User": "用户",
                "System": "系统", "Vendor": "厂商", "Other": "其他",
            }.get(value, value)
        return value

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


# ── 主应用管理页面 ────────────────────────────────────────────────────────


class AppManagerPage(QWidget):
    """可嵌入 Workspace、按设备会话固定的应用管理页。"""

    MASTER_DETAIL_BREAKPOINT = 1180

    dispose_ready = Signal()
    load_state_changed = Signal(str, str)
    device_connected_changed = Signal(bool)
    detail_opened = Signal(str)
    detail_closed = Signal()

    # 日志区由 AppManagerForm 控制器创建，此处提供类级类型声明供跨控制器解析。
    log_output: QTextEdit
    status_bar: CaptionLabel
    load_error_label: CaptionLabel
    load_error_panel: QWidget
    _master_panel: QWidget
    _page_layout: QVBoxLayout

    def __init__(self, parent=None, device_ip: str = ""):
        super().__init__(parent)
        self.device_ip = device_ip
        self._device_connected = bool(device_ip)
        self._device_selected = bool(device_ip)
        self.selected_packages = set()
        self._syncing_selection = False
        self._batch_workers = set()
        self._batch_total = 0
        self._batch_action = ""
        self._workers = []
        self._load_request_id = 0
        self._active_load_request = 0
        self._load_in_progress = False
        self._load_refresh_pending = False
        self._load_result_received = False
        self._last_load_error = ""
        self.load_state = "idle"
        self._apps_data = []
        self._detail_cache = {}
        self._pending_detail_packages = set()
        self._detail_worker_running = False
        self._closing = False
        self._active = False
        self._activated_once = False
        self._dispose_requested = False
        self._dispose_finalized = False
        self._dispose_signal_emitted = False
        self._close_after_dispose = False
        self._shutdown_registered = False
        self._details_open = False
        self._detail_row_by_pkg = {}
        self._detail_icon_by_pkg = {}
        self._form_controller = AppManagerForm(self)
        self._views_controller = AppManagerViews(self)
        self._batch_controller = AppManagerBatch(self)
        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.timeout.connect(self._load_visible_details)
        self.setObjectName("appManagerPage")
        self.setProperty("feature", "app_manager")
        self.setProperty("deviceConnected", self._device_connected)
        # 该页面由 WorkspaceFeatureHost 管理实际几何；保留旧顶层窗口的固定
        # 最小尺寸会让 720×420 工作区中的页面超出宿主并裁切操作区。
        self.setMinimumSize(0, 0)
        self._init_ui()
        self._init_master_detail()
        self._icons_controller = AppManagerIcons(self)
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)

    def _init_master_detail(self) -> None:
        self._master_detail_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._master_detail_splitter.setObjectName("appManagerMasterDetail")
        self._master_detail_splitter.setChildrenCollapsible(False)
        self._master_detail_splitter.splitterMoved.connect(
            lambda _position, _index: self._reflow_master_controls()
        )
        self._master_detail_splitter.setMinimumSize(0, 0)
        self._master_detail_splitter.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self._master_panel.setMinimumSize(0, 0)
        self._master_panel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self._master_detail_splitter.addWidget(self._master_panel)
        self.details_page = AppDetailsPage(
            self._master_detail_splitter,
            device_ip=self.device_ip,
        )
        self.details_page.back_requested.connect(self.close_details)
        self.details_page.log_message.connect(self.log)
        self.details_page.dispose_ready.connect(self._maybe_finish_dispose)
        self._master_detail_splitter.addWidget(self.details_page)
        self._page_layout.addWidget(self._master_detail_splitter)
        self._update_master_detail_layout()

    @staticmethod
    def _package_from_payload(payload) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            return str(payload.get("package_name") or payload.get("package") or "").strip()
        return ""

    def activate(self, payload=None) -> None:
        """激活页面，首次激活时才启动应用列表加载。"""

        if self._dispose_requested:
            return
        self._active = True
        if not self._activated_once:
            self._activated_once = True
            self._load_apps()
        elif self._load_refresh_pending and not self._load_in_progress:
            self._load_refresh_pending = False
            self._load_apps()
        elif self._apps_data and self._has_unloaded_details():
            self._schedule_visible_detail_load()
        package_name = self._package_from_payload(payload)
        if package_name:
            self.open_details(package_name)
        self._icons_controller.schedule()

    def deactivate(self, reason: str = "navigation") -> None:
        """离开前台时暂停增量详情加载，但不终止业务 worker。"""

        self._active = False
        self._icons_controller.pause()
        if is_qobject_alive(self._detail_timer):
            self._detail_timer.stop()
        self.details_page.deactivate(reason)

    def set_device_connected(self, connected: bool) -> None:
        """更新设备在线状态；离线时保留缓存，只阻止新的 ADB 操作。"""

        connected = bool(connected and self.device_ip)
        changed = connected != self._device_connected
        self._device_connected = connected
        self.setProperty("deviceConnected", connected)
        self.details_page.set_device_connected(connected)
        self._form_controller._refresh_status_badge()
        if not connected:
            self._load_refresh_pending = False
            if is_qobject_alive(self._detail_timer):
                self._detail_timer.stop()
            self.status_bar.setText("设备已离线，仍可查看缓存的应用列表。")
        elif changed:
            self.status_bar.setText("设备已重新连接，刷新可更新应用列表。")
        if self._can_operate():
            self._icons_controller.schedule()
        else:
            self._icons_controller.pause()
        self._update_selection_ui()
        if changed:
            self.device_connected_changed.emit(connected)

    def _can_operate(self) -> bool:
        """已选、在线且未关闭的固定设备才可接受新的应用操作。"""
        return bool(
            self.device_ip and self._device_selected and self._device_connected
            and not self._closing
        )

    def set_device_selected(self, selected: bool) -> None:
        """更新会话操作资格；缓存可保留，已提交 worker 继续使用原设备。"""
        self._device_selected = bool(selected and self.device_ip)
        self.details_page.set_device_selected(self._device_selected)
        self._form_controller._refresh_status_badge()
        if not self._can_operate():
            self._load_refresh_pending = False
            self._detail_timer.stop()
            self._icons_controller.pause()
        else:
            self._schedule_visible_detail_load()
            self._icons_controller.schedule()
        self._update_selection_ui()
        if not self._device_selected:
            self.status_bar.setText("请在顶部设备栏勾选当前设备后执行应用操作；已加载内容仍可查看。")

    def open_details(self, package_name: str):
        """在当前管理页内打开指定包详情，不创建顶层窗口。"""

        package_name = str(package_name or "").strip()
        if not package_name or self._batch_action_blocked() or self._dispose_requested:
            return None
        self._details_open = True
        self.details_page.activate(package_name)
        self._update_master_detail_layout()
        self.detail_opened.emit(package_name)
        return self.details_page

    def close_details(self) -> None:
        if not self._details_open:
            return
        self.details_page.deactivate("back")
        self._details_open = False
        self._update_master_detail_layout()
        self.detail_closed.emit()

    @property
    def master_detail_mode(self) -> str:
        return str(self.property("masterDetailMode") or "stack")

    @staticmethod
    def _surface_minimum_size(surface: QWidget) -> QSize:
        """返回内容表面的有效最小尺寸，不把它写回控件约束。"""

        hint = surface.minimumSizeHint().expandedTo(surface.minimumSize())
        return QSize(max(0, hint.width()), max(0, hint.height()))

    def prepare_for_workspace(self) -> None:
        """嵌入工作区时复用宿主页头，将设备状态保留在本页工具栏。"""
        self.set_device_selected(False)
        self._form_controller.prepare_for_workspace()

    def workspace_content_minimum_size(self) -> QSize:
        """返回当前主从视图供 Workspace 外层滚动使用的内容下限。

        页面本身保持可压缩，避免把最小尺寸向上传播到主窗口。宿主需要避免
        内容裁切时可读取本方法，并把超出视口的部分交给滚动区域承载。
        """

        page_margins = self._page_layout.contentsMargins()
        horizontal_margin = page_margins.left() + page_margins.right()
        vertical_margin = page_margins.top() + page_margins.bottom()
        if not self._details_open:
            minimum = self._surface_minimum_size(self._master_panel)
            return QSize(
                minimum.width() + horizontal_margin,
                minimum.height() + vertical_margin,
            )

        detail_minimum = self._surface_minimum_size(self.details_page)
        if self.master_detail_mode != "split":
            return QSize(
                detail_minimum.width() + horizontal_margin,
                detail_minimum.height() + vertical_margin,
            )

        master_minimum = self._surface_minimum_size(self._master_panel)
        handle_width = self._master_detail_splitter.handleWidth() * max(
            0, self._master_detail_splitter.count() - 1
        )
        return QSize(
            master_minimum.width()
            + detail_minimum.width()
            + handle_width
            + horizontal_margin,
            max(master_minimum.height(), detail_minimum.height()) + vertical_margin,
        )

    def _update_master_detail_layout(self) -> None:
        wide = self.width() >= self.MASTER_DETAIL_BREAKPOINT
        mode = "split" if wide else "stack"
        self.setProperty("masterDetailMode", mode)
        if not self._details_open:
            self._master_panel.show()
            self.details_page.hide()
            self._reflow_master_controls()
            self.updateGeometry()
            return
        self.details_page.show()
        self._master_panel.setVisible(wide)
        if wide:
            width = max(1, self._master_detail_splitter.width())
            self._master_detail_splitter.setSizes(
                [max(1, width * 3 // 5), max(1, width * 2 // 5)]
            )
        self._reflow_master_controls()
        self.updateGeometry()

    def _reflow_master_controls(self) -> None:
        self._reflow_top_controls()
        self._reflow_action_buttons()

    def retry_load(self) -> None:
        """重试失败的应用列表加载；运行中请求会合并为一次后续刷新。"""

        if self._dispose_requested:
            return
        self._load_apps()

    def _set_load_state(self, state: str, message: str) -> None:
        self.load_state = state
        self.setProperty("loadState", state)
        is_error = state == "error"
        self.load_error_label.setText(message or "无法加载应用列表。")
        self.load_error_panel.setVisible(is_error)
        self.status_bar.setText(message)
        self._update_selection_ui()
        self.load_state_changed.emit(state, message)

    def _on_load_log(self, request_id: int, message: str) -> None:
        if request_id != self._active_load_request or self._closing:
            return
        self.log(message)
        normalized = message.strip()
        if normalized.lower().startswith(("error", "failed")):
            self._last_load_error = normalized

    def _record_load_success(self, request_id: int, count: int) -> None:
        if request_id != self._active_load_request or self._closing:
            return
        self._load_result_received = True
        if self._device_connected:
            message = f"已加载 {count} 个应用，正在读取详情…"
        else:
            message = f"设备已离线，显示 {count} 个缓存应用。"
        self._set_load_state("ready", message)

    def _on_load_worker_finished(self, request_id: int) -> None:
        if request_id != self._active_load_request:
            self._maybe_finish_dispose()
            return
        self._load_in_progress = False
        if not self._closing and not self._load_result_received:
            message = self._last_load_error or (
                "无法加载应用，请检查设备后重试。"
            )
            self._set_load_state("error", message)
        if not self._closing and self._load_refresh_pending and self._active:
            self._load_refresh_pending = False
            QTimer.singleShot(0, self._load_apps)
        else:
            self._update_selection_ui()
            self._icons_controller.schedule()
        self._maybe_finish_dispose()

    # ── 表单控制器委托 wrapper ─────────────────────────────────────────

    def _init_ui(self):
        return (getattr(self, "_form_controller", None) or AppManagerForm(self))._init_ui()

    def _apply_theme(self, _value=None):
        return (
            getattr(self, "_form_controller", None) or AppManagerForm(self)
        )._apply_theme(_value)

    def _action_layout_available_width(self):
        return (
            getattr(self, "_form_controller", None) or AppManagerForm(self)
        )._action_layout_available_width()

    @staticmethod
    def _buttons_fit_columns(buttons, columns, available_width, spacing):
        return AppManagerForm._buttons_fit_columns(buttons, columns, available_width, spacing)

    def _reflow_action_group(
        self, layout, buttons, short_labels, wide_columns, *, span_last_in_two_columns=False
    ):
        return (
            getattr(self, "_form_controller", None) or AppManagerForm(self)
        )._reflow_action_group(
            layout,
            buttons,
            short_labels,
            wide_columns,
            span_last_in_two_columns=span_last_in_two_columns,
        )

    def _reflow_action_buttons(self):
        return (
            getattr(self, "_form_controller", None) or AppManagerForm(self)
        )._reflow_action_buttons()

    def _top_controls_fit(self, columns):
        return (getattr(self, "_form_controller", None) or AppManagerForm(self))._top_controls_fit(
            columns
        )

    def _reflow_top_controls(self):
        return (
            getattr(self, "_form_controller", None) or AppManagerForm(self)
        )._reflow_top_controls()

    def _create_context_menu(self):
        return (
            getattr(self, "_form_controller", None) or AppManagerForm(self)
        )._create_context_menu()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_master_detail_layout()
        self._reflow_top_controls()
        self._reflow_action_buttons()

    # ── 视图控制器委托 wrapper ─────────────────────────────────────────

    def _load_apps(self):
        return (getattr(self, "_views_controller", None) or AppManagerViews(self))._load_apps()

    def _populate(self, apps, *, request_id=None):
        return (getattr(self, "_views_controller", None) or AppManagerViews(self))._populate(
            apps, request_id=request_id
        )

    def _on_detail(self, pkg, label, version, itime):
        return (getattr(self, "_views_controller", None) or AppManagerViews(self))._on_detail(
            pkg, label, version, itime
        )

    def _on_detail_worker_finished(self, packages=None, request_id=None):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._on_detail_worker_finished(packages, request_id)

    def _schedule_visible_detail_load(self, delay_ms=120):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._schedule_visible_detail_load(delay_ms)

    def _has_unloaded_details(self):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._has_unloaded_details()

    def _next_unloaded_detail_packages(self, limit=30):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._next_unloaded_detail_packages(limit)

    def _visible_detail_packages(self, limit=30):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._visible_detail_packages(limit)

    def _load_visible_details(self):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._load_visible_details()

    @staticmethod
    def _gen_icon(name, atype, size=48):
        return AppManagerViews._gen_icon(name, atype, size)

    def _toggle_view(self):
        return (getattr(self, "_views_controller", None) or AppManagerViews(self))._toggle_view()

    def _icon_context_menu(self, pos):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._icon_context_menu(pos)

    def _icon_double_click(self, item):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._icon_double_click(item)

    def _filter(self):
        return (getattr(self, "_views_controller", None) or AppManagerViews(self))._filter()

    def _on_table_item_changed(self, item):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._on_table_item_changed(item)

    def _on_icon_selection_changed(self):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._on_icon_selection_changed()

    def _sync_selection_views(self):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._sync_selection_views()

    def _update_selection_ui(self):
        return (
            getattr(self, "_views_controller", None) or AppManagerViews(self)
        )._update_selection_ui()

    def _on_row_clicked(self, index):
        return (getattr(self, "_views_controller", None) or AppManagerViews(self))._on_row_clicked(
            index
        )

    # ── 批量控制器委托 wrapper ─────────────────────────────────────────

    def _context_menu(self, pos):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._context_menu(
            pos
        )

    def _show_details_for(self, pkg):
        return self.open_details(pkg)

    def _batch_action_blocked(self):
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._batch_action_blocked()

    def _launch(self, pkg):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._launch(pkg)

    def _modify_one(self, action, pkg):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._modify_one(
            action, pkg
        )

    @staticmethod
    def _global_save_dir():
        return AppManagerBatch._global_save_dir()

    def _backup_one(self, pkg):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._backup_one(pkg)

    def _deselect_all(self):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._deselect_all()

    def _log_backup_progress(self, progress, message):
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._log_backup_progress(progress, message)

    def _get_selected_pkgs(self):
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._get_selected_pkgs()

    def _modify_selected(self, action):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._modify_selected(
            action
        )

    def _on_batch_worker_finished(self, worker):
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._on_batch_worker_finished(worker)

    def _backup_selected(self):
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._backup_selected()

    def _restore_apps(self):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._restore_apps()

    def _show_details(self):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._show_details()

    def _create_preset(self):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._create_preset()

    def _load_preset(self):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._load_preset()

    @staticmethod
    def _validate_preset(data):
        return AppManagerBatch._validate_preset(data)

    def _report_preset_error(self, action, error):
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._report_preset_error(action, error)

    def _track_worker(self, w):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._track_worker(w)

    def _prune_worker(self, w):
        return (getattr(self, "_batch_controller", None) or AppManagerBatch(self))._prune_worker(w)

    # ── 日志 / 关闭 ──────────────────────────────────────────────────────

    def log(self, msg):
        if self._closing or not is_qobject_alive(self.log_output):
            return
        self.log_output.append(msg)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def register_shutdown_tasks(self, supervisor, *, owner_id: str, task_prefix: str):
        """将仍在运行的应用管理 worker 作为一组资源注册到监督器。"""
        workers = self._running_workers()
        if not workers:
            return ()
        task_id = f"{task_prefix}-workers"
        handle = QThreadGroupShutdownTask(workers)
        supervisor.register(
            task_id,
            owner_id=owner_id,
            kind="app_manager_workers",
            request_stop=handle.request_stop,
            wait=handle.wait,
            is_running=handle.is_running,
        )
        self._shutdown_registered = True
        return (task_id,)

    def _all_workers(self):
        workers = [*self._workers, *self.details_page._workers]
        return list(dict.fromkeys(workers))

    def _running_workers(self):
        return [
            worker
            for worker in self._all_workers()
            if QThreadGroupShutdownTask._running(worker)
        ]

    def request_dispose(self, _reason: str = "user") -> bool:
        """请求释放页面；资源停止前返回 ``False`` 并延后发出完成信号。"""

        if self._dispose_finalized:
            return True
        self._dispose_requested = True
        self._closing = True
        self._icons_controller.reset()
        self._active = False
        if is_qobject_alive(self._detail_timer):
            self._detail_timer.stop()
            safe_disconnect(self._detail_timer.timeout, self._load_visible_details)
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
        self.details_page.request_dispose(_reason)
        for worker in self._running_workers():
            worker.abort()
        if self._running_workers():
            return False
        self._finalize_dispose(emit_signal=False)
        return True

    def _maybe_finish_dispose(self) -> None:
        if not self._dispose_requested or self._running_workers():
            return
        self._finalize_dispose(emit_signal=True)

    def _finalize_dispose(self, *, emit_signal: bool) -> None:
        if self._dispose_finalized:
            return
        self._dispose_finalized = True
        if emit_signal and not self._dispose_signal_emitted:
            self._dispose_signal_emitted = True
            self.dispose_ready.emit()
            if self._close_after_dispose and is_qobject_alive(self):
                QTimer.singleShot(0, lambda: self.close() if is_qobject_alive(self) else None)

    def closeEvent(self, event):
        """直接关闭控件时也遵循会话资源释放屏障。"""

        if self.request_dispose("close"):
            super().closeEvent(event)
            return
        self._close_after_dispose = True
        self.hide()
        event.ignore()

__all__ = ["AppManagerPage", "AppSortProxy", "AppManagerWorker"]
