"""主题化分割器组件。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QWidget

from gui.styles import BaseStyles
from gui.widgets.fluent._base import repolish

__all__ = ["FluentSplitter"]


class FluentSplitter(QSplitter):
    """带 hover 高亮手柄的主题化分割器。

    契约：
    * 手柄使用当前主题边框色，hover 时切换为焦点色；
    * ``_sync_theme_state()`` 读取当前主题重建手柄样式。
    """

    def __init__(
        self,
        orientation: Qt.Orientation = Qt.Orientation.Horizontal,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self.setChildrenCollapsible(False)
        self._sync_theme_state()

    # ── 主题 ────────────────────────────────────────────────────────────

    def _sync_theme_state(self) -> None:
        """按当前主题重建手柄样式。"""

        self.setStyleSheet(self._splitter_style())
        repolish(self)

    def _splitter_style(self) -> str:
        handle = BaseStyles.color("BORDER_COLOR")
        hover = BaseStyles.color("BORDER_FOCUS")
        return (
            f"QSplitter::handle {{ background-color: {handle}; }}"
            f"QSplitter::handle:hover {{ background-color: {hover}; }}"
            f"QSplitter::handle:horizontal {{ width: 6px; }}"
            f"QSplitter::handle:vertical {{ height: 6px; }}"
        )
