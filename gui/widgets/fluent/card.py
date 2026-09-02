"""卡片容器组件（迁移到 qfluentwidgets ``CardWidget``）。"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import CardWidget

from gui.styles import FontRole
from gui.widgets.fluent._base import apply_font_role_to
from gui.widgets.fluent.label import FluentLabel

__all__ = ["Card"]


class Card(CardWidget):
    """带标题、可选副标题与内容区的主题化卡片容器。

    契约（沿用自研 Card，调用方无需改动）：
    * ``body_layout()`` 返回内容区布局，供调用方追加控件；
    * 标题使用 ``FontRole.TITLE``、副标题使用 ``FontRole.UI_SMALL``；
    * ``_sync_theme_state()`` 读取当前主题重建标题/副标题颜色。

    卡片圆角背景与 hover 动画由 ``CardWidget`` 自行绘制并跟随 qfluentwidgets 主题，
    不再依赖自研 ``_card_style()`` QSS。
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

        self._title = FluentLabel(title, role=FontRole.TITLE, color_key="TITLE_COLOR")
        self._title.setVisible(bool(title))

        self._subtitle = FluentLabel(
            subtitle,
            role=FontRole.UI_SMALL if subtitle else None,
            color_key="TEXT_SECONDARY",
        )
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
        # 空副标题不挂 UI_SMALL 角色：面板字体爆发测试要求面板内无 UI_SMALL 控件。
        self._subtitle.set_role(FontRole.UI_SMALL if text else None)

    def title(self) -> str:
        return self._title.text()

    def title_label(self) -> FluentLabel:
        """返回标题标签，供测试与外部接入测量标题几何。"""

        return self._title

    def minimumSizeHint(self) -> QSize:
        """把完整标题宽度计入最小宽度，避免长标题在窄容器中被裁剪。"""

        base = super().minimumSizeHint()
        if self._title.isVisible() and self._title.text():
            title_width = self._title.fontMetrics().horizontalAdvance(self._title.text())
            base.setWidth(max(base.width(), title_width + 24))
        return base

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
        """标题/副标题颜色已由 FluentLabel 随 qfluentwidgets 主题自动切换。

        保留该方法以兼容主题广播（``findChildren`` 按 ``_sync_theme_state`` 遍历刷新）。
        """
