"""订阅已验证 macOS 会话窗口变化，仅向 GUI 提交刷新通知。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _load_runtime() -> tuple[Any, Any]:
    """延迟加载现有 macOS 依赖，普通模块导入不创建 RunLoop 或系统订阅。"""
    import CoreFoundation
    import objc

    return CoreFoundation, objc


class MacOSWindowSubscription:
    """GUI 主线程拥有 AXObserver 与 RunLoop source，不创建额外线程。

    回调只标记会话待刷新，位置查询和控件移动仍交给已有 GUI 合并入口。
    移动或缩放通知不支持时完整撤销部分注册，让调用方继续使用轮询兜底。
    """

    def __init__(
        self, ax: Any, pid: int, application: Any, window: Any, callback: Callable[[], None],
        *, state_changed: Callable[[], None] | None = None,
    ) -> None:
        self._ax = ax
        self._cf: Any = None
        self._application = application
        self._window = window
        self._callback: Callable[[], None] | None = callback
        self._state_changed = state_changed
        self._observer: Any = None
        self._source: Any = None
        self._runloop: Any = None
        self._registrations: list[tuple[Any, str]] = []
        self._active = False
        # 强引用覆盖 observer 的整个寿命；撤销前不能回收 PyObjC 回调。
        self._native_callback: Any = None
        try:
            if not callable(getattr(ax, "AXObserverCreate", None)):
                raise OSError("macOS 窗口事件不可用")
            try:
                self._cf, objc = _load_runtime()
            except ImportError as error:
                raise OSError("macOS 窗口事件依赖不可用") from error
            # AX 会保留 C 回调，必须显式创建 PyObjC closure，且不能直接装饰绑定方法。
            def native_callback(observer: Any, element: Any, name: str, context: Any) -> None:
                self._on_event(observer, element, name, context)

            self._native_callback = objc.callbackFor(ax.AXObserverCreate)(native_callback)
            error, observer = ax.AXObserverCreate(pid, self._native_callback, None)
            if error != ax.kAXErrorSuccess or observer is None:
                raise OSError("macOS 窗口事件创建失败")
            self._observer = observer
            for element, notification, required in (
                (window, "AXMoved", True),
                (window, "AXResized", True),
                (window, "AXWindowMiniaturized", False),
                (window, "AXWindowDeminiaturized", False),
                (window, "AXUIElementDestroyed", False),
                (window, "AXTitleChanged", False),
                (application, "AXFocusedWindowChanged", False),
                (application, "AXApplicationHidden", False),
                (application, "AXApplicationShown", False),
            ):
                error = ax.AXObserverAddNotification(observer, element, notification, None)
                if error == ax.kAXErrorSuccess:
                    self._registrations.append((element, notification))
                elif required:
                    raise OSError(f"macOS 窗口事件注册失败：{notification} ({error})")
            self._source = ax.AXObserverGetRunLoopSource(observer)
            self._runloop = self._cf.CFRunLoopGetMain()
            self._cf.CFRunLoopAddSource(
                self._runloop, self._source, self._cf.kCFRunLoopCommonModes,
            )
            self._active = True
        except BaseException:
            self.close()
            raise

    @property
    def active(self) -> bool:
        """只有几何通知和主 RunLoop source 均就绪时才使用事件驱动刷新。"""
        return self._active

    def _on_event(self, _observer: Any, element: Any, notification: str, _context: Any) -> None:
        if (not self._active or self._callback is None
                or (element, notification) not in self._registrations):
            return
        if notification not in ("AXMoved", "AXResized") and self._state_changed is not None:
            self._state_changed()
        self._callback()

    def close(self) -> None:
        """先作废晚到和重入通知，再撤销 source/注册，最后释放所有原生引用。"""
        self._active = False
        self._callback = None
        self._state_changed = None
        if self._source is not None:
            self._cf.CFRunLoopRemoveSource(
                self._runloop, self._source, self._cf.kCFRunLoopCommonModes,
            )
            self._source = None
        if self._observer is not None:
            for element, name in reversed(self._registrations):
                self._ax.AXObserverRemoveNotification(self._observer, element, name)
        self._registrations.clear()
        self._observer = None
        self._runloop = None
        self._native_callback = None
        self._application = None
        self._window = None
