"""提供宽屏 Pivot、窄屏下拉框切换的面板内分类容器。"""

from collections.abc import Iterable

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, Pivot


class _CurrentPageStack(QStackedWidget):
    """只用当前分类计算高度，避免隐藏长页继续撑大滚动区域。"""

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()


class AdaptiveCategoryStack(QWidget):
    """一次只展示一个功能分类，并在窄宽度下避免横向导航溢出。"""

    current_changed = Signal(str)
    COMPACT_WIDTH = 620

    def __init__(self, route_prefix: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        prefix = str(route_prefix).strip()
        if not prefix:
            raise ValueError("route_prefix must not be empty")
        self._route_prefix = prefix
        self._pages: dict[str, QWidget] = {}
        self._route_to_key: dict[str, str] = {}
        self._keys: list[str] = []
        self._current_key = ""
        self._compact: bool | None = None
        self._navigation_visible = True

        self.pivot = Pivot(self)
        self.pivot.setObjectName(f"{prefix}CategoryPivot")
        self.pivot.setAccessibleName("功能分类")
        self.combo = ComboBox(self)
        self.combo.setObjectName(f"{prefix}CategoryCombo")
        self.combo.setAccessibleName("功能分类")
        self.combo.setToolTip("选择当前功能分类")
        self.stack = _CurrentPageStack(self)
        self.stack.setObjectName(f"{prefix}CategoryStack")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.pivot)
        layout.addWidget(self.combo)
        layout.addWidget(self.stack, 1)

        self.pivot.currentItemChanged.connect(self._on_pivot_changed)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self._sync_navigation_mode(force=True)

    @property
    def current_key(self) -> str:
        return self._current_key

    @property
    def category_keys(self) -> tuple[str, ...]:
        return tuple(self._keys)

    def add_category(
        self,
        key: str,
        label: str,
        widgets: Iterable[QWidget] = (),
    ) -> QWidget:
        """新增分类页；键在当前容器内唯一，控件按给定顺序纵向排列。"""

        normalized = str(key).strip()
        if not normalized or normalized in self._pages:
            raise ValueError(f"invalid or duplicate category key: {key!r}")
        page = QWidget(self.stack)
        page.setObjectName(f"{self._route_prefix}{normalized.title()}Category")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for widget in widgets:
            page_layout.addWidget(widget)

        route_key = f"{self._route_prefix}:{normalized}"
        self._keys.append(normalized)
        self._pages[normalized] = page
        self._route_to_key[route_key] = normalized
        self.stack.addWidget(page)
        visible_label = str(label)
        self.pivot.addItem(routeKey=route_key, text=visible_label)
        pivot_item = self.pivot.widget(route_key)
        description = f"切换到“{visible_label}”分类"
        pivot_item.setToolTip(description)
        pivot_item.setAccessibleName(description)
        self.combo.addItem(visible_label, userData=normalized)
        if len(self._keys) == 1:
            self.set_current(normalized)
        return page

    def page(self, key: str) -> QWidget | None:
        return self._pages.get(str(key))

    def set_current(self, key: str) -> bool:
        """原子同步分类内容和两种导航控件；未知键不改变当前页面。"""

        normalized = str(key)
        page = self._pages.get(normalized)
        if page is None:
            return False
        changed = normalized != self._current_key
        self._current_key = normalized
        self.stack.setCurrentWidget(page)
        self.stack.updateGeometry()
        self.updateGeometry()
        route_key = f"{self._route_prefix}:{normalized}"
        pivot_blocker = QSignalBlocker(self.pivot)
        self.pivot.setCurrentItem(route_key)
        del pivot_blocker
        combo_index = self._keys.index(normalized)
        combo_blocker = QSignalBlocker(self.combo)
        self.combo.setCurrentIndex(combo_index)
        del combo_blocker
        if changed:
            self.current_changed.emit(normalized)
        return True

    def set_navigation_visible(self, visible: bool) -> None:
        """控制分类导航显隐，内容页与当前选择始终保持可用。"""

        normalized = bool(visible)
        if normalized == self._navigation_visible:
            return
        self._navigation_visible = normalized
        self._sync_navigation_mode(force=True)
        self.stack.updateGeometry()
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_navigation_mode()

    def _on_pivot_changed(self, route_key: str) -> None:
        key = self._route_to_key.get(str(route_key))
        if key is not None:
            self.set_current(key)

    def _on_combo_changed(self, index: int) -> None:
        if 0 <= index < len(self._keys):
            self.set_current(self._keys[index])

    def _sync_navigation_mode(self, *, force: bool = False) -> None:
        compact = self.width() < self.COMPACT_WIDTH
        if not force and compact == self._compact:
            return
        self._compact = compact
        self.pivot.setVisible(self._navigation_visible and not compact)
        self.combo.setVisible(self._navigation_visible and compact)


__all__ = ["AdaptiveCategoryStack"]
