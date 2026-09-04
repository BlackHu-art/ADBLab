"""提供文件浏览器页内预览与查看控制器。"""

import os
import tempfile

from PySide6.QtCore import QSize
from PySide6.QtGui import QImageReader, QPixmap, QPixmapCache

from gui.styles.fluent import add_menu_action
from services import file_explorer as explorer_service

MAX_TEXT_VIEW_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PREVIEW_DIMENSION = 2048


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
    """组合进 FileExplorerPage 的预览控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        self._frame = frame
        self._temporary_files: set[str] = set()

    # ── 双击操作 ────────────────────────────────────────────────────────

    def _view_or_pull(self, name: str):
        menu = self._frame._create_context_menu()
        pull = add_menu_action(menu, "Pull File")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        viewable = ext in self._frame.TEXT_EXTS or ext in self._frame.IMAGE_EXTS
        view = add_menu_action(menu, "View") if viewable else None
        act = menu.exec(
            self._frame.table.mapToGlobal(
                self._frame.table.visualItemRect(
                    self._frame.table.item(self._frame.table.currentRow(), self._frame.NAME_COL)
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
            request_id = self._frame._begin_preview_request(name)
            shell = self._frame._root(explorer_service.head_command(full, MAX_TEXT_VIEW_BYTES + 1))
            w = self._frame._run_adb("shell", shell)
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e: self._show_text_viewer(
                    name,
                    o,
                    e,
                    full,
                    request_id=request_id,
                ),
            )
            w.start()

    def _view_image(self, name: str, full_path: str):
        if not explorer_service.safe_name(name):
            self._frame._show_preview_error(
                "Invalid file name",
                f"Refusing to open image with unsafe name: {name}",
            )
            return
        request_id = self._frame._begin_preview_request(name)
        suffix = os.path.splitext(name)[1]
        file_descriptor, tmp_path = tempfile.mkstemp(prefix="adblab-preview-", suffix=suffix)
        os.close(file_descriptor)
        self._temporary_files.add(tmp_path)

        if self._frame.root_cb.isChecked():
            dev_tmp = f"/data/local/tmp/{name}"
            w1 = self._frame._run_adb(
                "shell",
                self._frame._root(explorer_service.copy_for_root_pull_command(full_path, dev_tmp)),
                timeout=120,
            )

            def _on_copy(output, error):
                if not self._frame._preview_request_is_current(request_id):
                    self._frame._run_adb(
                        "shell",
                        explorer_service.delete_command(dev_tmp),
                    ).start()
                    self._remove_temporary_file(tmp_path)
                    return
                if error:
                    self._frame._show_preview_error(
                        name,
                        output or "Unable to prepare image preview",
                    )
                    self._remove_temporary_file(tmp_path)
                    return
                w2 = self._frame._run_transfer("pull", dev_tmp, tmp_path)
                self._frame._connect_worker_ui(
                    w2,
                    w2.result_ready,
                    lambda o2, e2, _destination: self._show_image(
                        request_id,
                        name,
                        tmp_path,
                        dev_tmp,
                        output=o2,
                        error=e2,
                    ),
                )
                w2.start()

            self._frame._connect_worker_ui(w1, w1.result_ready, _on_copy)
            w1.start()
        else:
            w = self._frame._run_transfer("pull", full_path, tmp_path)
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o2, e2, _destination: self._show_image(
                    request_id,
                    name,
                    tmp_path,
                    "",
                    output=o2,
                    error=e2,
                ),
            )
            w.start()

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
        if dev_tmp:
            self._frame._run_adb("shell", explorer_service.delete_command(dev_tmp)).start()
        try:
            if not self._frame._preview_request_is_current(request_id):
                return
            if error:
                self._frame._show_preview_error(name, output or "Unable to pull image")
                return
            pixmap = _load_image_preview(tmp_path)
            if pixmap.isNull():
                self._frame._show_preview_error(name, "The downloaded image could not be decoded")
                return
            self._frame._show_image_preview(name, pixmap)
        finally:
            self._remove_temporary_file(tmp_path)

    def _show_text_viewer(
        self,
        name: str,
        content: str,
        error: bool,
        full_path: str,
        *,
        request_id: int | None = None,
    ):
        if request_id is not None and not self._frame._preview_request_is_current(request_id):
            return
        if error:
            self._frame._show_preview_error(name, content)
            return
        truncated = len(content.encode("utf-8", errors="ignore")) > MAX_TEXT_VIEW_BYTES
        self._frame._show_text_preview(
            name,
            content,
            full_path,
            editable=not truncated,
        )

    def _remove_temporary_file(self, path: str) -> None:
        self._temporary_files.discard(path)
        try:
            os.remove(path)
        except OSError:
            pass

    def dispose(self) -> None:
        """在页面 worker 停止后删除尚未进入完成回调的本地预览文件。"""

        for path in tuple(self._temporary_files):
            self._remove_temporary_file(path)
