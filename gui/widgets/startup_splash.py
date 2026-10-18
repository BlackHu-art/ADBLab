"""纯 Qt 启动画面：保留原始图标，用液体亮度呈现真实进度和等待活动。"""

from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QPointF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import QWidget

from utils.resource_path import resource_path

# 启动窗保持原图 10% 留白：180px 窗口、18px 留白、144px 图标，液体遮罩
# 仍使用原图的 256 单位坐标，绘制时统一缩放到 144。
SPLASH_SIZE = 180
SPLASH_MARGIN = 18
SPLASH_ICON_SIZE = SPLASH_SIZE - SPLASH_MARGIN * 2
LIQUID_SCALE = SPLASH_ICON_SIZE / 256


class StartupSplash(QWidget):
    """启动协调器拥有本窗口；首帧通知排队投递，完成与用户取消互不混淆。"""

    first_painted = Signal()
    cancelled = Signal()
    _first_frame_ready = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("startupSplash")
        self.setWindowTitle("ADBLab")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(SPLASH_SIZE, SPLASH_SIZE)
        self._source = QImage(resource_path("resources/app-icon.png"))
        if self._source.isNull():
            # QImage 默认读取 ICO 的首档 16px；显式请求大档，避免回退后图标模糊。
            self._source = QIcon(resource_path("icon.ico")).pixmap(256, 256).toImage()
        self._cached_dpr = 0.0
        self._icon = QPixmap()
        self._liquid = self._liquid_boundary()
        self._progress = 0.0
        self._target = 0.0
        self._animate = True
        self._activity_phase = 0.0
        self._elapsed = QElapsedTimer()
        self._animation = QTimer(self)
        self._animation.setTimerType(Qt.TimerType.PreciseTimer)
        self._animation.setInterval(16)
        self._animation.timeout.connect(self._advance)
        self._first_frame_pending = False
        self._first_frame_delivered = False
        self._centered = False
        self._closed = False
        self._first_frame_ready.connect(
            self._publish_first_frame, Qt.ConnectionType.QueuedConnection,
        )

    @staticmethod
    def _liquid_boundary() -> QPainterPath:
        """按原图的 256 单位坐标限定遮罩，瓶身、高光轮廓和白色符号不重画。"""

        path = QPainterPath(QPointF(43.4, 179.5))
        path.cubicTo(72, 165, 98, 176, 115, 180.5)
        path.cubicTo(157, 192.5, 180, 174.4, 201, 176)
        path.quadTo(208, 176, 212, 178.5)
        path.lineTo(221, 197.5)
        path.cubicTo(230, 216, 218, 224, 201, 224)
        path.lineTo(55, 224)
        path.cubicTo(32, 224, 26.5, 212, 34, 195)
        path.closeSubpath()
        return path

    def set_progress(self, value: float, *, animate: bool = True) -> None:
        """仅接受前进的阶段；等待高光不推进进度，animate=False 固定显示。"""

        if self._closed or not math.isfinite(value):
            return
        target = max(0.0, min(100.0, float(value)))
        if target < self._target:
            return
        if self._animation.isActive():
            # 先兑现旧目标已走过的时间，连续到达的阶段不会重置当前位置。
            self._advance()
        self._animate = animate
        if not animate:
            self._animation.stop()
            self._target = self._progress = target
        else:
            self._target = target
            if not self._animation.isActive() and (
                target > self._progress or (self._first_frame_delivered and target < 100)
            ):
                self._elapsed.start()
                self._animation.start()
        if self.isVisible():
            # 零间隔阶段调度可能推迟普通 update；只重绘完整的启动窗，不重入事件循环。
            self.repaint()
        else:
            self.update()

    @Slot()
    def _advance(self) -> None:
        if self._closed:
            return
        # 阶段完成值只负责单调填充；等待高光持续活动，不能冒充下一阶段的进度。
        elapsed = self._elapsed.restart()
        self._activity_phase = (self._activity_phase + elapsed / 1400.0) % 1.0
        fraction = -math.expm1(-elapsed / 160.0)
        self._progress += (self._target - self._progress) * fraction
        if self._target - self._progress <= 0.05:
            self._progress = self._target
            if self._target >= 100:
                self._animation.stop()
        self.update()

    def finish(self) -> None:
        """完成时立即停止动画并关闭，重复调用安全，不发出用户取消信号。"""

        self._animation.stop()
        if self._closed:
            return
        self._closed = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._animation.stop()
        notify_cancelled = not self._closed
        self._closed = True
        super().closeEvent(event)
        if notify_cancelled:
            self.cancelled.emit()

    def showEvent(self, event: QShowEvent) -> None:
        # 首次映射窗口前确定位置，避免默认位置的一帧闪烁；进度刷新不再移动窗口。
        if not self._centered:
            screen = QGuiApplication.screenAt(QCursor.pos()) or self.screen()
            if screen is not None:
                self.move(screen.availableGeometry().center() - self.rect().center())
                self._centered = True
        super().showEvent(event)

    @Slot()
    def _publish_first_frame(self) -> None:
        """绘制栈退出后才放行初始化；在窗口销毁或取消之后不再通知宿主。"""

        if self._closed or self._first_frame_delivered:
            return
        self._first_frame_delivered = True
        # 先启动等待活动再通知宿主；首阶段导入尚未产出任何进度时也能独立刷新。
        if self._animate and self._target < 100 and not self._animation.isActive():
            self._elapsed.start()
            self._animation.start()
        self.first_painted.emit()

    def paintEvent(self, event: QPaintEvent) -> None:
        dpr = self.devicePixelRatioF()
        if dpr != self._cached_dpr:
            image = self._source.scaled(
                round(SPLASH_ICON_SIZE * dpr), round(SPLASH_ICON_SIZE * dpr),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
            image.setDevicePixelRatio(dpr)
            self._icon = QPixmap.fromImage(image)
            self._cached_dpr = dpr

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(QPointF(SPLASH_MARGIN, SPLASH_MARGIN), self._icon)
        if self._progress < 100:
            painter.translate(SPLASH_MARGIN, SPLASH_MARGIN)
            painter.scale(LIQUID_SCALE, LIQUID_SCALE)
            painter.setClipPath(self._liquid)
            # 保留原像素 alpha，透明边缘不能因反复叠色变成不透明描边。
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            boundary = 31 + 194 * self._progress / 100
            wave_phase = self._activity_phase * math.tau
            liquid_path = QPainterPath()
            liquid_path.moveTo(boundary, 232)
            for y in range(232, 165, -4):
                x = boundary + 2.6 * math.sin((y - 166) / 14.0 + wave_phase)
                liquid_path.lineTo(x, y)
            liquid_path.lineTo(256, 166)
            liquid_path.lineTo(256, 232)
            liquid_path.closeSubpath()
            edge = QLinearGradient(boundary - 2, 0, boundary + 2, 0)
            edge.setColorAt(0, QColor(6, 60, 146, 0))
            edge.setColorAt(1, QColor(6, 60, 146, 158))
            painter.fillPath(liquid_path, edge)

            # 液面边缘加一条低对比高光，弱化纯色块边界；仍使用 SourceAtop
            # 保留原图 alpha，透明轮廓不会因叠加变厚。
            paint_edge = QPainterPath()
            paint_edge.moveTo(boundary, 232)
            for y in range(232, 165, -4):
                x = boundary + 2.6 * math.sin((y - 166) / 14.0 + wave_phase)
                paint_edge.lineTo(x, y)
            painter.setPen(QColor(105, 175, 245, 72))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(paint_edge)
            painter.setBrush(QColor(6, 60, 146, 158))

            if self._animation.isActive() and self._target < 100:
                center = 128 + 92 * math.sin(self._activity_phase * math.tau)
                activity = QLinearGradient(center - 32, 0, center + 32, 0)
                activity.setColorAt(0, QColor(255, 255, 255, 0))
                activity.setColorAt(.5, QColor(255, 255, 255, 46))
                activity.setColorAt(1, QColor(255, 255, 255, 0))
                painter.save()
                painter.setClipPath(liquid_path, Qt.ClipOperation.IntersectClip)
                painter.fillRect(0, 166, 256, 66, activity)
                painter.restore()
        painter.end()
        if self.isVisible() and not self._closed and not self._first_frame_pending:
            self._first_frame_pending = True
            self._first_frame_ready.emit()
