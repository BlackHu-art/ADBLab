"""只拥有启动图标和本地连接的显示进程，不加载设置、Fluent 或设备业务。"""

from __future__ import annotations

import json
import math
import os

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from gui.widgets.startup_splash import StartupSplash

_CANCEL_EXIT_CODE = 42
_CANCEL_DRAIN_MS = 350


class _SplashSession(QObject):
    """连接断开、父进程结束或完成消息均关闭窗口，所有控件只在本进程主线程使用。"""

    def __init__(self, app: QApplication, server_name: str) -> None:
        super().__init__(app)
        self._app = app
        self._closed = False
        self._cancelling = False
        self._buffer = bytearray()
        self._splash = StartupSplash()
        self._splash.set_progress(0, animate=os.environ.get("ADBLAB_STARTUP_ANIMATE", "1") != "0")
        self._splash.first_painted.connect(lambda: self._send("ready"))
        self._splash.cancelled.connect(self._cancelled)
        self._socket = QLocalSocket(self)
        self._socket.connected.connect(self._splash.show)
        self._socket.readyRead.connect(self._read)
        self._socket.disconnected.connect(self._connection_lost)
        self._socket.errorOccurred.connect(lambda _error: self._connection_lost())
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self.close)
        self._socket.connected.connect(self._timeout.stop)
        self._cancel_timeout = QTimer(self)
        self._cancel_timeout.setSingleShot(True)
        self._cancel_timeout.timeout.connect(self._finish_cancel)
        self._timeout.start(5000)
        self._socket.connectToServer(server_name)

    def _send(self, kind: str) -> None:
        if not self._closed:
            self._socket.write(json.dumps({"type": kind}).encode("utf-8") + b"\n")
            self._socket.flush()

    def _cancelled(self) -> None:
        if self._closed or self._cancelling:
            return
        self._cancelling = True
        self._splash.finish()
        self._send("cancelled")
        # GUI 立即消失；连接保持到待发送字节排空，超时仍以取消退出码告知父进程。
        self._cancel_timeout.start(_CANCEL_DRAIN_MS)
        self._socket.disconnectFromServer()
        if self._socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self._finish_cancel()

    def _connection_lost(self) -> None:
        if self._cancelling:
            self._finish_cancel()
        else:
            self.close()

    def _finish_cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timeout.stop()
        self._cancel_timeout.stop()
        self._socket.abort()
        self._app.exit(_CANCEL_EXIT_CODE)

    def _read(self) -> None:
        self._buffer.extend(self._socket.readAll().data())
        if len(self._buffer) > 4096:
            self.close()
            return
        while not self._closed and b"\n" in self._buffer:
            line, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            try:
                message = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                self.close()
                return
            if not isinstance(message, dict):
                self.close()
                return
            if message.get("type") == "finish":
                self.close()
            elif message.get("type") == "progress":
                value = message.get("value")
                animate = message.get("animate")
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or not math.isfinite(value) or not isinstance(animate, bool)):
                    self.close()
                    return
                self._splash.set_progress(value, animate=animate)

    def close(self) -> None:
        """先停止动画和连接，再退出事件循环；正常关闭不回报用户取消。"""
        if self._closed:
            return
        self._closed = True
        self._timeout.stop()
        self._cancel_timeout.stop()
        self._splash.finish()
        self._socket.disconnectFromServer()
        # 连接可能在 app.exec 前同步失败；排队退出，避免 quit 被尚未开始的循环忽略。
        QTimer.singleShot(0, self._app, self._app.quit)


def run_startup_splash(server_name: str) -> int:
    """专用 CLI 入口；父连接是存活租约，断连后不保留独立启动窗口。"""
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    session = _SplashSession(app, server_name)
    try:
        return app.exec()
    finally:
        session.close()
