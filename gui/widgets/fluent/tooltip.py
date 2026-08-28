"""主题化悬浮气泡提示组件。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent._base import repolish

__all__ = ["FluentTooltip"]


class FluentTooltip(QWidget):
    """主题化悬浮气泡提示，供悬停或自定义时机显示。

    契约：
    * 使用 ``show_at`` 在指定全局坐标显示，不拦截鼠标事件；
    * ``_sync_theme_state()`` 读取当前主题重建气泡与文字样式。
    """

    def __init__(self, text: str = "", *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("fluentTooltip")
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setProperty("fontRole", FontRole.UI_SMALL.value)
        self._label.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(self._label)

        self._sync_theme_state()

    # ── 内容与显示 ──────────────────────────────────────────────────────

    def set_text(self, text: str) -> None:
        """更新提示文案并重新计算气泡尺寸。"""

        self._label.setText(text)
        self.adjustSize()

    def text(self) -> str:
        return self._label.text()

    def show_at(self, global_pos: QPoint) -> None:
        """在全局坐标处显示气泡。"""

        self.adjustSize()
        self.move(global_pos)
        self.show()

    # ── 主题 ────────────────────────────────────────────────────────────

    def _sync_theme_state(self) -> None:
        """按当前主题重建气泡与文字样式。"""

        self._label.setStyleSheet(f"color: {BaseStyles.color('TEXT_PRIMARY')};")
        self.setStyleSheet(self._bubble_style())
        repolish(self)

    def _bubble_style(self) -> str:
        radius = BaseStyles.RADIUS_SM
        return (
            f"QWidget#fluentTooltip {{"
            f" background-color: {BaseStyles.color('PANEL_BG')};"
            f" border: 1px solid {BaseStyles.color('BORDER_COLOR')};"
            f" border-radius: {radius}px; }}"
        )
