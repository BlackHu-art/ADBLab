"""把共享任务投影绘制到导航入口，不拥有任务或执行资源。"""

from __future__ import annotations

import weakref
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QLineF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap
from qfluentwidgets import FluentIcon, NavigationPushButton

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole


@dataclass(frozen=True)
class TaskNavigationSnapshot:
    """携带去重后的全局任务数；成功身份只由实时在途到成功的转换产生。

    调用方不得把初始终态、历史、说明记录或任务消失解释为成功事件。
    已消费的成功身份不得重新发布；控件另保留最近 160 个身份防止重复刷新。
    busy_count 为 None 时兼容旧活动动画；显式整数只驱动过渡阶段的动画。
    """

    active_count: int = 0
    unread_count: int = 0
    success_event_id: str | None = None
    busy_count: int | None = None


class _TaskStatusIcon(QIconEngine):
    """只替换父控件的图标绘制，保留原生导航背景、文字和选中指示。"""

    def __init__(self, owner: TaskNavigationButton) -> None:
        super().__init__()
        self._owner = weakref.ref(owner)

    def paint(self, painter, rect, mode, state) -> None:
        owner = self._owner()
        if owner is not None:
            owner._draw_status(painter, QRectF(rect))

    def clone(self) -> QIconEngine:
        owner = self._owner()
        return _TaskStatusIcon(owner) if owner is not None else QIconEngine()

    def pixmap(self, size, mode, state) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            self.paint(painter, pixmap.rect(), mode, state)
        finally:
            painter.end()
        return pixmap


