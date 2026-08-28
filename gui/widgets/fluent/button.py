"""主题化按钮组件：FluentButton 与 IconButton。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.fluent._base import (
    apply_button_variant,
    apply_font_role_to,
    repolish,
    set_function_tooltip,
)

__all__ = ["FluentButton", "IconButton"]


class FluentButton(QPushButton):
    """主题化文本按钮，支持 normal / accent / danger / ghost 变体。

    契约：
    * 构造必须提供非空 ``tooltip``，空提示抛 ``ValueError``（与
      ``BasePanel._set_button_help`` 一致）；
    * ``buttonVariant`` 决定 QSS 路由：``accent``/``danger`` 命中
      ``BaseStyles.BUTTON_QSS()`` 的 ``#accent``/``#danger`` 选择器，
      ``ghost`` 使用独立透明样式，normal 使用基础 ``QPushButton`` 样式；
    * ``_sync_theme_state()`` 读取当前主题重建样式与图标。
    """

    VARIANTS: tuple[str, ...] = ("", "accent", "danger", "ghost")

    def __init__(
        self,
        text: str = "",
        *,
        variant: str = "",
        tooltip: str | None = None,
        icon: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        if variant not in self.VARIANTS:
            raise ValueError(f"variant 必须是 {self.VARIANTS} 之一，收到 {variant!r}")
        set_function_tooltip(self, tooltip)
        self._variant = ""
        self._icon_name: str | None = None
        self._font_role = FontRole.UI
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.setProperty("fontRole", FontRole.UI.value)
        self.setAccessibleName(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(28)
        if icon:
            self.set_icon(icon)
        if variant:
            self.set_variant(variant)
        else:
            self.setStyleSheet(BaseStyles.BUTTON_QSS())
            repolish(self)

    # ── 变体 ────────────────────────────────────────────────────────────

    def variant(self) -> str:
        """返回当前变体名；normal 返回空字符串。"""

        return self._variant

    def set_variant(self, variant: str) -> None:
        """切换按钮变体并重新应用样式。"""

        if variant not in self.VARIANTS:
            raise ValueError(f"variant 必须是 {self.VARIANTS} 之一，收到 {variant!r}")
        self._variant = variant
        apply_button_variant(self, variant)

    # ── 内容 ────────────────────────────────────────────────────────────

    def set_text(self, text: str) -> None:
        """更新按钮文字，并在缺失时补全可访问名称。"""

        self.setText(text)
        if not self.accessibleName():
            self.setAccessibleName(text)

    def set_icon(self, icon_name: str, size: QSize | None = None) -> None:
        """设置主题图标并记录 ``iconName`` property。"""

        self._icon_name = icon_name
        self.setIcon(get_themed_icon(icon_name))
        self.setProperty("iconName", icon_name)
        if size is not None:
            self.setIconSize(size)

    def set_tooltip(self, tooltip: str) -> None:
        """更新功能提示；空提示抛 ``ValueError``。"""

        set_function_tooltip(self, tooltip)

    # ── 字体与主题 ──────────────────────────────────────────────────────

    def apply_font_role(self, role: FontRole | str) -> None:
        """切换字体角色并同步 ``fontRole`` property。"""

        self._font_role = apply_font_role_to(self, role)

    def _sync_theme_state(self) -> None:
        """按当前主题重建图标与样式表。"""

        if self._icon_name:
            self.setIcon(get_themed_icon(self._icon_name))
        if self._variant:
            apply_button_variant(self, self._variant)
        else:
            self.setStyleSheet(BaseStyles.BUTTON_QSS())
            repolish(self)


class IconButton(FluentButton):
    """仅显示主题图标的按钮，以功能提示作为可访问名称。"""

    def __init__(
        self,
        icon: str,
        tooltip: str,
        *,
        variant: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("", tooltip=tooltip, variant=variant, icon=icon, parent=parent)
        self.setAccessibleName(str(tooltip).strip())
        self.setIconSize(QSize(BaseStyles.ICON_SIZE, BaseStyles.ICON_SIZE))
        self.setMinimumWidth(BaseStyles.ICON_SIZE + 12)
