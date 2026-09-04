"""提供设备文件浏览、传输、编辑和管理页。"""

import weakref

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    InfoBadge,
    InfoLevel,
    LineEdit,
    PlainTextEdit,
    PushButton,
    RoundMenu,
    TableWidget,
)

from gui.dialogs.file_explorer_image import FileExplorerImagePreview
from gui.dialogs.file_explorer_list import FileExplorerList
from gui.dialogs.file_explorer_ops import FileExplorerOps
from gui.dialogs.file_explorer_view import FileExplorerView
from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.dialogs.lifecycle import (
    QThreadGroupShutdownTask,
    alive_callback,
    is_qobject_alive,
    safe_disconnect,
)
from gui.styles import BaseStyles
from gui.styles.fluent import add_menu_action, apply_label_role
from gui.styles.icon_loader import get_themed_icon
from gui.styles.typography import FontRole
from gui.widgets.responsive_layout import reflow_widgets
from models.file_explorer_worker import ADBWorker, TransferWorker
from services import file_explorer as explorer_service

__all__ = ["FileExplorerPage"]


class FileExplorerPage(QWidget):
    """按设备持有状态的页内文件浏览器会话。"""

    dispose_ready = Signal()

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
    def __init__(self, parent=None, device_ip: str = ""):
        super().__init__(parent)
        self._list_controller = FileExplorerList(self)
        self._view_controller = FileExplorerView(self)
        self._ops_controller = FileExplorerOps(self)
        self.device_ip = device_ip
        self._device_connected = bool(device_ip)
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
        self._active_refresh_worker = None
        self._pending_navigation = None
        self._directory_loading = False
        self._closing = False
        self._disposing = False
        self._disposed = False
        self._close_when_disposed = False
        self._activated_once = False
        self._loaded_once = False
        self._active = False
        self._shutdown_registered = False
        self._preview_active = False
        self._preview_request_id = 0
        self._preview_full_path = ""
        self._preview_name = ""
        self._sort_col = 0
        self._sort_order = Qt.SortOrder.AscendingOrder

        self.setWindowTitle(f"File Explorer - {device_ip}")
        self.setWindowIcon(get_themed_icon("folder-open.svg"))
        self.setObjectName("fileExplorerPage")
        self.setProperty("feature", "file_explorer")
        self.setProperty("deviceConnected", self._device_connected)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._init_ui()
        self._sync_directory_controls()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        BaseStyles.fonts_changed.connect(self._apply_theme)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        # ── 页头卡片：标题、副标题与设备连接状态徽标 ─────────────────────
        # 页面内容顶部统一为 Fluent CardWidget 卡片页头。
        # 副标题保持 UI 字体角色并以 TEXT_SECONDARY 次级文字色维持视觉层级。
        self.header_card = CardWidget()
        self.header_card.setObjectName("dialogHeaderCard")
        self.header_card.setBorderRadius(BaseStyles.RADIUS_LG)
        hl = QVBoxLayout(self.header_card)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.dialog_title = apply_label_role(
            BodyLabel("File Explorer"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self.dialog_title.setObjectName("dialogTitle")
        self.status_badge = InfoBadge.info("No device", self.header_card)
        self.status_badge.setProperty("fontRole", FontRole.UI.value)
        self.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.status_badge.setToolTip("Device availability for file operations")
        title_row.addWidget(self.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self.status_badge)
        self.dialog_subtitle = apply_label_role(
            BodyLabel("Browse and manage device files"),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        self.dialog_subtitle.setObjectName("dialogSubtitle")
        self.dialog_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self.dialog_subtitle)
        layout.addWidget(self.header_card)

        self._path_layout = QGridLayout()
        self._path_layout.setSpacing(4)
        self._path_label = apply_label_role(BodyLabel("Path:"), FontRole.UI)
        self.path_field = LineEdit()
        self.path_field.setText(self.current_path)
        self._path_label.setBuddy(self.path_field)
        self.path_field.setAccessibleName("Remote path")
        self.path_field.returnPressed.connect(
            lambda: self._navigate(self.path_field.text().strip())
        )
        self.search_field = LineEdit()
        self.search_field.setPlaceholderText("Search...")
        self.search_field.setAccessibleName("File search")
        self.search_field.textChanged.connect(self._filter)
        layout.addLayout(self._path_layout)

        self._toolbar_layout = QGridLayout()
        self._toolbar_layout.setSpacing(3)
        self.back_btn = PushButton()
        self.back_btn.setIcon(get_themed_icon("arrow-left.svg"))
        self.back_btn.setIconSize(QSize(14, 14))
        self.back_btn.setToolTip("Return to the previous folder")
        self.back_btn.setAccessibleName("Back")
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        self.fwd_btn = PushButton()
        self.fwd_btn.setIcon(get_themed_icon("arrow-right.svg"))
        self.fwd_btn.setIconSize(QSize(14, 14))
        self.fwd_btn.setToolTip("Return to the next folder")
        self.fwd_btn.setAccessibleName("Forward")
        self.fwd_btn.clicked.connect(self._go_forward)
        self.fwd_btn.setEnabled(False)
        self.up_btn = PushButton()
        self.up_btn.setIcon(get_themed_icon("arrow-up.svg"))
        self.up_btn.setIconSize(QSize(14, 14))
        self.up_btn.setToolTip("Open the parent folder")
        self.up_btn.setAccessibleName("Parent folder")
        self.up_btn.clicked.connect(self._go_parent)
        self.refresh_btn = PushButton()
        self.refresh_btn.setText("Refresh")
        self.refresh_btn.setToolTip("Reload the current device folder")
        self.refresh_btn.setIcon(get_themed_icon("arrows-clockwise.svg"))
        self.refresh_btn.setIconSize(QSize(14, 14))
        self.refresh_btn.clicked.connect(self._refresh)
        self.mkdir_btn = PushButton()
        self.mkdir_btn.setText("New Folder")
        self.mkdir_btn.setToolTip("Create a folder in the current location")
        self.mkdir_btn.setIcon(get_themed_icon("folder-plus.svg"))
        self.mkdir_btn.setIconSize(QSize(14, 14))
        self.mkdir_btn.clicked.connect(self._mkdir)
        self.touch_btn = PushButton()
        self.touch_btn.setText("New File")
        self.touch_btn.setToolTip("Create an empty file in the current location")
        self.touch_btn.setIcon(get_themed_icon("file-plus.svg"))
        self.touch_btn.setIconSize(QSize(14, 14))
        self.touch_btn.clicked.connect(self._touch)
        self.pull_btn = PushButton()
        self.pull_btn.setText("Pull")
        self.pull_btn.setToolTip("Copy selected items to the computer")
        self.pull_btn.setIcon(get_themed_icon("download-simple.svg"))
        self.pull_btn.setIconSize(QSize(14, 14))
        self.pull_btn.clicked.connect(self._pull_selected)
        self.push_btn = PushButton()
        self.push_btn.setText("Push")
        self.push_btn.setToolTip("Copy a local file to the current device folder")
        self.push_btn.setIcon(get_themed_icon("upload-simple.svg"))
        self.push_btn.setIconSize(QSize(14, 14))
        self.push_btn.clicked.connect(self._push_file)
        self.delete_btn = PushButton()
        self.delete_btn.setText("Delete")
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
        self.root_cb = CheckBox()
        self.root_cb.setText("Root")
        self.root_cb.setToolTip("Use root access (su)")
        self.root_cb.setAccessibleName("Use root access")
        layout.addLayout(self._toolbar_layout)
        self._reflow_top_controls()

        self.browser_panel = QWidget(self)
        self.browser_panel.setObjectName("fileExplorerBrowserPanel")
        browser_layout = QVBoxLayout(self.browser_panel)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(4)

        self.table = TableWidget(self.browser_panel)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
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
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.table.setColumnWidth(self.TYPE_COL, 92)
        self.table.setColumnWidth(self.SIZE_COL, 92)
        self.table.setColumnWidth(self.MODIFIED_COL, 140)
        browser_layout.addWidget(self.table, 1)

        self.status_bar = apply_label_role(
            CaptionLabel("Ready"), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self.status_bar.setAccessibleName("File explorer status")
        browser_layout.addWidget(self.status_bar)

        self.preview_panel = self._build_preview_panel()
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.setObjectName("fileExplorerContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.browser_panel)
        self.content_splitter.addWidget(self.preview_panel)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([620, 380])
        layout.addWidget(self.content_splitter, 1)
        self._sync_preview_layout()

    def _build_preview_panel(self) -> CardWidget:
        """构建可在宽屏侧栏和窄屏子页之间切换的预览栈。"""

        panel = CardWidget(self)
        panel.setObjectName("fileExplorerPreviewPanel")
        panel.setBorderRadius(BaseStyles.RADIUS_LG)
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 10)
        panel_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.preview_back_btn = PushButton(panel)
        self.preview_back_btn.setIcon(get_themed_icon("arrow-left.svg"))
        self.preview_back_btn.setToolTip("Back to file list")
        self.preview_back_btn.setAccessibleName("Back to file list")
        self.preview_back_btn.clicked.connect(self._close_preview)
        header.addWidget(self.preview_back_btn)
        self.preview_title = apply_label_role(
            BodyLabel("Preview"), FontRole.UI, color_key="TITLE_COLOR"
        )
        self.preview_title.setWordWrap(True)
        self.preview_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.addWidget(self.preview_title, 1)
        self.preview_close_btn = PushButton(panel)
        self.preview_close_btn.setIcon(get_themed_icon("x.svg"))
        self.preview_close_btn.setToolTip("Close preview")
        self.preview_close_btn.setAccessibleName("Close preview")
        self.preview_close_btn.clicked.connect(self._close_preview)
        header.addWidget(self.preview_close_btn)
        panel_layout.addLayout(header)

        self.preview_stack = QStackedWidget(panel)
        self.preview_stack.setObjectName("fileExplorerPreviewStack")

        self.preview_empty_page = QWidget(self.preview_stack)
        empty_layout = QVBoxLayout(self.preview_empty_page)
        self.preview_empty_label = apply_label_role(
            BodyLabel("Select a text file, image, or script output to preview it here."),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        self.preview_empty_label.setWordWrap(True)
        self.preview_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.preview_empty_label)
        empty_layout.addStretch(1)
        self.preview_stack.addWidget(self.preview_empty_page)

        self.preview_loading_page = QWidget(self.preview_stack)
        loading_layout = QVBoxLayout(self.preview_loading_page)
        self.preview_loading_label = apply_label_role(
            BodyLabel("Loading preview…"), FontRole.UI, color_key="TEXT_SECONDARY"
        )
        self.preview_loading_label.setWordWrap(True)
        self.preview_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addStretch(1)
        loading_layout.addWidget(self.preview_loading_label)
        loading_layout.addStretch(1)
        self.preview_stack.addWidget(self.preview_loading_page)

        self.preview_text_page = QWidget(self.preview_stack)
        text_layout = QVBoxLayout(self.preview_text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_text_edit = PlainTextEdit(self.preview_text_page)
        self.preview_text_edit.setAccessibleName("File text preview")
        text_layout.addWidget(self.preview_text_edit, 1)
        text_actions = QHBoxLayout()
        self.preview_save_as_btn = PushButton("Save As…", self.preview_text_page)
        self.preview_save_as_btn.setToolTip("Save the edited text to the computer")
        self.preview_save_as_btn.clicked.connect(self._save_preview_as)
        self.preview_save_device_btn = PushButton("Save to Device", self.preview_text_page)
        self.preview_save_device_btn.setToolTip("Write the edited text back to the device")
        self.preview_save_device_btn.clicked.connect(self._save_preview_to_device)
        text_actions.addWidget(self.preview_save_as_btn)
        text_actions.addWidget(self.preview_save_device_btn)
        text_actions.addStretch(1)
        text_layout.addLayout(text_actions)
        self.preview_stack.addWidget(self.preview_text_page)

        self.preview_image = FileExplorerImagePreview(self.preview_stack)
        self.preview_image.closeRequested.connect(self._close_preview)
        self.preview_image.image_close.hide()
        self.preview_stack.addWidget(self.preview_image)

        self.preview_output = PlainTextEdit(self.preview_stack)
        self.preview_output.setReadOnly(True)
        self.preview_output.setAccessibleName("Script output preview")
        self.preview_stack.addWidget(self.preview_output)

        panel_layout.addWidget(self.preview_stack, 1)
        self.preview_stack.setCurrentWidget(self.preview_empty_page)
        return panel

    def _show_preview_loading(self, title: str) -> None:
        self._preview_active = True
        self.preview_title.setText(title)
        self.preview_loading_label.setText(f"Loading {title}…")
        self.preview_stack.setCurrentWidget(self.preview_loading_page)
        self._sync_preview_layout()

    def _begin_preview_request(self, title: str) -> int:
        self._preview_request_id += 1
        self._show_preview_loading(title)
        return self._preview_request_id

    def _preview_request_is_current(self, request_id: int) -> bool:
        return not self._disposing and request_id == self._preview_request_id

    def _show_text_preview(
        self,
        name: str,
        content: str,
        full_path: str,
        *,
        editable: bool = True,
    ) -> None:
        self._preview_active = True
        self._preview_name = name
        self._preview_full_path = full_path
        self.preview_title.setText(name)
        self.preview_text_edit.setPlainText(content)
        self.preview_text_edit.setReadOnly(not editable)
        self.preview_save_as_btn.setEnabled(editable)
        self.preview_save_device_btn.setEnabled(editable)
        self.preview_stack.setCurrentWidget(self.preview_text_page)
        self._sync_preview_layout()
        if not editable:
            self.status_bar.setText("Preview truncated; editing is disabled")
        else:
            self.status_bar.setText(f"Previewing {name}")
        self.preview_text_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def _show_image_preview(self, name: str, pixmap) -> None:
        self._preview_active = True
        self._preview_name = name
        self._preview_full_path = ""
        self.preview_title.setText(name)
        self.preview_image.set_image_source(pixmap, name)
        self.preview_stack.setCurrentWidget(self.preview_image)
        self._sync_preview_layout()

    def _show_output_preview(self, name: str, output: str, *, error: bool = False) -> None:
        self._preview_active = True
        self._preview_name = name
        self._preview_full_path = ""
        self.preview_title.setText(f"Output: {name}")
        self.preview_output.setPlainText(output)
        self.preview_output.setProperty("previewError", bool(error))
        self.preview_stack.setCurrentWidget(self.preview_output)
        self.status_bar.setText(f"Script failed: {name}" if error else f"Script finished: {name}")
        self._sync_preview_layout()
        self.preview_output.setFocus(Qt.FocusReason.OtherFocusReason)

    def _show_preview_error(self, title: str, message: str) -> None:
        self._preview_active = True
        self.preview_title.setText(title)
        self.preview_output.setPlainText(message or "Unable to load preview")
        self.preview_output.setProperty("previewError", True)
        self.preview_stack.setCurrentWidget(self.preview_output)
        self.status_bar.setText(f"Preview failed: {title}")
        self._sync_preview_layout()

    def _close_preview(self) -> None:
        self._preview_request_id += 1
        self.preview_image.release_image_source()
        self._preview_active = False
        self._preview_name = ""
        self._preview_full_path = ""
        self.preview_title.setText("Preview")
        self.preview_stack.setCurrentWidget(self.preview_empty_page)
        self._sync_preview_layout()
        if self.browser_panel.isVisible():
            self.table.setFocus(Qt.FocusReason.OtherFocusReason)

    def _save_preview_as(self) -> None:
        if self._preview_name:
            self._save_as(self._preview_name, self.preview_text_edit.toPlainText())

    def _save_preview_to_device(self) -> None:
        if self._preview_name and self._preview_full_path:
            self._save_to_device(
                self._preview_name,
                self.preview_text_edit.toPlainText(),
                self._preview_full_path,
            )

    def _sync_preview_layout(self) -> None:
        """宽屏并排显示预览；窄屏把预览作为带返回按钮的内容子页。"""

        if not hasattr(self, "content_splitter"):
            return
        narrow = self.contentsRect().width() < 880
        self.preview_back_btn.setVisible(narrow)
        self.preview_close_btn.setVisible(not narrow)
        if narrow:
            self.browser_panel.setVisible(not self._preview_active)
            self.preview_panel.setVisible(self._preview_active)
            if self._preview_active:
                self.content_splitter.setSizes([0, max(1, self.content_splitter.width())])
            else:
                self.content_splitter.setSizes([max(1, self.content_splitter.width()), 0])
        else:
            self.browser_panel.show()
            self.preview_panel.show()
            if min(self.content_splitter.sizes() or [0]) <= 0:
                self.content_splitter.setSizes([620, 380])

    def _set_directory_loading(self, loading: bool) -> None:
        self._directory_loading = bool(loading)
        self._sync_directory_controls()

    def _sync_directory_controls(self) -> None:
        """根据设备和目录请求状态统一维护文件操作可用性。"""

        if not hasattr(self, "refresh_btn"):
            return
        available = self._device_connected and not self._disposing
        interactive = available and not self._directory_loading
        self.path_field.setEnabled(interactive)
        self.root_cb.setEnabled(interactive)
        self.up_btn.setEnabled(interactive)
        self.mkdir_btn.setEnabled(interactive)
        self.touch_btn.setEnabled(interactive)
        self.pull_btn.setEnabled(interactive)
        self.push_btn.setEnabled(interactive)
        self.delete_btn.setEnabled(interactive)
        self.back_btn.setEnabled(interactive and bool(self.history))
        self.fwd_btn.setEnabled(interactive and bool(self.forward_stack))
        self.refresh_btn.setEnabled(available)
        self.table.setEnabled(interactive)

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
        self._sync_preview_layout()

    def _create_context_menu(self) -> RoundMenu:
        """创建跟随 qfluentwidgets 主题的上下文菜单。"""

        menu = RoundMenu(parent=self)
        menu.setFont(BaseStyles.font_for_role(FontRole.UI))
        return menu

    # ── 主题 ────────────────────────────────────────────────────────────

    def _apply_theme(self, _value=None):
        bs = BaseStyles
        ui_font = bs.font_for_role(FontRole.UI)
        mono_font = bs.font_for_role(FontRole.MONO)
        self.setStyleSheet(f"QTableView:focus {{ border: 2px solid {bs.color('BORDER_FOCUS')}; }}")
        self.setFont(ui_font)
        # 视觉重设计：页头卡片由 CardWidget 自绘制随主题切换，徽标按 device_ip 刷新。
        if hasattr(self, "header_card"):
            self.dialog_title.setFont(bs.font_for_role(FontRole.TITLE))
            self.dialog_subtitle.setFont(bs.font_for_role(FontRole.UI))
            self.status_badge.setFont(bs.font_for_role(FontRole.UI))
            has_device = self._device_connected
            self.status_badge.setText("Ready" if has_device else "No device")
            self.status_badge.setLevel(InfoLevel.SUCCESS if has_device else InfoLevel.INFOAMTION)
        # 表格样式由 qfluentwidgets TableWidget 自维护（随主题切换），无需在此重建。
        # 状态信息直接使用 qfluentwidgets CaptionLabel，无需额外 QSS。
        # qfluentwidgets LineEdit 默认使用像素字号，这里显式覆盖为点位角色字体。
        self.path_field.setFont(mono_font)
        self.search_field.setFont(ui_font)
        self.preview_title.setFont(bs.font_for_role(FontRole.UI))
        self.preview_empty_label.setFont(bs.font_for_role(FontRole.UI))
        self.preview_loading_label.setFont(bs.font_for_role(FontRole.UI))
        self.preview_image.image_info.setFont(bs.font_for_role(FontRole.UI_SMALL))
        self.preview_text_edit.setFont(mono_font)
        self.preview_text_edit.document().setDefaultFont(mono_font)
        self.preview_output.setFont(bs.font_for_role(FontRole.LOG))
        self.preview_output.document().setDefaultFont(bs.font_for_role(FontRole.LOG))
        self.preview_back_btn.setIcon(get_themed_icon("arrow-left.svg"))
        self.preview_close_btn.setIcon(get_themed_icon("x.svg"))

    # ── ADB 辅助方法 ────────────────────────────────────────────────────

    def _connect_worker_ui(self, worker, signal, handler, *, guard_objects=()):
        """连接 worker 的界面回调，并在页面或关联控件销毁后拒绝晚到信号。"""

        page_ref = weakref.ref(self)
        guard_refs = tuple(weakref.ref(obj) for obj in guard_objects if obj is not None)

        def guarded(*args):
            page = page_ref()
            if page is None or getattr(page, "_closing", False) or not is_qobject_alive(page):
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
        self._disconnect_worker_ui(worker)
        lifecycle_handler = self._worker_lifecycle_handlers.pop(worker, None)
        if lifecycle_handler is not None:
            safe_disconnect(worker.finished, lifecycle_handler)
        if worker in self._workers:
            self._workers.remove(worker)
        if self._active_refresh_worker is worker:
            self._active_refresh_worker = None
        try:
            worker.deleteLater()
        except RuntimeError:
            pass
        if self._disposing and not any(
            QThreadGroupShutdownTask._running(candidate) for candidate in self._workers
        ):
            QTimer.singleShot(0, self._finish_async_dispose)

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

    def _refresh(
        self,
        *,
        requested_path: str | None = None,
        navigation_action: str = "refresh",
    ):
        return self._list_controller._refresh(
            requested_path=requested_path,
            navigation_action=navigation_action,
        )

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

    def _show_image(
        self,
        request_id: int,
        name: str,
        tmp_path: str,
        dev_tmp: str,
        *,
        output: str = "",
        error: bool = False,
    ):
        return self._view_controller._show_image(
            request_id,
            name,
            tmp_path,
            dev_tmp,
            output=output,
            error=error,
        )

    def _show_text_viewer(self, name: str, content: str, error: bool, full_path: str):
        return self._view_controller._show_text_viewer(name, content, error, full_path)

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
            add_menu_action(menu, "Open", callback=lambda: self._on_double_click(row, 0))
        else:
            is_image = self._ext(name).lower() in self.IMAGE_EXTS
            add_menu_action(menu, "View", callback=lambda: self._view_file(name, is_image))
        menu.addSeparator()
        add_menu_action(menu, "Pull", callback=lambda: self._pull_file(name))
        if not is_dir:
            add_menu_action(menu, "Push Here", callback=self._push_file)
        if not is_dir and name.endswith(".apk"):
            add_menu_action(menu, "Install APK", callback=lambda: self._install_apk(name))
        if not is_dir and name.endswith(".sh"):
            add_menu_action(menu, "Execute Script", callback=lambda: self._exec_script(name))
        add_menu_action(menu, "Permissions", callback=lambda: self._show_chmod(name, is_dir))
        menu.addSeparator()
        add_menu_action(menu, "Rename", callback=lambda: self._rename_item(name))
        add_menu_action(menu, "Delete", callback=lambda: self._request_delete(name))
        menu.addSeparator()
        add_menu_action(menu, "Copy", callback=lambda: self._copy_items(True))
        add_menu_action(menu, "Cut", callback=lambda: self._copy_items(False))
        if self.clipboard:
            add_menu_action(menu, "Paste", callback=self._paste_items)
        menu.addSeparator()
        add_menu_action(menu, "Properties", callback=lambda: self._show_props(name, is_dir))
        menu.exec(self.table.mapToGlobal(pos))

    def _install_apk(self, name: str):
        full = self._dpath(self.current_path, name)
        cmd = self._root(explorer_service.install_apk_command(full))
        w = self._run_adb("shell", cmd)
        self._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e: self.status_bar.setText(
                f"APK {name} installed" if not e else f"APK install failed: {o}"
            ),
        )
        w.start()

    def _exec_script(self, name: str):
        full = self._dpath(self.current_path, name)
        cmd = explorer_service.script_command(full, self.root_cb.isChecked())
        request_id = self._begin_preview_request(f"Output: {name}")
        w = self._run_adb("shell", self._root(cmd) if self.root_cb.isChecked() else cmd)
        self._connect_worker_ui(
            w,
            w.result_ready,
            lambda o, e: self._show_script_output(name, o, e, request_id=request_id),
        )
        w.start()

    def _show_script_output(self, name, output, error, *, request_id: int | None = None):
        if request_id is not None and not self._preview_request_is_current(request_id):
            return
        self._show_output_preview(name, output, error=bool(error))

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
            FluentMessageBox.critical(
                self,
                f"Properties Error: {name}",
                output or "Unable to read file properties",
            )
            self.status_bar.setText(f"Failed to read properties for {name}")
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
        FluentMessageBox.information(self, f"Properties: {name}", info)

    def _show_props_done(self, name, full, ftype, size, error):
        if error:
            FluentMessageBox.critical(
                self,
                f"Properties Error: {name}",
                size or "Unable to read folder properties",
            )
            self.status_bar.setText(f"Failed to read properties for {name}")
            return
        info = f"Name: {name}\nType: {ftype}\nSize: {size}\nPath: {full}"
        FluentMessageBox.information(self, f"Properties: {name}", info)

    # ── 页会话生命周期 ──────────────────────────────────────────────────

    def activate(self, payload=None) -> None:
        """激活页面；仅首次激活时加载目录，后续切页保留会话状态。"""

        if self._disposing or self._disposed:
            return
        self._active = True
        requested_path = ""
        if isinstance(payload, dict):
            requested_path = str(payload.get("path", "") or "").strip()
        elif isinstance(payload, str):
            requested_path = payload.strip()
        self._activated_once = True
        if not self._loaded_once:
            if not self._device_connected:
                self.status_bar.setText("Select a device to browse files")
                return
            self._loaded_once = True
            if requested_path and requested_path != self.current_path:
                self._refresh(requested_path=requested_path, navigation_action="replace")
            else:
                self._refresh()
            return
        if requested_path and requested_path != self.current_path:
            self._navigate(requested_path)

    def deactivate(self, _reason: str = "navigation") -> None:
        """离开页面时保留路径、预览和后台任务，供返回后继续使用。"""

        self._active = False

    def set_device_connected(self, connected: bool) -> None:
        """同步稳定会话设备的在线状态，不静默切换到其他设备。"""

        connected = bool(connected and self.device_ip)
        became_available = connected and not self._device_connected
        self._device_connected = connected
        self.setProperty("deviceConnected", connected)
        self.status_badge.setText("Ready" if connected else "Device offline")
        self.status_badge.setLevel(InfoLevel.SUCCESS if connected else InfoLevel.ERROR)
        if not connected and self._active_refresh is not None:
            self._active_refresh = None
            self._pending_navigation = None
            worker = self._active_refresh_worker
            if worker is not None and QThreadGroupShutdownTask._running(worker):
                try:
                    worker.abort()
                except RuntimeError:
                    pass
            self._set_directory_loading(False)
        self._sync_directory_controls()
        if not connected:
            self.status_bar.setText("Device offline; reconnect or choose another device")
        elif became_available and self._active and self._activated_once and not self._loaded_once:
            self._loaded_once = True
            self._refresh()

    def request_dispose(self, _reason: str = "user") -> bool:
        """请求异步释放 worker；返回 ``False`` 表示等待 ``dispose_ready``。"""

        if self._disposed:
            return True
        if self._disposing:
            ready = not any(
                QThreadGroupShutdownTask._running(worker) for worker in self._workers
            )
            if ready:
                self._finish_dispose(emit_ready=False)
            return ready
        self._disposing = True
        self._closing = True
        self._active = False
        self._sync_directory_controls()
        self._active_refresh = None
        self._pending_navigation = None
        self._preview_request_id += 1
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        safe_disconnect(BaseStyles.fonts_changed, self._apply_theme)

        workers = list(dict.fromkeys((*self._workers, *self._worker_ui_bindings)))
        for worker in workers:
            self._disconnect_worker_ui(worker)
            if not QThreadGroupShutdownTask._running(worker):
                self._prune_worker(worker)
                continue
            try:
                worker.abort()
            except RuntimeError:
                continue

        if any(QThreadGroupShutdownTask._running(worker) for worker in self._workers):
            return False
        self._finish_dispose(emit_ready=False)
        return True

    def _finish_async_dispose(self) -> None:
        if not self._disposing or self._disposed:
            return
        if any(QThreadGroupShutdownTask._running(worker) for worker in self._workers):
            return
        self._finish_dispose(emit_ready=True)

    def _finish_dispose(self, *, emit_ready: bool) -> None:
        if self._disposed:
            return
        self._disposed = True
        self.preview_image.release_image_source()
        self._view_controller.dispose()
        for worker in tuple(self._workers):
            self._prune_worker(worker)
        if self._close_when_disposed:
            self.hide()
        if emit_ready:
            self.dispose_ready.emit()

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
        """直接关闭控件时也等待运行中的 worker 完成清理。"""

        if self._disposed or self.request_dispose("window_close"):
            event.accept()
            return
        self._close_when_disposed = True
        self.hide()
        event.ignore()
