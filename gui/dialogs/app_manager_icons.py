"""应用图标的可见区加载与会话缓存；后台仅返回 PNG，Qt 图像归 GUI 线程所有。"""

from collections import OrderedDict
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Slot
from PySide6.QtGui import QIcon, QImage, QPixmap

if TYPE_CHECKING:
    from models.app_manager_worker import AppManagerWorker


class AppManagerIcons(QObject):
    """每个设备页面独立持有缓存与代次，刷新或关闭后拒绝旧 worker 结果。"""

    BATCH_SIZE = 12
    CACHE_LIMIT = 512

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.cache: OrderedDict[str, QIcon] = OrderedDict()
        self.failures: set[str] = set()
        self._pending: set[str] = set()
        self._worker: AppManagerWorker | None = None
        self._cancelled = False
        self._epoch = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._load_visible)
        page.icon_list.viewport().installEventFilter(self)
        for bar in (page.icon_list.verticalScrollBar(), page.icon_list.horizontalScrollBar()):
            bar.valueChanged.connect(self.schedule)

    def _allowed(self) -> bool:
        return bool(
            self.page._active and self.page._view_mode and not self.page._closing
            and self.page._can_operate() and not self.page._load_in_progress
        )

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.schedule()
        return super().eventFilter(watched, event)

    def schedule(self, *_args) -> None:
        """合并切换、筛选和滚动产生的请求，表格视图与后台页面不发起图标 I/O。"""
        if self._allowed():
            self._timer.start(100)
        else:
            self._timer.stop()

    def pause(self) -> None:
        """停止继续加载，已接收的图标保留；在途 worker 由页面原有关闭屏障管理。"""
        self._timer.stop()
        if self._worker is not None:
            self._cancelled = True
            self._worker.abort()

    def reset(self) -> None:
        """新列表快照使旧缓存失效，应用升级后不会继续显示旧图标。"""
        self.pause()
        self._epoch += 1
        self.cache.clear()
        self.failures.clear()
        self._pending.clear()

    def decorate(self, package: str) -> None:
        """只更新现有项目的图标与失败提示，保留选择、排序和详情数据。"""
        item = self.page._detail_icon_by_pkg.get(package)
        if item is None:
            return
        if package in self.cache:
            item.setIcon(self.cache[package])
            self.cache.move_to_end(package)
        elif package in self.failures and "图标未读取" not in item.toolTip():
            item.setToolTip(item.toolTip() + "\n图标未读取，点击刷新重试。")

    def _visible_packages(self) -> list[str]:
        view = self.page.icon_list
        viewport = view.viewport().rect()
        packages = []
        for index in range(view.count()):
            item = view.item(index)
            if item.isHidden() or not viewport.intersects(view.visualItemRect(item)):
                continue
            package = item.data(Qt.ItemDataRole.UserRole)
            if package in self.cache:
                self.cache.move_to_end(package)
            elif package and package not in self.failures and package not in self._pending:
                packages.append(package)
                if len(packages) >= self.BATCH_SIZE:
                    break
        return packages

    def _load_visible(self) -> None:
        if not self._allowed() or self._worker is not None:
            return
        packages = self._visible_packages()
        if not packages:
            return
        from gui.dialogs.app_manager import AppManagerWorker

        worker = AppManagerWorker(self.page.device_ip, "load_icon_batch", packages=packages)
        worker.setProperty("iconEpoch", self._epoch)
        self._worker = worker
        self._cancelled = False
        self._pending = set(packages)
        worker.app_icon_loaded.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.page._track_worker(worker)
        worker.start()

    @Slot(str, bytes, str)  # type: ignore[reportArgumentType]  # PySide6 多参数 Slot 的桩类型不完整。
    def _receive(self, package: str, data: bytes, error: str) -> None:
        worker = self.sender()
        if (
            self.page._closing or worker is None or worker is not self._worker
            or worker.property("iconEpoch") != self._epoch or package not in self._pending
        ):
            return
        self._pending.discard(package)
        image = QImage()
        if not error and len(data) <= 256 * 1024:
            image = QImage.fromData(data)
        if image.isNull() or image.width() > 256 or image.height() > 256:
            self.failures.add(package)
        else:
            self.cache[package] = QIcon(QPixmap.fromImage(image))
            while len(self.cache) > self.CACHE_LIMIT:
                self.cache.popitem(last=False)
        self.decorate(package)

    @Slot()
    def _finished(self) -> None:
        worker = self.sender()
        if worker is None or worker is not self._worker:
            return
        if not self.page._closing and worker.property("iconEpoch") == self._epoch:
            if not self._cancelled:
                for package in self._pending:
                    self.failures.add(package)
                    self.decorate(package)
        self._pending.clear()
        self._worker = None
        self.schedule()
