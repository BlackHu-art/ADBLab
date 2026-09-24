"""纯 Qt 启动画面：保留原始图标，只从左向右恢复底部液体的亮度。"""

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
        self.setFixedSize(240, 240)
        self._source = QImage(resource_path("resources/app-icon.png"))
        if self._source.isNull():
            # QImage 默认读取 ICO 的首档 16px；显式请求大档，避免回退后图标模糊。
            self._source = QIcon(resource_path("icon.ico")).pixmap(256, 256).toImage()
        self._cached_dpr = 0.0
        self._icon = QPixmap()
        self._liquid = self._liquid_boundary()
        self._progress = 0.0
        self._target = 0.0
        self._animation_from = 0.0
        self._elapsed = QElapsedTimer()
        self._animation = QTimer(self)
        self._animation.setInterval(33)
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
        """仅接受前进的阶段；缓动追赶真实目标，关闭后的晚到进度无效。"""

        if self._closed or not math.isfinite(value):
            return
        target = max(0.0, min(100.0, float(value)))
        if target < self._target:
            return
        if self._animation.isActive():
            # 阶段构建可能占满 GUI 线程；先兑现真实经过的时间，再衔接新目标。
            self._advance()
        if not animate:
            self._animation.stop()
            self._target = self._progress = target
        elif target > self._target:
            self._animation_from = self._progress
            self._target = target
            self._elapsed.start()
            self._animation.start()
        if self.isVisible():
            # 零间隔阶段调度可能推迟普通 update；只重绘完整的启动窗，不重入事件循环。
            self.repaint()
        else:
            self.update()

    @Slot()
    def _advance(self) -> None:
        fraction = min(1.0, self._elapsed.elapsed() / 150.0)
        eased = 1.0 - (1.0 - fraction) ** 3
        self._progress = self._animation_from + (self._target - self._animation_from) * eased
        if fraction >= 1.0:
            self._progress = self._target
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
        self.first_painted.emit()

    def paintEvent(self, event: QPaintEvent) -> None:
        dpr = self.devicePixelRatioF()
        if dpr != self._cached_dpr:
            image = self._source.scaled(
                round(192 * dpr), round(192 * dpr),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
            image.setDevicePixelRatio(dpr)
            self._icon = QPixmap.fromImage(image)
            self._cached_dpr = dpr

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(QPointF(24, 24), self._icon)
        if self._progress < 100:
            painter.translate(24, 24)
            painter.scale(.75, .75)
            painter.setClipPath(self._liquid)
            # 保留原像素 alpha，透明边缘不能因反复叠色变成不透明描边。
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            boundary = 31 + 194 * self._progress / 100
            if self._progress <= 0:
                painter.fillRect(0, 166, 256, 66, QColor(6, 60, 146, 158))
            else:
                edge = QLinearGradient(boundary - .5, 0, boundary + 1, 0)
                edge.setColorAt(0, QColor(6, 60, 146, 0))
                edge.setColorAt(1, QColor(6, 60, 146, 158))
                painter.fillRect(0, 166, 256, 66, edge)
        painter.end()
        if self.isVisible() and not self._closed and not self._first_frame_pending:
            self._first_frame_pending = True
            self._first_frame_ready.emit()
