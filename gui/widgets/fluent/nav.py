"""左侧竖排导航栏：设备 / 任务 / 日志 / 设置。

宽窗显示「图标 + 文字」，窄窗（宽度预算低于 ``COLLAPSE_WIDTH_BUDGET``）折叠为
纯图标并改用 tooltip 传达条目含义。折叠状态变化通过 ``collapsed_changed(bool)``
发布，供 P1-C 接入 ResponsiveCoordinator 的宽度预算决策；条目点击统一发布
``navigate_requested(str)``，参数为业务键。

本组件沿用 Fluent 组件库约定：样式在构造时按当前主题一次性生成，主题 / 字体
广播在 P2 接入；P1 阶段调用方可在主题切换后调用 ``_sync_theme_state()`` 重建。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import get_themed_icon

__all__ = ["NavBar"]

# 业务键 -> (显示文案, 图标名)。图标名与 resources/icons 现有资源一一对应。
_DEFAULT_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("devices", "Devices", "devices.svg"),
    ("tasks", "Tasks", "list-checks.svg"),
    ("logs", "Logs", "log.svg"),
    ("settings", "Settings", "gear.svg"),
)


class NavBar(QWidget):
    """主题化的竖排导航栏，宽窄两态可切换。

    契约：
    * ``navigate_requested(str)`` 在条目被点击时发出，参数为业务键；
    * ``collapsed_changed(bool)`` 仅在折叠状态真正变化时发出；
    * ``set_width_budget(int)`` 按 ``COLLAPSE_WIDTH_BUDGET`` 阈值推导折叠态，
      ``set_collapsed(bool)`` 供外部显式覆盖；
    * 折叠态条目只显示图标并携带 tooltip，展开态显示图标与文字；
    * ``_sync_theme_state()`` 读取当前主题重建图标与样式。
    """

    COLLAPSE_WIDTH_BUDGET = 720
    EXPANDED_RAIL_WIDTH = 120
    COLLAPSED_RAIL_WIDTH = 44

    navigate_requested = Signal(str)
    collapsed_changed = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        entries: tuple[tuple[str, str, str], ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("navBar")
        self._entries = tuple(entries) if entries else _DEFAULT_ENTRIES
        self._labels: dict[str, str] = {}
        self._icon_names: dict[str, str] = {}
        self._buttons: dict[str, QToolButton] = {}
        self._collapsed = False
        self._current_key: str | None = None

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)

        for key, label, icon_name in self._entries:
            self._labels[key] = label
            self._icon_names[key] = icon_name
            button = QToolButton(self)
            button.setCheckable(True)
            button.setText(label)
            button.setIcon(get_themed_icon(icon_name))
            button.setProperty("iconName", icon_name)
            button.setProperty("navKey", key)
            button.setProperty("fontRole", FontRole.UI.value)
            button.setFont(BaseStyles.font_for_role(FontRole.UI))
            button.setAccessibleName(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.clicked.connect(lambda _checked=False, k=key: self._on_clicked(k))
            self._group.addButton(button)
            self._layout.addWidget(button)
            self._buttons[key] = button

        self._layout.addStretch(1)
        self._apply_collapsed(False)
        self._sync_theme_state()

    # ── 条目与状态 ──────────────────────────────────────────────────────

    def keys(self) -> tuple[str, ...]:
        """返回按创建顺序排列的业务键序列。"""

        return tuple(key for key, _label, _icon in self._entries)

    def button(self, key: str) -> QToolButton:
        """按业务键返回对应条目按钮；未知键抛 ``KeyError``。"""

        return self._buttons[key]

    def buttons(self) -> tuple[QToolButton, ...]:
        """返回按创建顺序排列的条目按钮，供测试与外部接入。"""

        return tuple(self._buttons[key] for key, _label, _icon in self._entries)

    def current_key(self) -> str | None:
        """返回当前选中的业务键；无选中返回 ``None``。"""

        return self._current_key

    def set_current_key(self, key: str) -> None:
        """程序化选中指定条目，不触发 ``navigate_requested``。"""

        if key not in self._buttons:
            return
        self._current_key = key
        self._buttons[key].setChecked(True)

    def set_page(self, key: str) -> None:
        """``set_current_key`` 的兼容别名（供 main_frame 导航接入）。"""

        self.set_current_key(key)

    # ── 折叠态 ──────────────────────────────────────────────────────────

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_width_budget(self, width: int) -> None:
        """按宽度预算推导折叠态；低于阈值折叠、否则展开。"""

        self.set_collapsed(int(width) < self.COLLAPSE_WIDTH_BUDGET)

    def apply_width_budget(self, available_width: int) -> None:
        """``set_width_budget`` 的兼容别名（供 main_frame 宽度预算接入）。"""

        self.set_width_budget(available_width)

    def set_collapsed(self, collapsed: bool) -> None:
        """显式切换折叠态；状态未变化时不重复发出 ``collapsed_changed``。"""

        collapsed = bool(collapsed)
        changed = collapsed != self._collapsed
        self._collapsed = collapsed
        self._apply_collapsed(collapsed)
        if changed:
            self.collapsed_changed.emit(collapsed)

    def _apply_collapsed(self, collapsed: bool) -> None:
        style = (
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if collapsed
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        for key, button in self._buttons.items():
            button.setToolButtonStyle(style)
            button.setToolTip(self._labels[key] if collapsed else "")
        # 导航栏作为固定宽度栏参与主布局，避免展开态按钮把栏宽撑到超出内容宽度，
        # 挤压右侧页面栈（见 main_frame 组合根接入后的几何契约）。
        self.setFixedWidth(
            self.COLLAPSED_RAIL_WIDTH if collapsed else self.EXPANDED_RAIL_WIDTH
        )

    def _on_clicked(self, key: str) -> None:
        self._current_key = key
        self.navigate_requested.emit(key)

    # ── 主题 ────────────────────────────────────────────────────────────

    def _sync_theme_state(self) -> None:
        """按当前主题重建条目图标与导航栏样式。"""

        for key, button in self._buttons.items():
            button.setIcon(get_themed_icon(self._icon_names[key]))
        self.setStyleSheet(self._nav_style())
        self.style().unpolish(self)
        self.style().polish(self)

    def _nav_style(self) -> str:
        bs = BaseStyles
        radius = bs.RADIUS_MD
        bg = bs.color("PANEL_BG")
        border = bs.color("BORDER_COLOR")
        text = bs.color("TEXT_PRIMARY")
        hover = bs.color("BUTTON_HOVER")
        accent = bs.color("BUTTON_ACCENT")
        accent_hover = bs.color("BUTTON_ACCENT_HOVER")
        return (
            f"QWidget#navBar {{ background-color: {bg}; border-right: 1px solid {border}; }}"
            f"QToolButton {{"
            f" background-color: transparent; color: {text}; border: none;"
            f" border-radius: {radius}px; padding: 6px 8px; text-align: left; }}"
            f"QToolButton:hover {{ background-color: {hover}; }}"
            f"QToolButton:checked {{ background-color: {accent}; color: #ffffff; }}"
            f"QToolButton:checked:hover {{ background-color: {accent_hover}; }}"
        )
