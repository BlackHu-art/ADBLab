"""冻结任务动作的物理输入身份，避免同次拖动或按键重复被解释为新版本操作。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from PySide6.QtCore import (
    QAbstractEventDispatcher,
    QEvent,
    QObject,
    QSignalBlocker,
    Qt,
    QTimerEvent,
    Signal,
)
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QAbstractButton
from shiboken6 import isValid


class _RegisteredTimer(Protocol):
    """补齐当前 PySide6 TimerInfo 存根未列出的实际注册标识字段。"""

    timerId: int


class TaskActionGesture(QObject):
    """随按钮销毁的手势边界；只交付按下身份，不决定任务准入或执行停止。

    QAbstractButton 在按住移出、移回时会重发 pressed，不能用它改写物理手势。
    真实输入从 Press 冻结到非重复 Release；AX/programmatic click 没有物理事件，
    仍以 pressed 取得本次身份。放弃手势后的下一次 Press 会覆盖旧身份。
    键盘按压失焦后由 Qt 取消，释放可能交给别的控件；此时必须丢弃旧身份。
    可选 admission 同时约束按下与激活；宿主撤销呈现时还须 cancel_pending，
    不能让 animateClick 的迟到 clicked 借用重新打开后的准入。
    """

    activated = Signal(str, bool, str)

    def __init__(
        self, button: QAbstractButton, capture: Callable[[], tuple[str, bool, str]],
        *, admission: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(button)
        self._capture = capture
        self._admission = admission
        self._input_kind: str | None = None
        self._identity: tuple[str, bool, str] | None = None
        button.installEventFilter(self)
        button.pressed.connect(self._capture_programmatic)
        button.clicked.connect(self._activate)

    def _capture_programmatic(self) -> None:
        if self._input_kind is None:
            self._identity = self._capture_current()

    def _capture_current(self) -> tuple[str, bool, str] | None:
        return self._capture() if self._admission is None or self._admission() else None

    def cancel_pending(self) -> None:
        """呈现撤销时丢弃未完成的输入身份和按压态，不执行动作或改变业务 enabled。"""
        self._input_kind = None
        self._identity = None
        button = self.parent()
        if isinstance(button, QAbstractButton) and isValid(button):
            button.setDown(False)
            dispatcher = QAbstractEventDispatcher.instance(button.thread())
            if dispatcher is not None:
                checked = button.isChecked()
                # setDown 只停重复计时器；由原生基类正常结束动画，内部 QBasicTimer 才会清空。
                # 基类忽略其他 timerId，不调用子类计时逻辑，也不硬杀仍标为 active 的计时器。
                with QSignalBlocker(button):
                    for timer in dispatcher.registeredTimers(button):
                        timer_id = cast(_RegisteredTimer, timer).timerId
                        QAbstractButton.timerEvent(button, QTimerEvent(timer_id))
                    # 原生完成会切换 Toggle；撤销不得改变业务 checked 或交付按钮副作用。
                    if button.isChecked() != checked:
                        button.setChecked(checked)

    def _activate(self) -> None:
        if self._input_kind is not None:
            # 旧 animateClick 定时器可能在新物理手势按住时到期，不能替它完成 Release。
            # 原生按钮已被该定时器松开，恢复按压态让真实 Release 仍按原身份完成。
            button = self.parent()
            if isinstance(button, QAbstractButton) and isValid(button):
                button.setDown(True)
            return
        identity, self._identity = self._identity, None
        if identity is not None and (self._admission is None or self._admission()):
            self.activated.emit(*identity)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        kind = event.type()
        if (
            kind == QEvent.Type.FocusOut and self._input_kind == "keyboard"
            or kind in (QEvent.Type.Hide, QEvent.Type.WindowDeactivate)
            or kind == QEvent.Type.EnabledChange
            and isinstance(watched, QAbstractButton) and not watched.isEnabled()
        ):
            # 鼠标单纯移焦仍可能拖回；只有键盘失焦或控件实际取消输入才清除身份。
            self.cancel_pending()
        if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                self._input_kind = "mouse"
                self._identity = self._capture_current()
            elif event.type() == QEvent.Type.MouseButtonRelease:
                # clicked 在按钮处理 Release 时同步发出，此处仍保留已冻结身份。
                self._input_kind = None
        elif isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Space:
            if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                if event.isAutoRepeat():
                    return True
                self._input_kind = "keyboard" if event.type() == QEvent.Type.KeyPress else None
                if self._input_kind is not None:
                    self._identity = self._capture_current()
        return super().eventFilter(watched, event)
