"""应用管理器详情对话框 — 展示单个应用的详情与权限管理。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs.app_manager_form import _apply_adaptive_text_heights
from gui.dialogs.lifecycle import (
    alive_callback,
    alive_forwarding_callback,
    is_qobject_alive,
)
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from models.app_manager_worker import AppManagerWorker


class AppDetailsDialog(QDialog):
    """展示单个应用详情与权限，并可对运行时权限执行授权/撤销。"""

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
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
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
            QMessageBox.warning(
                self,
                "No Selection",
                f"No permissions selected to {action}.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
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

    def _rw(self, op, **kw):
        if self._closing:
            return None
        w = AppManagerWorker(self.device_ip, op, **kw)
        w.setParent(self)
        for s in ["log_message", "app_details_loaded", "permissions_loaded", "operation_done"]:
            if s in kw:
                getattr(w, s).connect(kw[s], Qt.ConnectionType.QueuedConnection)
        owner = self.parent()
        if hasattr(owner, "log"):
            w.log_message.connect(
                alive_forwarding_callback(owner, "log"), Qt.ConnectionType.QueuedConnection
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

    def closeEvent(self, event):
        """中止详情 worker，并把等待操作移交后台，避免阻塞关闭事件。"""
        from gui.dialogs import app_manager as _app_manager

        self._closing = True
        _app_manager.safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        _app_manager.safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
        workers = self._workers
        self._workers = []
        for w in workers:
            w.abort()
            w.setParent(None)
        _app_manager.wait_for_threads_later(workers, 5000)
        super().closeEvent(event)
