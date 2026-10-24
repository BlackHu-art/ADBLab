"""在独立 Qt 线程下载并验证安装器，以发布代次隔离取消和晚到回调。"""

from __future__ import annotations

import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from services.app_update import InstallerAsset, UpdateSnapshot
from services.installer_update import (
    DownloadWriter,
    VerifiedInstaller,
    find_cached,
    validate_installer_asset,
)
from utils.app_metadata import APP_RELEASES_URL, APP_VERSION

InstallerStatus = Literal["idle", "downloading", "ready", "cancelled", "error"]
ManagerFactory = Callable[[QObject], QNetworkAccessManager]


@dataclass(frozen=True)
class InstallerSnapshot:
    """下载状态；只有完成文件验证且工作线程已退出后才向界面公开 ready。"""

    status: InstallerStatus = "idle"
    received: int = 0
    total: int = 0
    error: str = ""
    verified: VerifiedInstaller | None = None


class _DownloadWorker(QObject):
    """网络、计时器与文件仅由工作线程操作，每轮最多写入四个 64 KiB 块。"""

    updated = Signal(int, object, object)
    done = Signal()
    CHUNK_BYTES = 64 * 1024
    CHUNKS_PER_TICK = 4
    MAX_REDIRECTS = 3

    def __init__(
        self, generation: int, asset: InstallerAsset, cache_root: Path | None,
        manager_factory: ManagerFactory, idle_timeout: int, total_timeout: int,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.asset = asset
        self._cache_root = cache_root
        self._manager_factory = manager_factory
        self._idle_timeout = idle_timeout
        self._total_timeout = total_timeout
        self._manager: QNetworkAccessManager | None = None
        self._reply: QNetworkReply | None = None
        self._writer: DownloadWriter | None = None
        self._idle: QTimer | None = None
        self._total: QTimer | None = None
        self._drain_timer: QTimer | None = None
        self._received = 0
        self._redirects = 0
        self._done = False
        self._started = 0.0

    @Slot()
    def begin(self) -> None:
        """在线程启动后创建全部有亲和性的资源，缓存恢复也遵守取消和总期限。"""

        self._started = time.monotonic()
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._timeout)
        self._total = QTimer(self)
        self._total.setSingleShot(True)
        self._total.timeout.connect(self._timeout)
        self._drain_timer = QTimer(self)
        self._drain_timer.setSingleShot(True)
        self._drain_timer.timeout.connect(self._drain)
        self._total.start(self._total_timeout)
        try:
            if self._cancelled():
                raise InterruptedError
            cached = find_cached(self.asset, self._cache_root, cancelled=self._cancelled)
            if cached is not None:
                self._received = self.asset.size
                self._complete("ready", verified=cached)
                return
            self._writer = DownloadWriter(self.asset, self._cache_root)
            self._manager = self._manager_factory(self)
            self._request(self.asset.download_url)
        except InterruptedError:
            self._interrupted()
        except ValueError:
            self._complete("error", error="verification")
        except OSError:
            self._complete("error", error="disk")
        except RuntimeError:
            self._complete("error", error="network")

    def _cancelled(self) -> bool:
        return (
            QThread.currentThread().isInterruptionRequested()
            or time.monotonic() - self._started >= self._total_timeout / 1000
        )

    def _interrupted(self) -> None:
        if QThread.currentThread().isInterruptionRequested():
            self._complete("cancelled")
        else:
            self._complete("error", error="timeout")

    def _request(self, url: str) -> None:
        if self._cancelled():
            self._interrupted()
            return
        assert self._manager is not None and self._idle is not None
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.AlwaysNetwork,
        )
        request.setRawHeader(b"User-Agent", f"ADBLab/{APP_VERSION}".encode("ascii"))
        request.setRawHeader(b"Accept-Encoding", b"identity")
        request.setTransferTimeout(self._idle_timeout)
        reply = self._manager.get(request)
        self._reply = reply
        reply.setReadBufferSize(self.CHUNK_BYTES * self.CHUNKS_PER_TICK)
        reply.metaDataChanged.connect(self._schedule_drain)
        reply.readyRead.connect(self._schedule_drain)
        reply.finished.connect(self._schedule_drain)
        reply.sslErrors.connect(self._tls_failed)
        self._idle.start(self._idle_timeout)

    @Slot()
    def _schedule_drain(self) -> None:
        if self._done or self.sender() is not self._reply:
            return
        assert self._drain_timer is not None
        if not self._drain_timer.isActive():
            self._drain_timer.start(0)

    @staticmethod
    def _redirect_url(reply: QNetworkReply) -> str:
        """只允许已批准的 CDN HTTPS 地址；不接受相对地址、身份信息或片段。"""

        raw = bytes(reply.rawHeader("Location").data())
        url = raw.decode("ascii")
        parsed = urlsplit(url)
        if (
            not url or url != url.strip() or any(ord(char) < 33 for char in url)
            or parsed.scheme != "https" or parsed.hostname != "release-assets.githubusercontent.com"
            or parsed.port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or "#" in url
        ):
            raise ValueError("Invalid installer redirect")
        return url

    def _headers_valid(self, reply: QNetworkReply) -> bool:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status in (301, 302, 303, 307, 308):
            try:
                url = self._redirect_url(reply)
                if self._redirects >= self.MAX_REDIRECTS:
                    raise ValueError("Too many redirects")
            except (ValueError, UnicodeError):
                self._complete("error", error="redirect")
                return False
            self._redirects += 1
            self._detach_reply()
            self._request(url)
            return False
        if reply.error() != QNetworkReply.NetworkError.NoError:
            error = "network"
            if reply.error() == QNetworkReply.NetworkError.SslHandshakeFailedError:
                error = "tls"
            elif reply.error() == QNetworkReply.NetworkError.TimeoutError:
                error = "timeout"
            self._complete("error", error=error)
            return False
        if status is None and not reply.isFinished():
            return False
        if status != 200:
            self._complete("error", error="unavailable")
            return False
        if reply.hasRawHeader("Content-Length"):
            length = bytes(reply.rawHeader("Content-Length").data())
            if not length.isdigit() or len(length) > 12 or int(length) != self.asset.size:
                self._complete("error", error="invalid_response")
                return False
        encoding = bytes(reply.rawHeader("Content-Encoding").data()).lower()
        if encoding not in (b"", b"identity"):
            self._complete("error", error="invalid_response")
            return False
        return True

    @Slot()
    def _drain(self) -> None:
        """有限分块后归还事件循环，确保网络缓冲充满时仍能处理取消和超时。"""

        if self._done:
            return
        if self._cancelled():
            self._interrupted()
            return
        reply = self._reply
        if reply is None or not self._headers_valid(reply):
            return
        assert self._writer is not None and self._idle is not None
        assert self._drain_timer is not None
        try:
            for _ in range(self.CHUNKS_PER_TICK):
                if self._cancelled():
                    raise InterruptedError
                if reply.bytesAvailable() <= 0:
                    break
                data = bytes(reply.read(self.CHUNK_BYTES).data())
                if not data:
                    break
                self._writer.write(data)
                self._received += len(data)
                self._idle.start(self._idle_timeout)
            self.updated.emit(self.generation, self.asset, self._snapshot("downloading"))
            if reply.bytesAvailable() > 0:
                self._drain_timer.start(0)
            elif reply.isFinished():
                verified = self._writer.finish(cancelled=self._cancelled)
                self._writer = None
                self._complete("ready", verified=verified)
        except InterruptedError:
            self._interrupted()
        except ValueError:
            self._complete("error", error="verification")
        except OSError:
            self._complete("error", error="disk")

    @Slot()
    def _timeout(self) -> None:
        self._complete("error", error="timeout")

    @Slot()
    def _tls_failed(self) -> None:
        if self.sender() is self._reply:
            self._complete("error", error="tls")

    @Slot()
    def cancel(self) -> None:
        """取消由队列送入所属线程；先撤销回调身份，再中止同步发信号的 reply。"""

        self._complete("cancelled")

    def _detach_reply(self) -> None:
        reply, self._reply = self._reply, None
        if reply is not None:
            if not reply.isFinished():
                reply.abort()
            reply.deleteLater()

    def _snapshot(
        self, status: InstallerStatus, error: str = "", verified: VerifiedInstaller | None = None,
    ) -> InstallerSnapshot:
        return InstallerSnapshot(status, self._received, self.asset.size, error, verified)

    def _complete(
        self, status: InstallerStatus, *, error: str = "",
        verified: VerifiedInstaller | None = None,
    ) -> None:
        """先封闭重入，再释放本任务文件；失败清理不能发布 ready。"""

        if self._done:
            return
        self._done = True
        for timer in (self._idle, self._total, self._drain_timer):
            if timer is not None:
                timer.stop()
        self._detach_reply()
        if self._writer is not None:
            try:
                self._writer.cancel()
            except (OSError, ValueError):
                status, error, verified = "error", "disk", None
            self._writer = None
        self.updated.emit(self.generation, self.asset, self._snapshot(status, error, verified))
        self.done.emit()


