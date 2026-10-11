"""只缓存内置静态 SVG 的解析结果，保留 Fluent 的主题和原始矢量绘制。"""

from __future__ import annotations

import weakref
from functools import lru_cache
from typing import TypeVar

from PySide6.QtCore import QRect, QRectF, Qt, QThread
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QIconEngine, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from qfluentwidgets import FluentIcon, FluentIconBase, Theme
from qfluentwidgets.common import icon as fluent_icons

_CACHE_LIMIT = 128
_application_ref: weakref.ReferenceType[QGuiApplication] | None = None
_IconT = TypeVar("_IconT")


def clear_icon_caches(*_args: object) -> None:
    """在 GUI 退出或资源验证边界释放缓存；不查询正在销毁的应用或控件树。"""
    _renderer.cache_clear()
    _rewritten_svg.cache_clear()
    _native_icon.cache_clear()


def _can_cache() -> bool:
    """QObject 解析器仅在应用 GUI 线程复用，后台 QImage 绘制独立创建解析器。"""
    global _application_ref
    app = QGuiApplication.instance()
    if not isinstance(app, QGuiApplication) or QThread.currentThread() != app.thread():
        return False
    if _application_ref is None or _application_ref() is not app:
        clear_icon_caches()
        _application_ref = weakref.ref(app)
        app.aboutToQuit.connect(clear_icon_caches)
        app.destroyed.connect(clear_icon_caches)
    return True


@lru_cache(maxsize=_CACHE_LIMIT)
def _renderer(source: str | bytes) -> QSvgRenderer:
    # 不挂到长寿命父对象，LRU 淘汰时即可在 GUI 线程释放解析器。
    return QSvgRenderer(source)


@lru_cache(maxsize=_CACHE_LIMIT)
def _rewritten_svg(
    path: str, indexes: tuple[int, ...] | None, attributes: tuple[tuple[str, object], ...],
) -> bytes:
    return fluent_icons.writeSvg(path, indexes, **dict(attributes)).encode()


@lru_cache(maxsize=_CACHE_LIMIT)
def _native_icon(path: str) -> QIcon:
    # 原生 QIcon 保留 Qt 的 Disabled/Selected 转换及不同 DPR 的像素缓存。
    return QIcon(path)


def _svg_source(path: str, indexes=None, **attributes) -> str | bytes:
    if not attributes:
        return path
    if _can_cache():
        return _rewritten_svg(
            path, tuple(indexes) if indexes else None, tuple(sorted(attributes.items())),
        )
    return fluent_icons.writeSvg(path, indexes, **attributes).encode()


def render_cached_svg(source: str | bytes, painter: QPainter, rect: QRectF | QRect) -> None:
    """按当前 painter 的变换、DPR 和透明度绘制，不缓存页面背景或低分辨率快照。"""
    renderer = _renderer(source) if _can_cache() else QSvgRenderer(source)
    renderer.render(painter, QRectF(rect))


class CachedSvgIconEngine(QIconEngine):
    """保持 Fluent SvgIconEngine 的模式语义，仅替换重复解析这一内部步骤。"""

    def __init__(self, source: str | bytes) -> None:
        super().__init__()
        self._source = source

    def paint(self, painter, rect, mode, state) -> None:
        render_cached_svg(self._source, painter, rect)

    def clone(self) -> QIconEngine:
        return CachedSvgIconEngine(self._source)

    def pixmap(self, size, mode, state) -> QPixmap:
        image = QImage(size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        pixmap = QPixmap.fromImage(image, Qt.ImageConversionFlag.NoFormatConversion)
        painter = QPainter(pixmap)
        try:
            self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        finally:
            painter.end()
        return pixmap


class _CachedFluentIcon(FluentIconBase):
    """局部包装内置 FluentIcon，未知彩色或字体图标保留它们自己的绘制实现。"""

    def __init__(self, source: FluentIcon) -> None:
        self._source = source

    def path(self, theme=Theme.AUTO) -> str:
        return self._source.path(theme)

    def icon(self, theme=Theme.AUTO, color=None) -> QIcon:
        path = self.path(theme)
        if not color:
            return QIcon(_native_icon(path)) if _can_cache() else QIcon(path)
        source = _svg_source(path, fill=QColor(color).name())
        return QIcon(CachedSvgIconEngine(source))

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes) -> None:
        render_cached_svg(_svg_source(self.path(theme), indexes, **attributes), painter, rect)


@lru_cache(maxsize=_CACHE_LIMIT)
def _fluent_wrapper(icon: FluentIcon) -> _CachedFluentIcon:
    return _CachedFluentIcon(icon)


def cached_fluent_icon(icon: _IconT) -> _IconT | FluentIconBase:
    """按实例接入内置图标缓存，不替换语义查找返回值或第三方全局绘制函数。

    ResourceIcon 已直接使用缓存引擎；ColoredFluentIcon、字体及调用方自定义图标
    可能有额外绘制语义，因此原样交还，重复包装也保持对象身份。
    """
    return _fluent_wrapper(icon) if isinstance(icon, FluentIcon) else icon
