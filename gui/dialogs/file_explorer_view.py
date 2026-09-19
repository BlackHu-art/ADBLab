"""提供文件浏览器页内预览与查看控制器。"""

import os
import tempfile
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap, QPixmapCache

from core.log_service import LogService
from gui.dialogs.file_explorer_preview_tasks import (
    PreviewIdentity,
    PreviewImageCache,
    PreviewReadWorker,
)
from gui.i18n import tr
from gui.styles.fluent import add_menu_action
from models.file_explorer_worker import TextReadWorker
from services import file_explorer as explorer_service

MAX_TEXT_VIEW_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PREVIEW_DIMENSION = 2048


@dataclass
class _ImageRequest:
    """一次预览固定设备、权限和临时路径，终态清理不依赖界面结果回调。"""

    request_id: int
    name: str
    identity: PreviewIdentity
    cleanup_token: object
    version: explorer_service.PreviewVersion | None = None
    temporary_path: str = ""
    remote_path: str = ""
    cancelled: bool = False
    finished: bool = False


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
        self._cache = PreviewImageCache()
        self._cache_generation = 0
        self._session_id = uuid.uuid4().hex
        self._request: _ImageRequest | None = None
        self._text_request_id: int | None = None

    # ── 双击操作 ────────────────────────────────────────────────────────

    def _view_or_pull(self, name: str):
        if not self._frame._can_operate():
            return
        menu = self._frame._create_context_menu()
        # RoundMenu 非阻塞展示且不返回所选动作；业务入口必须连接到动作信号。
        add_menu_action(menu, tr("Pull File"), callback=lambda: self._frame._pull_file(name))
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        viewable = ext in self._frame.TEXT_EXTS or ext in self._frame.IMAGE_EXTS
        if viewable:
            add_menu_action(
                menu, tr("View"),
                callback=lambda: self._view_file(name, ext in self._frame.IMAGE_EXTS),
            )
        menu.exec(
            self._frame.table.mapToGlobal(
                self._frame.table.visualItemRect(
                    self._frame.table.item(self._frame.table.currentRow(), self._frame.NAME_COL)
                ).center()
            )
        )

    # ── 查看与编辑文件 ──────────────────────────────────────────────────

    def _view_file(self, name: str, is_image: bool = False):
        if not self._frame._can_operate():
            return
        full = self._frame._dpath(self._frame.current_path, name)
        if is_image:
            self._view_image(name, full)
        else:
            request_id = self._frame._begin_preview_request(name)
            self._text_request_id = request_id
            generation = self._cache_generation
            w = self._frame._track_worker(TextReadWorker(
                self._frame.device_ip, full, self._frame.root_cb.isChecked(), MAX_TEXT_VIEW_BYTES,
            ))
            self._frame._connect_worker_ui(
                w,
                w.result_ready,
                lambda o, e: self._show_text_viewer(
                    name,
                    o,
                    e,
                    full,
                    request_id=request_id,
                ) if generation == self._cache_generation else None,
            )
            self._frame._transfers.enqueue(w, preview=True)

    def _view_image(self, name: str, full_path: str):
        if not self._frame._can_operate():
            return
        if not explorer_service.safe_name(name):
            self._frame._show_preview_error(
                tr("Invalid file name"),
                tr('Refusing to open image with unsafe name: {value0}').format(value0=name),
            )
            return
        identity = (
            self._frame.device_ip, full_path, self._frame.root_cb.isChecked(),
            self._cache_generation,
        )
        if self._request is not None and self._request.identity == identity:
            return
        request_id = self._frame._begin_preview_request(name)
        request = _ImageRequest(
            request_id, name, identity, self._frame._transfers.hold_cleanup(),
        )
        self._request = request
        worker = self._version_worker(request)
        self._enqueue_stage(request, worker, self._version_ready)

    def _version_worker(self, request: _ImageRequest):
        return self._frame._run_adb(
            "shell", explorer_service.root_command(
                explorer_service.preview_version_command(request.identity[1]), request.identity[2],
            ), timeout=5, _device_ip=request.identity[0],
        )

    def _enqueue_stage(self, request: _ImageRequest, worker, continuation) -> None:
        """业务结果先存快照；线程和进程终态后才推进，取消无结果也会清理。"""
        if worker is None:
            self._finish_request(request)
            return
        result: list = []
        signal = getattr(worker, "result_ready", None)
        if signal is not None:
            signal.connect(
                lambda *values: result.extend(values), Qt.ConnectionType.QueuedConnection,
            )

        def finished():
            if (request.cancelled or not self._frame._can_operate()
                    or not self._frame._preview_request_is_current(request.request_id)):
                self._finish_request(request)
            else:
                continuation(request, worker, result)

        self._frame._transfers.enqueue(worker, preview=True, on_terminal=finished)

    def _version_ready(self, request: _ImageRequest, _worker, result: list) -> None:
        request.version = (
            explorer_service.parse_preview_version(result[0])
            if len(result) >= 2 and not result[1] else None
        )
        cached = self._cache.get(request.identity, request.version)
        if not cached.isNull():
            self._frame._show_image_preview(
                request.name, QPixmap.fromImage(cached),
                self._cache.native_size(request.identity, request.version),
            )
            self._finish_request(request)
            return
        try:
            descriptor, path = tempfile.mkstemp(
                prefix="adblab-preview-", suffix=os.path.splitext(request.name)[1],
            )
            os.close(descriptor)
        except OSError:
            self._frame._show_preview_error(request.name, tr("Unable to prepare image preview"))
            self._finish_request(request)
            return
        request.temporary_path = path
        self._temporary_files.add(path)
        if request.identity[2]:
            # 路径属于本页本请求，即使 copy 未返回业务结果也保留清理义务。
            request.remote_path = (
                f"/data/local/tmp/adblab-preview-{self._session_id}-{request.request_id}"
            )
            worker = self._frame._run_adb(
                "shell", explorer_service.root_command(
                    explorer_service.copy_for_root_pull_command(
                        request.identity[1], request.remote_path,
                    ), True,
                ), timeout=120, _device_ip=request.identity[0],
            )
            self._enqueue_stage(request, worker, self._copy_ready)
        else:
            self._start_pull(request)

    def _copy_ready(self, request: _ImageRequest, _worker, result: list) -> None:
        if len(result) < 2 or result[1]:
            self._frame._show_preview_error(
                request.name, result[0] if result else tr("Unable to prepare image preview"),
            )
            self._finish_request(request)
            return
        self._start_pull(request)

    def _start_pull(self, request: _ImageRequest) -> None:
        worker = self._frame._run_transfer(
            "pull", request.remote_path or request.identity[1], request.temporary_path,
            _device_ip=request.identity[0],
        )
        self._enqueue_stage(request, worker, self._pull_ready)

    def _pull_ready(self, request: _ImageRequest, _worker, result: list) -> None:
        if len(result) < 2 or result[1]:
            self._frame._show_preview_error(
                request.name, result[0] if result else tr("Unable to pull image"),
            )
            self._finish_request(request)
            return
        if request.version is None:
            self._start_decode(request)
        else:
            self._enqueue_stage(request, self._version_worker(request), self._version_rechecked)

    def _version_rechecked(self, request: _ImageRequest, _worker, result: list) -> None:
        after = (
            explorer_service.parse_preview_version(result[0])
            if len(result) >= 2 and not result[1] else None
        )
        if after != request.version:
            # 下载期间变化的快照可供本次查看，但不能成为下一次打开的缓存。
            request.version = None
        self._start_decode(request)

    def _start_decode(self, request: _ImageRequest) -> None:
        worker = self._frame._track_worker(PreviewReadWorker(request.temporary_path))
        self._enqueue_stage(request, worker, self._decoded)

    def _decoded(self, request: _ImageRequest, worker: PreviewReadWorker, _result: list) -> None:
        if worker.image.isNull():
            self._frame._show_preview_error(
                request.name, tr("The downloaded image could not be decoded"),
            )
        else:
            self._cache.add(request.identity, request.version, worker.image, worker.native_size)
            self._frame._show_image_preview(
                request.name, QPixmap.fromImage(worker.image), worker.native_size,
            )
        self._finish_request(request)

    def _finish_request(self, request: _ImageRequest) -> None:
        """各阶段真实退出后收尾，远端清理沿原设备和 Root 快照执行一次。"""
        if request.finished:
            return
        request.finished = True
        if self._request is request:
            self._request = None
        if request.temporary_path:
            self._remove_temporary_file(request.temporary_path)
        if not request.remote_path:
            self._frame._transfers.release_cleanup(request.cleanup_token)
            return
        worker = self._frame._run_adb(
            "shell", explorer_service.root_command(
                f"rm -f -- {explorer_service.shell_quote(request.remote_path)}", True,
            ), timeout=10, _cleanup=True, _device_ip=request.identity[0],
        )
        result: list = []
        worker.result_ready.connect(
            lambda *values: result.extend(values), Qt.ConnectionType.QueuedConnection,
        )

        def cleaned():
            if len(result) < 2 or result[1]:
                LogService().log("WARNING", "图片预览的远端临时文件清理失败，设备可能已离线。")
            self._frame._transfers.release_cleanup(request.cleanup_token)

        worker.finished.connect(cleaned, Qt.ConnectionType.QueuedConnection)
        worker.start()

    def cancel_preview(self) -> None:
        """只请求取消当前预览，资源由终态回调收口，不等待或中止普通传输。"""
        self._text_request_id = None
        if self._request is not None:
            self._request.cancelled = True
            self._request = None
        self._frame._transfers.cancel_preview()

    def invalidate_cache(self) -> None:
        """刷新或连接边界失效缓存，阻止旧请求重新写回这一代像素。"""
        self._cache_generation += 1
        self._cache.clear()
        if self._request is not None or self._text_request_id is not None:
            self._frame._close_preview()

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
            self._frame._cleanup_remote_file(dev_tmp)
        try:
            if not self._frame._preview_request_is_current(request_id):
                return
            if error:
                self._frame._show_preview_error(name, output or tr("Unable to pull image"))
                return
            pixmap = _load_image_preview(tmp_path)
            if pixmap.isNull():
                self._frame._show_preview_error(
                    name, tr("The downloaded image could not be decoded")
                )
                return
            self._frame._show_image_preview(name, pixmap)
        finally:
            self._remove_temporary_file(tmp_path)

    def _show_text_viewer(
        self,
        name: str,
        content: bytes | str,
        error: bool,
        full_path: str,
        *,
        request_id: int | None = None,
    ):
        if request_id is not None and not self._frame._preview_request_is_current(request_id):
            return
        if request_id == self._text_request_id:
            self._text_request_id = None
        if error:
            self._frame._show_preview_error(name, str(content))
            return
        raw = content.encode("utf-8") if isinstance(content, str) else content
        source = explorer_service.decode_text_preview(raw, MAX_TEXT_VIEW_BYTES)
        self._frame._show_text_preview(
            name,
            source.text,
            full_path,
            editable=source.editable,
            source=source,
        )

    def _remove_temporary_file(self, path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            self._temporary_files.discard(path)
        except OSError:
            LogService().log("WARNING", "图片预览的本地临时文件暂时无法清理，将在页面关闭时重试。")
        else:
            self._temporary_files.discard(path)

    def dispose(self) -> None:
        """在页面 worker 停止后删除尚未进入完成回调的本地预览文件。"""

        for path in tuple(self._temporary_files):
            self._remove_temporary_file(path)
        self._cache.clear()
