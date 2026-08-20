"""应用管理器对话框 — 列出、筛选、管理、备份/恢复设备上的应用。"""

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
from PySide6.QtWidgets import QDialog

from gui.dialogs.app_manager_batch import AppManagerBatch
from gui.dialogs.app_manager_details import AppDetailsDialog  # noqa: F401  供测试直接导入。
from gui.dialogs.app_manager_form import AppManagerForm
from gui.dialogs.app_manager_views import AppManagerViews
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    is_qobject_alive,
    safe_disconnect,
    wait_for_threads_later,
)
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
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
        self._form_controller = AppManagerForm(self)
        self._views_controller = AppManagerViews(self)
        self._batch_controller = AppManagerBatch(self)
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
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._show_details_for(pkg)

    def _forget_detail_dialog(self, pkg, dialog):
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._forget_detail_dialog(pkg, dialog)

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

    def _confirm_dangerous_action(self, action, target_count):
        return (
            getattr(self, "_batch_controller", None) or AppManagerBatch(self)
        )._confirm_dangerous_action(action, target_count)

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
