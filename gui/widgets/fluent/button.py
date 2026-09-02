"""主题化按钮组件：FluentButton、IconButton 与 DangerPushButton。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QSizePolicy, QWidget
from qfluentwidgets import PrimaryPushButton, PushButton, qconfig

from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.fluent._base import (
    apply_font_role_to,
    repolish,
    set_function_tooltip,
)

__all__ = ["DangerPushButton", "FluentButton", "IconButton"]


class FluentButton(PushButton):
    """主题化文本按钮，外观由 PushButton 的 FluentStyleSheet 提供。

    契约：
    * 构造必须提供非空 ``tooltip``，空提示抛 ``ValueError``（与
      ``BasePanel._set_button_help`` 一致）；
    * ``_sync_theme_state()`` 读取当前主题重建图标；按钮配色随 qfluentwidgets
      主题自动切换。
    """

    def __init__(
        self,
        text: str = "",
        *,
        tooltip: str | None = None,
        icon: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setText(text)
        set_function_tooltip(self, tooltip)
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
        """按当前主题重建图标；按钮配色随 qfluentwidgets 主题自动切换。"""

        if self._icon_name:
            self.setIcon(get_themed_icon(self._icon_name))


class IconButton(FluentButton):
    """仅显示主题图标的按钮，以功能提示作为可访问名称。"""

    def __init__(
        self,
        icon: str,
        tooltip: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("", tooltip=tooltip, icon=icon, parent=parent)
        self.setAccessibleName(str(tooltip).strip())
        self.setIconSize(QSize(BaseStyles.ICON_SIZE, BaseStyles.ICON_SIZE))
        self.setMinimumWidth(BaseStyles.ICON_SIZE + 12)


class DangerPushButton(PrimaryPushButton):
    """危险操作主按钮：主题化红色，替代 ``DANGER_BUTTON_STYLE`` 旧 QSS。

    契约：
    * 外观与 ``PrimaryPushButton`` 一致（Fluent 圆角/内边距），仅把强调色替换为
      主题 token 的 ``BUTTON_DANGER`` 系列，白色前景保持不变；
    * 主题切换时通过 ``qconfig.themeChangedFinished`` 重建红色样式（该信号在
      FluentStyleSheet 重应用之后触发，确保自定义红色不被覆盖）。
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        if text:
            self.setText(text)
        self.setProperty("buttonVariant", "danger")
        self._apply_danger_style()
        qconfig.themeChangedFinished.connect(self._apply_danger_style)
        self.destroyed.connect(self._disconnect_theme)

    def _disconnect_theme(self) -> None:
        """销毁时断开主题信号；解释器收尾阶段 qconfig 可能已删除，容错处理。"""

        try:
            qconfig.themeChangedFinished.disconnect(self._apply_danger_style)
        except (RuntimeError, TypeError):
            pass

    def _apply_danger_style(self) -> None:
        """按当前主题 token 重建危险红色样式。"""

        bs = BaseStyles
        radius = BaseStyles.RADIUS_MD
        self.setStyleSheet(
            f"""
            PrimaryPushButton {{
                color: #ffffff;
                background-color: {bs.color('BUTTON_DANGER')};
                border: 1px solid {bs.color('BUTTON_DANGER')};
                border-radius: {radius}px;
                padding: 5px 12px 6px 12px;
            }}
            PrimaryPushButton:hover {{
                background-color: {bs.color('BUTTON_DANGER_HOVER')};
            }}
            PrimaryPushButton:pressed {{
                color: rgba(255, 255, 255, 0.63);
                background-color: {bs.color('BUTTON_DANGER')};
            }}
            PrimaryPushButton:focus {{
                border: 2px solid {bs.color('TEXT_PRIMARY')};
            }}
            PrimaryPushButton:disabled {{
                color: rgba(255, 255, 255, 0.9);
                background-color: {bs.color('INPUT_BG')};
                border: 1px solid {bs.color('BORDER_COLOR')};
            }}
            """
        )
        repolish(self)
