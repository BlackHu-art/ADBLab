"""让应用管理的表格与图文视图共享宿主材质，不改变模型、选择或列布局。"""

from __future__ import annotations

import weakref
from collections.abc import Iterable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractItemView, QTreeView, QWidget
from qfluentwidgets import setCustomStyleSheet
from shiboken6 import isValid

from gui.dialogs.lifecycle import safe_disconnect
from gui.styles import BaseStyles


class AppManagerMaterial(QObject):
    """按实际窗口的云母状态刷新局部表面；对象随页面销毁，重挂宿主后重新绑定。

    FluentWindow 没有材质变化信号，因此在窗口下一次重绘前读取其公开状态。
    签名未变时不重写样式；隐藏页面再次显示也会补齐，避免轮询计时器与全局设置副本。
    本对象独占传入视图的局部 QSS，调用方更新字体后可显式 ``refresh(force=True)``。
    """

    def __init__(self, owner: QWidget, views: Iterable[QAbstractItemView]):
        super().__init__(owner)
        self._owner_ref = weakref.ref(owner)
        self._views = tuple(views)
        self._window_ref: weakref.ReferenceType[QWidget] | None = None
        self._signature: tuple[int, bool, str, tuple[str, ...]] | None = None
        self._applying = False
        self._stopped = False
        owner.installEventFilter(self)
        BaseStyles.theme_changed.connect(self.refresh)
        BaseStyles.fonts_changed.connect(self.refresh)
        self.refresh()

    def refresh(self, _value=None, *, force: bool = False) -> None:
        """仅在 GUI 线程同步主题和透明底板，保留条目、选择与表头尺寸。"""
        owner = self._owner_ref()
        if self._stopped or owner is None or not isValid(owner) or self._applying:
            return
        window = owner.window() or owner
        previous = self._window_ref() if self._window_ref is not None else None
        if previous is not window:
            if previous is not None and isValid(previous) and previous is not owner:
                previous.removeEventFilter(self)
            self._window_ref = weakref.ref(window)
            if window is not owner:
                window.installEventFilter(self)
        mica_query = getattr(window, "isMicaEffectEnabled", None)
        mica = bool(mica_query()) if callable(mica_query) else False
        signature = (
            id(window), mica, BaseStyles.resolved_theme(),
            tuple(view.font().toString() for view in self._views),
        )
        if not force and signature == self._signature:
            return
        self._signature = signature
        self._applying = True
        try:
            for view in self._views:
                self._apply_view(view, mica)
        finally:
            self._applying = False

    def stop(self) -> None:
        """页面进入释放阶段时幂等断开回调，不等待异步 worker 结束或控件销毁。"""
        if self._stopped:
            return
        self._stopped = True
        safe_disconnect(BaseStyles.theme_changed, self.refresh)
        safe_disconnect(BaseStyles.fonts_changed, self.refresh)
        owner = self._owner_ref()
        window = self._window_ref() if self._window_ref is not None else None
        if owner is not None and isValid(owner):
            owner.removeEventFilter(self)
        if window is not None and window is not owner and isValid(window):
            window.removeEventFilter(self)
        self._window_ref = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """借用宿主重绘与页面挂载边界补齐材质，不拦截原有窗口事件。"""
        owner = self._owner_ref()
        window = self._window_ref() if self._window_ref is not None else None
        kind = event.type()
        if watched is owner and kind in (QEvent.Type.ParentChange, QEvent.Type.Show):
            self.refresh()
        elif watched is window and kind in (
            QEvent.Type.UpdateRequest, QEvent.Type.StyleChange, QEvent.Type.PaletteChange,
        ):
            self.refresh()
        return False

    @staticmethod
    def _apply_view(view: QAbstractItemView, mica: bool) -> None:
        """普通行与空白共用底板；交替行只叠轻量中性色，交互绘制仍由 Fluent 负责。"""
        selector = "QTreeView" if isinstance(view, QTreeView) else "QListView"
        font = view.font()
        font_size = f"{font.pointSizeF()}pt" if font.pointSizeF() > 0 else f"{font.pixelSize()}px"
        styles = []
        for theme in ("Light", "Dark"):
            background = "transparent" if mica else BaseStyles.color_for(theme, "INPUT_BG")
            alternate = (
                "rgba(255, 255, 255, 7)" if theme == "Dark" else "rgba(0, 0, 0, 7)"
            ) if mica else BaseStyles.color_for(theme, "INPUT_BG_HOVER")
            border = (
                "rgba(255, 255, 255, 18)" if theme == "Dark" else "rgba(0, 0, 0, 18)"
            ) if mica else BaseStyles.color_for(theme, "BORDER_COLOR")
            styles.append(
                f"{selector} {{ background-color: {background}; "
                f"alternate-background-color: {alternate}; "
                f"color: {BaseStyles.color_for(theme, 'TEXT_PRIMARY')}; "
                f"border: 1px solid {border}; border-radius: {BaseStyles.RADIUS_MD}px; }} "
                "QHeaderView { background-color: transparent; } "
                "QHeaderView::section { background-color: transparent; "
                f"color: {BaseStyles.color_for(theme, 'TEXT_SECONDARY')}; "
                f"border-color: {border}; font-size: {font_size}; }} "
                "QTreeView#appManagerIconList QHeaderView::section { "
                "padding-left: 12px; padding-right: 12px; }"
            )
        setCustomStyleSheet(view, styles[0], styles[1])
        palette = QPalette(view.palette())
        background_color = QColor(0, 0, 0, 0) if mica else BaseStyles.get_color("INPUT_BG")
        alternate_color = (
            QColor(255, 255, 255, 7) if BaseStyles.resolved_theme() == "Dark"
            else QColor(0, 0, 0, 7)
        ) if mica else BaseStyles.get_color("INPUT_BG_HOVER")
        palette.setColor(QPalette.ColorRole.Base, background_color)
        palette.setColor(QPalette.ColorRole.Window, background_color)
        palette.setColor(QPalette.ColorRole.AlternateBase, alternate_color)
        palette.setColor(QPalette.ColorRole.Text, BaseStyles.get_color("TEXT_PRIMARY"))
        view.viewport().setPalette(palette)
        view.viewport().setAutoFillBackground(not mica)
        if isinstance(view, QTreeView):
            view.header().setAutoFillBackground(False)
            view.header().viewport().setAutoFillBackground(False)
        view.viewport().update()
