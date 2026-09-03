"""qfluentwidgets 参考控件的项目级度量与可访问性配置。

本模块只配置第三方或 Qt 控件实例，不定义控件子类。这样既保留 ADBLab 的可缩放
字体、键盘焦点和功能提示契约，也避免再次形成一套与 qfluentwidgets 并行的组件库。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import QAbstractButton, QWidget
from qfluentwidgets import RoundMenu, setCustomStyleSheet

from gui.styles.fonts import FontMixin
from gui.styles.theme import ThemeMixin
from gui.styles.typography import FontRole

_WidgetT = TypeVar("_WidgetT", bound=QWidget)
_ButtonT = TypeVar("_ButtonT", bound=QAbstractButton)


def _font(role: FontRole | str, *, bold: bool = False) -> QFont:
    resolved = FontRole(role)
    font = FontMixin.font_for_role(resolved)
    if bold:
        font.setBold(True)
    return font


def apply_font_role(
    widget: _WidgetT,
    role: FontRole | str = FontRole.UI,
    *,
    bold: bool = False,
    ensure_height: bool = False,
) -> _WidgetT:
    """把项目字体角色应用到现有控件，并按需解除第三方固定像素高度。"""

    resolved = FontRole(role)
    widget.setFont(_font(resolved, bold=bold))
    widget.setProperty("fontRole", resolved.value)
    if ensure_height:
        safe_height = max(
            FontMixin.control_height(role=resolved),
            widget.minimumSizeHint().height(),
        )
        if widget.minimumHeight() == widget.maximumHeight() or widget.maximumHeight() < safe_height:
            widget.setFixedHeight(safe_height)
        else:
            widget.setMinimumHeight(safe_height)
    return widget


def apply_label_role(
    label: _WidgetT,
    role: FontRole | str = FontRole.UI,
    *,
    color_key: str = "TEXT_PRIMARY",
    bold: bool = False,
) -> _WidgetT:
    """配置 qfluentwidgets 标签的字体与明暗主题文字色。"""

    apply_font_role(label, role, bold=bold)
    set_text_color = getattr(label, "setTextColor", None)
    if callable(set_text_color):
        set_text_color(
            QColor(ThemeMixin.color_for("Light", color_key)),
            QColor(ThemeMixin.color_for("Dark", color_key)),
        )
    return label


def set_function_tooltip(widget: QWidget, tooltip: str | None) -> None:
    """保存功能提示与可访问描述；交互按钮不允许缺少提示。"""

    description = str(tooltip or "").strip()
    if not description:
        raise ValueError("Interactive controls must provide a functional tooltip")
    widget.setToolTip(description)
    widget.setAccessibleDescription(description)
    widget.setProperty("functionalToolTip", description)


def apply_focus_indicator(widget: QWidget, *, selector: str | None = None) -> None:
    """为 qfluentwidgets 默认移除 outline 的控件补充可见键盘焦点。"""

    name = selector or type(widget).__name__
    widget.setProperty("adblabFocusSelector", name)
    light = ThemeMixin.color_for("Light", "BORDER_FOCUS")
    dark = ThemeMixin.color_for("Dark", "BORDER_FOCUS")
    radius = ThemeMixin.RADIUS_MD
    setCustomStyleSheet(
        widget,
        f"{name}:focus {{ border: 2px solid {light}; border-radius: {radius}px; }}",
        f"{name}:focus {{ border: 2px solid {dark}; border-radius: {radius}px; }}",
    )


def _apply_button_custom_style(button: QAbstractButton, *, danger: bool) -> None:
    """重建按钮的项目级焦点和危险态 QSS，确保主题与强调色即时生效。"""

    selector = type(button).__name__
    light_focus = ThemeMixin.color_for("Light", "BORDER_FOCUS")
    dark_focus = ThemeMixin.color_for("Dark", "BORDER_FOCUS")
    radius = ThemeMixin.RADIUS_MD
    if danger:

        def danger_qss(theme: str, focus_color: str) -> str:
            background = ThemeMixin.color_for(theme, "BUTTON_DANGER")
            hover = ThemeMixin.color_for(theme, "BUTTON_DANGER_HOVER")
            disabled = ThemeMixin.color_for(theme, "INPUT_BG")
            disabled_text = ThemeMixin.color_for(theme, "TEXT_DISABLED")
            border = ThemeMixin.color_for(theme, "BORDER_COLOR")
            return (
                f"{selector} {{ color: white; background: {background}; "
                f"border: 1px solid {background}; border-radius: {radius}px; }}"
                f"{selector}:hover {{ background: {hover}; }}"
                f"{selector}:focus {{ border: 2px solid {focus_color}; }}"
                f"{selector}:disabled {{ color: {disabled_text}; background: {disabled}; "
                f"border-color: {border}; }}"
            )

        setCustomStyleSheet(
            button,
            danger_qss("Light", light_focus),
            danger_qss("Dark", dark_focus),
        )
        return

    setCustomStyleSheet(
        button,
        f"{selector}:focus {{ border: 2px solid {light_focus}; border-radius: {radius}px; }}",
        f"{selector}:focus {{ border: 2px solid {dark_focus}; border-radius: {radius}px; }}",
    )


def refresh_fluent_widget_style(widget: QWidget) -> None:
    """强调色变化后刷新项目注入的 widget 级 QSS，不改动控件业务状态。"""

    if isinstance(widget, QAbstractButton) and bool(
        widget.property("adblabConfiguredButton")
    ):
        _apply_button_custom_style(
            widget,
            danger=widget.property("buttonVariant") == "danger",
        )
        return
    selector = widget.property("adblabFocusSelector")
    if selector:
        apply_focus_indicator(widget, selector=str(selector))


def configure_fluent_control(
    widget: _WidgetT,
    role: FontRole | str = FontRole.UI,
    *,
    focus: bool = True,
    ensure_height: bool = True,
) -> _WidgetT:
    """统一配置直接使用的 qfluentwidgets 控件。"""

    apply_font_role(widget, role, ensure_height=ensure_height)
    if focus:
        apply_focus_indicator(widget)
    return widget


def configure_button(
    button: _ButtonT,
    *,
    text: str,
    tooltip: str | None,
    role: FontRole | str = FontRole.UI,
    danger: bool = False,
) -> _ButtonT:
    """配置直接使用的 qfluentwidgets 按钮；危险色使用 light/dark 自定义 QSS。"""

    button.setText(text)
    button.setAccessibleName(text or str(tooltip or ""))
    set_function_tooltip(button, tooltip)
    apply_font_role(button, role, ensure_height=True)
    button.setProperty("adblabConfiguredButton", True)
    if danger:
        button.setProperty("buttonVariant", "danger")
    else:
        button.setProperty("buttonVariant", "")
    _apply_button_custom_style(button, danger=danger)
    return button


def add_menu_action(
    menu: RoundMenu,
    text: str,
    *,
    callback: Callable[[], object] | None = None,
    data: object | None = None,
    checkable: bool = False,
    checked: bool = False,
) -> QAction:
    """向 qfluentwidgets RoundMenu 添加带业务数据的 QAction。"""

    action = QAction(text, menu)
    action.setData(data)
    action.setCheckable(checkable)
    action.setChecked(checked)
    if callback is not None:
        action.triggered.connect(lambda _checked=False, fn=callback: fn())
    menu.addAction(action)
    return action


__all__ = [
    "add_menu_action",
    "apply_focus_indicator",
    "apply_font_role",
    "apply_label_role",
    "configure_button",
    "configure_fluent_control",
    "refresh_fluent_widget_style",
    "set_function_tooltip",
]
