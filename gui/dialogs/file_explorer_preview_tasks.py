"""提供文件预览的有界像素缓存和后台解码任务，不在工作线程操作控件。"""

from __future__ import annotations

import threading
from collections import OrderedDict

from PySide6.QtCore import QSize, QThread
from PySide6.QtGui import QImage, QImageReader

from services.file_explorer import PreviewVersion

MAX_IMAGE_PREVIEW_DIMENSION = 2048
PreviewIdentity = tuple[str, str, bool, int]


class PreviewImageCache:
    """由页面主线程独占的 LRU 缓存；未知版本和超出预算的图片不保留。"""

    def __init__(self, max_bytes: int = 64 * 1024 * 1024):
        self.max_bytes = max(0, max_bytes)
        self.size_bytes = 0
        self._images: OrderedDict[
            PreviewIdentity, tuple[PreviewVersion, QImage, QSize]
        ] = OrderedDict()

    def get(self, key: PreviewIdentity, version: PreviewVersion | None) -> QImage:
        """仅返回此次设备查询已验证的版本，淘汰相同路径的旧内容。"""
        cached = self._images.get(key)
        if cached is None:
            return QImage()
        if version is None or cached[0] != version:
            self._remove(key)
            return QImage()
        self._images.move_to_end(key)
        return QImage(cached[1])

    def native_size(self, key: PreviewIdentity, version: PreviewVersion | None) -> QSize:
        """原始尺寸与版本绑定；缩略图命中后仍展示源文件的像素尺寸。"""
        cached = self._images.get(key)
        if cached is None or version is None or cached[0] != version:
            return QSize()
        return QSize(cached[2])

    def add(
        self, key: PreviewIdentity, version: PreviewVersion | None, image: QImage,
        native_size: QSize | None = None,
    ) -> None:
        """按实际像素字节数驱逐，并保留原始尺寸；展示像素归控件独立持有。"""
        self._remove(key)
        cost = image.sizeInBytes()
        if version is None or image.isNull() or cost > self.max_bytes:
            return
        while self._images and self.size_bytes + cost > self.max_bytes:
            _, (_, old_image, _) = self._images.popitem(last=False)
            self.size_bytes -= old_image.sizeInBytes()
        source_size = (
            native_size if native_size is not None and not native_size.isEmpty() else image.size()
        )
        self._images[key] = (version, QImage(image), QSize(source_size))
        self.size_bytes += cost

    def _remove(self, key: PreviewIdentity) -> None:
        old = self._images.pop(key, None)
        if old is not None:
            self.size_bytes -= old[1].sizeInBytes()

    def clear(self) -> None:
        """连接代次、手动刷新或页面销毁后释放全部缓存引用。"""
        self._images.clear()
        self.size_bytes = 0


class PreviewReadWorker(QThread):
    """完成解码后才交回 QImage；取消不能强杀解码器，但会丢弃结果像素。"""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.image = QImage()
        self.native_size = QSize()
        self.error = ""
        self._aborted = threading.Event()

    def abort(self) -> None:
        """非阻塞取消；受监督线程保持存活直到正在进行的解码返回。"""
        self._aborted.set()
        self.requestInterruption()

    def run(self) -> None:
        if self._aborted.is_set():
            return
        try:
            reader = QImageReader(self.path)
            native = reader.size()
            self.native_size = QSize(native)
            if native.isValid() and not native.isEmpty():
                scale = min(1.0, MAX_IMAGE_PREVIEW_DIMENSION / max(native.width(), native.height()))
                if scale < 1.0:
                    reader.setScaledSize(QSize(
                        max(1, int(native.width() * scale)),
                        max(1, int(native.height() * scale)),
                    ))
            image = reader.read()
            if not self._aborted.is_set():
                self.image = image
                self.error = "invalid" if image.isNull() else ""
        except (OSError, RuntimeError):
            self.error = "invalid"
