"""主题化文本标签：兼顾项目可缩放字体与 qfluentwidgets 主题色自动切换。

迁移说明：项目的标题/副标题此前用原生 ``QLabel`` + ``fontRole`` property +
``setStyleSheet(color)``，并在每次主题切换时由 ``_apply_*_header_style`` 手动重建颜色。
本组件改为继承 qfluentwidgets ``BodyLabel``，用 ``setTextColor(light, dark)`` 同时固化
明暗两套 token 颜色，随 qfluentwidgets 主题自动切换，从而移除手动颜色重建逻辑。
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel

from gui.styles import BaseStyles, FontRole

__all__ = ["FluentLabel"]


class FluentLabel(BodyLabel):
    """主题化文本标签，字体按项目 FontRole 缩放，颜色按 token 明暗两套固化。

    契约：
    * ``role`` 决定 ``fontRole`` property 与初始字体（参与项目字体变更遍历）；
    * ``color_key`` 指定 token 键（如 ``TITLE_COLOR``/``TEXT_SECONDARY``），
      明暗两套颜色经 ``setTextColor`` 固化后随 qfluentwidgets 主题自动切换。
    """

    def __init__(
        self,
        text: str = "",
        *,
        role: FontRole | str | None = FontRole.UI,
        color_key: str = "TEXT_PRIMARY",
        bold: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        # BodyLabel 的 singledispatchmethod 会按 text 分发到 str 重载，该重载又回调
        # self.__init__，与子类重载冲突；这里走 parent 默认重载后再 setText。
        super().__init__(parent)
        self.setText(text)
        self._color_key = color_key
        self._bold = bold
        if role is not None:
            role = FontRole(role)
            self.setProperty("fontRole", role.value)
            font = BaseStyles.font_for_role(role)
            if bold:
                font.setBold(True)
            self.setFont(font)
        self._apply_token_color()

    def _apply_token_color(self) -> None:
        """按 token 键固化明暗两套文字色（随 qfluentwidgets 主题自动切换）。"""

        self.setTextColor(
            BaseStyles.color_for("Light", self._color_key),
            BaseStyles.color_for("Dark", self._color_key),
        )

    def set_color_key(self, color_key: str) -> None:
        """切换 token 配色键并立即重建文字色。"""

        self._color_key = color_key
        self._apply_token_color()

    def set_role(self, role: FontRole | str | None) -> None:
        """切换字体角色；``None`` 表示撤销角色（回退 UI 字体，清空 ``fontRole``）。"""

        if role is None:
            self.setProperty("fontRole", "")
            self.setFont(BaseStyles.font_for_role(FontRole.UI))
            return
        role = FontRole(role)
        self.setProperty("fontRole", role.value)
        self.setFont(BaseStyles.font_for_role(role))
