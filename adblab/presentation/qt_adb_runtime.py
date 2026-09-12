"""把 ADB 运行实例接入 Qt 信号、延迟启动和应用资源监督。"""

from __future__ import annotations

import weakref

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from core.adb_runtime import AdbRuntime, RuntimeSnapshot
from core.exec import adb_runtime, install_adb_runtime, reset_adb_program_cache
from utils.adb_resolver import invalidate_adb_path_cache, resolve_adb_path


class QtAdbRuntime(QObject):
    """窗口拥有的薄适配器；后台只发信号，不持有窗口或直接操作控件。"""

    ready = Signal()
    changed = Signal(object)
    diagnostic = Signal(str)
    _state_changed = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._accept_updates = True
        self._state_changed.connect(self._publish_current, Qt.ConnectionType.QueuedConnection)
        reference = weakref.ref(self)

        def emit(name: str, *args) -> None:
            owner = reference()
            if owner is not None:
                try:
                    getattr(owner, name).emit(*args)
                except RuntimeError:
                    # 窗口已销毁时不再投递；实际工作资源仍由运行实例自行退出。
                    return

        self.runtime = AdbRuntime(
            resolve_adb_path,
            ready=lambda: emit("ready"),
            changed=lambda _value: emit("_state_changed"),
            diagnostic=lambda message: emit("diagnostic", message),
        )
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start)
        # QObject 意外销毁也封闭后台请求；正常退出仍通过监督器等待线程完成。
        owned_runtime = self.runtime
        self.destroyed.connect(lambda: owned_runtime.close())

    def schedule(self) -> None:
        """仅安排下一个事件循环启动，构造窗口时不进行文件和网络探测。"""
        self._timer.start(0)

    def _start(self) -> None:
        install_adb_runtime(self.runtime)
        self.runtime.start()

    def recheck(self) -> None:
        """用户显式重新检查并恢复自动选择；同时重新解析本地 ADB 客户端。

        解析器与短命令执行器各有一层路径缓存，必须同时失效，否则安装或移除
        platform-tools 之后「重新检测」仍会复用启动时的旧结果。
        """
        invalidate_adb_path_cache()
        reset_adb_program_cache()
        self.runtime.recheck()
        self._publish_current()

    def note_server_restart(self) -> None:
        """本机 ADB 服务被外部重启后立即作废能力并重测。"""
        self.runtime.note_server_restart()
        self._publish_current()

    def set_selection_mode(self, mode: str) -> None:
        """切换执行模式（auto/fast/native）；只影响后续命令，不重放在途请求。"""
        self.runtime.set_mode(mode)
        self._publish_current()

    def set_native_only(self, enabled: bool) -> None:
        """将本次运行的原生选择交给线程安全的策略层。"""
        self.runtime.set_native_only(enabled)
        self._publish_current()

    @Slot()
    def _publish_current(self) -> None:
        """在 GUI 线程读取最新状态，旧后台通知不能覆盖随后发生的手动选择。"""
        if self._accept_updates:
            self.changed.emit(self.runtime.snapshot())

    def prepare_shutdown(self) -> None:
        """取消尚未启动的定时器和当前探测，清理阶段暂保留运行实例。"""
        self._accept_updates = False
        self._timer.stop()
        self.runtime.prepare_shutdown()

    def close(self) -> None:
        """最终封闭运行实例；不从 GUI 线程等待网络或进程。"""
        self._accept_updates = False
        self._timer.stop()
        self.runtime.close()
        if adb_runtime() is self.runtime:
            install_adb_runtime(None)

    def snapshot(self) -> RuntimeSnapshot:
        """为初始化界面返回当前脱敏状态。"""
        return self.runtime.snapshot()
