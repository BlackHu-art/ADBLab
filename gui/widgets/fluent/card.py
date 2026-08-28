"""卡片容器组件。"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent._base import apply_font_role_to, repolish

__all__ = ["Card"]


class Card(QFrame):
    """带标题、可选副标题与内容区的主题化卡片容器。

    契约：
    * ``body_layout()`` 返回内容区布局，供调用方追加控件；
    * 标题使用 ``FontRole.TITLE``、副标题使用 ``FontRole.UI_SMALL``；
    * ``_sync_theme_state()`` 读取当前主题重建卡片与标题颜色。
    """

    def __init__(
        self,
        title: str = "",
        *,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fluentCard")

        self._title = QLabel(title)
        self._title.setProperty("fontRole", FontRole.TITLE.value)
        self._title.setFont(BaseStyles.font_for_role(FontRole.TITLE))
        self._title.setVisible(bool(title))

        self._subtitle = QLabel(subtitle)
        self._subtitle.setProperty("fontRole", FontRole.UI_SMALL.value)
        self._subtitle.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        self._subtitle.setVisible(bool(subtitle))
        self._subtitle.setWordWrap(True)

        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)
        layout.addWidget(self._body, 1)

        self._sync_theme_state()

    # ── 内容 ────────────────────────────────────────────────────────────

    def set_title(self, text: str) -> None:
        """更新标题；空标题时隐藏标题标签。"""

        self._title.setText(text)
        self._title.setVisible(bool(text))

    def set_subtitle(self, text: str) -> None:
        """更新副标题；空文本时隐藏副标题标签。"""

        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def title(self) -> str:
        return self._title.text()

    def subtitle(self) -> str:
        return self._subtitle.text()

    def body_layout(self) -> QVBoxLayout:
        """返回内容区布局，供调用方追加控件。"""

        return self._body_layout

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        """向内容区追加控件。"""

        self._body_layout.addWidget(widget, stretch)

    # ── 字体与主题 ──────────────────────────────────────────────────────

    def apply_font_role(self, role: FontRole | str) -> None:
        """切换标题字体角色并同步 ``fontRole`` property。"""

        apply_font_role_to(self._title, role)

    def _sync_theme_state(self) -> None:
        """按当前主题重建卡片与标题样式。"""

        self._title.setStyleSheet(f"color: {BaseStyles.color('TITLE_COLOR')};")
        self._subtitle.setStyleSheet(f"color: {BaseStyles.color('TEXT_SECONDARY')};")
        self.setStyleSheet(self._card_style())
        repolish(self)

    def _card_style(self) -> str:
        radius = BaseStyles.RADIUS_LG
        return (
            f"QFrame#fluentCard {{"
            f" background-color: {BaseStyles.color('PANEL_BG')};"
            f" border: 1px solid {BaseStyles.color('BORDER_COLOR')};"
            f" border-radius: {radius}px; }}"
        )
