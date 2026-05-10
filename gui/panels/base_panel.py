"""Tab base class — shared UI factory methods and device/package accessors."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from gui.styles.base_styles import BaseStyles
from gui.widgets.double_click_button import DoubleClickButton
from utils.resource_path import resource_path


class BasePanel(QWidget):
    """所有标签页的抽象基类。通过 `panel` 属性访问 SidePanel 的共享状态。"""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel

    # ── Shared properties快捷访问 ──

    @property
    def signals(self):
        return self.panel.signals

    @property
    def selected_devices(self):
        return self.panel.selected_devices

    @property
    def current_package(self):
        """当前选中的包名（来自 AppPanel 的 program_edit）。"""
        if hasattr(self.panel, "_apps_tab") and self.panel._apps_tab:
            return self.panel._apps_tab.package_text
        return ""

    @property
    def _font_sm(self):
        return self.panel._font_sm

    @property
    def _font_mono(self):
        return self.panel._font_mono

    @property
    def _font_base(self):
        return self.panel._font_base

    @property
    def _font_tab(self):
        return self.panel._font_tab

    def _sh(self, cmd: str):
        """Emit a shell command for the selected devices."""
        self.signals.shell_command_requested.emit(self.selected_devices, cmd)

    # ── UI 工厂方法 ──

    def _g(self, t):
        """创建统一样式的 QGroupBox。"""
        g = QGroupBox(t)
        g.setFont(self._font_base)
        g.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return g

    def _b(self, t, i, variant=""):
        """Create icon button. variant: '' (default), 'accent', 'danger'."""
        b = QPushButton(t)
        b.setFont(self._font_sm)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setFixedHeight(28)
        b.setIcon(QIcon(resource_path(f"resources/icons/{i}")))
        b.setIconSize(QSize(14, 14))
        if variant:
            b.setObjectName(variant)
        return b

    def _db(self, t, i):
        """Create double-click icon button."""
        b = DoubleClickButton(t)
        b.setFont(self._font_sm)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setFixedHeight(28)
        b.setIcon(QIcon(resource_path(f"resources/icons/{i}")))
        b.setIconSize(QSize(14, 14))
        return b

    def _qb(self, t, variant=""):
        """Create text-only button. variant: '' (default), 'accent', 'danger'."""
        b = QPushButton(t)
        b.setFont(self._font_sm)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setFixedHeight(28)
        if variant:
            b.setObjectName(variant)
        return b

    def _in(self, p, w=0):
        """创建统一样式的输入框。"""
        i = QLineEdit()
        i.setFont(self._font_sm)
        i.setPlaceholderText(p)
        i.setMaximumHeight(28)
        i.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if w:
            i.setMaximumWidth(w)
        return i

    def _combo(self, items=None, font=None):
        """创建统一样式的下拉框。"""
        c = QComboBox()
        c.setFont(font or self._font_sm)
        if items:
            c.addItems(items)
        return c
