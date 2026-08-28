"""互斥分段选择控件。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent._base import apply_font_role_to, repolish

__all__ = ["SegmentedControl"]


class SegmentedControl(QWidget):
    """互斥分段选择控件；选中项发布下标与业务 data。

    契约：
    * ``set_items`` 一次性写入分段文案与可选 data，默认选中第一段；
    * 用户点击或 ``set_current_index`` 都触发 ``selectionChanged(int)``
      与 ``currentChanged(object)``；
    * ``current_data()`` 返回当前段业务数据，无选中返回 ``None``；
    * ``_sync_theme_state()`` 重建分段样式。
    """

    selectionChanged = Signal(int)
    currentChanged = Signal(object)

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        self._data: list[object] = []
        self._current_index = -1
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._group.idClicked.connect(self._on_id_clicked)
        self.setProperty("fontRole", FontRole.UI.value)
        self._sync_theme_state()

    # ── 数据 ────────────────────────────────────────────────────────────

    def set_items(
        self,
        items: Iterable[str],
        *,
        data: Sequence[object] | None = None,
        current_index: int = 0,
    ) -> None:
        """清空后重建分段；``data`` 缺省时以文案作为业务数据。"""

        for button in self._buttons:
            self._group.removeButton(button)
            self._layout.removeWidget(button)
            button.deleteLater()
        self._buttons.clear()
        self._data.clear()
        self._current_index = -1

        texts = [str(item) for item in items]
        values = list(data) if data is not None else list(texts)
        for index, text in enumerate(texts):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("fontRole", FontRole.UI.value)
            button.setFont(BaseStyles.font_for_role(FontRole.UI))
            self._group.addButton(button, index)
            self._layout.addWidget(button)
            self._buttons.append(button)
            self._data.append(values[index] if index < len(values) else text)
        self._refresh_segment_roles()
        if self._buttons:
            self.set_current_index(min(max(0, current_index), len(self._buttons) - 1))

    def count(self) -> int:
        return len(self._buttons)

    def buttons(self) -> tuple[QPushButton, ...]:
        """返回当前分段按钮的不可变序列，供测试与外部接入。"""

        return tuple(self._buttons)

    # ── 选中 ────────────────────────────────────────────────────────────

    def current_index(self) -> int:
        return self._current_index

    def set_current_index(self, index: int) -> None:
        """选中指定分段并发布选择信号。"""

        if not self._buttons:
            self._current_index = -1
            return
        if not 0 <= index < len(self._buttons):
            raise IndexError(f"index 越界：{index}")
        self._current_index = index
        self._buttons[index].setChecked(True)
        self.selectionChanged.emit(index)
        self.currentChanged.emit(self.current_data())

    def current_text(self) -> str:
        """返回当前分段文案，无选中返回空串。"""

        if 0 <= self._current_index < len(self._buttons):
            return self._buttons[self._current_index].text()
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
        for button in self._buttons:
            apply_font_role_to(button, resolved)

    def _on_id_clicked(self, index: int) -> None:
        if index != self._current_index:
            self._current_index = index
            self.selectionChanged.emit(index)
            self.currentChanged.emit(self.current_data())

    def _refresh_segment_roles(self) -> None:
        """为首/中/尾分段标记 ``segment`` property 供 QSS 控制圆角。"""

        last = len(self._buttons) - 1
        for index, button in enumerate(self._buttons):
            if last == 0:
                role = "only"
            elif index == 0:
                role = "first"
            elif index == last:
                role = "last"
            else:
                role = "middle"
            button.setProperty("segment", role)

    def _sync_theme_state(self) -> None:
        """按当前主题重建分段样式。"""

        self.setStyleSheet(self._segmented_style())
        repolish(self)

    def _segmented_style(self) -> str:
        radius = BaseStyles.RADIUS_MD
        bg = BaseStyles.color("BUTTON_BG")
        hover = BaseStyles.color("BUTTON_HOVER")
        pressed = BaseStyles.color("BUTTON_PRESSED")
        border = BaseStyles.color("BORDER_COLOR")
        text = BaseStyles.color("TEXT_PRIMARY")
        accent = BaseStyles.color("BUTTON_ACCENT")
        accent_hover = BaseStyles.color("BUTTON_ACCENT_HOVER")
        # 白色文字沿用现有 accent/danger 按钮的固定对比色约定，P2 迁移到 tokens。
        return (
            f"QPushButton {{"
            f" background-color: {bg}; color: {text};"
            f" border: 1px solid {border}; padding: 4px 12px;"
            f" border-left: none; }}"
            f"QPushButton[segment=\"first\"], QPushButton[segment=\"only\"] {{"
            f" border-left: 1px solid {border};"
            f" border-top-left-radius: {radius}px; border-bottom-left-radius: {radius}px; }}"
            f"QPushButton[segment=\"last\"], QPushButton[segment=\"only\"] {{"
            f" border-top-right-radius: {radius}px; border-bottom-right-radius: {radius}px; }}"
            f"QPushButton:checked {{"
            f" background-color: {accent}; color: #ffffff; border-color: {accent}; }}"
            f"QPushButton:checked:hover {{ background-color: {accent_hover}; }}"
            f"QPushButton:hover:!checked {{ background-color: {hover}; }}"
            f"QPushButton:pressed:!checked {{ background-color: {pressed}; }}"
        )
