"""提供标签页共享的控件工厂和设备、包名访问接口。"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.double_click_button import DoubleClickButton
from gui.widgets.responsive_layout import reflow_widgets, responsive_column_count


class BasePanel(QWidget):
    """所有标签页的抽象基类。通过 `panel` 属性访问 SidePanel 的共享状态。"""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self._responsive_rows = []

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
        g.setProperty("fontRole", FontRole.UI.value)
        g.setStyleSheet(BaseStyles.GROUP_BOX_STYLE())
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return g

    def _label(self, text: str, *, small: bool = False, align=None) -> QLabel:
        role = FontRole.UI_SMALL if small else FontRole.UI
        label = QLabel(text)
        label.setFont(
            BaseStyles.font_for_role(FontRole.UI_SMALL) if small else self._font_base
        )
        label.setProperty("fontRole", role.value)
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
        cb.setProperty("fontRole", FontRole.UI.value)
        if tooltip:
            cb.setToolTip(tooltip)
        return cb

    def _b(self, t, i, variant="", tooltip=None):
        """创建图标按钮；variant 可指定默认、强调或危险样式。"""
        b = QPushButton(t)
        b.setFont(self._font_sm)
        b.setProperty("fontRole", FontRole.UI.value)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setMinimumHeight(28)
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
        b.setProperty("fontRole", FontRole.UI.value)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setMinimumHeight(28)
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
        b.setProperty("fontRole", FontRole.UI.value)
        b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        b.setMinimumHeight(28)
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

    def _add_responsive_row(
        self,
        layout,
        *items,
        spacing=4,
        compact_columns=2,
        medium_columns=2,
        wide_columns=None,
    ):
        """创建只重排既有控件的响应式网格行。"""

        widgets = tuple(item[0] if isinstance(item, tuple) else item for item in items)
        stretches = tuple(item[1] if isinstance(item, tuple) else 0 for item in items)
        row = QGridLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(spacing)
        row.setVerticalSpacing(spacing)
        spec = {
            "layout": row,
            "widgets": widgets,
            "stretches": stretches,
            "compact_columns": compact_columns,
            "medium_columns": medium_columns,
            "wide_columns": wide_columns or len(widgets),
            "mode": None,
        }
        self._responsive_rows.append(spec)
        layout.addLayout(row)
        self._reflow_responsive_row(spec, 10_000)
        return row

    @staticmethod
    def _reflow_responsive_row(spec, width: int):
        columns = responsive_column_count(
            width,
            compact_columns=spec["compact_columns"],
            medium_columns=spec["medium_columns"],
            wide_columns=spec["wide_columns"],
        )
        columns = min(columns, max(1, len(spec["widgets"])))
        if spec["mode"] == columns:
            return
        spec["mode"] = columns
        reflow_widgets(
            spec["layout"],
            spec["widgets"],
            columns,
            widget_stretches=spec["stretches"],
        )

    def apply_responsive_width(self, width: int) -> None:
        """仅在跨越布局断点时重排本面板登记的响应式行。"""

        for spec in self._responsive_rows:
            self._reflow_responsive_row(spec, width)

    def _in(self, p, w=0):
        """创建统一样式的输入框。"""
        i = QLineEdit()
        i.setFont(self._font_sm)
        i.setProperty("fontRole", FontRole.UI.value)
        i.setPlaceholderText(p)
        i.setMinimumHeight(26)
        i.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if w:
            i.setMaximumWidth(w)
        return i

    def _combo(self, items=None, font=None, *, font_role=FontRole.UI):
        """创建统一样式的下拉框。"""
        role = FontRole(font_role)
        role_font = self._font_sm if role is FontRole.UI else BaseStyles.font_for_role(role)
        c = QComboBox()
        c.setFont(font or role_font)
        c.setProperty("fontRole", role.value)
        c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if items:
            c.addItems(items)
        return c

    def _combo_editable(self, items=None, font=None, *, font_role=FontRole.UI):
        """创建样式一致的可编辑下拉框。"""
        role = FontRole(font_role)
        role_font = self._font_sm if role is FontRole.UI else BaseStyles.font_for_role(role)
        resolved_font = font or role_font
        c = self._combo(items, font=resolved_font, font_role=role)
        c.setEditable(True)
        if c.lineEdit():
            c.lineEdit().setFont(resolved_font)
            c.lineEdit().setProperty("fontRole", role.value)
        return c
