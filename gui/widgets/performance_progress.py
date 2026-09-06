"""以 Fluent 环形进度和状态图标展示采集阶段，不把估算时间当成完成结果。"""

from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    IconWidget,
    IndeterminateProgressRing,
    ProgressRing,
)

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role


class PerformanceProgress(QWidget):
    """展示 GUI 线程传入的阶段与时间，隐藏或终态时停止不定进度动画。"""

    geometry_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._busy = False
        self._animation_enabled = True
        self._state = "idle"
        self._elapsed = 0
        self._duration = 0
        self._active = False
        self.ring = ProgressRing(self)
        self.ring.setFixedSize(36, 36)
        self.ring.setStrokeWidth(3)
        self.ring.setRange(0, 100)
        self.ring.setValue(0)
        self.ring.setFormat("0%")
        self.ring.setTextVisible(True)
        self.ring.setProperty("fontRole", FontRole.UI_SMALL.value)
        self.ring.setAccessibleName(tr("采集进度"))
        self.ring.setToolTip(tr("进度按计划时长估算，报告生成后才确认完成。"))
        self.busy_ring = IndeterminateProgressRing(self, start=False)
        self.busy_ring.setFixedSize(36, 36)
        self.busy_ring.setStrokeWidth(3)
        self.icon = IconWidget(FluentIcon.HISTORY, self)
        self.icon.setFixedSize(24, 24)
        icon_page = QWidget(self)
        icon_layout = QHBoxLayout(icon_page)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignCenter)
        self.indicators = QStackedWidget(self)
        self.indicators.setFixedSize(40, 40)
        self.indicators.addWidget(icon_page)
        self.indicators.addWidget(self.ring)
        self.indicators.addWidget(self.busy_ring)
        self.status_label = BodyLabel(tr("Idle"), self)
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.detail_label = apply_label_role(
            BodyLabel(self), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self.detail_label.setWordWrap(True)
        labels = QVBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(2)
        labels.addWidget(self.status_label)
        labels.addWidget(self.detail_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.indicators)
        layout.addLayout(labels, 1)
        self.setMinimumWidth(0)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.refresh("idle", active=False)
        self.refresh_geometry()

    def refresh_geometry(self) -> None:
        """百分比保留在环内，尺寸随实际字体扩展，避免高 DPI 时裁字。"""
        size = max(48, self.ring.fontMetrics().horizontalAdvance("100%") + 18)
        self.ring.setFixedSize(size, size)
        self.busy_ring.setFixedSize(size, size)
        self.indicators.setFixedSize(size, size)
        self.updateGeometry()
        self.geometry_changed.emit()

    def heightForWidth(self, width: int) -> int:
        width = max(1, width - self.indicators.width() - 12)
        text_height = sum(
            label.heightForWidth(width)
            for label in (self.status_label, self.detail_label)
        ) + 2
        return max(self.indicators.height(), text_height)

    def minimumSizeHint(self) -> QSize:
        """最小高度不依赖构造时宽度，实际换行由状态卡按最终宽度预测。"""
        return QSize(0, self.indicators.height())

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, "indicators"):
            self.refresh_geometry()

    @staticmethod
    def _clock(seconds: int) -> str:
        hours, rest = divmod(max(0, seconds), 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def set_timing(self, elapsed: int, duration: int) -> None:
        """保存本次已用时间，终态继续展示，不依赖额外计时器。"""
        self._elapsed = max(0, elapsed)
        self._duration = max(0, duration)
        self.refresh(self._state, active=self._active)

    def refresh(self, state: str, *, active: bool) -> None:
        """只有真实运行仍在继续时展示估算进度，停止及超时等待使用不定环。"""
        self._state, self._active = state, active
        waiting = active and self._duration > 0 and self._elapsed >= self._duration
        self._busy = state == "stopping" or waiting
        if self._busy:
            self.indicators.setCurrentWidget(self.busy_ring)
        elif active:
            self.indicators.setCurrentWidget(self.ring)
        else:
            self.indicators.setCurrentIndex(0)
        icon, color_key = {
            "completed": (FluentIcon.COMPLETED, "LOG_SUCCESS"),
            "cancelled": (FluentIcon.CANCEL, "TEXT_SECONDARY"),
            "failed": (FluentIcon.CANCEL, "LOG_ERROR"),
            "warning": (FluentIcon.INFO, "LOG_WARNING"),
        }.get(state, (FluentIcon.HISTORY, "TEXT_SECONDARY"))
        # 直接绘制定色 SVG，避免 Python 图标引擎在 QIcon 复制分离后的释放冲突。
        color = QColor(BaseStyles.color(color_key))
        self.icon.setIcon(icon.colored(color, color))
        self.ring.setError(state == "failed")
        self.ring.setPaused(state == "warning")
        if state == "stopping":
            detail = tr("正在停止采集并生成报告，请稍候。")
        elif waiting:
            detail = tr("已达到计划时长，等待采集结束与报告生成。")
        elif active:
            detail = tr("预计进度 {percent}% · 已用 {elapsed} / 计划 {duration}").format(
                percent=self.ring.value(), elapsed=self._clock(self._elapsed),
                duration=self._clock(self._duration),
            )
        elif state == "completed":
            detail = tr("报告已生成，可查看图表或打开结果目录。")
        elif state == "cancelled":
            detail = tr("采集已停止，已生成的结果会保留。")
        elif state == "failed":
            detail = tr("采集失败，请查看运行日志后重试。")
        elif state == "warning":
            detail = tr("采集已结束，结果可能不完整。")
        else:
            detail = tr("配置采集参数后开始，运行期间可查看日志。")
        self.detail_label.setText(detail)
        self.setAccessibleDescription(detail)
        self.updateGeometry()
        self.geometry_changed.emit()
        self._sync_animation()

    def _sync_animation(self) -> None:
        animation_enabled = self._animation_enabled and self.isVisible()
        ring_enabled = animation_enabled and self.indicators.currentWidget() is self.ring
        self.ring.setUseAni(ring_enabled)
        if not ring_enabled:
            self.ring.ani.stop()
        running = self.busy_ring.aniGroup.state() == QAbstractAnimation.State.Running
        if self._busy and animation_enabled:
            if not running:
                self.busy_ring.start()
        elif running:
            self.busy_ring.stop()

    def stop_animation(self) -> None:
        """关闭准入后停止所有显示动画，采集资源仍由页面现有屏障收尾。"""
        self.busy_ring.stop()
        self.ring.setUseAni(False)
        self.ring.ani.stop()

    def set_animation_enabled(self, enabled: bool) -> None:
        """切页仅暂停绘制动画，返回时按保存的阶段恢复，不触碰后台采集。"""
        self._animation_enabled = enabled
        if not enabled:
            self.stop_animation()
        else:
            self._sync_animation()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.stop_animation()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation()