class TaskNavigationButton(NavigationPushButton):
    """主线程接收共享投影；隐藏丢弃成功反馈，关闭后拒绝晚到快照。

    父对象拥有两个 Timer；状态更新不提交或取消业务。活动、未读异常和成功提示
    依次覆盖，成功被覆盖后不排队重播。只有实际可见时推进动画与成功倒计时。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(FluentIcon.HISTORY, tr("任务中心"), True, parent)
        self.setObjectName("taskNavigationButton")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._snapshot = TaskNavigationSnapshot()
        self._closed = False
        self._presentation_enabled = True
        self._initialized = False
        self._success_visible = False
        self._success_ids: deque[str] = deque(maxlen=160)
        self._angle = 0
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(40)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._success_timer = QTimer(self)
        self._success_timer.setSingleShot(True)
        self._success_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._success_timer.setInterval(3000)
        self._success_timer.timeout.connect(self._clear_success)
        self.setIcon(QIcon(_TaskStatusIcon(self)))
        BaseStyles.ui_font_changed.connect(self._refresh_appearance)
        BaseStyles.theme_changed.connect(self._refresh_appearance)
        BaseStyles.accent_color_changed.connect(self._refresh_appearance)
        self._refresh_appearance()
        self._update_description()

    def set_snapshot(self, snapshot: TaskNavigationSnapshot) -> None:
        """消费全局快照；重复事件不延长成功期限，高优先状态立即丢弃成功提示。"""
        if self._closed:
            return
        if self._initialized and snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        event_id = snapshot.success_event_id
        unseen_success = event_id is not None and event_id not in self._success_ids
        fresh_success = self._initialized and unseen_success
        self._initialized = True
        if unseen_success and event_id is not None:
            self._success_ids.append(event_id)
        if (snapshot.active_count > 0 or snapshot.unread_count > 0
                or not self.isVisible() or not self._presentation_enabled):
            self._clear_success()
        elif fresh_success:
            self._success_visible = True
            self._success_timer.start()
        self._sync_animation()
        self._update_description()
        self._update_status()

    def set_presentation_enabled(self, enabled: bool) -> None:
        """宿主隐藏或最小化时停钟并丢弃成功提示；仍消费快照，恢复不重播后台成功。"""
        if self._closed:
            return
        self._presentation_enabled = enabled
        if not enabled:
            self._clear_success()
        self._sync_animation()

    def _update_description(self) -> None:
        parts = [tr("任务中心")]
        if self._snapshot.active_count > 0:
            parts.append(tr("进行中 {count} 项").format(count=self._snapshot.active_count))
        if self._snapshot.unread_count > 0:
            parts.append(tr("未读异常 {count} 项").format(count=self._snapshot.unread_count))
        if self._success_visible:
            parts.append(tr("已完成"))
        text = " · ".join(parts)
        self.setAccessibleName(text)
        self.setToolTip(text)

    def _clear_success(self) -> None:
        self._success_timer.stop()
        if not self._success_visible:
            return
        self._success_visible = False
        self._update_description()
        self._update_status()

    def _update_status(self) -> None:
        """仅刷新原生图标及环、角标的外沿，避免动画反复合成整行透明背景。"""
        self.update(QRect(7 + self._margins().left(), 4, 30, 29))

    def _is_busy(self) -> bool:
        """旧调用沿用活动动画，任务页显式区分资源活动与阶段忙碌。"""
        count = self._snapshot.busy_count
        return (self._snapshot.active_count if count is None else count) > 0

    def _sync_animation(self) -> None:
        if (not self._closed and self._presentation_enabled and self.isVisible()
                and self._is_busy()):
            if not self._animation_timer.isActive():
                self._animation_timer.start()
        else:
            self._animation_timer.stop()

    def _advance_animation(self) -> None:
        if self._closed:
            return
        self._angle = (self._angle + 12) % 360
        self._update_status()

    def _refresh_appearance(self, *_args) -> None:
        if not self._closed:
            self.setFont(BaseStyles.font_for_role(FontRole.UI))
            self.update()

    def _draw_status(self, painter, rect: QRectF) -> None:
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        warning = QColor(BaseStyles.color("LOG_WARNING"))
        if self._snapshot.active_count > 0:
            # 固定逻辑像素保持紧凑入口可读，字体族沿用界面设置，DPI 由 Qt 缩放。
            blue = QColor(BaseStyles.color("BUTTON_ACCENT"))
            ring = rect.adjusted(-2, -2, 2, 2)
            faint = QColor(blue)
            faint.setAlpha(55)
            painter.setPen(QPen(faint, 2))
            painter.drawEllipse(ring)
            painter.setPen(QPen(blue, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if self._is_busy():
                painter.drawArc(ring, -self._angle * 16, 245 * 16)
            else:
                # 稳定持续运行用完整强调色环，不能留下冻结的加载缺口。
                painter.drawEllipse(ring)
            count = str(self._snapshot.active_count) if self._snapshot.active_count < 100 else "99+"
            font = QFont(self.font())
            font.setPixelSize(8 if len(count) > 2 else 10)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, count)
            if self._snapshot.unread_count > 0:
                painter.setPen(QPen(QColor(BaseStyles.color("PANEL_BG")), 1.5))
                painter.setBrush(warning)
                painter.drawEllipse(QRectF(rect.right() - 1, rect.top() - 3, 6, 6))
        elif self._snapshot.unread_count > 0:
            painter.setPen(QPen(warning, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(rect)
            center = rect.center()
            painter.drawLine(QLineF(center.x(), rect.top() + 4, center.x(), rect.top() + 9))
            painter.setBrush(warning)
            painter.drawEllipse(QRectF(center.x() - .8, rect.bottom() - 4, 1.6, 1.6))
        elif self._success_visible:
            painter.setPen(QPen(QColor(BaseStyles.color("LOG_SUCCESS")), 2,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath()
            path.moveTo(rect.left() + 2, rect.center().y())
            path.lineTo(rect.left() + 6, rect.bottom() - 3)
            path.lineTo(rect.right() - 1, rect.top() + 3)
            painter.drawPath(path)
        else:
            FluentIcon.HISTORY.render(painter, rect)
        painter.restore()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation()

    def hideEvent(self, event) -> None:
        self._animation_timer.stop()
        self._clear_success()
        super().hideEvent(event)

    def shutdown(self) -> None:
        """幂等封闭快照准入并停止自有 Timer；不改变任务状态或执行资源。"""
        self._closed = True
        self._animation_timer.stop()
        self._success_timer.stop()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        activate = self.isPressed and self.rect().contains(event.position().toPoint())
        self.isPressed = False
        self.update()
        if activate:
            self.click()
        event.accept()
