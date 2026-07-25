"""提供跟随主题变化的 SVG 图标加载器。

每次绘制都会把当前主题色注入 SVG 的 currentColor。用法：
    from gui.styles.icon_loader import get_themed_icon

    btn.setIcon(get_themed_icon("gear.svg"))
    dlg.setWindowIcon(get_themed_icon("gear.svg"))

主题变化后图标颜色自动更新，不需要逐个刷新控件。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from gui.styles.theme import _tc
from utils.resource_path import resource_path

# 原始 SVG 内容与主题无关，可跨主题复用缓存。
_SVG: dict[str, str] = {}


def _load_svg(name: str) -> str:
    cached = _SVG.get(name)
    if cached is not None:
        return cached
    path = resource_path(f"resources/icons/{name}")
    try:
        with open(path, encoding="utf-8") as fh:
            _SVG[name] = fh.read()
    except FileNotFoundError:
        _SVG[name] = ""
    return _SVG[name]


class _ThemedIconEngine(QIconEngine):
    """每次 paint() 时渲染 SVG，并注入当前主题颜色。"""

    def __init__(self, name: str):
        super().__init__()
        self._name = name

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State):
        svg = _load_svg(self._name)
        if not svg:
            return
        svg = svg.replace("currentColor", _tc("TEXT_PRIMARY"))
        renderer = QSvgRenderer(svg.encode("utf-8"))
        renderer.render(painter, rect)

    def clone(self) -> _ThemedIconEngine:
        return _ThemedIconEngine(self._name)

    def key(self) -> str:
        return f"themed:{self._name}:{_tc('TEXT_PRIMARY')}"

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:
        return size

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pix = QPixmap(size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        self.paint(p, QRect(0, 0, size.width(), size.height()), mode, state)
        p.end()
        return pix


def get_themed_icon(name: str) -> QIcon:
    """返回始终使用当前主题颜色绘制的 QIcon。"""
    return QIcon(_ThemedIconEngine(name))


def clear_svg_cache() -> None:
    """清空 SVG 文件缓存，供磁盘图标更新后调用。"""
    _SVG.clear()
