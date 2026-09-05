"""提供由内容宽度和字体共同驱动的工作区与面板功能导航。"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import QApplication, QLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, Pivot

from gui.styles import BaseStyles, FontRole


class AdaptiveNavigation(QWidget):
    """在页签和下拉框间切换，并把用户选择交给所属页面确认。

    本控件只管理导航呈现，不拥有业务页面、返回历史或设备会话。
    ``set_current`` 用于提交选择且不发请求；只有用户操作会发出
    ``current_requested``，所属页面拒绝请求时恢复原来的选中项。
    """

    current_requested = Signal(str)

    def __init__(
        self,
        route_prefix: str,
        *,
        accessible_name: str = "功能分类",
        minimum_pivot_width: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._prefix = route_prefix
        self._keys: list[str] = []
        self._current_key = ""
        self._minimum_pivot_width = max(0, minimum_pivot_width)
        self._navigation_visible = True
        self._compact: bool | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.pivot = Pivot(self)
        self.combo = ComboBox(self)
        self.pivot.setAccessibleName(accessible_name)
        self.combo.setAccessibleName(accessible_name)
        self.combo.setToolTip(f"选择{accessible_name}")
        self.combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.combo.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # 页签的最小宽度只参与模式选择，不能反过来阻止宿主缩窄。
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.addWidget(self.pivot)
        layout.addWidget(self.combo)
        self.pivot.currentItemChanged.connect(self._on_pivot_changed)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        BaseStyles.ui_font_changed.connect(self._apply_font)
        self._apply_font()

    def add_item(self, key: str, label: str) -> None:
        """登记一个唯一功能键，首次登记只初始化选择而不触发业务。"""

        if not key or key in self._keys:
            raise ValueError("navigation key must be nonempty and unique")
        self._keys.append(key)
        pivot_blocker = QSignalBlocker(self.pivot)
        combo_blocker = QSignalBlocker(self.combo)
        self.pivot.addItem(routeKey=f"{self._prefix}:{key}", text=label)
        item = self.pivot.widget(f"{self._prefix}:{key}")
        item.setFont(BaseStyles.font_for_role(FontRole.UI))
        item.setAccessibleName(f"切换到“{label}”")
        item.setToolTip(f"切换到“{label}”")
        self.combo.addItem(label, userData=key)
        del combo_blocker, pivot_blocker
        if not self._current_key:
            self.set_current(key)
        self.refresh_mode()

    def set_current(self, key: str) -> bool:
        """提交有效的当前功能；无效键保持现有状态且返回 False。"""

        if key not in self._keys:
            return False
        self._current_key = key
        pivot_blocker = QSignalBlocker(self.pivot)
        combo_blocker = QSignalBlocker(self.combo)
        self.pivot.setCurrentItem(f"{self._prefix}:{key}")
        self.combo.setCurrentIndex(self._keys.index(key))
        del combo_blocker, pivot_blocker
        return True

    def set_navigation_visible(self, visible: bool) -> None:
        """隐藏导航时仍保留选择，供外层工作区统一驱动内容。"""

        self._navigation_visible = bool(visible)
        self.setVisible(self._navigation_visible)
        self.refresh_mode()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, max(self.pivot.sizeHint().height(), self.combo.sizeHint().height()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_mode()

    def refresh_mode(self) -> None:
        """根据实际内容宽度重排，焦点随可见控件迁移而不改变功能。"""

        pivot_layout = self.pivot.layout()
        if pivot_layout is not None:
            pivot_layout.invalidate()
            pivot_layout.activate()
        required_width = max(self._minimum_pivot_width, self.pivot.minimumSizeHint().width())
        compact = self.width() < required_width
        focus = QApplication.focusWidget()
        had_focus = focus is self.combo or (
            focus is not None and self.pivot.isAncestorOf(focus)
        )
        changed = compact != self._compact
        self._compact = compact
        self.pivot.setVisible(self._navigation_visible and not compact)
        self.combo.setVisible(self._navigation_visible and compact)
        if changed and had_focus and self._navigation_visible:
            target = self.combo if compact else self.pivot.currentItem()
            if target is not None:
                target.setFocus(Qt.FocusReason.OtherFocusReason)
        self.updateGeometry()

    def _apply_font(self, _config=None) -> None:
        """同步应用字体，避免放大字号后继续使用旧的导航断点。"""

        font = BaseStyles.font_for_role(FontRole.UI)
        self.combo.setFont(font)
        self.pivot.setFont(font)
        for item in self.pivot.items.values():
            item.setFont(font)
            item.updateGeometry()
        self.refresh_mode()

    def _on_pivot_changed(self, route_key: str) -> None:
        prefix = f"{self._prefix}:"
        if route_key.startswith(prefix):
            self._request_current(route_key[len(prefix):])

    def _on_combo_changed(self, index: int) -> None:
        if 0 <= index < len(self._keys):
            self._request_current(self._keys[index])

    def _request_current(self, key: str) -> None:
        if key != self._current_key:
            self.current_requested.emit(key)
        # 所属页面的同步槽负责确认或拒绝，此处恢复两种控件的一致性。
        self.set_current(self._current_key)
