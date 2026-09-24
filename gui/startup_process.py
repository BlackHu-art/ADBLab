"""以独立 Qt 进程显示启动图标，父进程只传送已完成阶段和生命周期消息。"""

from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from gui.widgets.startup_splash import StartupSplash

_START_TIMEOUT_MS = 5000
_MAX_MESSAGE_BYTES = 4096


def _worker_command(server_name: str) -> list[str]:
    """冻结子进程复用当前解包环境；源码运行始终通过同一绝对路径入口分派。"""
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve().parents[1] / "main.py"))
    return [*command, "--startup-splash", server_name]


class StartupSplashProcess(QObject):
    """拥有显示进程及本地降级窗；调用方退出事件循环后必须调用 shutdown。"""

    first_painted = Signal()
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.setMaxPendingConnections(1)
        self._server.newConnection.connect(self._connected)
        self._socket: QLocalSocket | None = None
        self._process = QProcess(self)
        self._process.setStandardOutputFile(QProcess.nullDevice())
        self._process.setStandardErrorFile(QProcess.nullDevice())
        self._process.errorOccurred.connect(self._process_error)
        self._process.finished.connect(self._process_finished)
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self._fallback)
        self._terminate_timer = QTimer(self)
        self._terminate_timer.setSingleShot(True)
        self._terminate_timer.timeout.connect(self._terminate)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._kill)
        self._local: StartupSplash | None = None
        self._buffer = bytearray()
        self._shown = False
        self._closed = False
        self._ready = False
        self._cancelled = False
        self._draining = False
        self._progress = 0.0
        self._animate = False

    def show(self) -> None:
        """只启动一次显示进程；真正首帧到达前不放行主窗口初始化。"""
        if self._shown or self._closed:
            return
        self._shown = True
        name = "adblab-startup-" + uuid4().hex
        if not self._server.listen(name):
            self._fallback()
            return
        command = _worker_command(name)
        self._startup_timer.start(_START_TIMEOUT_MS)
        # 继承冻结环境，使 onefile 子进程复用现有资源，不重复解包。
        self._process.start(command[0], command[1:])

    def set_progress(self, value: float, *, animate: bool = True) -> None:
        """保留单调真实进度；连接前合并消息，关闭后的晚到进度无效。"""
        if self._closed or not math.isfinite(value):
            return
        value = max(0.0, min(100.0, float(value)))
        if value < self._progress:
            return
        self._progress, self._animate = value, animate
        if self._local is not None:
            self._local.set_progress(value, animate=animate)
        else:
            self._send_progress()

    def _send_progress(self) -> None:
        self._send({"type": "progress", "value": self._progress, "animate": self._animate})

    def _send(self, message: dict[str, object]) -> None:
        if (self._socket is None
                or self._socket.state() != QLocalSocket.LocalSocketState.ConnectedState):
            return
        self._socket.write(json.dumps(message).encode("utf-8") + b"\n")
        # 下一启动阶段可能立即占用 GUI；现在提交到内核，让子进程独立推进动画。
        self._socket.flush()

    def _connected(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        if self._closed or self._local is not None or self._socket is not None:
            socket.abort()
            socket.deleteLater()
            return
        self._socket = socket
        socket.setParent(self)
        socket.readyRead.connect(self._read)
        socket.disconnected.connect(self._disconnected)
        self._server.close()
        self._read()

    def _read(self) -> None:
        if self._socket is None or self._closed:
            return
        self._buffer.extend(self._socket.readAll().data())
        if len(self._buffer) > _MAX_MESSAGE_BYTES:
            self._fallback()
            return
        while b"\n" in self._buffer:
            line, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            try:
                message = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                self._fallback()
                return
            if not isinstance(message, dict):
                self._fallback()
                return
            if message.get("type") == "ready":
                self._startup_timer.stop()
                self._send_progress()
                self._publish_ready()
            elif message.get("type") == "cancelled":
                self._publish_cancelled()

    def _publish_ready(self) -> None:
        if self._closed or self._ready:
            return
        self._ready = True
        self.first_painted.emit()

    def _publish_cancelled(self) -> None:
        if self._closed or self._cancelled:
            return
        self._cancelled = True
        self.finish()
        self.cancelled.emit()

    def _disconnected(self) -> None:
        self._worker_lost()

    def _process_error(self, _error: QProcess.ProcessError) -> None:
        self._worker_lost()

    def _process_finished(self, _code: int, _status: QProcess.ExitStatus) -> None:
        self._terminate_timer.stop()
        self._kill_timer.stop()
        self._worker_lost()

    def _worker_lost(self) -> None:
        """退出通知可早于 socket 通知；先无等待地收取尾包，避免用户取消变成降级。"""
        if self._closed or self._local is not None or self._draining:
            return
        self._draining = True
        try:
            if self._socket is not None:
                if (not self._socket.bytesAvailable()
                        and self._socket.state() == QLocalSocket.LocalSocketState.ConnectedState):
                    self._socket.waitForReadyRead(0)
                self._read()
        finally:
            self._draining = False
        self._fallback()

    def _fallback(self) -> None:
        if self._closed or self._local is not None:
            return
        logging.getLogger(__name__).warning("启动显示进程不可用，使用本地启动图标")
        self._startup_timer.stop()
        self._local = StartupSplash()
        self._local.first_painted.connect(self._publish_ready)
        self._local.cancelled.connect(self._publish_cancelled)
        self._local.set_progress(self._progress, animate=False)
        self._local.show()
        self._disconnect()
        self._schedule_reap()

    def _disconnect(self) -> None:
        self._server.close()
        if self._socket is not None:
            socket, self._socket = self._socket, None
            socket.disconnectFromServer()
            socket.deleteLater()

    def _schedule_reap(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._terminate_timer.start(250)

    def _terminate(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.terminate()
            self._kill_timer.start(250)

    def _kill(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()

    def finish(self) -> None:
        """立即请求关闭且不等待动画；取消信号与正常交接互斥，重复调用安全。"""
        if self._closed:
            return
        self._closed = True
        self._startup_timer.stop()
        if self._local is not None:
            self._local.finish()
            self._local.deleteLater()
        self._send({"type": "finish"})
        self._disconnect()
        self._schedule_reap()

    def shutdown(self) -> None:
        """事件循环退出后回收进程；短预算正常等待后依次终止、强杀并确认退出。"""
        self.finish()
        self._terminate_timer.stop()
        self._kill_timer.stop()
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        if self._process.waitForFinished(200):
            return
        self._process.terminate()
        if self._process.waitForFinished(200):
            return
        self._process.kill()
        if not self._process.waitForFinished(1000):
            raise RuntimeError("startup splash process did not exit after kill")
