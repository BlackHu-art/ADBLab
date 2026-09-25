"""应用图标的可见区加载与会话缓存；后台仅返回 PNG，Qt 图像归 GUI 线程所有。"""

from collections import OrderedDict
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Slot
from PySide6.QtGui import QIcon, QImage, QPixmap

from gui.i18n import tr

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
        self._fingerprints: dict[str, str] = {}
        self._verified: set[str] = set()
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
            and self.page.load_state != "error"
        )

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.schedule()
        return super().eventFilter(watched, event)

    def schedule(self, *_args) -> None:
        """合并切换、筛选和滚动产生的请求，表格视图与后台页面不发起图标 I/O。"""
        if self._allowed():
            # 到期时读取最新视口，连续滚动不能延长已有请求的等待时间。
            if not self._timer.isActive():
                self._timer.start(100)
        else:
            self._timer.stop()

    def prioritize_visible(self) -> bool:
        """可见文字已补全后，先读取其图标，再继续后台文字查询。"""
        if not self._allowed():
            return False
        if self._worker is not None or self._visible_packages():
            self.schedule()
            return True
        return False

    @property
    def busy(self) -> bool:
        """取消后仍占用设备查询预算，只有 finished 才能归还。"""
        return self._worker is not None

    def pause(self) -> None:
        """停止继续加载，已接收的图标保留；在途 worker 由页面原有关闭屏障管理。"""
        self._timer.stop()
        if self._worker is not None:
            self._cancelled = True
            self._worker.abort()

    def reset(self, *, preserve_cache: bool = False) -> None:
        """刷新暂存候选像素，验证指纹前只显示占位图；关闭时释放全部缓存。"""
        self.pause()
        self._epoch += 1
        for package in self.cache:
            self._restore_placeholder(package)
        if not preserve_cache:
            self.cache.clear()
            self._fingerprints.clear()
        self._verified.clear()
        self.failures.clear()
        self._pending.clear()

    def retain_packages(self, packages: set[str]) -> None:
        """新快照中已卸载的包不再持有像素及其身份信息。"""
        for package in set(self.cache) - packages:
            self.cache.pop(package)
        self._fingerprints = {
            package: value for package, value in self._fingerprints.items()
            if package in packages
        }
        self._verified.intersection_update(packages)

    def validate_metadata(self, package: str, fingerprint: str) -> None:
        """只有非空且相同的设备元数据指纹允许跨刷新复用原图标。"""
        if fingerprint and fingerprint == self._fingerprints.get(package):
            if package in self.cache:
                self._verified.add(package)
        else:
            self.cache.pop(package, None)
            self._verified.discard(package)
            self._restore_placeholder(package)
        if fingerprint:
            self._fingerprints[package] = fingerprint
        else:
            self._fingerprints.pop(package, None)

    def decorate(self, package: str) -> None:
        """只更新现有项目的图标与失败提示，保留选择、排序和详情数据。"""
        item = self.page._detail_icon_by_pkg.get(package)
        if item is None:
            return
        if package in self.cache and package in self._verified:
            item.setIcon(0, self.cache[package])
            self.cache.move_to_end(package)
        elif package in self.failures and tr("图标未读取") not in item.toolTip(0):
            for column in range(4):
                item.setToolTip(column, item.toolTip(column) + tr("\n图标未读取，点击刷新重试。"))

    def _restore_placeholder(self, package: str) -> None:
        """LRU 淘汰同时归还行项目的真实像素引用，缓存上限覆盖两个持有者。"""
        item = self.page._detail_icon_by_pkg.get(package)
        if item is not None:
            item.setIcon(0, self.page._gen_icon(
                item.text(1), item.data(0, Qt.ItemDataRole.UserRole + 1), 48,
            ))

    def _viewport_packages(self) -> list[str]:
        view = self.page.icon_list
        viewport = view.viewport().rect()
        packages = []
        for index in range(view.topLevelItemCount()):
            item = view.topLevelItem(index)
            if item.isHidden() or not viewport.intersects(view.visualItemRect(item)):
                continue
            package = item.data(0, Qt.ItemDataRole.UserRole)
            if package:
                packages.append(package)
        return packages

    def _visible_packages(self) -> list[str]:
        packages = []
        ready = self.page._loaded_detail_packages | self.page._failed_detail_packages
        for package in self._viewport_packages():
            if package not in ready:
                continue
            if package in self.cache and package in self._verified:
                self.cache.move_to_end(package)
            elif package and package not in self.failures and package not in self._pending:
                packages.append(package)
                if len(packages) >= self.BATCH_SIZE:
                    break
        return packages

    def _load_visible(self) -> None:
        if not self._allowed():
            return
        if self._worker is not None:
            # 完全离开旧批次的视口才取消，轻微滚动不会重复部署 helper。
            if self._pending and self._pending.isdisjoint(self._viewport_packages()):
                self.pause()
            return
        if self.page._detail_worker_running:
            return
        if self.page._visible_detail_packages():
            self.page._schedule_visible_detail_load()
            return
        packages = self._visible_packages()
        if not packages:
            return
        from gui.dialogs.app_manager import AppManagerWorker

        expected = {
            package: self._fingerprints[package]
            for package in packages if package in self._fingerprints
        }
        worker = AppManagerWorker(
            self.page.device_ip, "load_icon_batch", packages=packages,
            expected_fingerprints=expected,
        )
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
            or self._cancelled
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
            self._verified.add(package)
            while len(self.cache) > self.CACHE_LIMIT:
                evicted, _icon = self.cache.popitem(last=False)
                self._verified.discard(evicted)
                self._restore_placeholder(evicted)
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
        if not self.page._closing:
            self.page._schedule_visible_detail_load()
