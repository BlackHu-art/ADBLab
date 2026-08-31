"""主窗口外壳：组合左侧 NavBar 与主内容区（P1-A 结构骨架）。

本阶段只提供结构：``NavBar`` + 页面栈（``QStackedWidget``）的承载、页面注册与
导航路由。页面由 MainFrame 组合根在 P1-C 构造并注册；``settings`` 等无页面键
通过 ``register_nav_callback`` 挂接既有对话框，不在此建页。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from gui.widgets.fluent.nav import NavBar

__all__ = ["MainFrameShell"]


class MainFrameShell(QWidget):
    """NavBar + 页面栈：提供稳定的页面键路由（devices/tasks/logs/settings）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainFrameShell")
        self.nav_bar = NavBar(self)
        self.page_stack = QStackedWidget(self)

        self._pages: dict[str, QWidget] = {}
        self._nav_callbacks: dict[str, Callable[[], None]] = {}

        self.nav_bar.navigate_requested.connect(self.set_page)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.nav_bar)
        layout.addWidget(self.page_stack, stretch=1)

    # ── 页面注册 ────────────────────────────────────────────────────────

    def register_page(self, key: str, widget: QWidget) -> None:
        """把页面控件注册进页面栈（key: devices/tasks/logs）。"""

        self._pages[key] = widget
        self.page_stack.addWidget(widget)

    def set_page(self, key: str) -> None:
        """切换到指定页面；无页面但有导航回调的键（如 settings）执行回调。"""

        widget = self._pages.get(key)
        if widget is not None:
            self.page_stack.setCurrentWidget(widget)
            self.nav_bar.set_current_key(key)
            return
        callback = self._nav_callbacks.get(key)
        if callback is not None:
            self.nav_bar.set_current_key(key)
            callback()

    @property
    def current_page(self) -> str | None:
        """返回当前页面键；无页面时返回 ``None``。"""

        widget = self.page_stack.currentWidget()
        for key, page in self._pages.items():
            if page is widget:
                return key
        return None

    def register_nav_callback(self, key: str, callback: Callable[[], None]) -> None:
        """注册指定键的导航回调（如 settings 打开设置对话框）。"""

        self._nav_callbacks[key] = callback
