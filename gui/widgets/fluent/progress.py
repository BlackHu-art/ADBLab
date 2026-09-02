"""determinate 进度条组件（迁移到 qfluentwidgets ``ProgressBar``）。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import ProgressBar

__all__ = ["FluentProgressBar"]


class FluentProgressBar(ProgressBar):
    """determinate 进度条，值域与数值可配置。

    契约（沿用自研，调用方无需改动）：
    * 构造时固化最小值/最大值/当前值；
    * ``set_value`` 与 ``set_range`` 提供与控件语义一致的便捷入口；
    * ``_sync_theme_state()`` 请求按当前主题重绘。

    进度条背景与条色由 ``ProgressBar`` 自行绘制，条色取 ``themeColor()``
    （已由主题桥接映射为 ADBLab 的 ``BUTTON_ACCENT``），主题自动跟随。
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

    # ── 值 ──────────────────────────────────────────────────────────────

    def set_value(self, value: int) -> None:
        """设置当前值并触发 ``valueChanged``。"""

        self.setValue(value)

    def set_range(self, minimum: int, maximum: int) -> None:
        """同时设置值域上下界。"""

        self.setRange(minimum, maximum)

    # ── 主题 ────────────────────────────────────────────────────────────

    def _sync_theme_state(self) -> None:
        """按当前主题重绘（颜色由 ``ProgressBar`` 自绘逻辑跟随主题）。"""

        self.update()
