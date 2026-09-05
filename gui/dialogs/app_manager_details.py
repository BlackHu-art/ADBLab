"""应用管理详情页，展示单个应用信息并管理运行时权限。"""

import html

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLayout,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, ListWidget, PushButton, TabWidget, TextEdit

from gui.dialogs.app_manager_form import _apply_adaptive_text_heights
from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    alive_callback,
    is_qobject_alive,
    safe_disconnect,
)
from gui.styles import BaseStyles
from gui.styles.fluent import apply_label_role
from gui.styles.icon_loader import get_themed_icon
from gui.styles.typography import FontRole
from models.app_manager_worker import AppManagerWorker


class AppDetailsPage(QWidget):
    """可嵌入 Workspace 的应用详情页。

    构造阶段只创建控件，不执行 ADB 命令。首次 ``activate`` 后才加载数据；
    ``deactivate`` 仅停止前台交互，不会把仍在收尾的 worker 当作已释放资源。
    """

    back_requested = Signal()
    dispose_ready = Signal()
    log_message = Signal(str)
    load_state_changed = Signal(str, str)
    device_connected_changed = Signal(bool)

    def __init__(self, parent=None, device_ip: str = "", package_name: str = ""):
        super().__init__(parent)
        self.device_ip = device_ip
        self._device_connected = bool(device_ip)
        self._device_selected = bool(device_ip)
        self.package_name = package_name
        self._workers = []
        self._closing = False
        self._active = False
        self._loaded_package = ""
        self._load_generation = 0
        self._pending_load_parts: set[str] = set()
        self._pending_reload = False
        self._last_load_error = ""
        self._dispose_requested = False
        self._dispose_finalized = False
        self._dispose_signal_emitted = False
        self._close_after_dispose = False
        self._shutdown_registered = False
        self.load_state = "idle"
        self.setObjectName("appDetailsPage")
        self.setProperty("masterDetailRole", "detail")
        self.setProperty("deviceConnected", self._device_connected)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._init_ui()
        self.set_device_connected(self._device_connected)
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(8, 8, 8, 6)
        header = QHBoxLayout()
        self.back_btn = PushButton("返回列表")
        self.back_btn.setToolTip("返回已安装应用列表")
        self.back_btn.setAccessibleName("返回应用列表")
        self.back_btn.setIcon(get_themed_icon("arrow-left.svg"))
        self.back_btn.setIconSize(QSize(14, 14))
        self.back_btn.clicked.connect(self.back_requested)
        self.package_label = apply_label_role(
            BodyLabel(self.package_name or "应用详情"),
            FontRole.TITLE,
            color_key="TITLE_COLOR",
        )
        self.package_label.setWordWrap(True)
        header.addWidget(self.back_btn)
        header.addWidget(self.package_label, 1)
        layout.addLayout(header)

        error_row = QHBoxLayout()
        self.load_error_label = apply_label_role(
            CaptionLabel("无法加载应用详情。"),
            FontRole.UI_SMALL,
            color_key="ERROR_COLOR",
        )
        self.load_error_label.setWordWrap(True)
        self.retry_btn = PushButton("重试")
        self.retry_btn.setToolTip("重新尝试加载应用详情")
        self.retry_btn.setAccessibleName("重试应用详情")
        self.retry_btn.clicked.connect(self.retry_load)
        error_row.addWidget(self.load_error_label, 1)
        error_row.addWidget(self.retry_btn)
        self.load_error_label.hide()
        self.retry_btn.hide()
        layout.addLayout(error_row)

        self.tabs = TabWidget()
        dw = QWidget()
        dl = QVBoxLayout(dw)
        self.detail_text = TextEdit()
        self.detail_text.setReadOnly(True)
        dl.addWidget(self.detail_text)
        self.tabs.addTab(dw, "应用详情")

        pw = QWidget()
        pl = QVBoxLayout(pw)
        self.declared_list = self._ps(pl, "声明权限（只读）", checkable=False)
        self.requested_list = self._ps(pl, "请求权限")
        self.runtime_list = self._ps(pl, "运行时权限（授权或撤销）")
        pb = QHBoxLayout()
        self.grant_btn = PushButton()
        self.grant_btn.setText("授权所选")
        self.grant_btn.setToolTip("授予选中的运行时权限")
        self.grant_btn.setIcon(get_themed_icon("check-circle.svg"))
        self.grant_btn.setIconSize(QSize(14, 14))
        self.revoke_btn = PushButton()
        self.revoke_btn.setText("撤销所选")
        self.revoke_btn.setToolTip("撤销选中的运行时权限")
        self.revoke_btn.setIcon(get_themed_icon("x-circle.svg"))
        self.revoke_btn.setIconSize(QSize(14, 14))
        self.grant_btn.clicked.connect(lambda: self._mp("grant"))
        self.revoke_btn.clicked.connect(lambda: self._mp("revoke"))
        pb.addWidget(self.grant_btn)
        pb.addWidget(self.revoke_btn)
        pl.addLayout(pb)
        self.tabs.addTab(pw, "权限")
        layout.addWidget(self.tabs)

    def _apply_theme(self, _value=None):
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        mono_font = BaseStyles.font_for_role(FontRole.MONO)
        self.detail_text.setFont(mono_font)
        self.detail_text.document().setDefaultFont(mono_font)
        self.package_label.setFont(BaseStyles.font_for_role(FontRole.TITLE))
        self.load_error_label.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        _apply_adaptive_text_heights(self)

    def _ps(self, parent, title, *, checkable=True):
        hl = QHBoxLayout()
        hl.addWidget(apply_label_role(BodyLabel(title), FontRole.UI))
        if checkable:
            sb = PushButton()
            sb.setText("全选 / 全不选")
            sb.setToolTip("切换此列表的全部权限选择")
            sb.setIcon(get_themed_icon("check-square.svg"))
            sb.setIconSize(QSize(14, 14))
            sb.setMinimumWidth(130)
            sb.setProperty("adaptiveBaseHeight", 28)
            hl.addWidget(sb)
        parent.addLayout(hl)
        lw = ListWidget()
        lw.setMinimumHeight(100)
        lw.setSelectionMode(
            ListWidget.SelectionMode.MultiSelection
            if checkable
            else ListWidget.SelectionMode.NoSelection
        )
        parent.addWidget(lw)
        if checkable:
            sb.clicked.connect(lambda: self._ta(lw))
        return lw

    @staticmethod
    def _ta(lw):
        any_u = False
        for i in range(lw.count()):
            item = lw.item(i)
            assert item is not None  # stub Optional 收窄
            if item.checkState() != Qt.CheckState.Checked:
                any_u = True
                break
        st = Qt.CheckState.Checked if any_u else Qt.CheckState.Unchecked
        for i in range(lw.count()):
            item = lw.item(i)
            assert item is not None  # stub Optional 收窄
            item.setCheckState(st)

    @staticmethod
    def _package_from_payload(payload) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            return str(payload.get("package_name") or payload.get("package") or "").strip()
        return ""

    def activate(self, payload=None) -> None:
        """激活详情页；仅在首次打开某个包时执行数据加载。"""

        if self._dispose_requested:
            return
        self._active = True
        package_name = self._package_from_payload(payload) or self.package_name
        if not package_name:
            self._set_load_state("error", "请先选择一个应用。")
            return
        package_changed = package_name != self.package_name
        if package_changed:
            self._cancel_current_generation()
            self.package_name = package_name
            self._loaded_package = ""
            self.detail_text.clear()
            self.declared_list.clear()
            self.requested_list.clear()
            self.runtime_list.clear()
        self.package_label.setText(package_name)
        if self._loaded_package != package_name:
            if self._running_workers():
                self._pending_reload = True
            else:
                self._load_data()

    def deactivate(self, _reason: str = "navigation") -> None:
        """标记页面离开前台；进行中的短命令继续安全收尾。"""

        self._active = False

    def set_device_connected(self, connected: bool) -> None:
        """同步设备状态；离线时保留已显示详情并禁用新的 ADB 操作。"""

        connected = bool(connected and self.device_ip)
        changed = connected != self._device_connected
        self._device_connected = connected
        self.setProperty("deviceConnected", connected)
        self._sync_operation_controls()
        if changed:
            self.device_connected_changed.emit(connected)

    def _can_operate(self) -> bool:
        """详情查询和权限修改复用所属固定设备的选择资格。"""
        return bool(
            self.device_ip and self._device_selected and self._device_connected
            and not self._closing
        )

    def set_device_selected(self, selected: bool) -> None:
        """取消选择只封闭新命令，保留已显示的详情和现有任务归属。"""
        self._device_selected = bool(selected and self.device_ip)
        if not self._device_selected:
            self._pending_reload = False
        self._sync_operation_controls()

    def _sync_operation_controls(self) -> None:
        allowed = self._can_operate()
        self.grant_btn.setEnabled(allowed)
        self.revoke_btn.setEnabled(allowed)
        self.retry_btn.setEnabled(allowed)

    def retry_load(self) -> None:
        if self._dispose_requested or not self.package_name:
            return
        self._cancel_current_generation()
        if self._running_workers():
            self._pending_reload = True
        else:
            self._load_data()

    def _load_data(self):
        if (
            self._closing
            or not self.package_name
            or not self.device_ip
            or not self._can_operate()
        ):
            self._set_load_state("error", "请连接设备并选择应用后重试。")
            return False
        self._pending_reload = False
        self._load_generation += 1
        generation = self._load_generation
        self._pending_load_parts = {"details", "permissions"}
        self._last_load_error = ""
        self._set_load_state("loading", f"正在加载 {self.package_name}…")
        self._rw(
            "app_details",
            _generation=generation,
            _finished_part="details",
            package_name=self.package_name,
            app_details_loaded=lambda data: self._receive_load_part(
                generation, "details", self._od, data
            ),
        )
        self._rw(
            "permissions",
            _generation=generation,
            _finished_part="permissions",
            package_name=self.package_name,
            permissions_loaded=lambda declared, requested, runtime: self._receive_load_part(
                generation,
                "permissions",
                self._op,
                declared,
                requested,
                runtime,
            ),
        )
        return True

    def _rp(self):
        if self._closing:
            return
        self._rw(
            "permissions",
            package_name=self.package_name,
            permissions_loaded=self._op,
        )

    def _receive_load_part(self, generation, part, callback, *args) -> None:
        if generation != self._load_generation or self._closing:
            return
        self._pending_load_parts.discard(part)
        callback(*args)
        if not self._pending_load_parts and self.load_state != "error":
            self._loaded_package = self.package_name
            self._set_load_state("ready", f"已加载 {self.package_name}")

    def _on_load_part_finished(self, generation: int, part: str) -> None:
        if generation != self._load_generation or self._closing:
            return
        if part not in self._pending_load_parts:
            return
        self._pending_load_parts.discard(part)
        part_text = "权限" if part == "permissions" else "详情"
        message = self._last_load_error or f"无法加载 {self.package_name} 的{part_text}。"
        self._set_load_state("error", message)

    def _on_worker_log(self, generation: int, message: str) -> None:
        if generation != self._load_generation or self._closing:
            return
        self.log_message.emit(message)
        normalized = message.strip()
        if normalized.lower().startswith(("error", "failed")):
            self._last_load_error = normalized

    def _set_load_state(self, state: str, message: str) -> None:
        if state == self.load_state and not message:
            return
        self.load_state = state
        self.setProperty("loadState", state)
        is_error = state == "error"
        self.load_error_label.setText(message or "无法加载应用详情。")
        self.load_error_label.setVisible(is_error)
        self.retry_btn.setVisible(is_error)
        self.load_state_changed.emit(state, message)

    def _od(self, d):
        self.detail_text.clear()
        for k, v in d.items():
            self.detail_text.append(f"<b>{html.escape(str(k))}:</b> {html.escape(str(v))}")

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
        fill(self.runtime_list, runtime, lambda r: f"{r[0]} (已授权：{'是' if r[1] else '否'})")

    def _mp(self, action):
        if not self._can_operate():
            self.log_message.emit(
                "请在顶部设备栏勾选当前在线设备后修改权限。"
            )
            return
        rc = []
        for i in range(self.runtime_list.count()):
            item = self.runtime_list.item(i)
            assert item is not None  # stub Optional 收窄
            if item.checkState() == Qt.CheckState.Checked:
                rc.append(item.text().split(" (")[0])
        rq = []
        for i in range(self.requested_list.count()):
            item = self.requested_list.item(i)
            assert item is not None  # stub Optional 收窄
            if item.checkState() == Qt.CheckState.Checked:
                rq.append(item.text())
        sel = rc + rq
        if not sel:
            FluentMessageBox.warning(
                self,
                "未选择权限",
                "请先选择要授权或撤销的权限。",
            )
            return
        for perm in sel:
            self._rw(
                "modify_permission",
                package_name=self.package_name,
                permission=perm,
                action=action,
                operation_done=alive_callback(self, "_rp"),
            )

    def _rw(self, op, *, _generation=None, _finished_part=None, **kw):
        if not self._can_operate():
            return None
        generation = self._load_generation if _generation is None else int(_generation)
        signal_handlers = {}
        for signal_name in (
            "app_details_loaded",
            "permissions_loaded",
            "operation_done",
        ):
            handler = kw.pop(signal_name, None)
            if handler is not None:
                signal_handlers[signal_name] = handler
        w = AppManagerWorker(self.device_ip, op, **kw)
        w.setParent(self)
        for signal_name, handler in signal_handlers.items():
            def guarded_handler(*args, _handler=handler, _generation=generation):
                if _generation == self._load_generation and not self._closing:
                    _handler(*args)

            getattr(w, signal_name).connect(
                guarded_handler,
                Qt.ConnectionType.QueuedConnection,
            )
        w.log_message.connect(
            lambda message, value=generation: self._on_worker_log(value, message),
            Qt.ConnectionType.QueuedConnection,
        )
        if _finished_part is not None:
            w.finished.connect(
                lambda value=generation, part=str(_finished_part): self._on_load_part_finished(
                    value, part
                ),
                Qt.ConnectionType.QueuedConnection,
            )
        w.finished.connect(
            alive_callback(self, "_prune_worker", w), Qt.ConnectionType.QueuedConnection
        )
        self._workers.append(w)
        w.start()
        return w

    def _prune_worker(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
        if is_qobject_alive(worker) and hasattr(worker, "deleteLater"):
            worker.deleteLater()
        if (
            self._pending_reload
            and not self._closing
            and not self._running_workers()
        ):
            self._load_data()
        self._maybe_finish_dispose()

    def _cancel_current_generation(self) -> None:
        self._load_generation += 1
        self._pending_load_parts = set()
        self._pending_reload = False
        for worker in tuple(self._workers):
            if QThreadGroupShutdownTask._running(worker):
                worker.abort()

    def _running_workers(self):
        return [worker for worker in self._workers if QThreadGroupShutdownTask._running(worker)]

    def register_shutdown_tasks(self, supervisor, *, owner_id: str, task_prefix: str):
        """把详情页尚未完成的 worker 注册到统一退出监督器。"""

        workers = self._running_workers()
        if not workers:
            return ()
        task_id = f"{task_prefix}-details-workers"
        handle = QThreadGroupShutdownTask(workers)
        supervisor.register(
            task_id,
            owner_id=owner_id,
            kind="app_details_workers",
            request_stop=handle.request_stop,
            wait=handle.wait,
            is_running=handle.is_running,
        )
        self._shutdown_registered = True
        return (task_id,)

    def request_dispose(self, _reason: str = "user") -> bool:
        """请求释放页面；仍有 worker 时在全部结束后发出 ``dispose_ready``。"""

        if self._dispose_finalized:
            return True
        self._dispose_requested = True
        self._closing = True
        self._active = False
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
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
                QTimer.singleShot(0, alive_callback(self, "close"))

    def closeEvent(self, event):
        """直接关闭控件时也遵循会话资源释放屏障。"""

        if self.request_dispose("close"):
            super().closeEvent(event)
            return
        self._close_after_dispose = True
        self.hide()
        event.ignore()

__all__ = ["AppDetailsPage"]
