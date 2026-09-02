"""主题化状态栏：替代 ``STATUS_BAR_STYLE`` 旧 QSS。"""

from __future__ import annotations

from PySide6.QtWidgets import QStatusBar, QWidget
from qfluentwidgets import qconfig

from gui.styles import BaseStyles
from gui.widgets.fluent._base import repolish

__all__ = ["FluentStatusBar"]


class FluentStatusBar(QStatusBar):
    """状态栏：面板底色 + 顶部细分隔线，主题切换时自重建样式。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._apply_style()
        qconfig.themeChangedFinished.connect(self._apply_style)
        self.destroyed.connect(self._disconnect_theme)

    def _apply_style(self) -> None:
        """按当前主题 token 重建状态栏样式。"""

        bs = BaseStyles
        self.setStyleSheet(
            f"QStatusBar {{ background-color: {bs.color('PANEL_BG')}; "
            f"color: {bs.color('TEXT_PRIMARY')}; "
            f"border-top: 1px solid {bs.color('BORDER_COLOR')}; }}"
        )
        repolish(self)

    def _disconnect_theme(self) -> None:
        """销毁时断开主题信号；解释器收尾阶段 qconfig 可能已删除，容错处理。"""

        try:
            qconfig.themeChangedFinished.disconnect(self._apply_style)
        except (RuntimeError, TypeError):
            pass
