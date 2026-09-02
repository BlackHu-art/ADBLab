"""主题化下拉框组件。

迁移说明：本组件保持自研实现，不迁移到 qfluentwidgets。原因：qfluentwidgets 把下拉框
拆分为只读的 ``ComboBox``（QPushButton + 弹窗列表）与 ``EditableComboBox``（可编辑）两个
不同类，二者不能在同一实例上切换；而自研契约要求 ``set_editable(True/False)`` 在同实例
切换只读/可编辑（IP 地址输入等场景依赖该能力）。原生 ``QComboBox`` + 主题 QSS 已满足契约，
迁移反而引入回归。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtWidgets import QComboBox, QLineEdit, QSizePolicy, QWidget
from qfluentwidgets import qconfig

from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent._base import apply_font_role_to, repolish

__all__ = ["FluentComboBox"]


class FluentComboBox(QComboBox):
    """主题化下拉框，支持只读与 editable 变体。

    契约：
    * ``set_editable(True)`` 后内置编辑器继承当前字体角色；
    * ``line_edit()`` 对可编辑变体返回非空编辑器（Optional 收窄断言）；
    * ``current_data()`` 返回当前项的 UserRole 业务数据；
    * ``_sync_theme_state()`` 重建输入控件样式并同步编辑器字体。
    """

    def __init__(self, *, editable: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editable = False
        self._font_role = FontRole.UI
        self.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.setProperty("fontRole", FontRole.UI.value)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_editable(editable)
        self._sync_theme_state()
        qconfig.themeChangedFinished.connect(self._sync_theme_state)
        self.destroyed.connect(self._disconnect_theme)

    def _disconnect_theme(self) -> None:
        """销毁时断开主题信号；解释器收尾阶段 qconfig 可能已删除，容错处理。"""

        try:
            qconfig.themeChangedFinished.disconnect(self._sync_theme_state)
        except (RuntimeError, TypeError):
            pass

    # ── editable 变体 ───────────────────────────────────────────────────

    def set_editable(self, editable: bool) -> None:
        """切换只读 / 可编辑形态，并同步内置编辑器字体。"""

        self._editable = bool(editable)
        self.setEditable(self._editable)
        self._sync_editor_font()

    def is_editable(self) -> bool:
        return self._editable

    def line_edit(self) -> QLineEdit:
        """返回内置编辑器；仅当可编辑时非空（Optional 收窄断言）。"""

        editor = self.lineEdit()
        assert editor is not None  # 可编辑下拉框必有内置 QLineEdit
        return editor

    # ── 数据 ────────────────────────────────────────────────────────────

    def set_items(
        self,
        items: Iterable[str],
        *,
        data: Sequence[object] | None = None,
        current_index: int = 0,
    ) -> None:
        """清空后批量写入项与可选 UserRole 数据，并选中指定下标。"""

        self.clear()
        self.addItems([str(item) for item in items])
        if data is not None:
            for index, value in enumerate(data):
                if index < self.count():
                    self.setItemData(index, value)
        if self.count() and 0 <= current_index < self.count():
            self.setCurrentIndex(current_index)

    def add_data_item(self, text: str, data: object | None = None) -> None:
        """追加一个携带 UserRole 业务数据的项。"""

        self.addItem(text, data)

    def current_data(self) -> object | None:
        """返回当前项的业务数据，无选中时返回 ``None``。"""

        return self.currentData()

    # ── 字体与主题 ──────────────────────────────────────────────────────

    def apply_font_role(self, role: FontRole | str) -> None:
        """切换字体角色并同步内置编辑器。"""

        self._font_role = apply_font_role_to(self, role)
        self._sync_editor_font()

    def _sync_editor_font(self) -> None:
        if not self._editable:
            return
        editor = self.lineEdit()
        if editor is not None:
            editor.setFont(BaseStyles.font_for_role(self._font_role))
            editor.setProperty("fontRole", self._font_role.value)

    def _sync_theme_state(self) -> None:
        """按当前主题重建输入控件样式。"""

        self.setStyleSheet(BaseStyles.COMBO_BOX_STYLE())
        self._sync_editor_font()
        repolish(self)