class QtInstallerUpdate(QObject):
    """窗口拥有的显式下载器；GUI 发意图，监督器只调用线程安全的 wait/is_running。

    已退出 QThread 随 owner 保存至最终销毁，避免监督等待与 GUI deleteLater 竞争。
    重新检查撤销旧结果，只有最新 available 发布绑定的资产可创建一次下载。
    """

    changed = Signal(object)
    _cancel_worker = Signal()
    IDLE_TIMEOUT_MS = 30_000
    TOTAL_TIMEOUT_MS = 30 * 60 * 1000

    def __init__(
        self, parent: QObject | None = None, *, cache_root: Path | None = None,
        manager_factory: ManagerFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self._cache_root = cache_root
        self._manager_factory = manager_factory or QNetworkAccessManager
        self._allowed_asset: InstallerAsset | None = None
        self._closing = False
        self._generation = 0
        self._thread: QThread | None = None
        self._threads: list[QThread] = []
        self._worker: _DownloadWorker | None = None
        self._pending: InstallerSnapshot | None = None
        self.snapshot = InstallerSnapshot()
        self._join_timer = QTimer(self)
        self._join_timer.setInterval(1)
        self._join_timer.timeout.connect(self._settle)

    @Slot(object)  # type: ignore[reportArgumentType]  # PySide6 带参数的 Slot 桩不完整。
    def set_release(self, snapshot: UpdateSnapshot) -> None:
        """更新发布准入；冷却标记变化不撤销同一结果，检查和失败立即作废旧代次。"""

        if self._closing:
            return
        asset = snapshot.installer_asset if snapshot.status == "available" else None
        if asset is not None:
            try:
                validate_installer_asset(asset)
                if (
                    snapshot.release is None or snapshot.release.version != asset.version
                    or snapshot.release.url != f"{APP_RELEASES_URL}/tag/{asset.tag}"
                ):
                    raise ValueError("Release does not match installer")
            except ValueError:
                asset = None
        if asset == self._allowed_asset:
            return
        self._allowed_asset = asset
        self._invalidate()
        self._publish(InstallerSnapshot())

    def start(self, asset: InstallerAsset) -> bool:
        """只启动本轮允许的资产；重复点击、关闭和旧资产都不创建线程。"""

        if (sys.platform != "win32" or self._closing or asset != self._allowed_asset
                or self._allowed_asset is None):
            return False
        self._settle()
        if self._thread is not None or self.snapshot.status == "ready":
            return False
        self._generation += 1
        thread = QThread(self)
        worker = _DownloadWorker(
            self._generation, asset, self._cache_root, self._manager_factory,
            self.IDLE_TIMEOUT_MS, self.TOTAL_TIMEOUT_MS,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.begin)
        worker.updated.connect(self._on_snapshot)
        worker.done.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(self._settle)
        self._cancel_worker.connect(worker.cancel, Qt.ConnectionType.QueuedConnection)
        self._thread, self._worker = thread, worker
        self._threads.append(thread)
        self._pending = None
        thread.start()
        self._publish(InstallerSnapshot("downloading", total=asset.size))
        return True

    @Slot(int, object, object)  # type: ignore[reportArgumentType]  # PySide6 多参数 Slot 桩不完整。
    def _on_snapshot(
        self, generation: int, asset: InstallerAsset, snapshot: InstallerSnapshot,
    ) -> None:
        if self._closing or generation != self._generation or asset != self._allowed_asset:
            return
        if snapshot.status == "downloading":
            self._publish(snapshot)
        else:
            self._pending = snapshot
            self._settle()

    @Slot()
    def _settle(self) -> None:
        thread = self._thread
        if thread is None:
            return
        if not thread.wait(0):
            if not self._closing and (self._pending is not None or not thread.isRunning()):
                self._join_timer.start()
            return
        self._join_timer.stop()
        self._thread = self._worker = None
        pending, self._pending = self._pending, None
        if pending is not None:
            self._publish(pending)

    def _publish(self, snapshot: InstallerSnapshot) -> None:
        if not self._closing:
            self.snapshot = snapshot
            self.changed.emit(snapshot)

    def _invalidate(self) -> None:
        self._generation += 1
        self._pending = None
        if self._thread is not None:
            self._thread.requestInterruption()
            self._cancel_worker.emit()

    @Slot()
    def cancel(self) -> None:
        """GUI 立即撤销可安装结果，真实资源由工作线程停止并由监督器确认 join。"""

        if self._closing:
            return
        self._invalidate()
        self._publish(InstallerSnapshot("cancelled"))

    def prepare_shutdown(self) -> None:
        """在 GUI 关闭阶段封闭准入并请求取消，不同步等待磁盘或网络。"""

        self._closing = True
        self._allowed_asset = None
        self._join_timer.stop()
        self._invalidate()

    def wait(self, timeout: float) -> bool:
        """供监督后台使用秒级总预算，确认每条实际线程已 join；不操作 Qt 控件。"""

        deadline = time.monotonic() + max(0.0, timeout)
        for thread in tuple(self._threads):
            remaining = max(0.0, deadline - time.monotonic())
            if not thread.wait(math.ceil(min(remaining, 2_147_483.0) * 1000)):
                return False
        return True

    def is_running(self) -> bool:
        """未取得零等待 join 证明前均视为仍有资源，由关闭监督继续等待。"""

        return any(not thread.wait(0) for thread in tuple(self._threads))
