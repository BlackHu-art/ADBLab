"""为投屏工具窗独立应用 DWM 材质，不改变主窗口配置或焦点归属。"""

from __future__ import annotations

import ctypes
import weakref
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from gui.styles import BaseStyles
from gui.window_effects import is_mica_supported, set_dwm_attribute, sync_mica_backdrop


class _Margins(ctypes.Structure):
    """DWM 客户区扩展使用有符号边距，负值表示覆盖整个窗口。"""

    _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]


def _native_mica_available() -> bool:
    return QApplication.platformName() == "windows" and is_mica_supported()


def _extend_frame(hwnd: int, enabled: bool) -> bool:
    """仅扩展本工具窗客户区；显式 HWND 签名避免截断 64 位窗口句柄。"""
    try:
        extend = ctypes.WinDLL("dwmapi").DwmExtendFrameIntoClientArea
    except (AttributeError, OSError):
        return False
    extend.argtypes = [wintypes.HWND, ctypes.POINTER(_Margins)]
    extend.restype = ctypes.c_long
    inset = -1 if enabled else 0
    return extend(hwnd, ctypes.byref(_Margins(inset, inset, inset, inset))) == 0


def _apply_native_mica(hwnd: int, enabled: bool, dark: bool) -> bool:
    """原生调用全部成功才透出材质；关闭或失败时撤销 backdrop 和扩展区。

    工具窗保留不抢焦点语义，失活时由 DWM 显示系统实色后备材质，不伪造激活状态。
    """
    if enabled:
        applied = (
            _extend_frame(hwnd, True)
            and set_dwm_attribute(hwnd, 20, int(dark))
            and set_dwm_attribute(hwnd, 33, 2)
            and sync_mica_backdrop(hwnd, True)
        )
        if applied:
            return True
    sync_mica_backdrop(hwnd, False)
    _extend_frame(hwnd, False)
    set_dwm_attribute(hwnd, 33, 1)
    return False


class RemoteToolbarMaterial(QObject):
    """消费主宿主实际材质并管理两个工具窗；窗口销毁或释放后不再订阅外部事件。"""

    changed = Signal()

    def __init__(self, toolbar: QWidget, popup: QWidget, source: QWidget | None) -> None:
        super().__init__(toolbar)
        self._surfaces = tuple(weakref.ref(item) for item in (toolbar, popup))
        self._source = weakref.ref(source) if source is not None else None
        self._signature: tuple | None = None
        self._applying = False
        self._disposed = False
        self._handles: list[weakref.ReferenceType] = []
        self._active = {id(toolbar): False, id(popup): False}
        for widget in (source, toolbar, popup):
            if widget is not None:
                widget.installEventFilter(self)
        BaseStyles.theme_changed.connect(self.refresh)

    def is_active(self, widget: QWidget) -> bool:
        """返回本工具窗实际启用状态，嵌入式更多面板消费侧栏的同一材质。"""
        return self._active.get(id(widget), False)

    def refresh(self, *_args, force: bool = False) -> None:
        if self._disposed or self._applying:
            return
        source = self._source() if self._source is not None else None
        query = (
            getattr(source, "isMicaEffectEnabled", None)
            if source is not None and isValid(source) else None
        )
        supported = _native_mica_available()
        enabled = supported and callable(query) and bool(query())
        dark = BaseStyles.resolved_theme() == "Dark"
        surfaces = [reference() for reference in self._surfaces]
        if any(widget is None or not isValid(widget) for widget in surfaces):
            return
        windows = [widget for widget in surfaces if widget is not None and widget.isWindow()]
        handles = tuple(
            int(widget.winId()) if widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created) else 0
            for widget in windows
        ) if supported else (0,) * len(windows)
        signature = (enabled, dark, handles)
        if signature == self._signature and not force:
            return
        self._applying = True
        self._signature = signature
        try:
            states = {}
            for widget, hwnd in zip(windows, handles):
                states[id(widget)] = _apply_native_mica(hwnd, enabled, dark) if hwnd else False
                handle = widget.windowHandle()
                if handle is not None and all(item() is not handle for item in self._handles):
                    handle.installEventFilter(self)
                    self._handles.append(weakref.ref(handle))
            toolbar = surfaces[0]
            for widget in surfaces:
                if widget is not None and not widget.isWindow():
                    states[id(widget)] = states.get(id(toolbar), False)
            if states != self._active:
                self._active = states
                self.changed.emit()
        finally:
            self._applying = False

    def dispose(self) -> None:
        """只断开此会话的材质观察，原生窗口由侧栏宿主统一销毁。"""
        if self._disposed:
            return
        self._disposed = True
        BaseStyles.theme_changed.disconnect(self.refresh)
        for reference in (*self._surfaces, *self._handles, self._source):
            widget = reference() if reference is not None else None
            if widget is not None and isValid(widget):
                widget.removeEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind in (
            QEvent.Type.Show, QEvent.Type.WinIdChange, QEvent.Type.ApplicationPaletteChange,
        ):
            self.refresh(force=True)
        elif kind in (
            QEvent.Type.UpdateRequest, QEvent.Type.StyleChange, QEvent.Type.PaletteChange,
        ):
            self.refresh()
        return False
