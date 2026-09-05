"""提供宽屏 Pivot、窄屏下拉框切换的面板内分类容器。"""

from collections.abc import Iterable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QStackedLayout, QVBoxLayout, QWidget

from gui.widgets.adaptive_navigation import AdaptiveNavigation


class _CurrentPageLayout(QStackedLayout):
    """Qt 父布局直接查询子布局高度，因此在实际布局层排除隐藏长页。"""

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSize(self) -> QSize:
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else QSize(0, 0)

    def hasHeightForWidth(self) -> bool:
        page = self.currentWidget()
        return page.hasHeightForWidth() if page is not None else False

    def heightForWidth(self, width: int) -> int:
        """QStackedLayout 默认取所有页高度，必须同步委托当前页的换行测量。"""

        page = self.currentWidget()
        if page is None:
            return -1
        return page.heightForWidth(width) if page.hasHeightForWidth() else page.sizeHint().height()


class _CurrentPageStack(QWidget):
    """保留分类堆栈入口，使用只测量当前页的原生 QStackedLayout。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page_layout = _CurrentPageLayout(self)

    def addWidget(self, page: QWidget) -> int:
        return self._page_layout.addWidget(page)

    def setCurrentWidget(self, page: QWidget) -> None:
        self._page_layout.setCurrentWidget(page)
        self._page_layout.invalidate()
        self.updateGeometry()

    def currentWidget(self) -> QWidget | None:
        return self._page_layout.currentWidget()

    def count(self) -> int:
        return self._page_layout.count()


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
        self._aliases: dict[str, str] = {}
        self._keys: list[str] = []
        self._current_key = ""
        self._navigation_visible = True

        self.navigation = AdaptiveNavigation(
            prefix, minimum_pivot_width=self.COMPACT_WIDTH, parent=self
        )
        self.pivot = self.navigation.pivot
        self.pivot.setObjectName(f"{prefix}CategoryPivot")
        self.pivot.setAccessibleName("功能分类")
        self.combo = self.navigation.combo
        self.combo.setObjectName(f"{prefix}CategoryCombo")
        self.combo.setAccessibleName("功能分类")
        self.combo.setToolTip("选择当前功能分类")
        self.stack = _CurrentPageStack(self)
        self.stack.setObjectName(f"{prefix}CategoryStack")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)

        self.navigation.current_requested.connect(self.set_current)
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
        if not normalized or normalized in self._pages or normalized in self._aliases:
            raise ValueError(f"invalid or duplicate category key: {key!r}")
        page = QWidget(self.stack)
        page.setObjectName(f"{self._route_prefix}{normalized.title()}Category")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for widget in widgets:
            page_layout.addWidget(widget)

        self._keys.append(normalized)
        self._pages[normalized] = page
        self.stack.addWidget(page)
        self.navigation.add_item(normalized, str(label))
        if len(self._keys) == 1:
            self.set_current(normalized)
        return page

    def add_alias(self, alias: str, target: str) -> None:
        """让旧入口指向已存在的正式分类，不增加页面、导航项或控件归属。"""

        normalized = str(alias).strip()
        canonical = str(target).strip()
        if not normalized or normalized in self._pages or normalized in self._aliases:
            raise ValueError(f"invalid or duplicate category alias: {alias!r}")
        # 别名只接受正式分类作为目标，避免链式映射或循环使导航状态产生歧义。
        if canonical not in self._pages:
            raise ValueError(f"unknown canonical category: {target!r}")
        self._aliases[normalized] = canonical

    def page(self, key: str) -> QWidget | None:
        """返回正式分类或兼容别名对应的同一个页面。"""

        normalized = str(key).strip()
        return self._pages.get(self._aliases.get(normalized, normalized))

    def set_current(self, key: str) -> bool:
        """按正式键同步页面与导航；旧别名可用，未知键不改变当前页面。"""

        requested = str(key).strip()
        normalized = self._aliases.get(requested, requested)
        page = self._pages.get(normalized)
        if page is None:
            return False
        changed = normalized != self._current_key
        self._current_key = normalized
        self.stack.setCurrentWidget(page)
        self.stack.updateGeometry()
        self.updateGeometry()
        self.navigation.set_current(normalized)
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

    def _sync_navigation_mode(self, *, force: bool = False) -> None:
        self.navigation.set_navigation_visible(self._navigation_visible)


__all__ = ["AdaptiveCategoryStack"]
