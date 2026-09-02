"""主题化分组框：替代 ``GROUP_BOX_STYLE`` 旧 QSS。

分组框标题上边距依赖当前界面字号（``group_box_title_margin``），因此除主题切换
（``qconfig.themeChangedFinished``）外，还需在字体变化（``BaseStyles.fonts_changed``）
时重建样式。
"""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QWidget
from qfluentwidgets import qconfig

from gui.styles import BaseStyles
from gui.widgets.fluent._base import repolish

__all__ = ["ScalableGroupBox"]


class ScalableGroupBox(QGroupBox):
    """主题化、标题净空随字号缩放的分组框。"""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(title, parent)
        self._apply_style()
        qconfig.themeChangedFinished.connect(self._apply_style)
        BaseStyles.fonts_changed.connect(self._apply_style)
        self.destroyed.connect(self._disconnect)

    def _apply_style(self, *_args) -> None:
        """按当前主题 token 与字号重建分组框样式。"""

        bs = BaseStyles
        title_margin = bs.group_box_title_margin()
        self.setStyleSheet(
            f"""
            QGroupBox {{
                background-color: {bs.color('PANEL_BG')};
                border: 1px solid {bs.color('BORDER_COLOR')};
                border-radius: {bs.RADIUS_LG}px; margin-top: {title_margin}px;
                padding: 2px 4px 1px 4px;
                font-weight: bold; color: {bs.color('TEXT_PRIMARY')};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 0 8px; left: 10px; color: {bs.color('GROUP_TITLE_COLOR')};
            }}
            """
        )
        repolish(self)

    def _disconnect(self) -> None:
        """销毁时断开主题/字体信号；解释器收尾阶段信号对象可能已删除。"""

        try:
            qconfig.themeChangedFinished.disconnect(self._apply_style)
            BaseStyles.fonts_changed.disconnect(self._apply_style)
        except (RuntimeError, TypeError):
            pass
