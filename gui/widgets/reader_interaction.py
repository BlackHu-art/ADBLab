"""阅读器的呈现期动作边界；撤销未完按钮激活及只读正文菜单，不干预后台数据。"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction, QContextMenuEvent
from PySide6.QtWidgets import QAbstractButton, QPlainTextEdit, QTextEdit, QWidget
from qfluentwidgets.components.widgets.menu import TextEditMenu
from shiboken6 import isValid

from gui.widgets.task_action_gesture import TaskActionGesture


class ReaderInteraction(QObject):
    """只允许同一连续呈现和身份内的动作；独立阅读器由调用方默认允许。

    菜单归正文编辑器所有，撤销时只关闭本边界创建的菜单并禁用其私有 QAction。
    不禁用业务按钮、不屏蔽数据更新；已经撤销的菜单动作不会因重新展开而恢复。
    """

    def __init__(
        self, owner: QWidget, allowed: Callable[[], bool], identity: Callable[[], str],
    ) -> None:
        super().__init__(owner)
        self._owner = weakref.ref(owner)
        self._allowed = allowed
        self._identity = identity
        self._gestures: list[TaskActionGesture] = []
        self._editors: weakref.WeakKeyDictionary[QWidget, QPlainTextEdit] = (
            weakref.WeakKeyDictionary()
        )
        self._menus: weakref.WeakSet[TextEditMenu] = weakref.WeakSet()
        owner.installEventFilter(self)

    def bind_button(self, button: QAbstractButton, callback: Callable[[], None]) -> None:
        """按下时冻结准入与阅读身份；迟到 clicked 不能借用另一次展开或另一条正文。"""
        gesture = TaskActionGesture(
            button, lambda: (self._identity(), False, ""), admission=self._allowed,
        )
        gesture.activated.connect(lambda key, _stop, _revision: self._dispatch(key, callback))
        self._gestures.append(gesture)

    def _dispatch(self, key: str, callback: Callable[[], None]) -> None:
        if self._allowed() and key == self._identity():
            callback()

    def watch_editor(self, editor: QPlainTextEdit) -> None:
        """复用 Fluent 正文菜单，同时让 viewport 请求服从同一呈现边界。"""
        for surface in (editor, editor.viewport()):
            self._editors[surface] = editor
            surface.installEventFilter(self)

    def revoke(self) -> None:
        """在关闭、隐藏、销毁或身份切换前撤销旧输入及已打开菜单，幂等且无副作用。"""
        for gesture in self._gestures:
            if isValid(gesture):
                gesture.cancel_pending()
        for menu in tuple(self._menus):
            if isValid(menu):
                for action in menu.findChildren(QAction):
                    action.setEnabled(False)
                menu.close()
        self._menus.clear()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide) and watched is self._owner():
            self.revoke()
        if (isinstance(event, QContextMenuEvent) and isinstance(watched, QWidget)
                and watched in self._editors):
            if self._allowed():
                editor = self._editors[watched]
                # 上游注解只列 QTextEdit，但其 PlainTextEdit 原入口也用该共用光标菜单。
                menu = TextEditMenu(cast(QTextEdit, editor))
                self._menus.add(menu)
                menu.exec(event.globalPos())
            event.accept()
            return True
        return super().eventFilter(watched, event)
