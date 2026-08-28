"""焦点环 token 应用辅助。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from gui.styles import BaseStyles
from gui.widgets.fluent._base import repolish

__all__ = ["FocusRing"]


class FocusRing:
    """按当前主题为宿主控件应用焦点环 QSS（token 应用辅助）。

    契约：
    * 构造时记录宿主原始样式，随后叠加 ``:focus`` 焦点环；
    * ``_sync_theme_state()`` 读取当前主题的 ``BORDER_FOCUS`` 重建焦点环；
    * ``clear()`` 恢复宿主原始样式。
    """

    def __init__(
        self,
        target: QWidget,
        *,
        radius: int | None = None,
        selector: str | None = None,
    ) -> None:
        self._target = target
        self._radius = radius if radius is not None else BaseStyles.RADIUS_MD
        self._selector = selector or type(target).__name__
        self._original = target.styleSheet()
        self._apply()

    # ── 只读访问 ────────────────────────────────────────────────────────

    def target(self) -> QWidget:
        return self._target

    def radius(self) -> int:
        return self._radius

    # ── 配置 ────────────────────────────────────────────────────────────

    def set_radius(self, radius: int) -> None:
        """更新圆角半径并重建焦点环。"""

        self._radius = int(radius)
        self._apply()

    def ring_style(self) -> str:
        """返回当前主题下的焦点环样式片段。"""

        return (
            f"{self._selector}:focus {{"
            f" border: 2px solid {BaseStyles.color('BORDER_FOCUS')};"
            f" border-radius: {self._radius}px; }}"
        )

    def clear(self) -> None:
        """恢复宿主原始样式并移除焦点环。"""

        self._target.setStyleSheet(self._original)
        repolish(self._target)

    # ── 主题 ────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        base = self._original.strip()
        combined = f"{base}\n{self.ring_style()}".strip() if base else self.ring_style()
        self._target.setStyleSheet(combined)
        repolish(self._target)

    def _sync_theme_state(self) -> None:
        """按当前主题重建焦点环。"""

        self._apply()
