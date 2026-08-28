"""determinate 进度条组件。"""

from __future__ import annotations

from PySide6.QtWidgets import QProgressBar, QWidget

from gui.styles import BaseStyles
from gui.widgets.fluent._base import repolish

__all__ = ["FluentProgressBar"]


class FluentProgressBar(QProgressBar):
    """determinate 进度条，值域与数值可配置。

    契约：
    * 构造时固化最小值/最大值/当前值；
    * ``set_value`` 与 ``set_range`` 提供与控件语义一致的便捷入口；
    * ``_sync_theme_state()`` 读取当前主题重建进度条样式。
    """

    def __init__(
        self,
        *,
        minimum: int = 0,
        maximum: int = 100,
        value: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setRange(minimum, maximum)
        self.setValue(value)
        self.setTextVisible(False)
        self._sync_theme_state()

    # ── 值 ──────────────────────────────────────────────────────────────

    def set_value(self, value: int) -> None:
        """设置当前值并触发 ``valueChanged``。"""

        self.setValue(value)

    def set_range(self, minimum: int, maximum: int) -> None:
        """同时设置值域上下界。"""

        self.setRange(minimum, maximum)

    # ── 主题 ────────────────────────────────────────────────────────────

    def _sync_theme_state(self) -> None:
        """按当前主题重建进度条样式。"""

        self.setStyleSheet(self._progress_style())
        repolish(self)

    def _progress_style(self) -> str:
        radius = BaseStyles.RADIUS_SM
        return (
            f"QProgressBar {{"
            f" background-color: {BaseStyles.color('INPUT_BG')};"
            f" border: 1px solid {BaseStyles.color('BORDER_COLOR')};"
            f" border-radius: {radius}px; }}"
            f"QProgressBar::chunk {{"
            f" background-color: {BaseStyles.color('BUTTON_ACCENT')};"
            f" border-radius: {radius}px; }}"
        )
