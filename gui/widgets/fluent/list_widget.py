"""字号可缩放的 Fluent 列表：替代设备列表的 ``DEVICE_LIST_STYLE`` 旧 QSS。

qfluentwidgets ``ListWidget`` 的 FluentStyleSheet 固定 ``::item{height:35px}``，
破坏"行高随字号缩放"的字体爆发契约，因此这里保留原生 ``QListWidget``（行高
由 delegate 按字体度量），仅把容器/条目/勾选指示器的样式封装进本组件，主题
切换时通过 ``qconfig.themeChangedFinished`` 重建。
"""

from __future__ import annotations

from PySide6.QtWidgets import QListWidget, QWidget
from qfluentwidgets import SmoothScrollDelegate, qconfig

from gui.styles import BaseStyles
from gui.widgets.fluent._base import repolish

__all__ = ["ScalableListWidget"]


class ScalableListWidget(QListWidget):
    """主题化、行高随字号缩放的列表；勾选指示器由自绘 SVG 提供。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("deviceList")
        # 原生滚动条已被 SCROLLBAR_STYLE 移除后回退为系统样式，这里用
        # SmoothScrollDelegate 承接为 Fluent 平滑滚动条，行高仍由 delegate 按字体度量。
        SmoothScrollDelegate(self)
        self._apply_style()
        qconfig.themeChangedFinished.connect(self._apply_style)
        self.destroyed.connect(self._disconnect_theme)

    def _apply_style(self) -> None:
        """按当前主题 token 重建容器与勾选指示器样式。"""

        bs = BaseStyles
        radius = bs.RADIUS_MD
        self.setStyleSheet(
            f"""
            QListWidget#deviceList {{
                background-color: {bs.color('INPUT_BG')}; color: {bs.color('TEXT_PRIMARY')};
                border: 1px solid {bs.color('BORDER_COLOR')}; border-radius: {radius}px;
                padding: 2px; outline: none;
            }}
            QListWidget#deviceList::item {{
                padding: 3px 6px; color: {bs.color('TEXT_PRIMARY')};
            }}
            QListWidget#deviceList::item:selected {{
                background-color: {bs.color('SELECTION_BG')};
                color: {bs.color('SELECTION_TEXT')};
            }}
            QListWidget#deviceList::item:hover {{
                background-color: {bs.color('BUTTON_HOVER')};
            }}
            QListWidget#deviceList:focus {{
                border: 2px solid {bs.color('BORDER_FOCUS')};
            }}
            QListWidget::indicator {{ width: 14px; height: 14px; }}
            QListWidget::indicator:unchecked {{
                image: none; border: 2px solid {bs.color('BORDER_COLOR')};
                border-radius: 3px; background-color: {bs.color('INPUT_BG')};
            }}
            QListWidget::indicator:checked {{ image: url(icons:check.svg); border: none; }}
            """
        )
        repolish(self)

    def _disconnect_theme(self) -> None:
        """销毁时断开主题信号；解释器收尾阶段 qconfig 可能已删除，容错处理。"""

        try:
            qconfig.themeChangedFinished.disconnect(self._apply_style)
        except (RuntimeError, TypeError):
            pass
