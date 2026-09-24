"""只拥有启动图标和本地连接的显示进程，不加载设置、Fluent 或设备业务。"""

from __future__ import annotations

import json
import math

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from gui.widgets.startup_splash import StartupSplash


class _SplashSession(QObject):
    """连接断开、父进程结束或完成消息均关闭窗口，所有控件只在本进程主线程使用。"""

    def __init__(self, app: QApplication, server_name: str) -> None:
        super().__init__(app)
        self._app = app
        self._closed = False
        self._buffer = bytearray()
        self._splash = StartupSplash()
        self._splash.first_painted.connect(lambda: self._send("ready"))
        self._splash.cancelled.connect(self._cancelled)
        self._socket = QLocalSocket(self)
        self._socket.connected.connect(self._splash.show)
        self._socket.readyRead.connect(self._read)
        self._socket.disconnected.connect(self.close)
        self._socket.errorOccurred.connect(lambda _error: self.close())
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self.close)
        self._socket.connected.connect(self._timeout.stop)
        self._timeout.start(5000)
        self._socket.connectToServer(server_name)

    def _send(self, kind: str) -> None:
        if not self._closed:
            self._socket.write(json.dumps({"type": kind}).encode("utf-8") + b"\n")
            self._socket.flush()

    def _cancelled(self) -> None:
        self._send("cancelled")
        self.close()

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
