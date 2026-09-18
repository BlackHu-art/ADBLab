"""只读正文的局部材质适配，关闭云母或恢复编辑时交还 Fluent 原生绘制。"""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget
from qfluentwidgets import setCustomStyleSheet
from shiboken6 import isValid

from gui.dialogs.lifecycle import safe_disconnect
from gui.styles.theme import ThemeMixin

_Reader = QPlainTextEdit | QTextEdit
_CONTROLLER_ATTRIBUTE = "_adblab_reading_surface"


class ReadingSurfaceMaterial(QObject):
    """按实际宿主同步阅读表面，不改动文档、字体、选区与滚动位置。

    控制器独占阅读框的局部 QSS；主题和焦点刷新统一转交此处。
    宿主没有材质信号，因此在重绘前检查状态，重挂与重新显示时补齐绑定。
    """

    def __init__(self, owner: QWidget, output: _Reader):
        super().__init__(owner)
        self._owner_ref = weakref.ref(owner)
        self._output_ref = weakref.ref(output)
        self._window_ref: weakref.ReferenceType[QWidget] | None = None
        self._signature: tuple[int, bool, bool, str] | None = None
        # Fluent 完成 polish 后会改变视口填充属性，必须记录完成后的原生状态。
        output.ensurePolished()
        self._native_auto_fill = output.autoFillBackground(), output.viewport().autoFillBackground()
        self._applying = False
        self._stopped = False
        setattr(output, _CONTROLLER_ATTRIBUTE, self)
        output.setProperty("adblabReadingSurface", True)
        owner.installEventFilter(self)
        if output is not owner:
            output.installEventFilter(self)
        ThemeMixin.theme_changed.connect(self.refresh)
        self.refresh()

    def refresh(self, _value=None, *, force: bool = False) -> None:
        """在 GUI 线程同步材质，重复窗口重绘不会重建相同样式。"""
        owner = self._owner_ref()
        output = self._output_ref()
        if (
            self._stopped or self._applying or owner is None or not isValid(owner)
            or output is None or not isValid(output)
        ):
            return
        window = output.window() or owner
        previous = self._window_ref() if self._window_ref is not None else None
        if previous is not window:
            if previous is not None and isValid(previous) and previous not in (owner, output):
                previous.removeEventFilter(self)
            self._window_ref = weakref.ref(window)
            if window not in (owner, output):
                window.installEventFilter(self)
        mica_query = getattr(window, "isMicaEffectEnabled", None)
        mica = bool(mica_query()) if callable(mica_query) else False
        readonly = output.isReadOnly()
        signature = (id(window), mica, readonly, ThemeMixin.resolved_theme())
        if not force and signature == self._signature:
            return
        self._signature = signature
        self._applying = True
        try:
            self._apply_surface(mica and readonly)
        finally:
            self._applying = False

    def stop(self) -> None:
        """页面请求释放时幂等断开回调，不等待后台工作或控件销毁。"""
        if self._stopped:
            return
        self._stopped = True
        safe_disconnect(ThemeMixin.theme_changed, self.refresh)
        owner = self._owner_ref()
        output = self._output_ref()
        window = self._window_ref() if self._window_ref is not None else None
        for widget in {owner, output, window} - {None}:
            if isValid(widget):
                widget.removeEventFilter(self)
        self._window_ref = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """监听挂载、只读切换及宿主重绘，不拦截控件原有事件。"""
        owner = self._owner_ref()
        output = self._output_ref()
        window = self._window_ref() if self._window_ref is not None else None
        kind = event.type()
        if watched in (owner, output) and kind in (
            QEvent.Type.ParentChange, QEvent.Type.Show, QEvent.Type.ReadOnlyChange,
        ):
            self.refresh()
        elif watched is window and kind in (
            QEvent.Type.UpdateRequest, QEvent.Type.StyleChange, QEvent.Type.PaletteChange,
        ):
            self.refresh()
        return False

    def _apply_surface(self, transparent: bool) -> None:
        """仅覆盖云母阅读底板；原生焦点底线、选区和文字仍由 Fluent 维护。"""
        output = self._output_ref()
        if output is None or not isValid(output):
            return
        selector = "PlainTextEdit" if isinstance(output, QPlainTextEdit) else "TextEdit"
        style = (
            f"{selector}, {selector}:hover, {selector}:focus, {selector}:disabled "
            "{ background-color: transparent; }"
        ) if transparent else ""
        # 空调色板解除显式颜色，恢复当前主题继承，不能恢复创建时的旧主题快照。
        palette = QPalette()
        if transparent:
            palette.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
            palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        output.setPalette(palette)
        output.viewport().setPalette(palette)
        setCustomStyleSheet(output, style, style)
        # 相同 custom 属性不会触发 Fluent watcher；强制刷新也要重新应用原生文字调色板。
        output.setStyleSheet(output.styleSheet())
        output.setAutoFillBackground(False if transparent else self._native_auto_fill[0])
        output.viewport().setAutoFillBackground(
            False if transparent else self._native_auto_fill[1],
        )
        output.viewport().update()


def ensure_reading_surface(widget: _Reader) -> ReadingSurfaceMaterial:
    """复用控件已有控制器，避免重复主题连接和多份材质状态。"""
    controller = getattr(widget, _CONTROLLER_ATTRIBUTE, None)
    if isinstance(controller, ReadingSurfaceMaterial) and isValid(controller):
        controller.refresh(force=True)
        return controller
    return ReadingSurfaceMaterial(widget, widget)


def stop_reading_surface(widget: _Reader) -> None:
    """停止已挂载的控制器；释放路径不能为尚未适配的控件创建新对象。"""
    controller = getattr(widget, _CONTROLLER_ATTRIBUTE, None)
    if isinstance(controller, ReadingSurfaceMaterial) and isValid(controller):
        controller.stop()
