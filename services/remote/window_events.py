"""订阅 Windows 窗口变化，只通知待刷新，不在原生回调中查询或操作窗口。"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

_LOGGER = logging.getLogger(__name__)
_FOREGROUND = 0x0003
_OWNER_EVENTS = frozenset({0x0016, 0x0017, 0x8001, 0x8002, 0x8003, 0x8004, 0x800A, 0x800B, 0x800C})
# 只有原生撤销失败才保留回调地址；继续持有 trampoline，避免系统调用已回收的函数指针。
_RETAINED_SUBSCRIPTIONS: set[WinEventSubscription] = set()


class WinEventSubscription:
    """在 GUI 消息循环线程安装和撤销 OUTOFCONTEXT hook，不创建后台线程。

    Windows 把事件投递到安装线程。对象变化仅订阅已验证 PID 并过滤 HWND；前台
    变化单独全局订阅，以便切到其它进程时及时收起更多面板。调用方仍需重新校验身份。
    """

    def __init__(
        self, user32: ctypes.WinDLL, hwnd: int, pid: int, callback: Callable[[], None],
    ):
        self._user32 = user32
        self._hwnd = hwnd
        self._callback: Callable[[], None] | None = callback
        self._owner_thread = threading.get_ident()
        self._hooks: list[int] = []
        self._active = False
        callback_type = ctypes.WINFUNCTYPE(
            None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
            wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
        )
        # 强引用覆盖全部已安装 hook 的生命周期，不能只把临时 ctypes 对象传给系统。
        self._native_callback = callback_type(self._on_event)
        user32.SetWinEventHook.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, callback_type,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        ]
        user32.SetWinEventHook.restype = wintypes.HANDLE
        user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        user32.UnhookWinEvent.restype = wintypes.BOOL
        try:
            for minimum, maximum, process in (
                (0x8001, 0x800C, pid),
                (0x0016, 0x0017, pid),
                (_FOREGROUND, _FOREGROUND, 0),
            ):
                hook = user32.SetWinEventHook(
                    minimum, maximum, None, self._native_callback, process, 0, 0,
                )
                if not hook:
                    self.close()
                    _LOGGER.debug("注册投屏窗口事件失败，继续轮询")
                    return
                self._hooks.append(int(hook))
        except OSError:
            self.close()
            _LOGGER.debug("注册投屏窗口事件失败，继续轮询", exc_info=True)
            return
        self._active = True

    @property
    def active(self) -> bool:
        """仅全部 hook 注册成功且尚未关闭时，允许调用方降低兜底轮询频率。"""
        return self._active

    def _on_event(
        self, hook: int, event: int, hwnd: int, object_id: int, child_id: int,
        _event_thread: int, _event_time: int,
    ) -> None:
        if not self._active or hook not in self._hooks or object_id != 0 or child_id != 0:
            return
        if event != _FOREGROUND and (hwnd != self._hwnd or event not in _OWNER_EVENTS):
            return
        callback = self._callback
        if callback is not None:
            try:
                callback()
            except Exception:
                # 异常不能穿过 C 回调边界；记录诊断，由调用方的周期快照继续恢复状态。
                _LOGGER.exception("投屏窗口事件通知失败")

    def close(self) -> None:
        """先封闭通知再在安装线程撤销；重复关闭安全，原生失败可在原线程重试。

        撤销失败只保留无业务回调的原生 trampoline，并记录诊断，防止释放后被系统
        再次调用。正常关闭不留下全局引用；调用方不能从后台线程释放此资源。
        """
        self._active = False
        self._callback = None
        if self._hooks and threading.get_ident() != self._owner_thread:
            _RETAINED_SUBSCRIPTIONS.add(self)
            _LOGGER.warning("投屏窗口事件必须在安装线程释放")
            return
        remaining: list[int] = []
        for hook in reversed(self._hooks):
            try:
                removed = self._user32.UnhookWinEvent(hook)
            except OSError:
                removed = False
                _LOGGER.debug("撤销投屏窗口事件失败", exc_info=True)
            if not removed:
                remaining.append(hook)
        self._hooks = remaining
        if remaining:
            _RETAINED_SUBSCRIPTIONS.add(self)
            _LOGGER.warning("投屏窗口事件释放未确认，保留已停用的原生回调")
        else:
            _RETAINED_SUBSCRIPTIONS.discard(self)
