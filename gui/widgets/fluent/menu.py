"""主题化上下文菜单组件（迁移到 qfluentwidgets ``RoundMenu``）。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget
from qfluentwidgets import RoundMenu

from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent._base import apply_font_role_to

__all__ = ["FluentMenu"]


class FluentMenu(RoundMenu):
    """主题化上下文菜单，动作可携带业务 data 与可选勾选态。

    契约（沿用自研，调用方无需改动）：
    * ``add_action`` 返回 :class:`QAction`，回调适配 ``triggered(bool)`` 签名；
    * 外观与主题由 ``RoundMenu`` 自动跟随 qfluentwidgets 主题，不再依赖自研
      ``MENU_STYLE`` QSS。
    """

    def __init__(self, title: str = "", *, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.setProperty("fontRole", FontRole.UI.value)

    # ── 动作 ────────────────────────────────────────────────────────────

    def add_action(
        self,
        text: str,
        *,
        callback: Callable[[], object] | None = None,
        data: object | None = None,
        checkable: bool = False,
        checked: bool = False,
    ) -> QAction:
        """追加动作；``callback`` 会被包装以适配 ``triggered(bool)``。"""

        action = QAction(text, self)
        if data is not None:
            action.setData(data)
        if checkable:
            action.setCheckable(True)
            action.setChecked(checked)
        if callback is not None:
            action.triggered.connect(
                lambda _checked=False, fn=callback: fn()
            )
        self.addAction(action)
        return action

    # ── 字体与主题 ──────────────────────────────────────────────────────

    def apply_font_role(self, role: FontRole | str) -> None:
        """切换菜单字体角色并同步 ``fontRole`` property。"""

        apply_font_role_to(self, role)

    def _sync_theme_state(self) -> None:
        """外观由 RoundMenu 自动跟随主题，无需手动重建。"""

        self.update()
