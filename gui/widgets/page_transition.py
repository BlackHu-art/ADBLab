"""在稳定几何上提交页面切换，仅为内容提供可取消的轻淡入。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStyle, QWidget

from gui.widgets.frame_animation import FrameAnimation


class PageTransition(QObject):
    """合并同步导航更新；不持有业务会话，也不等待动画来提交业务终态。

    surface 是静止的材质面，content 是其内部透明内容栈。批次只暂缓绘制，不泵事件；
    路由、标题和布局仍同步完成。特效不覆盖 surface，不抓取桌面或缓存云母背景。
    """

    def __init__(self, surface: QWidget, content: QWidget) -> None:
        super().__init__(surface)
        self._surface = surface
        self._content = content
        self._depth = 0
        self._alive = True
        self._surface_alive = True
        self._enabled = True
        self._waiting_for_paint = False
        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.timeout.connect(self._resume_after_paint)
        surface.destroyed.connect(self._surface_destroyed)
        content.destroyed.connect(self._content_destroyed)
        self.effect = QGraphicsOpacityEffect(content)
        self.effect.setOpacity(1.0)
        self.effect.setEnabled(False)
        content.setGraphicsEffect(self.effect)
        self.animation = FrameAnimation(self, owner=content)
        self.animation.setDuration(320)
        self.animation.setStartValue(0.15)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.animation.valueChanged.connect(self._set_opacity)
        self.animation.stateChanged.connect(self._on_animation_state)
        content.installEventFilter(self)

    @contextmanager
    def batch(self, current_key: Callable[[], object]) -> Iterator[None]:
        """嵌套导航共用一次绘制提交，异常也恢复原更新权限及最终不透明状态。"""

        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        before = current_key()
        updates_enabled = self._surface.updatesEnabled()
        self.cancel()
        self._depth = 1
        succeeded = changed = False
        try:
            if updates_enabled:
                self._surface.setUpdatesEnabled(False)
            yield
            changed = before != current_key()
            succeeded = True
        finally:
            self._depth = 0
            try:
                if self._alive:
                    if succeeded and changed and updates_enabled:
                        self._start()
                    else:
                        self.cancel()
            finally:
                if self._surface_alive and updates_enabled:
                    self._surface.setUpdatesEnabled(True)

    def set_enabled(self, enabled: bool) -> None:
        """允许宿主禁用视觉动效，业务切换与最终布局不受影响。"""

        self._enabled = enabled
        if not enabled:
            self.cancel()

    def cancel(self) -> None:
        """直接恢复最终显示；取消不重放路由，也不触发业务回调。"""

        self.animation.stop()
        self._clear_pending_start()
        self._restore_content()

    def _start(self) -> None:
        window = self._content.window()
        if (
            not self._enabled or not self._content.isVisible()
            or window is not None and window.isMinimized()
            or not self._content.style().styleHint(QStyle.StyleHint.SH_Widget_Animate)
        ):
            self._restore_content()
            return
        self.effect.setOpacity(0.15)
        self.effect.setEnabled(True)
        self.animation.start()
        # 首帧的布局与绘制成本不占用淡入时长；暂停态也让现有等待者识别尚未结束。
        self.animation.pause()
        self._waiting_for_paint = self.animation.state() == QAbstractAnimation.State.Paused

    def _resume_after_paint(self) -> None:
        """绘制返回事件循环后再开始推进；取消会撤销此对象持有的单次计时器。"""

        if self._alive and self.animation.state() == QAbstractAnimation.State.Paused:
            self.animation.resume()

    def _clear_pending_start(self) -> None:
        self._waiting_for_paint = False
        self._resume_timer.stop()

    def _set_opacity(self, value: object) -> None:
        if self._alive and isinstance(value, (int, float)):
            self.effect.setOpacity(float(value))

    def _on_animation_state(self, state: object, _previous: object) -> None:
        if state == QAbstractAnimation.State.Stopped:
            self._clear_pending_start()
            self._restore_content()

    def _restore_content(self) -> None:
        if self._alive:
            self.effect.setOpacity(1.0)
            # 稳态绕过离屏特效合成，避免持续增加日志与图表的绘制成本。
            self.effect.setEnabled(False)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Hide, QEvent.Type.Close):
            self.cancel()
        elif event.type() == QEvent.Type.Paint and self._waiting_for_paint:
            self._waiting_for_paint = False
            # 不在 paint 调用栈中修改透明度或重绘；替换路由会先 stop 旧计时器。
            self._resume_timer.start(0)
        return False

    def _content_destroyed(self) -> None:
        self._alive = False
        self._clear_pending_start()

    def _surface_destroyed(self) -> None:
        self._surface_alive = False
