"""提供业务页面内单层、响应式的功能导航控件。"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, ComboBox, FluentIconBase, ListWidget

from gui.styles import BaseStyles


class AreaNavigationRail(QWidget):
    """同步宽屏功能列表与窄屏下拉框，不持有对应内容页面。"""

    current_changed = Signal(str)

    # 侧栏展开后会占用约 238px；900 的宿主阈值保证右侧内容仍有稳定宽度。
    COMPACT_WIDTH = 900
    RAIL_MAXIMUM_WIDTH = 224

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._keys: list[str] = []
        self._labels: dict[str, str] = {}
        self._icons: dict[str, str | QIcon | FluentIconBase | None] = {}
        self._current_key = ""
        self._compact: bool | None = None
        self._available_width: int | None = None

        self.setObjectName("areaNavigationRail")
        self.setAccessibleName("页面功能导航")
        self.setToolTip("选择当前页面的功能")

        self.list_widget = ListWidget(self)
        self.list_widget.setObjectName("areaNavigationList")
        self.list_widget.setAccessibleName("功能导航")
        self.list_widget.setAccessibleDescription("选择当前页面中显示的功能")
        self.list_widget.setToolTip("选择当前功能")
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_widget.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.list_widget.setMinimumWidth(0)
        self.list_widget.setMaximumWidth(self.RAIL_MAXIMUM_WIDTH)
        self.list_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        # ``rail`` 是面向组装层的语义别名，避免调用方依赖具体列表类命名。
        self.rail = self.list_widget

        self.compact_widget = QWidget(self)
        self.compact_widget.setObjectName("areaNavigationCompact")
        compact_layout = QHBoxLayout(self.compact_widget)
        compact_layout.setContentsMargins(0, 0, 0, 0)
        compact_layout.setSpacing(8)
        self.current_label = BodyLabel("当前功能", self.compact_widget)
        self.current_label.setObjectName("areaNavigationCurrentLabel")
        self.combo = ComboBox(self.compact_widget)
        self.combo.setObjectName("areaNavigationCombo")
        self.combo.setAccessibleName("当前功能")
        self.combo.setAccessibleDescription("选择当前页面中显示的功能")
        self.combo.setToolTip("选择当前功能")
        self.combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.current_label.setBuddy(self.combo)
        compact_layout.addWidget(self.current_label)
        compact_layout.addWidget(self.combo, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(
            self.list_widget,
            1,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(self.compact_widget)

        self.list_widget.currentRowChanged.connect(self._on_list_row_changed)
        self.combo.currentIndexChanged.connect(self._on_combo_index_changed)
        BaseStyles.theme_changed.connect(self._refresh_icons)
        self._sync_navigation_mode(force=True)

    @property
    def current_key(self) -> str:
        """返回当前功能键；尚未添加条目时为空字符串。"""

        return self._current_key

    @property
    def keys(self) -> tuple[str, ...]:
        """按添加顺序返回不可变功能键集合。"""

        return tuple(self._keys)

    def add_item(
        self,
        key: str,
        label: str,
        icon: str | QIcon | FluentIconBase | None = None,
    ) -> None:
        """添加唯一功能项，并在首项加入时建立唯一初始选择。"""

        normalized_key = str(key).strip()
        normalized_label = str(label).strip()
        if not normalized_key or normalized_key in self._labels:
            raise ValueError(f"invalid or duplicate area navigation key: {key!r}")
        if not normalized_label:
            raise ValueError("area navigation label must not be empty")

        item = QListWidgetItem(normalized_label)
        item.setData(Qt.ItemDataRole.UserRole, normalized_key)
        description = f"切换到“{normalized_label}”"
        item.setToolTip(description)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, normalized_label)
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, description)
        if icon is not None:
            item.setIcon(self._to_qicon(icon))

        list_blocker = QSignalBlocker(self.list_widget)
        combo_blocker = QSignalBlocker(self.combo)
        self.list_widget.addItem(item)
        if icon is None:
            self.combo.addItem(normalized_label, userData=normalized_key)
        else:
            self.combo.addItem(
                normalized_label,
                icon=icon,
                userData=normalized_key,
            )
        del combo_blocker
        del list_blocker

        self._keys.append(normalized_key)
        self._labels[normalized_key] = normalized_label
        self._icons[normalized_key] = icon
        if len(self._keys) == 1:
            self.set_current(normalized_key)

    def set_current(self, key: str) -> bool:
        """同步两种导航控件；未知键和重复选择都不会发出信号。"""

        normalized_key = str(key).strip()
        if normalized_key not in self._labels:
            return False

        changed = normalized_key != self._current_key
        self._current_key = normalized_key
        index = self._keys.index(normalized_key)

        list_blocker = QSignalBlocker(self.list_widget)
        combo_blocker = QSignalBlocker(self.combo)
        self.list_widget.setCurrentRow(index)
        self.combo.setCurrentIndex(index)
        del combo_blocker
        del list_blocker

        if changed:
            self.current_changed.emit(normalized_key)
        return True

    def set_available_width(self, width: int) -> None:
        """按业务页面可用宽度选择形态，避免侧栏自身宽度造成误判。"""

        normalized = max(0, int(width))
        if self._available_width == normalized:
            return
        self._available_width = normalized
        self._sync_navigation_mode()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_navigation_mode()

    def _on_list_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._keys):
            self.set_current(self._keys[row])

    def _on_combo_index_changed(self, index: int) -> None:
        if 0 <= index < len(self._keys):
            self.set_current(self._keys[index])

    def _sync_navigation_mode(self, *, force: bool = False) -> None:
        available_width = self._available_width
        compact = (self.width() if available_width is None else available_width) < (
            self.COMPACT_WIDTH
        )
        if not force and compact == self._compact:
            return
        self._compact = compact
        self.list_widget.setVisible(not compact)
        self.compact_widget.setVisible(compact)

    def _refresh_icons(self, *_args) -> None:
        """主题切换后重建 Fluent 图标，避免列表保留旧主题颜色。"""

        for index, key in enumerate(self._keys):
            icon = self._icons.get(key)
            if icon is None:
                continue
            qicon = self._to_qicon(icon)
            self.list_widget.item(index).setIcon(qicon)
            self.combo.setItemIcon(index, qicon)

    @staticmethod
    def _to_qicon(icon: str | QIcon | FluentIconBase) -> QIcon:
        if isinstance(icon, QIcon):
            return icon
        if isinstance(icon, str):
            return QIcon(icon)
        if isinstance(icon, FluentIconBase):
            return icon.icon()
        raise TypeError(f"unsupported area navigation icon: {type(icon).__name__}")


__all__ = ["AreaNavigationRail"]
