"""提供文件浏览器对话框的导航、列表解析与渲染控制器。"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

from gui.styles.icon_loader import get_themed_icon
from services import file_explorer as explorer_service


class FileExplorerList:
    """组合进 FileExplorerDialog 的列表控制器，通过 ``self._frame`` 访问对话框。"""

    def __init__(self, frame):
        self._frame = frame

    # ── ADB 辅助方法 ────────────────────────────────────────────────────

    def _root(self, cmd: str) -> str:
        return explorer_service.root_command(cmd, self._frame.root_cb.isChecked())

    def _safe_name(self, name: str) -> bool:
        return explorer_service.safe_name(name)

    def _dpath(self, *parts) -> str:
        return explorer_service.device_path(*parts)

    # ── 路径导航 ────────────────────────────────────────────────────────

    def _navigate(self, path: str, push: bool = True):
        if not path or path == self._frame.current_path:
            return
        if push:
            self._frame.history.append(self._frame.current_path)
            self._frame.forward_stack.clear()
            self._frame.fwd_btn.setEnabled(False)
        self._frame.current_path = path
        self._frame.path_field.setText(path)
        self._frame.back_btn.setEnabled(bool(self._frame.history))
        self._refresh()

    def _go_back(self):
        if not self._frame.history:
            return
        self._frame.forward_stack.append(self._frame.current_path)
        self._frame.fwd_btn.setEnabled(True)
        self._navigate(self._frame.history.pop(), push=False)

    def _go_forward(self):
        if not self._frame.forward_stack:
            return
        self._frame.history.append(self._frame.current_path)
        self._frame.back_btn.setEnabled(True)
        self._navigate(self._frame.forward_stack.pop(), push=False)

    def _go_parent(self):
        self._frame.status_bar.showMessage("Opening parent folder...")
        self._navigate(os.path.dirname(self._frame.current_path))

    # ── 目录列表 ────────────────────────────────────────────────────────

    def _refresh(self):
        if self._frame._closing:
            return
        self._frame._refresh_request_id += 1
        request_id = self._frame._refresh_request_id
        requested_path = self._frame.current_path
        self._frame._active_refresh = (request_id, requested_path)
        self._frame.search_field.clear()
        self._frame.status_bar.showMessage("Loading...")
        self._frame.table.setRowCount(0)
        self._frame.symlink_targets.clear()

        cmd = explorer_service.ls_command(requested_path)
        shell_cmd = self._root(cmd)
        worker = self._frame._run_adb("shell", shell_cmd)
        worker.setProperty("refreshRequestId", request_id)
        worker.setProperty("requestedPath", requested_path)
        self._frame._connect_worker_ui(
            worker,
            worker.result_ready,
            lambda output, error: self._on_ls_result(
                output,
                error,
                request_id=request_id,
                requested_path=requested_path,
            ),
        )
        worker.start()

    def _on_ls_result(
        self,
        output,
        error,
        *,
        request_id: int | None = None,
        requested_path: str | None = None,
    ):
        requested_path = requested_path or self._frame.current_path
        if request_id is not None and (
            getattr(self._frame, "_closing", False)
            or getattr(self._frame, "_active_refresh", None) != (request_id, requested_path)
            or self._frame.current_path != requested_path
        ):
            return
        if error and not output.strip():
            if request_id is not None:
                self._frame._active_refresh = None
            self._frame.status_bar.showMessage("Error loading directory")
            return
        self._frame.table.setUpdatesEnabled(False)
        self._frame.table.setSortingEnabled(False)
        try:
            rows, symlink_targets = explorer_service.parse_ls_output(output)
            self._frame.symlink_targets = symlink_targets
            parent_offset = 1 if requested_path != "/" else 0
            self._frame.table.setRowCount(len(rows) + parent_offset)

            if parent_offset:
                self._set_file_row(0, "..", "Folder", "-", "-")

            for index, entry in enumerate(rows, parent_offset):
                self._set_file_row(
                    index, entry.name, entry.file_type, entry.size_text, entry.modified
                )
        finally:
            self._frame.table.setSortingEnabled(True)
            self._frame.table.setUpdatesEnabled(True)

        folders = sum(1 for entry in rows if entry.is_dir)
        files = len(rows) - folders
        if request_id is not None:
            self._frame._active_refresh = None
        self._frame.status_bar.showMessage(
            f"{requested_path}  |  {folders} folders, {files} files"
        )

    def _set_file_row(self, row: int, name: str, file_type: str, size: str, modified: str):
        type_item = QTableWidgetItem(file_type)
        type_item.setIcon(self._file_type_icon(name, file_type))
        type_item.setToolTip(file_type)
        name_item = QTableWidgetItem(name)
        name_item.setToolTip(name)
        self._frame.table.setItem(row, self._frame.TYPE_COL, type_item)
        self._frame.table.setItem(row, self._frame.NAME_COL, name_item)
        self._frame.table.setItem(row, self._frame.SIZE_COL, QTableWidgetItem(size))
        self._frame.table.setItem(row, self._frame.MODIFIED_COL, QTableWidgetItem(modified))

    def _file_name_at(self, row: int) -> str:
        item = self._frame.table.item(row, self._frame.NAME_COL)
        return item.text() if item else ""

    def _file_type_at(self, row: int) -> str:
        item = self._frame.table.item(row, self._frame.TYPE_COL)
        return item.text() if item else ""

    def _file_type_icon(self, name: str, file_type: str):
        return get_themed_icon(self._file_type_icon_name(name, file_type))

    def _file_type_icon_name(self, name: str, file_type: str) -> str:
        if name == "..":
            return "arrow-u-up-left.svg"
        if file_type == "Folder":
            return "folder.svg"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        explicit = {
            "apk": "android-logo.svg",
            "csv": "file-csv.svg",
            "css": "file-css.svg",
            "html": "file-html.svg",
            "ini": "file-ini.svg",
            "jpg": "file-jpg.svg",
            "jpeg": "file-jpg.svg",
            "js": "file-js.svg",
            "json": "file-code.svg",
            "md": "file-md.svg",
            "pdf": "file-pdf.svg",
            "png": "file-png.svg",
            "py": "file-py.svg",
            "sh": "terminal.svg",
            "sql": "file-sql.svg",
            "svg": "file-svg.svg",
            "txt": "file-txt.svg",
            "xml": "file-code.svg",
            "xls": "file-xls.svg",
            "xlsx": "file-xls.svg",
            "zip": "file-zip.svg",
        }
        if ext in explicit:
            return explicit[ext]
        if ext in self._frame.IMAGE_EXTS:
            return "file-image.svg"
        if ext in self._frame.ARCHIVE_EXTS:
            return "file-archive.svg"
        if ext in self._frame.AUDIO_EXTS:
            return "file-audio.svg"
        if ext in self._frame.VIDEO_EXTS:
            return "file-video.svg"
        if ext in self._frame.TEXT_EXTS:
            return "file-text.svg"
        return "file.svg"

    def _parse_ls(self, line: str) -> dict | None:
        return explorer_service.parse_ls_line(line)

    def _ext(self, name: str) -> str:
        return explorer_service.extension_label(name)

    def _safe_int(self, s: str) -> int:
        return explorer_service.safe_int(s)

    def _fmt_size(self, s: str) -> str:
        return explorer_service.format_size(s)

    # ── 双击操作 ────────────────────────────────────────────────────────

    def _on_double_click(self, row, col):
        name = self._file_name_at(row)
        ftype = self._file_type_at(row)
        if name == "..":
            self._go_parent()
        elif ftype == "Folder":
            target = self._frame.symlink_targets.get(name)
            new_path = (
                target
                if target and target.startswith("/")
                else self._dpath(self._frame.current_path, name)
            )
            self._navigate(new_path)
        else:
            self._frame._view_or_pull(name)

    # ── 排序与筛选 ──────────────────────────────────────────────────────

    def _filter(self, text):
        t = text.strip().lower()
        for r in range(self._frame.table.rowCount()):
            item = self._frame.table.item(r, self._frame.NAME_COL)
            if item and item.text() != "..":
                self._frame.table.setRowHidden(r, t not in item.text().lower())

    def _header_clicked(self, col):
        if col == self._frame._sort_col:
            self._frame._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._frame._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._frame._sort_col = col
            self._frame._sort_order = Qt.SortOrder.AscendingOrder
        self._frame.table.sortByColumn(col, self._frame._sort_order)
