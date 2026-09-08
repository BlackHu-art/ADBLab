"""首页随内容滚动的全宽横幅，复用主题与字体并按卡片换行自然增高。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import StrongBodyLabel

from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role


class HomeBanner(QWidget):
    """承载首页标题与快捷卡片，不固定高度、不持有业务或外部资源。

    卡片组件作为子控件随横幅释放；主题和字体使用 QObject 绑定槽，销毁后自动断连。
    左上角半径由主窗口材质策略设置，其余边缘始终贴合页面滚动区。
    """

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("homeBanner")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._top_left_radius = 0
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
        BaseStyles.accent_color_changed.connect(self._refresh_background)
        BaseStyles.ui_font_changed.connect(self._sync_font)
        self._sync_font()

    def set_top_left_radius(self, radius: int) -> None:
        """与主窗口的云母壳同步左上圆角；独立使用时默认为直角。"""

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
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

        accent = QColor(BaseStyles.color("BUTTON_ACCENT"))
        dark = BaseStyles.resolved_theme() == "Dark"
        wash = QLinearGradient(0, 0, 0, height)
        top_color = QColor(accent)
        top_color.setAlpha(76 if dark else 40)
        clear_color = QColor(accent)
        clear_color.setAlpha(0)
        wash.setColorAt(0, top_color)
        wash.setColorAt(1, clear_color)
        painter.fillPath(clip, wash)

        # 曲面仅占横幅上部，窄窗卡片增加行数时不把装饰拉长到正文底部。
        curve_height = min(height, 360.0)
        ribbon = QPainterPath()
        ribbon.moveTo(width * 0.38, 0)
        ribbon.cubicTo(
            width * 0.70, curve_height * 0.03,
            width * 0.45, curve_height * 0.62,
            width, curve_height * 0.48,
        )
        ribbon.lineTo(width, 0)
        ribbon.closeSubpath()
        ribbon_fill = QLinearGradient(width * 0.4, 0, width, curve_height * 0.5)
        ribbon_start = QColor(accent)
        ribbon_start.setAlpha(24 if dark else 36)
        ribbon_end = QColor(accent)
        ribbon_end.setAlpha(124 if dark else 108)
        ribbon_fill.setColorAt(0, ribbon_start)
        ribbon_fill.setColorAt(1, ribbon_end)
        painter.fillPath(ribbon, ribbon_fill)

        fold = QPainterPath()
        fold.moveTo(width * 0.70, 0)
        fold.cubicTo(
            width * 0.91, curve_height * 0.08,
            width * 0.66, curve_height * 0.35,
            width, curve_height * 0.32,
        )
        fold.lineTo(width, 0)
        fold.closeSubpath()
        fold_fill = QLinearGradient(width * 0.70, 0, width, curve_height * 0.35)
        fold_fill.setColorAt(0, clear_color)
        fold_end = QColor(accent.lighter(145))
        fold_end.setAlpha(90 if dark else 100)
        fold_fill.setColorAt(1, fold_end)
        painter.fillPath(fold, fold_fill)
