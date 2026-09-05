"""提供与页面背景融合的 Fluent 内容分区，保留原生卡片的布局接口。"""

from PySide6.QtWidgets import QBoxLayout, QWidget
from qfluentwidgets import HeaderCardWidget


class ContentSection(HeaderCardWidget):
    """通过标题与留白区分内容，不为结构容器绘制卡片底板和边框。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        # 上游标题重载会再次调用 self.__init__，子类需走父对象重载后单独设置标题。
        super().__init__(parent)
        self.setTitle(title)
        self.separator.hide()
        self.headerLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setDirection(QBoxLayout.Direction.TopToBottom)
        self.viewLayout.setContentsMargins(0, 8, 0, 18)
        self.viewLayout.setSpacing(8)

    def paintEvent(self, event) -> None:
        """只绕过结构卡片自绘，子控件继续使用自身的主题背景与交互边界。"""

        QWidget.paintEvent(self, event)
