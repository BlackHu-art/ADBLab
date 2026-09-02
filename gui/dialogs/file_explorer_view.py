"""提供文件浏览器对话框的文件预览与查看控制器。"""

import os
import tempfile

from PySide6.QtCore import QSize
from PySide6.QtGui import QImageReader, QPixmap, QPixmapCache, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)
from qfluentwidgets import PlainTextEdit, PushButton

from gui.dialogs.file_explorer_image import _ImageViewerDialog
from gui.dialogs.lifecycle import (
    fit_secondary_window_to_owner_screen,
    is_qobject_alive,
    safe_disconnect,
)
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.typography import FontRole
from services import file_explorer as explorer_service

MAX_TEXT_VIEW_BYTES = 2 * 1024 * 1024
TEXT_RENDER_CHUNK = 64 * 1024
MAX_IMAGE_PREVIEW_DIMENSION = 2048


def _set_plain_text_chunked(editor: QPlainTextEdit, content: str) -> None:
    editor.setUpdatesEnabled(False)
    try:
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for start in range(0, len(content), TEXT_RENDER_CHUNK):
            cursor.insertText(content[start : start + TEXT_RENDER_CHUNK])
    finally:
        editor.setUpdatesEnabled(True)


def _load_image_preview(path: str) -> QPixmap:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    key = f"adblab:explorer:image:{path}:{mtime}"
    cached = QPixmap()
    if QPixmapCache.find(key, cached) and not cached.isNull():
        return cached
    reader = QImageReader(path)
    native = reader.size()
    if native.isValid() and not native.isEmpty():
        scale = min(1.0, MAX_IMAGE_PREVIEW_DIMENSION / max(native.width(), native.height()))
        if scale < 1.0:
            reader.setScaledSize(
                QSize(max(1, int(native.width() * scale)), max(1, int(native.height() * scale)))
            )
    pixmap = QPixmap.fromImage(reader.read())
    if not pixmap.isNull():
        QPixmapCache.insert(key, pixmap)
    return pixmap


