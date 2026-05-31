"""Tab base class — shared UI factory methods and device/package accessors."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.double_click_button import DoubleClickButton


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

    def _b(self, t, i, variant="", tooltip=None):
        """Create icon button. variant: '' (default), 'accent', 'danger'."""
        b = QPushButton(t)
        b.setFont(self._font_sm)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setFixedHeight(28)
        b.setIcon(get_themed_icon(i))
        b.setIconSize(QSize(14, 14))
        b.setToolTip(tooltip or t)
        b.setProperty("iconName", i)
        b.setCursor(Qt.PointingHandCursor)
        if variant:
            b.setObjectName(variant)
        return b

    def _db(self, t, i, tooltip=None):
        """Create double-click icon button."""
        b = DoubleClickButton(t)
        b.setFont(self._font_sm)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setFixedHeight(28)
        b.setIcon(get_themed_icon(i))
        b.setIconSize(QSize(14, 14))
        b.setToolTip(tooltip or t)
        b.setProperty("iconName", i)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _qb(self, t, variant="", tooltip=None):
        """Create text-only button. variant: '' (default), 'accent', 'danger'."""
        b = QPushButton(t)
        b.setFont(self._font_sm)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setFixedHeight(28)
        b.setToolTip(tooltip or t)
        b.setCursor(Qt.PointingHandCursor)
        if variant:
            b.setObjectName(variant)
        return b

    def _row(self, *items, spacing=4):
        """Create a compact horizontal row.

        Each item can be a widget or ``(widget, stretch)`` to keep repeated
        panel rows consistent without retyping QHBoxLayout setup everywhere.
        """
        row = QHBoxLayout()
        row.setSpacing(spacing)
        for item in items:
            if isinstance(item, tuple):
                widget, stretch = item
            else:
                widget, stretch = item, 0
            row.addWidget(widget, stretch)
        return row

    def _add_row(self, layout, *items, spacing=4):
        """Create a row and append it to an existing vertical/group layout."""
        row = self._row(*items, spacing=spacing)
        layout.addLayout(row)
        return row

    def _in(self, p, w=0):
        """创建统一样式的输入框。"""
        i = QLineEdit()
        i.setFont(self._font_sm)
        i.setPlaceholderText(p)
        i.setMinimumHeight(26)
        i.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if w:
            i.setMaximumWidth(w)
        return i

    def _combo(self, items=None, font=None):
        """创建统一样式的下拉框。"""
        c = QComboBox()
        c.setFont(font or self._font_sm)
        c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if items:
            c.addItems(items)
        return c

    def _combo_editable(self, items=None, font=None):
        """Create a consistently styled editable combo box."""
        c = self._combo(items, font=font)
        c.setEditable(True)
        if c.lineEdit():
            c.lineEdit().setFont(font or self._font_sm)
        return c
