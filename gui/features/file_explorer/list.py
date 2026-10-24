"""提供文件浏览器页的导航、列表解析与渲染控制器。"""

import os
from collections.abc import Generator
from time import perf_counter
from typing import cast

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import QTableWidgetItem, QWidget
from qfluentwidgets import TableItemDelegate

from adblab.presentation.workers.file_explorer import ADBWorker, DirectoryListWorker
from gui.dialogs.lifecycle import QThreadGroupShutdownTask
from gui.i18n import tr
from gui.styles.icon_loader import get_fluent_icon
from services import file_explorer as explorer_service


def file_explorer_icon(name: str) -> QIcon:
    """使用 Qt 原生 SVG 引擎，由页面主题回调重新绑定颜色。

    文件页反复创建和释放表格及工具按钮时，Fluent 的 Python QIconEngine
    在 Windows 退出阶段可触发堆损坏；此边界交给 Qt 管理图标拷贝及释放。
    """
    return get_fluent_icon(name).icon()


class FileExplorerItemDelegate(TableItemDelegate):
    """按页面字号绘制并隐藏类型文字，保留 Qt 排序和 Fluent 行状态。"""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # PySide6 类型桩缺少这些公开结构字段，实际 Qt 绘制必须同步字号和度量。
        font = cast(QWidget, self.parent()).font()
        setattr(option, "font", font)
        setattr(option, "fontMetrics", QFontMetrics(font))
        if index.column() == 0:
            # PySide6 的类型桩未列出此公开结构字段，实际 Qt 委托使用 text 绘制。
            setattr(option, "text", "")


class FileSizeItem(QTableWidgetItem):
    """大小显示保留单位，比较原始字节数；两种方向都保留父目录和目录在前。"""

    def __init__(self, text: str, size: int, group: int):
        super().__init__(text)
        self._size = size
        self._group = group

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if not isinstance(other, FileSizeItem):
            return super().__lt__(other)
        if self._group != other._group:
            table = self.tableWidget()
            descending = (
                table is not None
                and table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
            )
            return self._group > other._group if descending else self._group < other._group
        return self._size < other._size


class FileTypeItem(QTableWidgetItem):
    """类型列显示本地化文本，排序使用稳定的原始业务类型。"""

    def __init__(self, text: str, file_type: str):
        super().__init__(text)
        self._type_key = str(file_type)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if not isinstance(other, FileTypeItem):
            return super().__lt__(other)
        return self._type_key < other._type_key


class FileModifiedItem(QTableWidgetItem):
    """日期显示保留原文；无年份与不可解析项独立置后，不伪造准确时间。"""

    def __init__(self, text: str, group: int):
        super().__init__(text)
        self._group = group
        self._key = explorer_service.modified_sort_key(text)
        if self._key[0] == 1:
            self.setToolTip(tr(
                "Year unavailable; sorted by month, day and time after dated entries",
            ))

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if not isinstance(other, FileModifiedItem):
            return super().__lt__(other)
        left_group = self._group, self._key[0]
        right_group = other._group, other._key[0]
        if left_group != right_group:
            table = self.tableWidget()
            descending = (
                table is not None
                and table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
            )
            return left_group > right_group if descending else left_group < right_group
        return self._key[1:] < other._key[1:]


