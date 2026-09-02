"""Fluent 组件库共享辅助：主题同步、字体角色与 BasePanel 兼容契约。

本模块提供组件之间复用的纯函数，不依赖任何面板或样式文件的内部实现；
颜色与样式统一从 :mod:`gui.styles` 的公开 API 读取。
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from gui.styles import BaseStyles, FontRole

__all__ = [
    "apply_font_role_to",
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


def apply_font_role_to(widget: QWidget, role: FontRole | str) -> FontRole:
    """给控件套用统一字体角色，并同步 ``fontRole`` property。"""

    resolved = FontRole(role)
    widget.setFont(BaseStyles.font_for_role(resolved))
    widget.setProperty("fontRole", resolved.value)
    return resolved
