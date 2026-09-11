"""首页随内容滚动的全宽横幅，复用主题与字体并按卡片换行自然增高。"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import StrongBodyLabel

from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role
from utils.resource_path import resource_path


class HomeBanner(QWidget):
    """承载首页标题与快捷卡片，不固定高度、不持有业务状态。

    仅持有一份本地横幅原图，不缓存窗口缩放版本；卡片作为子控件随横幅释放。
    主题和字体使用 QObject 绑定槽，销毁后自动断连。
    左上角半径由主窗口材质策略设置，其余边缘始终贴合页面滚动区。
    """

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homeBanner")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._top_left_radius = 0
        self._background = QPixmap(resource_path("resources/images/gallery_header.png"))
        self.title_label = StrongBodyLabel("ADBLab", self)
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)
        layout.addWidget(self.title_label)
        layout.addWidget(content)
        BaseStyles.theme_changed.connect(self._refresh_background)
        BaseStyles.ui_font_changed.connect(self._sync_font)
        self._sync_font()

    def set_top_left_radius(self, radius: int) -> None:
        """与主窗口的内容壳同步左上圆角；独立使用时默认为直角。"""

        radius = max(0, radius)
        if radius != self._top_left_radius:
            self._top_left_radius = radius
            self.update()

    def _refresh_background(self, _value: str) -> None:
        self.update()

    def _sync_font(self, _config=None) -> None:
        apply_label_role(self.title_label, FontRole.TITLE)
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        """按实际宽度测量内容，避免滚动区沿用创建时的单列高度。"""

        layout = self.layout()
        if layout is None:
            return super().sizeHint()
        width = max(1, self.width())
        return QSize(width, layout.heightForWidth(width))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        width, height = float(self.width()), float(self.height())
        radius = min(float(self._top_left_radius), width / 2, height / 2)
        clip = QPainterPath()
        clip.moveTo(radius, 0)
        clip.lineTo(width, 0)
        clip.lineTo(width, height)
        clip.lineTo(0, height)
        clip.lineTo(0, radius)
        clip.quadTo(0, 0, radius, 0)
        clip.closeSubpath()
        painter.setClipPath(clip)

        dark = BaseStyles.resolved_theme() == "Dark"
        wash = QLinearGradient(0, 0, 0, height)
        # 沿用 Gallery 的透明渐变底色，原图自身的颜色不随强调色重绘。
        top_color = QColor(0, 0, 0) if dark else QColor(207, 216, 228)
        clear_color = QColor(top_color)
        clear_color.setAlpha(0)
        wash.setColorAt(0, top_color)
        wash.setColorAt(1, clear_color)
        painter.fillPath(clip, wash)

        if not self._background.isNull():
            # 从原图直接映射至设备像素，避免逻辑分辨率缩略图在高 DPI 下二次放大。
            # 沿用 Gallery 的完整源图到横幅矩形映射，不能按宽度等比裁掉图案或留空。
            painter.drawPixmap(
                QRectF(self.rect()), self._background,
                QRectF(self._background.rect()),
            )
