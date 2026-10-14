"""让结果选择框适应宿主宽度，同时保留完整选项与业务数据。"""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QPushButton
from qfluentwidgets import ComboBox


class ElidingComboBox(ComboBox):
    """仅省略按钮文案；调用方先脱敏，候选、提示和条目数据保留完整内容。"""

    def setText(self, text: str) -> None:
        self.setToolTip(text)
        self.setAccessibleDescription(text)
        self._sync_display_text(text)

    def minimumSizeHint(self) -> QSize:
        # 外层卡片会逐层读取最小尺寸；文本省略后仍须解除原生按钮的文本宽度约束。
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_display_text(self.currentText())

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._sync_display_text(self.currentText())

    def _sync_display_text(self, text: str) -> None:
        # 绕过 ComboBox 的 adjustSize，避免长名称反向撑宽布局；为箭头保留空间。
        display = self.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideMiddle, max(0, self.width() - 48),
        )
        QPushButton.setText(self, display)