class FileExplorerView:
    """组合进 FileExplorerDialog 的预览查看控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    # ── 双击操作 ────────────────────────────────────────────────────────

    def _view_or_pull(self, name: str):
        menu = self._frame._create_context_menu()
        pull = menu.add_action("Pull File")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        viewable = ext in self._frame.TEXT_EXTS or ext in self._frame.IMAGE_EXTS
        view = menu.add_action("View") if viewable else None
        act = menu.exec(
            self._frame.table.mapToGlobal(
                self._frame.table.visualItemRect(
                    self._frame.table.item(
                        self._frame.table.currentRow(), self._frame.NAME_COL
                    )
                ).center()
            )
        )
        if act == pull:
            self._frame._pull_file(name)
        elif view and act == view:
            self._view_file(name, ext in self._frame.IMAGE_EXTS)

    # ── 查看与编辑文件 ──────────────────────────────────────────────────

    def _view_file(self, name: str, is_image: bool = False):
        full = self._frame._dpath(self._frame.current_path, name)
        if is_image:
            self._view_image(name, full)
        else:
            shell = self._frame._root(
                explorer_service.head_command(full, MAX_TEXT_VIEW_BYTES + 1)
            )
            w = self._frame._run_adb("shell", shell)
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e: self._show_text_viewer(name, o, e, full),
            )
            w.start()

    def _view_image(self, name: str, full_path: str):
        if not explorer_service.safe_name(name):
            QMessageBox.critical(
                self._frame,
                "Invalid file name",
                f"Refusing to open image with unsafe name: {name}",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        dlg = _ImageViewerDialog(self._frame)
        dlg.setWindowTitle(name)
        dlg.setMinimumSize(750, 550)
        dlg.setModal(True)
        fit_secondary_window_to_owner_screen(dlg, self._frame)

        tmp_dir = os.path.join(tempfile.gettempdir(), "adblab_explorer")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, name)

        if self._frame.root_cb.isChecked():
            dev_tmp = f"/data/local/tmp/{name}"
            w1 = self._frame._run_adb(
                "shell",
                self._frame._root(
                    explorer_service.copy_for_root_pull_command(full_path, dev_tmp)
                ),
                timeout=120,
            )

            def _on_copy(o, e):
                if e:
                    QMessageBox.critical(
                        dlg,
                        "Error",
                        o,
                        QMessageBox.StandardButton.Ok,
                        QMessageBox.StandardButton.NoButton,
                    )
                    return
                w2 = self._frame._run_transfer("pull", dev_tmp, tmp_path)
                self._frame._connect_worker_ui(
                    w2,
                    w2.result_ready,
                    lambda o2, e2, d: self._show_image(dlg, name, tmp_path, dev_tmp),
                    guard_objects=(dlg,),
                )
                w2.start()

            self._frame._connect_worker_ui(w1, w1.result_ready, _on_copy, guard_objects=(dlg,))
            w1.start()
        else:
            w = self._frame._run_transfer("pull", full_path, tmp_path)
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o2, e2, d: self._show_image(dlg, name, tmp_path, ""),
                guard_objects=(dlg,),
            )
            w.start()

        try:
            dlg.exec()
        finally:
            if is_qobject_alive(dlg):
                dlg.release_image_source()
                dlg.deleteLater()
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def _show_image(self, dlg, name, tmp_path, dev_tmp):
        if dev_tmp:
            self._frame._run_adb("shell", explorer_service.delete_command(dev_tmp)).start()
        dlg.set_image_source(_load_image_preview(tmp_path), name)

    def _show_text_viewer(self, name: str, content: str, error: bool, full_path: str):
        if error:
            QMessageBox.critical(
                self._frame,
                "Error",
                content,
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
            )
            return
        truncated = len(content.encode("utf-8", errors="ignore")) > MAX_TEXT_VIEW_BYTES
        dlg = QDialog(self._frame)
        dlg.setWindowTitle(name)
        dlg.setMinimumSize(750, 550)
        dlg.setModal(True)
        lo = QVBoxLayout(dlg)
        editor = PlainTextEdit()
        _set_plain_text_chunked(editor, content)
        if truncated:
            editor.appendPlainText(
                f"\n… (preview truncated; file exceeds {MAX_TEXT_VIEW_BYTES // (1024 * 1024)} MB)"
            )
        lo.addWidget(editor)
        btns = QHBoxLayout()
        save_as = PushButton()
        save_as.setText("Save As...")
        save_as.setToolTip("Save the edited text to the computer")
        save_as.setIcon(get_themed_icon("floppy-disk.svg"))
        save_as.setIconSize(QSize(14, 14))
        save_as.clicked.connect(lambda: self._frame._save_as(name, editor.toPlainText()))
        save_dev = PushButton()
        save_dev.setText("Save to Device")
        save_dev.setToolTip("Write the edited text back to the device")
        save_dev.setIcon(get_themed_icon("device-mobile.svg"))
        save_dev.setIconSize(QSize(14, 14))
        save_dev.clicked.connect(
            lambda: self._frame._save_to_device(name, editor.toPlainText(), full_path)
        )
        close = PushButton()
        close.setText("Close")
        close.setToolTip("Close the text viewer")
        close.setIcon(get_themed_icon("x.svg"))
        close.setIconSize(QSize(14, 14))
        close.clicked.connect(dlg.accept)
        for b in (save_as, save_dev, close):
            btns.addWidget(b)
        lo.addLayout(btns)
        self._bind_dialog_font_refresh(
            dlg,
            lambda: self._apply_text_dialog_fonts(dlg, editor, FontRole.MONO),
        )
        fit_secondary_window_to_owner_screen(dlg, self._frame)
        dlg.exec()
        dlg.deleteLater()

    @staticmethod
    def _apply_text_dialog_fonts(dialog, editor, role: FontRole) -> None:
        """刷新临时文本窗口及其显式文本字体。"""

        dialog.setFont(BaseStyles.font_for_role(FontRole.UI))
        text_font = BaseStyles.font_for_role(role)
        editor.setFont(text_font)
        editor.document().setDefaultFont(text_font)

    @staticmethod
    def _bind_dialog_font_refresh(dialog, refresh) -> None:
        """让临时对话框在存活期间响应全局字体变化。"""

        font_signal = BaseStyles.fonts_changed

        def apply_font(_config=None):
            try:
                refresh()
            except RuntimeError:
                return

        def disconnect_font(_result=None):
            safe_disconnect(font_signal, apply_font)

        font_signal.connect(apply_font)
        dialog.finished.connect(disconnect_font)
        dialog.destroyed.connect(disconnect_font)
        apply_font()
