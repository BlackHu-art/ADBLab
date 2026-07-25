"""提供标签页共享的控件工厂和设备、包名访问接口。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
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

    # ── 共享属性快捷访问 ────────────────────────────────────────────────

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
        """为当前选中设备发出 Shell 命令请求。"""
        self.signals.shell_command_requested.emit(self.selected_devices, cmd)

    # ── 界面控件工厂 ────────────────────────────────────────────────────

    def _g(self, t):
        """创建统一样式的 QGroupBox。"""
        g = QGroupBox(t)
        g.setFont(self._font_base)
        g.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return g

    def _label(self, text: str, *, small: bool = False, align=None) -> QLabel:
        label = QLabel(text)
        label.setFont(self._font_sm if small else self._font_base)
        label.setWordWrap(False)
        if align is not None:
            label.setAlignment(align)
        return label

    def _status_text(self, text: str = "") -> QLabel:
        label = self._label(text)
        label.setObjectName("statusLabel")
        return label

    def _checkbox(self, text: str, tooltip: str | None = None) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setFont(self._font_base)
        if tooltip:
            cb.setToolTip(tooltip)
        return cb

    def _b(self, t, i, variant="", tooltip=None):
        """创建图标按钮；variant 可指定默认、强调或危险样式。"""
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
            self._apply_button_variant(b, variant)
        return b

    def _db(self, t, i, tooltip=None):
        """创建只在双击时触发的图标按钮。"""
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
        """创建纯文本按钮；variant 可指定默认、强调或危险样式。"""
        b = QPushButton(t)
        b.setFont(self._font_sm)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setFixedHeight(28)
        b.setToolTip(tooltip or t)
        b.setCursor(Qt.PointingHandCursor)
        if variant:
            self._apply_button_variant(b, variant)
        return b

    def _apply_button_variant(self, button: QPushButton, variant: str):
        button.setObjectName(variant)
        button.setProperty("buttonVariant", variant)
        button.setStyleSheet(BaseStyles.BUTTON_QSS())
        self._refresh_button_style(button)

    def _refresh_button_style(self, button: QPushButton):
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _set_button_enabled(self, button: QPushButton | None, enabled: bool):
        if button is None:
            return
        button.setEnabled(enabled)
        self._refresh_button_style(button)

    def _row(self, *items, spacing=4):
        """创建紧凑的水平控件行。

        每个参数可以是控件或 ``(widget, stretch)``，用于统一重复面板行的布局规则。
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
        """创建水平控件行并追加到已有的垂直或分组布局。"""
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
        """创建样式一致的可编辑下拉框。"""
        c = self._combo(items, font=font)
        c.setEditable(True)
        if c.lineEdit():
            c.lineEdit().setFont(font or self._font_sm)
        return c
