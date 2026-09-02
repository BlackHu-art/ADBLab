"""空状态与加载状态组件。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import IndeterminateProgressBar

from gui.styles import FontRole
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.fluent._base import apply_font_role_to, repolish
from gui.widgets.fluent.button import FluentButton
from gui.widgets.fluent.label import FluentLabel

__all__ = ["EmptyState", "LoadingState"]


class EmptyState(QWidget):
    """空状态占位：主题图标 + 标题 + 描述 + 可选动作按钮。

    契约：
    * ``set_action`` 创建的动作按钮默认以动作文案作为功能提示（满足
      ``functionalToolTip`` 契约）；
    * 动作按钮点击时先发出 ``actionClicked``，再回调 ``callback``；
    * ``_sync_theme_state()`` 读取当前主题重建图标与文字颜色。
    """

    actionClicked = Signal()

    def __init__(
        self,
        *,
        icon: str = "",
        title: str = "",
        description: str = "",
        action_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = ""
        self._action_callback: Callable[[], object] | None = None

        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title_label = FluentLabel(
            title, role=FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._description_label = FluentLabel(
            description, role=FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self._description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._description_label.setWordWrap(True)

        self._action_button: FluentButton | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(8)
        self._layout.addWidget(self._icon_label)
        self._layout.addWidget(self._title_label)
        self._layout.addWidget(self._description_label)
        self._layout.addStretch(1)
        self.setProperty("fontRole", FontRole.UI.value)

        if icon:
            self.set_icon(icon)
        else:
            self._icon_label.setVisible(False)

        if action_text:
            self.set_action(action_text)
        self._sync_theme_state()

    # ── 内容 ────────────────────────────────────────────────────────────

    def set_icon(self, icon: str) -> None:
        """设置主题图标；空图标名隐藏图标区。"""

        self._icon_name = icon
        self._icon_label.setVisible(bool(icon))
        self._refresh_icon_pixmap()

    def set_title(self, text: str) -> None:
        self._title_label.setText(text)

    def set_description(self, text: str) -> None:
        self._description_label.setText(text)

    def title(self) -> str:
        return self._title_label.text()

    def description(self) -> str:
        return self._description_label.text()

    def set_action(
        self,
        text: str,
        callback: Callable[[], object] | None = None,
        *,
        tooltip: str | None = None,
    ) -> FluentButton:
        """创建或更新动作按钮，并登记点击回调。"""

        if self._action_button is None:
            button = FluentButton(text, tooltip=tooltip or text, parent=self)
            button.clicked.connect(self._on_action_clicked)
            self._layout.addWidget(button)
            self._action_button = button
        else:
            self._action_button.set_text(text)
            self._action_button.set_tooltip(tooltip or text)
        self._action_callback = callback
        assert self._action_button is not None  # 分支后必已创建
        return self._action_button

    def action_button(self) -> FluentButton | None:
        """返回当前动作按钮，未设置时返回 ``None``。"""

        return self._action_button

    # ── 字体与主题 ──────────────────────────────────────────────────────

    def apply_font_role(self, role: FontRole | str) -> None:
        """切换描述文字字体角色并同步 ``fontRole`` property。"""

        apply_font_role_to(self._description_label, role)

    def _on_action_clicked(self, _checked: bool = False) -> None:
        self.actionClicked.emit()
        if self._action_callback is not None:
            self._action_callback()

    def _refresh_icon_pixmap(self) -> None:
        if self._icon_name:
            self._icon_label.setPixmap(
                get_themed_icon(self._icon_name).pixmap(QSize(48, 48))
            )

    def _sync_theme_state(self) -> None:
        """按当前主题重建图标（文字颜色已由 FluentLabel 随 qfluentwidgets 主题切换）。"""

        self._refresh_icon_pixmap()
        repolish(self)


class LoadingState(QWidget):
    """加载状态：不确定进度条 spinner 或纯文案。

    契约：
    * ``set_spinning`` 控制 spinner 可见性；
    * ``_sync_theme_state()`` 读取当前主题重建进度条与文字样式。
    """

    def __init__(
        self,
        message: str = "",
        *,
        spinner: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._spinner = IndeterminateProgressBar(self, start=False)

        self._label = FluentLabel(message, role=FontRole.UI, color_key="TEXT_SECONDARY")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self._spinner)
        layout.addWidget(self._label)
        self.setProperty("fontRole", FontRole.UI.value)

        self.set_spinning(spinner)
        self._sync_theme_state()

    # ── 内容 ────────────────────────────────────────────────────────────

    def set_message(self, message: str) -> None:
        self._label.setText(message)

    def message(self) -> str:
        return self._label.text()

    def set_spinning(self, spinning: bool) -> None:
        """切换 spinner 可见性与动画。"""

        self._spinner.setVisible(bool(spinning))
        if spinning:
            self._spinner.start()
        else:
            self._spinner.stop()

    def is_spinning(self) -> bool:
        return self._spinner.isStarted()

    # ── 字体与主题 ──────────────────────────────────────────────────────

    def apply_font_role(self, role: FontRole | str) -> None:
        """切换文字字体角色并同步 ``fontRole`` property。"""

        apply_font_role_to(self._label, role)

    def _sync_theme_state(self) -> None:
        """文字颜色已由 FluentLabel 随主题切换（spinner 由 IndeterminateProgressBar 自绘跟随）。"""

        repolish(self)
