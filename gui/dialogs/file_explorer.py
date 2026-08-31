"""提供设备文件浏览、传输、编辑和管理对话框。"""

import threading
import weakref

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QVBoxLayout,
)

from gui.dialogs.file_explorer_image import _ImageViewerDialog
from gui.dialogs.file_explorer_list import FileExplorerList
from gui.dialogs.file_explorer_ops import FileExplorerOps
from gui.dialogs.file_explorer_view import FileExplorerView
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    alive_callback,
    fit_secondary_window_to_owner_screen,
    is_qobject_alive,
    safe_disconnect,
)
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from gui.styles.typography import FontRole
from gui.widgets.responsive_layout import reflow_widgets
from models.file_explorer_worker import ADBWorker, TransferWorker
from services import file_explorer as explorer_service

__all__ = ["FileExplorerDialog", "_ImageViewerDialog"]


class FileExplorerDialog(QDialog):
    TYPE_COL = 0
    NAME_COL = 1
    SIZE_COL = 2
    MODIFIED_COL = 3

    TEXT_EXTS = {
        "txt",
        "log",
        "json",
        "xml",
        "html",
        "csv",
        "md",
        "ini",
        "conf",
        "prop",
        "sh",
        "bat",
        "py",
        "js",
        "css",
        "cpp",
        "h",
        "hpp",
        "c",
        "rc",
        "",
    }
    IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "bmp"}
    ARCHIVE_EXTS = {"zip", "gz", "tar", "tgz", "xz", "7z", "rar"}
    AUDIO_EXTS = {"mp3", "wav", "ogg", "m4a", "aac", "flac"}
    VIDEO_EXTS = {"mp4", "mkv", "webm", "mov", "avi"}
    _orphaned_workers = set()
    _orphaned_workers_lock = threading.Lock()

    def __init__(self, parent=None, device_ip: str = ""):
        super().__init__(parent, Qt.WindowType.Window)
        self._list_controller = FileExplorerList(self)
        self._view_controller = FileExplorerView(self)
        self._ops_controller = FileExplorerOps(self)
        self.device_ip = device_ip
        self.current_path = "/storage/emulated/0"
        self.history = []
        self.forward_stack = []
        self.clipboard = []
        self.copy_mode = False
        self.symlink_targets = {}
        self._workers = []
        self._worker_ui_bindings = {}
        self._worker_lifecycle_handlers = {}
        self._refresh_request_id = 0
        self._active_refresh = None
        self._closing = False
        self._sort_col = 0
        self._sort_order = Qt.SortOrder.AscendingOrder

        self.setWindowTitle(f"File Explorer - {device_ip}")
        self.setWindowIcon(get_themed_icon("folder-open.svg"))
        self.setMinimumSize(950, 620)
        self.resize(1000, 650)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._init_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)
        self._refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        # ── 页头卡片：标题、副标题与设备连接状态徽标 ─────────────────────
        # 视觉重设计：对话框内容顶部统一为卡片页头（面板底色+细边框+大圆角）。
        # 副标题保持 UI 字体角色并以 TEXT_SECONDARY 次级文字色维持视觉层级。
        self.header_card = QFrame()
        self.header_card.setObjectName("dialogHeaderCard")
        hl = QVBoxLayout(self.header_card)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.dialog_title = QLabel("File Explorer")
        self.dialog_title.setObjectName("dialogTitle")
        self.dialog_title.setProperty("fontRole", FontRole.TITLE.value)
        self.dialog_title.setFont(BaseStyles.font_for_role(FontRole.TITLE))
        self.status_badge = QLabel("No device")
        self.status_badge.setObjectName("dialogStatusBadge")
        self.status_badge.setProperty("fontRole", FontRole.UI.value)
        self.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.status_badge.setToolTip("Device availability for file operations")
        title_row.addWidget(self.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self.status_badge)
        self.dialog_subtitle = QLabel("Browse and manage device files")
        self.dialog_subtitle.setObjectName("dialogSubtitle")
        self.dialog_subtitle.setProperty("fontRole", FontRole.UI.value)
        self.dialog_subtitle.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.dialog_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self.dialog_subtitle)
        layout.addWidget(self.header_card)

        self._path_layout = QGridLayout()
        self.path_layout = self._path_layout
        self._path_layout.setSpacing(4)
        self._path_label = QLabel("Path:")
        self.path_field = QLineEdit(self.current_path)
        self._path_label.setBuddy(self.path_field)
        self.path_field.setAccessibleName("Remote path")
        self.path_field.returnPressed.connect(
            lambda: self._navigate(self.path_field.text().strip())
        )
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search...")
        self.search_field.setAccessibleName("File search")
        self.search_field.textChanged.connect(self._filter)
        layout.addLayout(self._path_layout)

        self._toolbar_layout = QGridLayout()
        self._toolbar_layout.setSpacing(3)
        self.back_btn = QPushButton()
        self.back_btn.setIcon(get_themed_icon("arrow-left.svg"))
        self.back_btn.setIconSize(QSize(14, 14))
        self.back_btn.setToolTip("Return to the previous folder")
        self.back_btn.setAccessibleName("Back")
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        self.fwd_btn = QPushButton()
        self.fwd_btn.setIcon(get_themed_icon("arrow-right.svg"))
        self.fwd_btn.setIconSize(QSize(14, 14))
        self.fwd_btn.setToolTip("Return to the next folder")
        self.fwd_btn.setAccessibleName("Forward")
        self.fwd_btn.clicked.connect(self._go_forward)
        self.fwd_btn.setEnabled(False)
        self.up_btn = QPushButton()
        self.up_btn.setIcon(get_themed_icon("arrow-up.svg"))
        self.up_btn.setIconSize(QSize(14, 14))
        self.up_btn.setToolTip("Open the parent folder")
        self.up_btn.setAccessibleName("Parent folder")
        self.up_btn.clicked.connect(self._go_parent)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Reload the current device folder")
        self.refresh_btn.setIcon(get_themed_icon("arrows-clockwise.svg"))
        self.refresh_btn.setIconSize(QSize(14, 14))
        self.refresh_btn.clicked.connect(self._refresh)
        self.mkdir_btn = QPushButton("New Folder")
        self.mkdir_btn.setToolTip("Create a folder in the current location")
        self.mkdir_btn.setIcon(get_themed_icon("folder-plus.svg"))
        self.mkdir_btn.setIconSize(QSize(14, 14))
        self.mkdir_btn.clicked.connect(self._mkdir)
        self.touch_btn = QPushButton("New File")
        self.touch_btn.setToolTip("Create an empty file in the current location")
        self.touch_btn.setIcon(get_themed_icon("file-plus.svg"))
        self.touch_btn.setIconSize(QSize(14, 14))
        self.touch_btn.clicked.connect(self._touch)
        self.pull_btn = QPushButton("Pull")
        self.pull_btn.setToolTip("Copy selected items to the computer")
        self.pull_btn.setIcon(get_themed_icon("download-simple.svg"))
        self.pull_btn.setIconSize(QSize(14, 14))
        self.pull_btn.clicked.connect(self._pull_selected)
        self.push_btn = QPushButton("Push")
        self.push_btn.setToolTip("Copy a local file to the current device folder")
        self.push_btn.setIcon(get_themed_icon("upload-simple.svg"))
        self.push_btn.setIconSize(QSize(14, 14))
        self.push_btn.clicked.connect(self._push_file)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Remove the selected device items")
        self.delete_btn.setIcon(get_themed_icon("trash.svg"))
        self.delete_btn.setIconSize(QSize(14, 14))
        self.delete_btn.clicked.connect(self._delete_selected)
        self._toolbar_buttons = (
            self.back_btn,
            self.fwd_btn,
            self.up_btn,
            self.refresh_btn,
            self.mkdir_btn,
            self.touch_btn,
            self.pull_btn,
            self.push_btn,
            self.delete_btn,
        )
        self.root_cb = QCheckBox("Root")
        self.root_cb.setToolTip("Use root access (su)")
        self.root_cb.setAccessibleName("Use root access")
        layout.addLayout(self._toolbar_layout)
        self._reflow_top_controls()

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Type", "Name", "Size", "Modified"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            self.NAME_COL, QHeaderView.ResizeMode.Stretch
        )
        for i in (self.TYPE_COL, self.SIZE_COL, self.MODIFIED_COL):
            self.table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.Interactive
            )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.table.setColumnWidth(self.TYPE_COL, 92)
        self.table.setColumnWidth(self.SIZE_COL, 92)
        self.table.setColumnWidth(self.MODIFIED_COL, 140)
        layout.addWidget(self.table, 1)

        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        layout.addWidget(self.status_bar)

    def _reflow_top_controls(self) -> None:
        """在窄窗口中把路径、搜索和工具按钮重排到多行。"""

        if not hasattr(self, "_path_layout"):
            return
        available_width = max(1, self.contentsRect().width() - 12)
        for widget in (self._path_label, self.path_field, self.search_field):
            self._path_layout.removeWidget(widget)
        if available_width < 720:
            self._path_layout.addWidget(self._path_label, 0, 0)
            self._path_layout.addWidget(self.path_field, 0, 1)
            self._path_layout.addWidget(self.search_field, 1, 0, 1, 2)
            self._path_layout.setColumnStretch(1, 1)
        else:
            self._path_layout.addWidget(self._path_label, 0, 0)
            self._path_layout.addWidget(self.path_field, 0, 1)
            self._path_layout.addWidget(self.search_field, 0, 2)
            self._path_layout.setColumnStretch(1, 1)

        columns = 9 if available_width >= 900 else 5 if available_width >= 560 else 3
        self._toolbar_layout.removeWidget(self.root_cb)
        reflow_widgets(self._toolbar_layout, self._toolbar_buttons, columns)
        remainder = len(self._toolbar_buttons) % columns
        root_row = len(self._toolbar_buttons) // columns
        if remainder:
            self._toolbar_layout.addWidget(self.root_cb, root_row, remainder)
        else:
            self._toolbar_layout.addWidget(self.root_cb, root_row, 0, 1, columns)
        for column in range(columns):
            self._toolbar_layout.setColumnStretch(column, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_top_controls()

    def _create_context_menu(self) -> QMenu:
        """创建跟随当前主题且由窗口托管的上下文菜单。"""

        menu = QMenu(self)
        menu.setStyleSheet(BaseStyles.MENU_STYLE())
        return menu

    # ── 主题 ────────────────────────────────────────────────────────────

    def _apply_theme(self, _value=None):
        apply_dark_title_bar(self)
        bs = BaseStyles
        ui_font = bs.font_for_role(FontRole.UI)
        mono_font = bs.font_for_role(FontRole.MONO)
        self.setStyleSheet(bs.PANEL_BASE_STYLE())
        self.setFont(ui_font)
        bg = bs.color("INPUT_BG")
        fg = bs.color("TEXT_PRIMARY")
        border = bs.color("BORDER_COLOR")
        sel_bg = bs.color("SELECTION_BG")
        sel_fg = bs.color("SELECTION_TEXT")
        btn_bg = bs.color("BUTTON_BG")
        # 视觉重设计：页头卡片样式随主题重建，徽标按 device_ip 刷新。
        if hasattr(self, "header_card"):
            self.header_card.setStyleSheet(
                f"QFrame#dialogHeaderCard {{ background-color: {bs.color('PANEL_BG')};"
                f" border: 1px solid {bs.color('BORDER_COLOR')};"
                f" border-radius: {bs.RADIUS_LG}px; }}"
            )
            self.dialog_title.setFont(bs.font_for_role(FontRole.TITLE))
            self.dialog_title.setStyleSheet(f"color: {bs.color('TITLE_COLOR')};")
            self.dialog_subtitle.setFont(bs.font_for_role(FontRole.UI))
            self.dialog_subtitle.setStyleSheet(f"color: {bs.color('TEXT_SECONDARY')};")
            self.status_badge.setFont(bs.font_for_role(FontRole.UI))
            has_device = bool(self.device_ip)
            self.status_badge.setText("Ready" if has_device else "No device")
            background = (
                bs.color("LOG_SUCCESS") if has_device else bs.color("TEXT_SECONDARY")
            )
            self.status_badge.setStyleSheet(
                f"QLabel#dialogStatusBadge {{ background-color: {background};"
                f" color: {bs.color('PANEL_BG')};"
                f" border-radius: 7px; padding: 1px 8px; }}"
            )
        self.table.setStyleSheet(f"""
            QTableWidget {{ background-color: {bg}; color: {fg};
                border: 1px solid {border}; border-radius: {bs.RADIUS_MD}px;
                gridline-color: {border}; }}
            QTableWidget::item:selected {{ background-color: {sel_bg}; color: {sel_fg}; }}
            QHeaderView::section {{ background-color: {btn_bg}; color: {fg};
                padding: 4px; border: 1px solid {border}; }}
        """)
        self.status_bar.setStyleSheet(bs.STATUS_BAR_STYLE())
        field_style = (
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            f"border-radius: {bs.RADIUS_SM}px; padding: 2px 4px;"
        )
        self.path_field.setStyleSheet(field_style)
        self.path_field.setFont(mono_font)
        self.search_field.setStyleSheet(field_style)

    # ── ADB 辅助方法 ────────────────────────────────────────────────────

    def _connect_worker_ui(self, worker, signal, handler, *, guard_objects=()):
        """连接 worker 的界面回调，并在窗口或关联子窗口销毁后拒绝晚到信号。"""

        dialog_ref = weakref.ref(self)
        guard_refs = tuple(weakref.ref(obj) for obj in guard_objects if obj is not None)

        def guarded(*args):
            dialog = dialog_ref()
            if dialog is None or getattr(dialog, "_closing", False) or not is_qobject_alive(dialog):
                return
            if any(not is_qobject_alive(ref()) for ref in guard_refs):
                return
            handler(*args)

        signal.connect(guarded, Qt.ConnectionType.QueuedConnection)
        self._worker_ui_bindings.setdefault(worker, []).append((signal, guarded))
        return guarded

    def _disconnect_worker_ui(self, worker) -> None:
        """断开指定 worker 的全部界面回调。"""

        for signal, handler in self._worker_ui_bindings.pop(worker, ()):
            safe_disconnect(signal, handler)

    def _prune_worker(self, worker) -> None:
        if self._closing:
            return
        self._disconnect_worker_ui(worker)
        lifecycle_handler = self._worker_lifecycle_handlers.pop(worker, None)
        if lifecycle_handler is not None:
            safe_disconnect(worker.finished, lifecycle_handler)
        if worker in self._workers:
            self._workers.remove(worker)
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    @classmethod
    def _retain_workers_until_stopped(cls, workers) -> None:
        """解除窗口所有权后持续持有线程，避免运行中的 QThread 被销毁。"""

        retained = []
        for worker in workers:
            try:
                worker.setParent(None)
            except RuntimeError:
                continue
            if QThreadGroupShutdownTask._running(worker):
                retained.append(worker)
            else:
                worker.deleteLater()
        if not retained:
            return

        with cls._orphaned_workers_lock:
            cls._orphaned_workers.update(retained)

        def wait_for_workers():
            for worker in retained:
                try:
                    worker.wait()
                except RuntimeError:
                    pass
                finally:
                    with cls._orphaned_workers_lock:
                        cls._orphaned_workers.discard(worker)
                    try:
                        worker.deleteLater()
                    except RuntimeError:
                        pass

        threading.Thread(
            target=wait_for_workers,
            name="adblab-file-explorer-worker-wait",
            daemon=True,
        ).start()

    def _run_adb(self, *args, timeout: int = 30):
        worker = ADBWorker(self.device_ip, list(args), timeout=timeout)
        lifecycle_handler = alive_callback(self, "_prune_worker", worker)
        worker.finished.connect(lifecycle_handler, Qt.ConnectionType.QueuedConnection)
        self._worker_lifecycle_handlers[worker] = lifecycle_handler
        self._workers.append(worker)
        worker.setParent(self)
        return worker

    def _run_transfer(self, *args):
        worker = TransferWorker(self.device_ip, list(args))
        lifecycle_handler = alive_callback(self, "_prune_worker", worker)
        worker.finished.connect(lifecycle_handler, Qt.ConnectionType.QueuedConnection)
        self._worker_lifecycle_handlers[worker] = lifecycle_handler
        self._workers.append(worker)
        worker.setParent(self)
        return worker

    # ── 列表控制器委托 wrapper ──────────────────────────────────────────

    def _root(self, cmd: str) -> str:
        return self._list_controller._root(cmd)

    def _safe_name(self, name: str) -> bool:
        return self._list_controller._safe_name(name)

    def _dpath(self, *parts) -> str:
        return self._list_controller._dpath(*parts)

    def _navigate(self, path: str, push: bool = True):
        return self._list_controller._navigate(path, push)

    def _go_back(self):
        return self._list_controller._go_back()

    def _go_forward(self):
        return self._list_controller._go_forward()

    def _go_parent(self):
        return self._list_controller._go_parent()

    def _refresh(self):
        return self._list_controller._refresh()

    def _on_ls_result(
        self,
        output,
        error,
        *,
        request_id: int | None = None,
        requested_path: str | None = None,
    ):
        controller = getattr(self, "_list_controller", None)
        if controller is None:
            controller = FileExplorerList(self)
        return controller._on_ls_result(
            output,
            error,
            request_id=request_id,
            requested_path=requested_path,
        )

    def _set_file_row(self, row: int, name: str, file_type: str, size: str, modified: str):
        controller = getattr(self, "_list_controller", None)
        if controller is None:
            controller = FileExplorerList(self)
        return controller._set_file_row(row, name, file_type, size, modified)

    def _file_name_at(self, row: int) -> str:
        return self._list_controller._file_name_at(row)

    def _file_type_at(self, row: int) -> str:
        return self._list_controller._file_type_at(row)

    def _file_type_icon(self, name: str, file_type: str):
        return self._list_controller._file_type_icon(name, file_type)

    def _file_type_icon_name(self, name: str, file_type: str) -> str:
        return self._list_controller._file_type_icon_name(name, file_type)

    def _parse_ls(self, line: str) -> dict | None:
        return self._list_controller._parse_ls(line)

    def _ext(self, name: str) -> str:
        return self._list_controller._ext(name)

    def _safe_int(self, s: str) -> int:
        return self._list_controller._safe_int(s)

    def _fmt_size(self, s: str) -> str:
        return self._list_controller._fmt_size(s)

    def _on_double_click(self, row, col):
        return self._list_controller._on_double_click(row, col)

    def _filter(self, text):
        return self._list_controller._filter(text)

    def _header_clicked(self, col):
        return self._list_controller._header_clicked(col)

    # ── 预览查看控制器委托 wrapper ──────────────────────────────────────

    def _view_or_pull(self, name: str):
        return self._view_controller._view_or_pull(name)

    def _view_file(self, name: str, is_image: bool = False):
        return self._view_controller._view_file(name, is_image)

    def _view_image(self, name: str, full_path: str):
        return self._view_controller._view_image(name, full_path)

    def _show_image(self, dlg, name, tmp_path, dev_tmp):
        return self._view_controller._show_image(dlg, name, tmp_path, dev_tmp)

    def _show_text_viewer(self, name: str, content: str, error: bool, full_path: str):
        return self._view_controller._show_text_viewer(name, content, error, full_path)

    @staticmethod
    def _apply_text_dialog_fonts(dialog, editor, role: FontRole) -> None:
        return FileExplorerView._apply_text_dialog_fonts(dialog, editor, role)

    @staticmethod
    def _bind_dialog_font_refresh(dialog, refresh) -> None:
        return FileExplorerView._bind_dialog_font_refresh(dialog, refresh)

    # ── 文件操作控制器委托 wrapper ──────────────────────────────────────

    @staticmethod
    def _global_save_dir() -> str:
        return FileExplorerOps._global_save_dir()

    def _save_as(self, name, content):
        return self._ops_controller._save_as(name, content)

    def _save_to_device(self, name, content, full_path):
        return self._ops_controller._save_to_device(name, content, full_path)

    def _on_save_result(self, output, error, name):
        return self._ops_controller._on_save_result(output, error, name)

    def _pull_file(self, name: str):
        return self._ops_controller._pull_file(name)

    def _finish_root_pull(self, o, e, name, dev_tmp, save_path):
        return self._ops_controller._finish_root_pull(o, e, name, dev_tmp, save_path)

    def _pull_selected(self):
        return self._ops_controller._pull_selected()

    def _push_file(self):
        return self._ops_controller._push_file()

    def _on_transfer_done(self, o, e, msg):
        controller = getattr(self, "_ops_controller", None)
        if controller is None:
            controller = FileExplorerOps(self)
        return controller._on_transfer_done(o, e, msg)

    def _on_file_op_done(self, output: str, error: bool, success_msg: str):
        controller = getattr(self, "_ops_controller", None)
        if controller is None:
            controller = FileExplorerOps(self)
        return controller._on_file_op_done(output, error, success_msg)

    def _mkdir(self):
        return self._ops_controller._mkdir()

    def _touch(self):
        return self._ops_controller._touch()

    def _rename_item(self, name: str):
        return self._ops_controller._rename_item(name)

    def _delete_item(self, name: str):
        return self._ops_controller._delete_item(name)

    def _request_delete(self, names: str | list[str]):
        return self._ops_controller._request_delete(names)

    def _delete_selected(self):
        return self._ops_controller._delete_selected()

    def _copy_items(self, copy_mode: bool):
        return self._ops_controller._copy_items(copy_mode)

    def _paste_items(self):
        return self._ops_controller._paste_items()

    def _show_chmod(self, name: str, is_dir: bool):
        return self._ops_controller._show_chmod(name, is_dir)

    # ── 右键菜单 ────────────────────────────────────────────────────────

    def _context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        name = self._file_name_at(row)
        if name == "..":
            return
        is_dir = self._file_type_at(row) == "Folder"
        menu = self._create_context_menu()
        if is_dir:
            menu.addAction("Open", lambda: self._on_double_click(row, 0))
        else:
            is_image = self._ext(name).lower() in self.IMAGE_EXTS
            menu.addAction("View", lambda: self._view_file(name, is_image))
        menu.addSeparator()
        menu.addAction("Pull", lambda: self._pull_file(name))
        if not is_dir:
            menu.addAction("Push Here", self._push_file)
        if not is_dir and name.endswith(".apk"):
            menu.addAction("Install APK", lambda: self._install_apk(name))
        if not is_dir and name.endswith(".sh"):
            menu.addAction("Execute Script", lambda: self._exec_script(name))
        menu.addAction("Permissions", lambda: self._show_chmod(name, is_dir))
        menu.addSeparator()
        menu.addAction("Rename", lambda: self._rename_item(name))
        menu.addAction("Delete", lambda: self._request_delete(name))
        menu.addSeparator()
        menu.addAction("Copy", lambda: self._copy_items(True))
        menu.addAction("Cut", lambda: self._copy_items(False))
        if self.clipboard:
            menu.addAction("Paste", self._paste_items)
        menu.addSeparator()
        menu.addAction("Properties", lambda: self._show_props(name, is_dir))
        menu.exec(self.table.mapToGlobal(pos))

    def _install_apk(self, name: str):
        full = self._dpath(self.current_path, name)
        cmd = self._root(explorer_service.install_apk_command(full))
        w = self._run_adb("shell", cmd)
        self._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e: self.status_bar.showMessage(
                f"APK {name} installed" if not e else f"APK install failed: {o}"
            ),
        )
        w.start()

    def _exec_script(self, name: str):
        full = self._dpath(self.current_path, name)
        cmd = explorer_service.script_command(full, self.root_cb.isChecked())
        w = self._run_adb("shell", self._root(cmd) if self.root_cb.isChecked() else cmd)
        self._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e: self._show_script_output(name, o, e),
        )
        w.start()

    def _show_script_output(self, name, output, error):
        dlg = QDialog(self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.setWindowTitle(f"Output: {name}")
        dlg.setMinimumSize(700, 400)
        dlg.setModal(False)
        lo = QVBoxLayout(dlg)
        v = QPlainTextEdit()
        v.setReadOnly(True)
        v.setPlainText(output)
        lo.addWidget(v)
        cb = QPushButton("Close")
        cb.setToolTip("Close the script output window")
        cb.setIcon(get_themed_icon("x.svg"))
        cb.setIconSize(QSize(14, 14))
        cb.clicked.connect(dlg.accept)
        lo.addWidget(cb)
        self._bind_dialog_font_refresh(
            dlg,
            lambda: self._apply_text_dialog_fonts(dlg, v, FontRole.LOG),
        )
        fit_secondary_window_to_owner_screen(dlg, self)
        dlg.show()

    def _show_props(self, name: str, is_dir: bool):
        full = self._dpath(self.current_path, name)
        if is_dir:
            w = self._run_adb("shell", explorer_service.folder_size_command(full))
            self._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e: self._show_props_done(
                    name,
                    full,
                    "Folder",
                    (o.strip() if e else (o.strip().split()[0] if o.strip() else "?")),
                    e,
                ),
            )
            w.start()
        else:
            w = self._run_adb("shell", explorer_service.ls_command(full))
            self._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e: self._show_props_file(name, full, o, e),
            )
            w.start()

    def _show_props_file(self, name, full, output, error):
        if error:
            QMessageBox.critical(
                self,
                f"Properties Error: {name}",
                output or "Unable to read file properties",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            self.status_bar.showMessage(f"Failed to read properties for {name}")
            return
        entry = self._parse_ls(output.splitlines()[0] if output.strip() else "")
        if entry:
            info = (
                f"Name: {name}\nType: {self._ext(name)}\n"
                f"Size: {self._fmt_size(entry['size'])}\nPath: {full}\n"
                f"Permissions: {entry['perms']}\n"
                f"Owner: {entry['owner']}:{entry['group']}\n"
                f"Modified: {entry['modified']}"
            )
        else:
            info = f"Name: {name}\nPath: {full}"
        QMessageBox.information(self, f"Properties: {name}", info)

    def _show_props_done(self, name, full, ftype, size, error):
        if error:
            QMessageBox.critical(
                self,
                f"Properties Error: {name}",
                size or "Unable to read folder properties",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            self.status_bar.showMessage(f"Failed to read properties for {name}")
            return
        info = f"Name: {name}\nType: {ftype}\nSize: {size}\nPath: {full}"
        QMessageBox.information(self, f"Properties: {name}", info)

    def register_shutdown_tasks(self, supervisor, *, owner_id: str, task_prefix: str):
        """将仍在运行的文件 worker 作为一组资源注册到监督器。"""
        workers = [worker for worker in self._workers if QThreadGroupShutdownTask._running(worker)]
        if not workers:
            return ()
        handle = QThreadGroupShutdownTask(workers)
        supervisor.register(
            f"{task_prefix}-workers",
            owner_id=owner_id,
            kind="file_explorer_workers",
            request_stop=handle.request_stop,
            wait=handle.wait,
            is_running=handle.is_running,
        )
        self._shutdown_registered = True
        return (f"{task_prefix}-workers",)

    # ── 资源清理 ────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """先隔离全部界面回调，再中止并持续持有尚未退出的 worker。"""
        if self._closing:
            super().closeEvent(event)
            return
        self._closing = True
        self._active_refresh = None
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)
        workers = list(
            dict.fromkeys(
                (
                    *self._workers,
                    *self._worker_ui_bindings,
                    *self._worker_lifecycle_handlers,
                )
            )
        )
        self._workers = []
        for worker in workers:
            self._disconnect_worker_ui(worker)
            lifecycle_handler = self._worker_lifecycle_handlers.pop(worker, None)
            if lifecycle_handler is not None:
                safe_disconnect(worker.finished, lifecycle_handler)
            if QThreadGroupShutdownTask._running(worker):
                try:
                    worker.abort()
                except RuntimeError:
                    pass
        self._retain_workers_until_stopped(workers)
        super().closeEvent(event)
