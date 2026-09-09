"""将手动版本检查接入 Qt 异步网络和主窗口关闭生命周期。"""

from __future__ import annotations

import json
import math
import time
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from services.app_update import UpdateError, UpdateSnapshot, parse_release, release_status
from utils.app_metadata import APP_UPDATE_API_URL, APP_VERSION


class QtAppUpdate(QObject):
    """窗口拥有的更新检查器；所有方法在所属 Qt 线程调用，构造时不联网。

    只拥有自己发出的请求。可注入调用方拥有的 manager；默认 manager 随本对象释放。
    关闭先封闭准入，再中止请求与定时器；同步 abort 信号和晚到回调均不得发布结果。
    """

    changed = Signal(object)
    TIMEOUT_MS = 10_000
    COOLDOWN_SECONDS = 5.0
    MAX_RESPONSE_BYTES = 256 * 1024

    def __init__(
        self, parent: QObject | None = None, *, manager: QNetworkAccessManager | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager if manager is not None else QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._body = bytearray()
        self._closing = False
        self._retry_at = 0.0
        self.snapshot = UpdateSnapshot()
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._timeout)
        self._cooldown = QTimer(self)
        self._cooldown.setSingleShot(True)
        self._cooldown.timeout.connect(self._allow_retry)

    @Slot()
    def check(self) -> None:
        """只处理显式检查；合并在途请求，并遵守本地冷却和服务端重试时间。"""

        if self._closing or self._reply is not None or time.monotonic() < self._retry_at:
            return
        self._cooldown.stop()
        request = QNetworkRequest(QUrl(APP_UPDATE_API_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"ADBLab/{APP_VERSION}".encode("ascii"))
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        # 更新源固定；拒绝跳转，避免配置错误或异常响应把查询带到未知站点。
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.AlwaysNetwork,
        )
        request.setTransferTimeout(self.TIMEOUT_MS)
        self._body.clear()
        reply = self._manager.get(request)
        self._reply = reply
        reply.setReadBufferSize(self.MAX_RESPONSE_BYTES + 1)
        reply.readyRead.connect(self._read_response)
        reply.finished.connect(self._finished)
        self._deadline.start(self.TIMEOUT_MS)
        self.snapshot = replace(self.snapshot, status="checking", error="", can_check=False)
        self.changed.emit(self.snapshot)

    @Slot()
    def _read_response(self) -> None:
        reply = self._reply
        if reply is None or self.sender() is not reply:
            return
        self._body.extend(reply.read(self.MAX_RESPONSE_BYTES + 1 - len(self._body)).data())
        if len(self._body) > self.MAX_RESPONSE_BYTES:
            self._fail("invalid_response")

    @Slot()
    def _finished(self) -> None:
        reply = self._reply
        if reply is None or self.sender() is not reply:
            return
        self._read_response()
        if self._reply is not reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status == 429 or (
            status == 403 and (
                reply.rawHeader("X-RateLimit-Remaining").data() == b"0"
                or reply.hasRawHeader("Retry-After")
            )
        ):
            self._fail("rate_limited", retry_seconds=self._retry_delay(reply))
        elif status is not None and status != 200:
            self._fail("unavailable")
        elif reply.error() != QNetworkReply.NetworkError.NoError:
            error: UpdateError = "network"
            if reply.error() == QNetworkReply.NetworkError.SslHandshakeFailedError:
                error = "tls"
            elif reply.error() == QNetworkReply.NetworkError.TimeoutError:
                error = "timeout"
            self._fail(error)
        elif status != 200:
            self._fail("unavailable")
        else:
            try:
                release = parse_release(json.loads(self._body))
                snapshot = UpdateSnapshot(
                    status=release_status(release, APP_VERSION), release=release,
                    checked_at=datetime.now(timezone.utc), can_check=False,
                )
            except (ValueError, UnicodeError, RecursionError):
                self._fail("invalid_response")
                return
            self._complete(snapshot)

    @staticmethod
    def _retry_delay(reply: QNetworkReply) -> float:
        """优先尊重 Retry-After，再结合主限流重置时间；无有效时间时至少等待一分钟。"""

        delays = [60.0]
        retry = bytes(reply.rawHeader("Retry-After").data()).decode("ascii", errors="replace")[:128]
        reset = bytes(reply.rawHeader("X-RateLimit-Reset").data()).decode(
            "ascii", errors="replace",
        )[:128]
        for value, absolute in ((retry, False), (reset, True)):
            try:
                seconds = float(value)
            except ValueError:
                if not value or absolute:
                    continue
                try:
                    seconds = parsedate_to_datetime(value).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    continue
            else:
                if absolute:
                    seconds -= time.time()
            if math.isfinite(seconds):
                delays.append(max(0.0, seconds))
        return max(delays)

    @Slot()
    def _timeout(self) -> None:
        if self._reply is not None:
            self._fail("timeout")

    def _fail(self, error: UpdateError, *, retry_seconds: float = 0.0) -> None:
        self._complete(
            replace(self.snapshot, status="error", error=error, can_check=False),
            retry_seconds=retry_seconds,
        )

    def _detach_reply(self) -> None:
        """先清空当前身份再 abort，防止同步 finished 重入并覆盖终态。"""

        reply, self._reply = self._reply, None
        self._deadline.stop()
        self._body.clear()
        if reply is not None:
            if not reply.isFinished():
                reply.abort()
            reply.deleteLater()

    def _complete(self, snapshot: UpdateSnapshot, *, retry_seconds: float = 0.0) -> None:
        self._detach_reply()
        if self._closing:
            return
        self._retry_at = time.monotonic() + max(self.COOLDOWN_SECONDS, retry_seconds)
        self.snapshot = snapshot
        self._schedule_retry_timer()
        self.changed.emit(snapshot)

    def _schedule_retry_timer(self) -> None:
        # QTimer 使用有符号毫秒整数；很远的服务端时间分段等待，不提前重新请求。
        remaining = max(0.0, self._retry_at - time.monotonic())
        self._cooldown.start(max(1, math.ceil(min(remaining, 2_147_483.0) * 1000)))

    @Slot()
    def _allow_retry(self) -> None:
        if self._closing or self._reply is not None:
            return
        if time.monotonic() < self._retry_at:
            self._schedule_retry_timer()
            return
        self.snapshot = replace(self.snapshot, can_check=True)
        self.changed.emit(self.snapshot)

    def prepare_shutdown(self) -> None:
        """在窗口关闭的 GUI 阶段停止准入、定时器与在途请求，不再发出界面状态。"""

        self._closing = True
        self._cooldown.stop()
        self._detach_reply()
