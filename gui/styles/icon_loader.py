"""Theme-aware icon loader — injects theme color into SVG currentColor on every paint.

Usage:
    from gui.styles.icon_loader import get_themed_icon

    btn.setIcon(get_themed_icon("gear.svg"))
    dlg.setWindowIcon(get_themed_icon("gear.svg"))

Icon colours update automatically on theme change — no widget refresh needed.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from gui.styles.theme import _tc
from utils.resource_path import resource_path

# Raw SVG content cache (doesn't depend on theme)
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
    """Renders an SVG on every paint(), injecting the *current* theme colour."""

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
        return f"themed:{self._name}"

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
    """Return a QIcon that always paints with the current theme colour."""
    return QIcon(_ThemedIconEngine(name))


def clear_svg_cache() -> None:
    """Drop cached SVG files (call if icons are updated on disk)."""
    _SVG.clear()
