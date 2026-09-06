"""采集实际控件的可见界面文案，用于跨页面语言验收。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QAbstractItemView, QLabel, QLineEdit, QWidget
from qfluentwidgets import ComboBox, EditableComboBox


def visible_ui_texts(root: QWidget) -> list[tuple[str, str, str]]:
    """读取可见控件、可选项和表头；输入值、原始日志及设备数据不属于翻译源。"""
    result = []
    for widget in (root, *root.findChildren(QWidget)):
        if not widget.isVisibleTo(root):
            continue
        name = widget.objectName() or type(widget).__name__
        for field in ("toolTip", "accessibleName", "accessibleDescription"):
            text = getattr(widget, field)()
            if text:
                result.append((name, field, text))
        if isinstance(widget, (QLabel, QAbstractButton)) and widget.text():
            result.append((name, "text", widget.text()))
        if isinstance(widget, QLineEdit) and widget.placeholderText():
            result.append((name, "placeholder", widget.placeholderText()))
        if isinstance(widget, (ComboBox, EditableComboBox)):
            for index in range(widget.count()):
                result.append((name, "option", widget.itemText(index)))
        if isinstance(widget, QAbstractItemView) and widget.model() is not None:
            model = widget.model()
            for column in range(model.columnCount()):
                text = model.headerData(column, Qt.Orientation.Horizontal)
                if isinstance(text, str) and text:
                    result.append((name, "header", text))
    return sorted(set(result))
