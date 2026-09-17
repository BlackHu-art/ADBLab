"""应用图文行的展示数据与委托；布局随字体伸缩，省略不改变原始名称。"""

from typing import Any, cast

from PySide6.QtCore import QEvent, QItemSelectionModel, QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPalette
from PySide6.QtWidgets import QStyleOptionViewItem, QTreeWidgetItem, QWidget
from qfluentwidgets import TreeItemDelegate, TreeWidget

from gui.i18n import tr
from gui.styles import BaseStyles

STATUS_ROLE = Qt.ItemDataRole.UserRole + 2
VERSION_ROLE = Qt.ItemDataRole.UserRole + 3


class AppManagerIconView(TreeWidget):
    """四列默认填满视口，手工列宽优先，键盘快速定位始终使用应用名称。"""

    def __init__(self, parent: QWidget | None = None):
        self._column_fill_configured = False
        self._auto_fill_enabled = False
        self._filling_columns = False
        super().__init__(parent)
        self.header().sectionResized.connect(self._on_column_resized)

    def enable_auto_column_fill(self) -> None:
        """初始四列配置完成后调用一次；再次调用不会覆盖用户已调整的列宽。"""
        if self._column_fill_configured:
            return
        self._column_fill_configured = True
        self._auto_fill_enabled = True
        self._fill_default_columns()

    def _on_column_resized(self, _column: int, _old_size: int, _new_size: int) -> None:
        # header 的信号也涵盖现有 setColumnWidth 调用，只有本类自动分配可忽略。
        if self._column_fill_configured and not self._filling_columns:
            self._auto_fill_enabled = False

    def _fill_default_columns(self) -> None:
        """默认布局把剩余宽度分给名称和包名，狭窄视口以横滚保留可读宽度。"""
        if not self._auto_fill_enabled or self._filling_columns or not self.isVisible():
            return
        if self.columnCount() != 4:
            return
        metrics = QFontMetrics(self.font())
        labels = self.headerItem()
        widths = [
            max(64, metrics.horizontalAdvance(labels.text(0)) + 24),
            max(160, metrics.horizontalAdvance(labels.text(1)) + 24),
            max(240, metrics.horizontalAdvance(labels.text(2)) + 24),
            max(110, *(metrics.horizontalAdvance(text) + 24 for text in (
                labels.text(3), tr("已启用"), tr("已停用"),
            ))),
        ]
        extra = max(0, self.viewport().width() - sum(widths))
        # 包名通常更长，多分配一份余量；像素余数归包名，确保宽屏右侧没有空列。
        name_extra = extra * 2 // 5
        widths[1] += name_extra
        widths[2] += extra - name_extra
        self._filling_columns = True
        try:
            for column, width in enumerate(widths):
                self.header().resizeSection(column, width)
        finally:
            self._filling_columns = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fill_default_columns()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fill_default_columns()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fill_default_columns()

    def keyboardSearch(self, search: str) -> None:
        # 首列没有文本，其他列也不能改变搜索含义；保留 Qt 的累积匹配和隐藏项规则。
        current = self.currentIndex()
        name_index = current.siblingAtColumn(1) if current.isValid() else self.model().index(0, 1)
        if name_index.isValid():
            self.selectionModel().setCurrentIndex(
                name_index, QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        super().keyboardSearch(search)


def row_status(item: QTreeWidgetItem) -> str:
    """保留状态的业务值，列表和悬停展示同一份本地化文案。"""
    status = item.data(0, STATUS_ROLE)
    return {"Enabled": tr("已启用"), "Disabled": tr("已停用")}.get(status, status or "")


def row_metadata(item: QTreeWidgetItem) -> str:
    """状态保持业务值，只在绘制、提示和辅助技术描述中本地化。"""
    app_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
    type_text = {
        "User": tr("用户"), "System": tr("系统"), "Vendor": tr("厂商"), "Other": tr("其他"),
    }.get(app_type, app_type)
    values = (type_text, row_status(item), item.data(0, VERSION_ROLE))
    return " · ".join(str(value) for value in values if value)


def refresh_row_description(item: QTreeWidgetItem) -> None:
    """详情补全时保留类型和状态，悬停与辅助技术均可取得未截断的信息。"""
    package = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
    description = package + "\n" + row_metadata(item)
    item.setText(3, row_status(item))
    for column in range(4):
        item.setToolTip(column, item.text(1) + "\n" + description)
        item.setData(column, Qt.ItemDataRole.AccessibleDescriptionRole, description)
    item.setData(0, Qt.ItemDataRole.AccessibleTextRole, item.text(1))


class AppManagerRowDelegate(TreeItemDelegate):
    """各列仅绘制自己的内容，真实表头负责调宽、裁剪和水平滚动。"""

    @staticmethod
    def row_height(font: QFont) -> int:
        return max(54, QFontMetrics(font).height() + 20)

    def sizeHint(self, option, index):
        return QSize(0, self.row_height(cast(QWidget, self.parent()).font()))

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # PySide6 的类型存根遗漏这些公开数据成员，限制动态访问在样式选项边界。
        option = cast(Any, option)
        option.font = cast(QWidget, self.parent()).font()
        option.fontMetrics = QFontMetrics(option.font)
        # 标准委托只绘制交互态，内容按列布局；模型仍保留完整的可访问文本。
        option.text = ""
        option.icon = QIcon()
        option.features &= ~(
            QStyleOptionViewItem.ViewItemFeature.HasDisplay
            | QStyleOptionViewItem.ViewItemFeature.HasDecoration
        )

    def paint(self, painter, option, index):
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        painter.save()
        # Fluent 首列背景使用固定左边距，横滚时连同交互底板一起限制在当前单元格。
        painter.setClipRect(option.rect, Qt.ClipOperation.IntersectClip)
        super().paint(painter, background, index)
        if index.column() == 0:
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if isinstance(icon, QIcon):
                icon_rect = QRect(0, 0, 32, 32)
                icon_rect.moveCenter(option.rect.center())
                icon.paint(painter, icon_rect)
        else:
            content = option.rect.adjusted(12, 8, -12, -8)
            font = QFont(cast(QWidget, self.parent()).font())
            color = BaseStyles.get_color("TEXT_SECONDARY")
            if index.column() == 1:
                font.setWeight(QFont.Weight.DemiBold)
                color = cast(Any, background).palette.color(QPalette.ColorRole.Text)
            metrics = QFontMetrics(font)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(
                content,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(str(index.data() or ""), Qt.TextElideMode.ElideRight,
                                   max(0, content.width())),
            )
        painter.restore()

    def _drawIndicator(self, painter, option, index):
        # 强调条只属于行首，避免非首列绘制时重复覆盖图标列。
        if index.column() == 0:
            super()._drawIndicator(painter, option, index)
