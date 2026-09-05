"""将同页的次要操作折叠收纳，控件及其业务状态始终保留。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, PushButton

from gui.styles import BaseStyles, FontRole


class CollapsibleTools(QWidget):
    """只管理显隐，不接管设备目标、任务或内容控件的信号连接。"""

    expanded_changed = Signal(bool)

    def __init__(
        self, title: str, content: QWidget, parent=None, *,
        icon: FluentIcon = FluentIcon.APPLICATION,
        tooltip: str = "批量操作使用顶部勾选的操作设备；本地 APK 工具无需设备。收起时保留输入",
    ):
        super().__init__(parent)
        self.title = title
        self.content = content
        self.toggle_button = PushButton(icon, f"展开 · {title}", self)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setAccessibleName(title)
        self.toggle_button.setToolTip(tooltip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.toggle_button)
        layout.addWidget(content)
        content.hide()
        self.toggle_button.toggled.connect(self._set_expanded)
        BaseStyles.ui_font_changed.connect(self._apply_font)
        self._apply_font()

    def _apply_font(self, *_args):
        self.toggle_button.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.toggle_button.setMinimumHeight(max(32, self.toggle_button.fontMetrics().height() + 14))

    def _set_expanded(self, expanded: bool):
        self.content.setVisible(expanded)
        self.toggle_button.setText(f"{'收起' if expanded else '展开'} · {self.title}")
        self.updateGeometry()
        self.expanded_changed.emit(expanded)
