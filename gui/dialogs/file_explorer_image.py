"""提供文件浏览器页内复用的图片预览控件。"""

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ImageLabel, PushButton, SmoothScrollArea

from gui.styles import FontRole
from gui.styles.fluent import apply_label_role
from gui.styles.icon_loader import get_themed_icon


class FileExplorerImagePreview(QWidget):
    """保持页内图片预览稳定，并让源图片适配可视区域。"""

    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self._fit_pending = False
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._refit_image)

        layout = QVBoxLayout(self)
        self.image_viewport = SmoothScrollArea()
        self.image_viewport.setWidgetResizable(False)
        self.image_viewport.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label = ImageLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_viewport.setWidget(self.image_label)
        layout.addWidget(self.image_viewport, 1)

        self.image_info = apply_label_role(
            BodyLabel(), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self.image_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_info.setWordWrap(True)
        self.image_info.setMinimumWidth(0)
        self.image_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.image_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.image_info.setAccessibleName("Image details")
        layout.addWidget(self.image_info)

        self.image_close = PushButton()
        self.image_close.setText("Close")
        self.image_close.setToolTip("Close the image preview")
        self.image_close.setIcon(get_themed_icon("x.svg"))
        self.image_close.setIconSize(QSize(14, 14))
        self.image_close.clicked.connect(self.closeRequested.emit)
        layout.addWidget(self.image_close, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_image_source(self, source: QPixmap, name: str) -> None:
        self._source_pixmap = QPixmap(source)
        details = f"{source.width()}x{source.height()}  |  {name}"
        self.image_info.setText(details)
        self.image_info.setToolTip(details)
        self.image_info.setAccessibleDescription(details)
        self._schedule_fit()

    def _fit_image_to_viewport(self, source: QPixmap) -> QPixmap:
        """从原始图片等比缩放到可视区域，且不放大小图。"""

        available = self.image_viewport.viewport().contentsRect().size()
        if source.isNull() or available.width() <= 0 or available.height() <= 0:
            return QPixmap(source)
        if source.width() <= available.width() and source.height() <= available.height():
            return QPixmap(source)
        return source.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _refit_image(self) -> None:
        self._fit_pending = False
        if self._source_pixmap.isNull():
            return
        pixmap = self._fit_image_to_viewport(self._source_pixmap)
        self.image_label.setPixmap(pixmap)
        self.image_label.setFixedSize(pixmap.size())

    def release_image_source(self) -> None:
        """释放预览前取消待处理适配并清空图片。"""

        self._fit_timer.stop()
        self._fit_pending = False
        self._source_pixmap = QPixmap()
        self.image_label.clear()
        self.image_label.setFixedSize(QSize())

    def _schedule_fit(self) -> None:
        if self._fit_pending:
            return
        self._fit_pending = True
        self._fit_timer.start(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_fit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_fit()

__all__ = ["FileExplorerImagePreview"]
