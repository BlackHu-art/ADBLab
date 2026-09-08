"""在受监督线程中读取截图或删除固定图库快照，不接触 GUI 对象。"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from gui.dialogs.lifecycle import QThreadGroupShutdownTask

ImageKey = tuple[str, int, int]


class ScreenshotIOShutdownTask(QThreadGroupShutdownTask):
    """截图线程的监督完成条件与页面一致，必须确认原生 join 已结束。"""

    @staticmethod
    def _running(thread: QThread) -> bool:
        try:
            return thread.isRunning() or not thread.wait(0)
        except RuntimeError:
            return False


class ScreenshotImageCache:
    """页面独占的像素缓存按字节驱逐；超大单图仅保留在当前预览中。"""

    def __init__(self, max_bytes: int = 64 * 1024 * 1024):
        self.max_bytes = max(0, max_bytes)
        self.images: OrderedDict[ImageKey, QImage] = OrderedDict()
        self.size_bytes = 0

    def add(self, key: ImageKey, image: QImage) -> None:
        self.remove_path(key[0])
        cost = image.sizeInBytes()
        if image.isNull() or cost > self.max_bytes:
            return
        while self.images and self.size_bytes + cost > self.max_bytes:
            _, previous = self.images.popitem(last=False)
            self.size_bytes -= previous.sizeInBytes()
        self.images[key] = image
        self.size_bytes += cost

    def remove_path(self, path: str) -> None:
        """文件被替换或移出图库时同时释放该路径的旧像素。"""
        for key in tuple(self.images):
            if key[0] == path:
                self.size_bytes -= self.images.pop(key).sizeInBytes()

    def image(self, path: str) -> QImage:
        for key in reversed(self.images):
            if key[0] == path:
                return self.images[key]
        return QImage()

    def clear(self) -> None:
        self.images.clear()
        self.size_bytes = 0


class ScreenshotReadWorker(QThread):
    """只传递 QImage；修改时间和文件大小在读取前后校验，旧请求不控制页面。"""

    image_ready = Signal(int, object)

    def __init__(
        self, generation: int, paths: tuple[str, ...], cache: dict[ImageKey, QImage],
        reader_factory: Callable[[str], Any], parent=None,
    ):
        super().__init__(parent)
        self.generation = generation
        self.paths = paths
        self.cache = cache
        self.reader_factory = reader_factory
        self._aborted = threading.Event()

    def abort(self) -> None:
        """正在进行的本地解码返回后停止；不启动后续邻图读取。"""
        self._aborted.set()
        self.requestInterruption()

    def run(self) -> None:
        for path in self.paths:
            if self._aborted.is_set() or self.isInterruptionRequested():
                break
            try:
                stat = os.stat(path)
                key = (path, stat.st_mtime_ns, stat.st_size)
                image = self.cache.get(key)
                if image is None:
                    image = self.reader_factory(path).read()
                current = os.stat(path)
                if (current.st_mtime_ns, current.st_size) != key[1:]:
                    result = (path, None, QImage(), "changed")
                else:
                    result = (path, key, image, "" if not image.isNull() else "invalid")
            except (OSError, RuntimeError):
                result = (path, None, QImage(), "invalid")
            # 当前图先发布，邻图预读不能延迟首图显示；资源仍由 finished/join 收口。
            self.image_ready.emit(self.generation, result)
        # 快照只供本次读取复用，不让已结束的 worker 延长整个缓存的像素所有权。
        self.cache.clear()


class ScreenshotDeleteWorker(QThread):
    """逐项删除启动时快照；取消不回滚已删除项，也不触及后续新增图片。"""

    def __init__(self, paths: tuple[str, ...], versions: dict[str, int], parent=None):
        super().__init__(parent)
        self.paths = paths
        self.versions = versions
        self.deleted: list[str] = []
        self.failed: list[str] = []
        self._aborted = threading.Event()
        self._superseded: set[str] = set()
        self._path_lock = threading.Lock()

    def supersede(self, path: str) -> None:
        """同路径新批次使尚未执行的旧删除失效，不撤回已进入的系统调用。"""
        with self._path_lock:
            self._superseded.add(path)

    def abort(self) -> None:
        """系统删除调用不能强杀，取消只阻止剩余快照项。"""
        self._aborted.set()
        self.requestInterruption()

    def run(self) -> None:
        for path in self.paths:
            if self._aborted.is_set() or self.isInterruptionRequested():
                break
            with self._path_lock:
                if path in self._superseded:
                    continue
            try:
                os.remove(path)
            except FileNotFoundError:
                self.deleted.append(path)
            except OSError:
                self.failed.append(path)
            else:
                self.deleted.append(path)