class FileExplorerList:
    """组合进 FileExplorerPage 的列表控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        self._frame = frame
        self._link_requests: dict[tuple[int, str, bool], ADBWorker] = {}
        self._work: Generator[None, None, None] | None = None
        self._work_timer: QTimer | None = None
        self._paused = False
        self._uncommitted = False
        self._committed_listing = explorer_service.DirectoryListing((), {})
        self._saved_selection: tuple[set[str], tuple[str, int] | None] = (set(), None)
        self._filter_text = ""
        self._filter_revision = 0

    @property
    def populating(self) -> bool:
        """未提交或正在恢复的快照不得作为文件命令的目标。"""
        return self._uncommitted

    def pause_population(self) -> None:
        """离开页面只暂停 GUI 构建，保留后台读取与原请求身份。"""
        self._paused = True
        if self._work_timer is not None:
            self._work_timer.stop()

    def resume_population(self) -> None:
        """返回页面后继续未完成的构建或筛选，不重复读取设备。"""
        self._paused = False
        self._schedule_work()

    def _stop_work(self) -> None:
        if self._work_timer is not None:
            self._work_timer.stop()
        if self._work is not None:
            self._work.close()
            self._work = None

    def _schedule_work(self) -> None:
        if self._work is None or self._paused or getattr(self._frame, "_closing", False):
            return
        if self._work_timer is None:
            self._work_timer = QTimer(self._frame)
            self._work_timer.setSingleShot(True)
            self._work_timer.timeout.connect(self._continue_work)
        self._work_timer.start(0)

    def _continue_work(self) -> None:
        if self._paused or self._work is None or getattr(self._frame, "_closing", False):
            return
        try:
            next(self._work)
        except StopIteration:
            self._work = None
        self._schedule_work()

    def cancel_refresh(self, *, restore: bool = True) -> None:
        """撤销请求与后续 GUI 批次；失去操作资格后仅恢复已提交的缓存。"""
        self._stop_work()
        self._frame._active_refresh = None
        self._frame._pending_navigation = None
        worker = getattr(self._frame, "_active_refresh_worker", None)
        if worker is not None and QThreadGroupShutdownTask._running(worker):
            try:
                worker.abort()
            except RuntimeError:
                pass
        if restore and self._uncommitted:
            self._start_population(
                self._committed_listing, self._frame.current_path, None, restoring=True,
            )
        elif restore:
            self._set_loading(False)
            self._work = self._filter_rows()
            self._continue_work()
        else:
            self._frame.table.setUpdatesEnabled(True)

    # ── ADB 辅助方法 ────────────────────────────────────────────────────

    def _root(self, cmd: str) -> str:
        return explorer_service.root_command(cmd, self._frame.root_cb.isChecked())

    def _safe_name(self, name: str) -> bool:
        return explorer_service.safe_name(name)

    def _dpath(self, *parts) -> str:
        return explorer_service.device_path(*parts)

    def _set_loading(self, loading: bool) -> None:
        callback = getattr(self._frame, "_set_directory_loading", None)
        if callable(callback):
            callback(loading)
        else:
            self._frame.table.setEnabled(not loading)

    # ── 路径导航 ────────────────────────────────────────────────────────

    def _navigate(self, path: str, push: bool = True):
        path = str(path or "")
        if not path or (path == self._frame.current_path and self._frame._active_refresh is None):
            return
        self._refresh(
            requested_path=path,
            navigation_action="push" if push else "replace",
        )

    def _go_back(self):
        if not self._frame.history:
            return
        self._refresh(
            requested_path=self._frame.history[-1],
            navigation_action="back",
        )

    def _go_forward(self):
        if not self._frame.forward_stack:
            return
        self._refresh(
            requested_path=self._frame.forward_stack[-1],
            navigation_action="forward",
        )

    def _go_parent(self):
        parent = os.path.dirname(self._frame.current_path.rstrip("/")) or "/"
        if parent == self._frame.current_path:
            # 根目录没有上级；不要先写下“正在打开”再被 _navigate 直接返回。
            return
        self._frame.status_bar.setText(tr("Opening parent folder..."))
        self._navigate(parent)

    # ── 目录列表 ────────────────────────────────────────────────────────

    def _refresh(
        self,
        *,
        requested_path: str | None = None,
        navigation_action: str = "refresh",
    ):
        if self._frame._closing:
            return
        if not self._frame._can_operate():
            self._frame.status_bar.setText(tr("Select an online device before browsing files"))
            return
        requested_path = str(requested_path or self._frame.current_path)
        if not requested_path:
            return
        # 替换请求可以中断半成品；直到新结果或旧快照恢复完成都不开放命令准入。
        self._stop_work()
        self.cancel_link_requests()
        if navigation_action == "refresh":
            self._frame._view_controller.invalidate_cache()
        self._frame._refresh_request_id += 1
        request_id = self._frame._refresh_request_id
        self._frame._active_refresh = (request_id, requested_path)
        if navigation_action != "refresh":
            close_preview = getattr(self._frame, "_close_preview", None)
            if callable(close_preview):
                close_preview()
        self._frame._pending_navigation = (
            (request_id, navigation_action, requested_path)
            if navigation_action != "refresh"
            else None
        )
        previous_worker = getattr(self._frame, "_active_refresh_worker", None)
        if previous_worker is not None and QThreadGroupShutdownTask._running(previous_worker):
            try:
                previous_worker.abort()
            except RuntimeError:
                pass
        self._frame.search_field.clear()
        self._frame.status_bar.setText(tr('Opening {value0}…').format(value0=requested_path))
        self._set_loading(True)

        worker = self._frame._track_worker(DirectoryListWorker(
            self._frame.device_ip, requested_path, self._frame.root_cb.isChecked(),
        ))
        self._frame._active_refresh_worker = worker
        worker.setProperty("refreshRequestId", request_id)
        worker.setProperty("requestedPath", requested_path)
        self._frame._connect_worker_ui(
            worker,
            worker.result_ready,
            lambda output, error: self._on_directory_result(
                output,
                error,
                request_id=request_id,
                requested_path=requested_path,
            ),
        )
        worker.start()

    def _on_directory_result(self, output, error, **context):
        """真实刷新只接受经过后台原始协议校验的快照，文本兼容解析不可回退。"""
        if not error and not isinstance(output, explorer_service.DirectoryListing):
            output, error = tr("Directory loading failed"), True
        self._on_ls_result(output, error, **context)

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
        ):
            return
        if error:
            if request_id is not None:
                self._frame._active_refresh = None
                self._frame._pending_navigation = None
            if self._uncommitted:
                self._start_population(
                    self._committed_listing, self._frame.current_path, None, restoring=True,
                )
            else:
                self._set_loading(False)
                # 刷新可能中断了空查询的分批取消隐藏，失败后仍需完成缓存筛选。
                self._filter(self._frame.search_field.text())
            self._frame.path_field.setText(self._frame.current_path)
            self._frame.status_bar.setText(
                tr("Unable to open {value0}").format(value0=requested_path)
            )
            self._frame.status_bar.setToolTip(str(output or tr("Directory loading failed")))
            return
        if not isinstance(output, explorer_service.DirectoryListing):
            # 旧调用方的展示适配保留；真实设备刷新只连接上面的严格快照入口。
            rows, targets = explorer_service.parse_ls_output(output)
            output = explorer_service.DirectoryListing(tuple(rows), targets)
        self._start_population(output, requested_path, request_id)

    def _start_population(self, listing, path, request_id, *, restoring=False) -> None:
        self._stop_work()
        table = self._frame.table
        if not self._uncommitted:
            names = {
                self._file_name_at(index.row()) for index in table.selectionModel().selectedRows()
            }
            current = None if table.currentItem() is None else (
                self._file_name_at(table.currentRow()), table.currentColumn(),
            )
            self._saved_selection = (names, current)
        self._uncommitted = True
        self._set_loading(True)
        self._filter_text = self._frame.search_field.text().strip().lower()
        self._work = self._populate(listing, path, request_id, restoring=restoring)
        self._continue_work()

    def _populate(self, listing, path, request_id, *, restoring) -> Generator[None, None, None]:
        """每批最多创建 64 行或占用约 6ms；最终 Qt 排序仍是一次原生调用。"""
        table = self._frame.table
        rows = listing.entries
        large = len(rows) > 128
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        # 重用行位置不能继承旧选择；快照未提交时也不公开链接元数据。
        table.selectionModel().clear()
        table.clearContents()
        parent_offset = int(path != "/")
        table.setRowCount(len(rows) + parent_offset)
        if parent_offset:
            self._set_file_row(0, "..", "Folder", "-", "-")
        started = perf_counter()
        folders = 0
        for index, entry in enumerate(rows, parent_offset):
            self._set_file_row(
                index, entry.name, entry.file_type, entry.size_text, entry.modified,
                size_bytes=entry.size,
            )
            table.item(index, self._frame.NAME_COL).setData(Qt.ItemDataRole.UserRole, entry)
            folders += entry.is_dir
            if large and (
                (index - parent_offset + 1) % 64 == 0 or perf_counter() - started >= .006
            ):
                yield
                started = perf_counter()
        table.setSortingEnabled(True)
        # 隐藏状态属于行位置，必须在最终排序后重算；筛选变化会重新开始这一分批扫描。
        yield from self._filter_rows()
        filtered_revision = self._filter_revision
        names, current = (
            self._saved_selection if path == self._frame.current_path else (set(), None)
        )
        yield from self._restore_selection(names, current)
        # 恢复选择也可能让出事件循环，提交前再确认搜索词未被用户更新。
        if filtered_revision != self._filter_revision:
            yield from self._filter_rows()
        if not restoring:
            pending = getattr(self._frame, "_pending_navigation", None)
            if request_id is not None and pending is not None and pending[0] == request_id:
                self._commit_navigation(pending[1], path)
                self._frame._pending_navigation = None
            self._committed_listing = listing
            if request_id is not None:
                self._frame._active_refresh = None
            self._frame.status_bar.setText(
                tr("{value0}  |  {value1} folders, {value2} files").format(
                    value0=path, value1=folders, value2=len(rows) - folders,
                )
            )
        self._frame.symlink_targets = listing.symlink_targets
        self._uncommitted = False
        table.setUpdatesEnabled(True)
        self._set_loading(False)

    def _restore_selection(
        self, selected_names: set[str], current_cell: tuple[str, int] | None,
    ) -> Generator[None, None, None]:
        """排序完成后按原始文件名恢复行选择；已消失项及跨目录的当前项保持为空。"""
        table = self._frame.table
        model = table.model()
        selection = QItemSelection()
        current_index = QModelIndex()
        started = perf_counter()
        for row in range(table.rowCount() if selected_names or current_cell is not None else 0):
            name = self._file_name_at(row)
            if name in selected_names:
                selection.select(model.index(row, 0), model.index(row, table.columnCount() - 1))
            if current_cell is not None and name == current_cell[0]:
                current_index = model.index(row, current_cell[1])
            if table.rowCount() > 128 and (row % 64 == 63 or perf_counter() - started >= .006):
                yield
                started = perf_counter()
        selection_model = table.selectionModel()
        # 当前单元格可以不属于多选集合，直接使用 Qt 选择模型避免控件隐式选中当前行。
        selection_model.setCurrentIndex(current_index, QItemSelectionModel.SelectionFlag.NoUpdate)
        selection_model.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        table.updateSelectedRows()

    def _commit_navigation(self, action: str, target: str) -> None:
        """仅在目录读取成功后原子提交路径和前进/后退历史。"""

        current = self._frame.current_path
        if action == "push" and target != current:
            self._frame.history.append(current)
            self._frame.forward_stack.clear()
        elif action == "back" and self._frame.history and self._frame.history[-1] == target:
            self._frame.history.pop()
            self._frame.forward_stack.append(current)
        elif (
            action == "forward"
            and self._frame.forward_stack
            and self._frame.forward_stack[-1] == target
        ):
            self._frame.forward_stack.pop()
            self._frame.history.append(current)
        self._frame.current_path = target
        self._frame.path_field.setText(target)
        sync_controls = getattr(self._frame, "_sync_directory_controls", None)
        if callable(sync_controls):
            sync_controls()

    def _set_file_row(
        self, row: int, name: str, file_type: str, size: str, modified: str,
        *, size_bytes: int = 0,
    ):
        display_type = tr(file_type) if file_type in {"Folder", "File", "Link"} else file_type
        type_item = FileTypeItem(display_type, file_type)
        # 类型文字可随语言变化；目录导航和图标选择始终读取原始业务类型。
        type_item.setData(Qt.ItemDataRole.UserRole, file_type)
        type_item.setIcon(self._file_type_icon(name, file_type))
        type_item.setToolTip(display_type)
        type_item.setData(Qt.ItemDataRole.AccessibleTextRole, display_type)
        name_item = QTableWidgetItem(name)
        name_item.setToolTip(name)
        self._frame.table.setItem(row, self._frame.TYPE_COL, type_item)
        self._frame.table.setItem(row, self._frame.NAME_COL, name_item)
        group = 0 if name == ".." else 1 if file_type == "Folder" else 2
        self._frame.table.setItem(row, self._frame.SIZE_COL, FileSizeItem(size, size_bytes, group))
        self._frame.table.setItem(row, self._frame.MODIFIED_COL, FileModifiedItem(modified, group))

    def _file_name_at(self, row: int) -> str:
        item = self._frame.table.item(row, self._frame.NAME_COL)
        return item.text() if item else ""

    def _file_type_at(self, row: int) -> str:
        item = self._frame.table.item(row, self._frame.TYPE_COL)
        return str(item.data(Qt.ItemDataRole.UserRole) or item.text()) if item else ""

    def _file_type_icon(self, name: str, file_type: str):
        return file_explorer_icon(self._file_type_icon_name(name, file_type))

    def _file_type_icon_name(self, name: str, file_type: str) -> str:
        if name == "..":
            return "arrow-u-up-left.svg"
        if file_type == "Folder":
            return "folder.svg"
        if file_type == "Link":
            return "link.svg"
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
        if not self._frame._can_use_directory_snapshot():
            return
        name = self._file_name_at(row)
        ftype = self._file_type_at(row)
        if name == "..":
            self._go_parent()
        elif ftype == "Link":
            self._open_symlink(name)
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

    def _open_symlink(self, name: str) -> None:
        """按需查询一次链接目标；同目录重复打开合并，过期或失选结果不启动操作。"""
        frame = self._frame
        if not frame._can_operate():
            return
        full_path = self._dpath(frame.current_path, name)
        root = frame.root_cb.isChecked()
        request = (frame._refresh_request_id, full_path, root)
        if request in self._link_requests:
            return
        self.cancel_link_requests()
        worker = frame._run_adb("shell", self._root(
            explorer_service.link_target_type_command(full_path),
        ))
        if worker is None:
            return
        self._link_requests[request] = worker
        directory = frame.current_path

        def forget() -> bool:
            if self._link_requests.get(request) is not worker:
                return False
            self._link_requests.pop(request)
            return True

        def finish(output: str, failed: bool) -> None:
            if not forget():
                return
            if (
                not frame._can_operate() or frame.current_path != directory
                or frame._refresh_request_id != request[0] or frame.root_cb.isChecked() != root
            ):
                return
            kind = output.strip()
            if not failed and kind == "directory":
                # ls -l 会显示链接本身；尾斜杠明确要求跟随到目录内容。
                self._navigate(full_path.rstrip("/") + "/")
            elif not failed and kind == "file":
                frame._view_or_pull(name)
            else:
                frame.status_bar.setText(tr("Unable to open {value0}").format(value0=name))
                frame.status_bar.setToolTip(tr("Directory loading failed") if failed else tr(
                    "链接目标不存在或无法访问，请刷新后重试。",
                ))

        frame._connect_worker_ui(worker, worker.result_ready, finish)
        frame._connect_worker_ui(
            worker, worker.finished, forget,
        )
        worker.start()

    def cancel_link_requests(self, *_args) -> None:
        """导航、选择或 Root 上下文改变即失效旧查询；只请求取消，不等待线程。"""
        workers = tuple(self._link_requests.values())
        self._link_requests.clear()
        for worker in workers:
            try:
                worker.abort()
            except RuntimeError:
                # 页面终态清理可能已经销毁 QObject，无需再次请求停止。
                continue

    # ── 排序与筛选 ──────────────────────────────────────────────────────

    def _filter(self, text):
        self._filter_text = text.strip().lower()
        self._filter_revision += 1
        if self._uncommitted or getattr(self._frame, "_closing", False):
            return
        self._stop_work()
        self._work = self._filter_rows()
        self._continue_work()

    def _filter_rows(self) -> Generator[None, None, None]:
        table = self._frame.table
        while True:
            revision = self._filter_revision
            text = self._filter_text
            started = perf_counter()
            for row in range(table.rowCount()):
                name = self._file_name_at(row)
                hidden = name != ".." and text not in name.lower()
                if table.isRowHidden(row) != hidden:
                    table.setRowHidden(row, hidden)
                if table.rowCount() > 128 and (row % 64 == 63 or perf_counter() - started >= .006):
                    yield
                    started = perf_counter()
                    if revision != self._filter_revision:
                        break
            if revision == self._filter_revision:
                return

    def _header_clicked(self, col):
        if self._uncommitted:
            return
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
        self._filter(self._frame.search_field.text())
