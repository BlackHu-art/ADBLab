"""日志页：包装既有 LogPanel 控件，保持其全部公开行为。

``LogPage`` 只是页面宿主：默认内部持有并布局一个 :class:`~gui.panels.log_panel.LogPanel`，
也可包装外部已有实例（如 ``MainFrame.log_panel``）。其余公开属性 / 方法
（``clear``、``set_max_lines``、``text_output`` 等）通过 ``__getattr__`` 委托。
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.panels.log_panel import LogPanel

__all__ = ["LogPage"]


class LogPage(QWidget):
    """日志页宿主；内部持有 :class:`~gui.panels.log_panel.LogPanel`。"""

    def __init__(
        self,
        log_panel: LogPanel | None = None,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("logPage")
        self._panel = log_panel if log_panel is not None else LogPanel(parent=self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._panel)

    @property
    def log_panel(self) -> LogPanel:
        """返回被包装的 LogPanel 实例。"""

        return self._panel

    def __getattr__(self, name: str):
        """把未定义属性委托给内部 LogPanel，保持全部公开行为。"""

        panel = self.__dict__.get("_panel")
        if name.startswith("_") or panel is None:
            raise AttributeError(name)
        return getattr(panel, name)
