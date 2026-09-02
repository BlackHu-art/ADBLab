"""互斥分段选择控件（迁移到 qfluentwidgets ``SegmentedWidget``）。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
from qfluentwidgets import SegmentedWidget

from gui.styles import FontRole
from gui.widgets.fluent._base import apply_font_role_to

__all__ = ["SegmentedControl"]


class SegmentedControl(SegmentedWidget):
    """互斥分段选择控件；保留下标契约，内部用 ``routeKey=str(index)`` 桥接 SegmentedWidget。

    契约（沿用自研，调用方无需改动）：
    * ``set_items`` 一次性写入分段文案与可选 data，默认选中第一段；
    * 用户点击或 ``set_current_index`` 都触发 ``selectionChanged(int)`` 与
      ``currentChanged(object)``；
    * ``current_data()`` 返回当前段业务数据，无选中返回 ``None``。

    外观与滑动指示器由 ``SegmentedWidget`` 自行绘制并跟随 qfluentwidgets 主题，
    不再依赖自研 ``_segmented_style()`` QSS。
    """

    selectionChanged = Signal(int)
    currentChanged = Signal(object)

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[object] = []
        self._current_index = -1
        self.currentItemChanged.connect(self._on_current_item_changed)

    # ── 数据 ────────────────────────────────────────────────────────────

    def set_items(
        self,
        items: Iterable[str],
        *,
        data: Sequence[object] | None = None,
        current_index: int = 0,
    ) -> None:
        """清空后重建分段；``data`` 缺省时以文案作为业务数据。"""

        self.clear()
        self._data.clear()
        self._current_index = -1

        texts = [str(item) for item in items]
        values = list(data) if data is not None else list(texts)
        for index, text in enumerate(texts):
            self.addItem(str(index), text)
            self._data.append(values[index] if index < len(values) else text)
        if texts:
            self.setCurrentItem(str(min(max(0, current_index), len(texts) - 1)))

    def count(self) -> int:
        return len(self.items)

    def buttons(self) -> tuple:
        """返回当前分段按钮的不可变序列，供测试与外部接入。"""

        return tuple(self.items.values())

    # ── 选中 ────────────────────────────────────────────────────────────

    def current_index(self) -> int:
        return self._current_index

    def set_current_index(self, index: int) -> None:
        """选中指定分段并发布选择信号。"""

        if not self.items:
            self._current_index = -1
            return
        if not 0 <= index < len(self.items):
            raise IndexError(f"index 越界：{index}")
        self.setCurrentItem(str(index))

    def current_text(self) -> str:
        """返回当前分段文案，无选中返回空串。"""

        if 0 <= self._current_index < len(self.items):
            return self.items[str(self._current_index)].text()
        return ""

    def current_data(self) -> object | None:
        """返回当前分段业务数据，无选中返回 ``None``。"""

        if 0 <= self._current_index < len(self._data):
            return self._data[self._current_index]
        return None

    # ── 字体与主题 ──────────────────────────────────────────────────────

    def apply_font_role(self, role: FontRole | str) -> None:
        """为所有分段按钮切换字体角色。"""

        resolved = FontRole(role)
        for item in self.items.values():
            apply_font_role_to(item, resolved)

    def _on_current_item_changed(self, route_key: str) -> None:
        self._current_index = int(route_key)
        self.selectionChanged.emit(self._current_index)
        self.currentChanged.emit(self.current_data())

    def _sync_theme_state(self) -> None:
        """外观由 SegmentedWidget 自动跟随主题，无需手动重建。"""

        self.update()
