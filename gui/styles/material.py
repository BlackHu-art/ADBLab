"""按控件实际宿主管理材质刷新，不读取尚未生效的持久化选项。"""

from __future__ import annotations

import weakref
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from gui.styles.theme import ThemeMixin


def is_mica_active(widget: QWidget) -> bool:
    """仅查询当前顶层宿主；普通独立窗口不继承父窗口的云母设置。"""
    window = widget.window() or widget
    query = getattr(window, "isMicaEffectEnabled", None)
    return bool(query()) if callable(query) else False


class MaterialObserver(QObject):
    """由控件拥有的材质观察器，挂载和宿主变化时幂等同步局部表面。"""

    def __init__(self, widget: QWidget, apply: Callable[[QWidget, bool], None]):
        super().__init__(widget)
        self._widget = weakref.ref(widget)
        self._window: weakref.ReferenceType[QWidget] | None = None
        self._apply = apply
        self._signature: tuple[int, bool, str, str] | None = None
        self._applying = False
        widget.installEventFilter(self)
        ThemeMixin.theme_changed.connect(self.refresh)
        self.refresh()

    def refresh(self, _value=None, *, force: bool = False) -> None:
        """只在状态变化时重建样式，避免样式事件递归触发重绘。"""
        widget = self._widget()
        if self._applying or widget is None or not isValid(widget):
            return
        window = widget.window() or widget
        previous = self._window() if self._window is not None else None
        if previous is not window:
            if previous is not None and isValid(previous) and previous is not widget:
                previous.removeEventFilter(self)
            self._window = weakref.ref(window)
            if window is not widget:
                window.installEventFilter(self)
        mica = is_mica_active(widget)
        signature = (id(window), mica, ThemeMixin.resolved_theme(), ThemeMixin.accent_color())
        if not force and signature == self._signature:
            return
        self._signature = signature
        self._applying = True
        try:
            self._apply(widget, mica)
        finally:
            self._applying = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """观察显示、重挂和宿主刷新，保留原事件分发与控件交互。"""
        widget = self._widget()
        window = self._window() if self._window is not None else None
        kind = event.type()
        if watched is widget and kind in (QEvent.Type.ParentChange, QEvent.Type.Show):
            self.refresh()
        elif watched is window and kind in (
            QEvent.Type.UpdateRequest, QEvent.Type.StyleChange, QEvent.Type.PaletteChange,
        ):
            self.refresh()
        return False


def ensure_material_observer(
    widget: QWidget, apply: Callable[[QWidget, bool], None],
) -> MaterialObserver:
    """重复配置复用同一观察器；回调不得持有控件的额外强引用。"""
    observer = getattr(widget, "_adblab_material_observer", None)
    if isinstance(observer, MaterialObserver) and isValid(observer):
        observer.refresh(force=True)
        return observer
    observer = MaterialObserver(widget, apply)
    setattr(widget, "_adblab_material_observer", observer)
    return observer
