"""Fluent 组件库共享辅助：主题同步、字体角色与 BasePanel 兼容契约。

本模块提供组件之间复用的纯函数，不依赖任何面板或样式文件的内部实现；
颜色与样式统一从 :mod:`gui.styles` 的公开 API 读取。
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from gui.styles import BaseStyles, FontRole

__all__ = [
    "apply_button_variant",
    "apply_font_role_to",
    "button_stylesheet_for",
    "ghost_button_style",
    "repolish",
    "set_function_tooltip",
]


def set_function_tooltip(widget: QWidget, tooltip: str | None) -> None:
    """按 ``BasePanel._set_button_help`` 语义写入功能提示。

    契约：空或纯空白提示视为缺失并抛 ``ValueError``；非空时同时写入
    ``toolTip``、可访问描述与 ``functionalToolTip`` property。
    """

    description = str(tooltip or "").strip()
    if not description:
        raise ValueError("Buttons must provide a functional tooltip")
    widget.setToolTip(description)
    widget.setAccessibleDescription(description)
    widget.setProperty("functionalToolTip", description)


def repolish(widget: QWidget) -> None:
    """请求 Qt 重新计算并应用当前样式表与调色板。"""

    widget.style().unpolish(widget)
    widget.style().polish(widget)
    # 显式走 QWidget.update：条目视图（QTableWidget 等）会以带索引的
    # update(QModelIndex) 覆盖无参重载，直接调用会因缺参抛 TypeError。
    QWidget.update(widget)


def ghost_button_style() -> str:
    """返回 ghost 变体 QSS：透明底，hover 显示边框，颜色取自 BaseStyles。"""

    radius = BaseStyles.RADIUS_MD
    return (
        f"QPushButton#ghost {{"
        f" border-radius: {radius}px; padding: 3px 8px;"
        f" background-color: transparent; color: {BaseStyles.color('TEXT_PRIMARY')};"
        f" border: 1px solid transparent; }}"
        f"QPushButton#ghost:hover {{"
        f" background-color: {BaseStyles.color('BUTTON_HOVER')};"
        f" border-color: {BaseStyles.color('BORDER_COLOR')}; }}"
        f"QPushButton#ghost:pressed {{"
        f" background-color: {BaseStyles.color('BUTTON_PRESSED')}; }}"
        f"QPushButton#ghost:focus {{"
        f" border: 2px solid {BaseStyles.color('BORDER_FOCUS')}; }}"
        f"QPushButton#ghost:disabled {{"
        f" color: {BaseStyles.color('TEXT_DISABLED')}; }}"
    )


def button_stylesheet_for(variant: str) -> str:
    """返回变体对应样式表；accent/danger 复用 ``BaseStyles.BUTTON_QSS()``。"""

    if variant == "ghost":
        return ghost_button_style()
    return BaseStyles.BUTTON_QSS()


def apply_button_variant(button: QPushButton, variant: str) -> None:
    """把变体名路由到 QSS 对象名选择器并设置 ``buttonVariant`` property。

    与 ``BasePanel._apply_button_variant`` 保持一致：``objectName`` 命中
    ``QPushButton#accent`` / ``QPushButton#danger`` 选择器，``buttonVariant``
    作为稳定的业务路由 property 供程序读取或后续 QSS 属性选择器使用。
    """

    button.setObjectName(variant)
    button.setProperty("buttonVariant", variant)
    button.setStyleSheet(button_stylesheet_for(variant))
    repolish(button)


def apply_font_role_to(widget: QWidget, role: FontRole | str) -> FontRole:
    """给控件套用统一字体角色，并同步 ``fontRole`` property。"""

    resolved = FontRole(role)
    widget.setFont(BaseStyles.font_for_role(resolved))
    widget.setProperty("fontRole", resolved.value)
    return resolved
