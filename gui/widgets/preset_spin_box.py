"""提供严格整数输入与可选预设菜单的复合控件。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QValidator
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QToolButton,
    QWidget,
)


class StrictIntComboBox(QComboBox):
    """保持原版可编辑下拉外观，并以严格整数作为业务值。"""

    valueChanged = Signal(int)
    validityChanged = Signal(bool)

    _MAX_INPUT_LENGTH = 64

    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        *,
        presets: Iterable[int] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if minimum > maximum:
            raise ValueError("minimum 不能大于 maximum")
        preset_values = tuple(presets)
        if any(type(preset) is not int for preset in preset_values):
            raise TypeError("预设值必须是 int")
        if any(not minimum <= preset <= maximum for preset in preset_values):
            raise ValueError("预设值必须位于输入范围内")

        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self._presets = preset_values
        self._value = int(value)
        self._input_valid = True
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addItems([str(preset) for preset in preset_values])
        editor = self.lineEdit()
        assert editor is not None  # stub Optional 收窄
        editor.setMaxLength(self._MAX_INPUT_LENGTH)
        editor.installEventFilter(self)
        editor.textChanged.connect(self._on_editor_text_changed)
        editor.editingFinished.connect(self.commit_value)
        self.activated.connect(lambda _index: self.commit_value())
        self.setValue(value)

    def _parse_acceptable(self, text: str) -> int | None:
        if not text or len(text) > self._MAX_INPUT_LENGTH:
            return None
        if any(character < "0" or character > "9" for character in text):
            return None
        try:
            value = int(text, 10)
        except ValueError:
            return None
        return value if self._minimum <= value <= self._maximum else None

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        value = int(value)
        if not self._minimum <= value <= self._maximum:
            raise ValueError("value 必须位于输入范围内")
        changed = value != self._value
        self._value = value
        editor = self.lineEdit()
        assert editor is not None  # stub Optional 收窄
        blocker = QSignalBlocker(editor)
        editor.setText(str(value))
        del blocker
        self._set_input_validity(True)
        if changed:
            self.valueChanged.emit(value)

    def presets(self) -> tuple[int, ...]:
        return self._presets

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def input_is_acceptable(self) -> bool:
        return self._parse_acceptable(self.currentText()) is not None

    def commit_value(self) -> bool:
        parsed = self._parse_acceptable(self.currentText())
        if parsed is None:
            self._set_input_validity(False)
            return False
        self.setValue(parsed)
        return True

    def focus_editor(self) -> None:
        editor = self.lineEdit()
        assert editor is not None  # stub Optional 收窄
        editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.lineEdit():
            if event.type() == QEvent.Type.FocusOut:
                self.commit_value()
            elif event.type() == QEvent.Type.KeyPress and cast(QKeyEvent, event).key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                if not self.commit_value():
                    return True
        return False

    def _on_editor_text_changed(self, _text: str) -> None:
        self._set_input_validity(self.input_is_acceptable())

    def _set_input_validity(self, valid: bool) -> None:
        valid = bool(valid)
        changed = valid != self._input_valid
        self._input_valid = valid
        invalid = not valid
        if self.property("inputInvalid") != invalid:
            self.setProperty("inputInvalid", invalid)
            style = self.style()
            style.unpolish(self)
            style.polish(self)
            self.update()
        if changed:
            self.validityChanged.emit(valid)


class StrictIntLineEdit(QLineEdit):
    """保持普通输入框外观，并在提交边界严格校验 ASCII 整数。"""

    valueChanged = Signal(int)
    validityChanged = Signal(bool)

    _MAX_INPUT_LENGTH = 64

    def __init__(
        self,
        *,
        minimum: int,
        maximum: int,
        value: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if minimum > maximum:
            raise ValueError("minimum 不能大于 maximum")
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self._value = int(value)
        self._input_valid = True
        self.setMaxLength(self._MAX_INPUT_LENGTH)
        self.textChanged.connect(self._on_text_changed)
        self.editingFinished.connect(self.commit_value)
        self.setValue(value)

    def _parse_acceptable(self, text: str) -> int | None:
        if not text or len(text) > self._MAX_INPUT_LENGTH:
            return None
        if any(character < "0" or character > "9" for character in text):
            return None
        try:
            value = int(text, 10)
        except ValueError:
            return None
        return value if self._minimum <= value <= self._maximum else None

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        value = int(value)
        if not self._minimum <= value <= self._maximum:
            raise ValueError("value 必须位于输入范围内")
        changed = value != self._value
        self._value = value
        blocker = QSignalBlocker(self)
        self.setText(str(value))
        del blocker
        self._set_input_validity(True)
        if changed:
            self.valueChanged.emit(value)

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def input_is_acceptable(self) -> bool:
        return self._parse_acceptable(self.text()) is not None

    def commit_value(self) -> bool:
        parsed = self._parse_acceptable(self.text())
        if parsed is None:
            self._set_input_validity(False)
            return False
        self.setValue(parsed)
        return True

    def focus_editor(self) -> None:
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.commit_value():
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.commit_value()
        super().focusOutEvent(event)

    def _on_text_changed(self, _text: str) -> None:
        self._set_input_validity(self.input_is_acceptable())

    def _set_input_validity(self, valid: bool) -> None:
        valid = bool(valid)
        changed = valid != self._input_valid
        self._input_valid = valid
        invalid = not valid
        if self.property("inputInvalid") != invalid:
            self.setProperty("inputInvalid", invalid)
            style = self.style()
            style.unpolish(self)
            style.polish(self)
            self.update()
        if changed:
            self.validityChanged.emit(valid)


class StrictIntSpinBox(QSpinBox):
    """只接受指定范围内 ASCII 十进制文本的整数输入框。"""

    validityChanged = Signal(bool)

    _MAX_INPUT_LENGTH = 64

    def __init__(
        self,
        *,
        minimum: int,
        maximum: int,
        value: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if minimum > maximum:
            raise ValueError("minimum 不能大于 maximum")

        self._input_valid = True
        self.setRange(minimum, maximum)
        self.setKeyboardTracking(False)
        editor = self.lineEdit()
        assert editor is not None  # stub Optional 收窄
        editor.installEventFilter(self)
        editor.textChanged.connect(self._on_editor_text_changed)
        self.setValue(value)

    def _parse_acceptable(self, text: str) -> int | None:
        """解析完全合法的 ASCII 十进制文本，非法时返回 ``None``。"""

        if not text or len(text) > self._MAX_INPUT_LENGTH:
            return None
        if any(character < "0" or character > "9" for character in text):
            return None
        try:
            value = int(text, 10)
        except ValueError:
            return None
        if not self.minimum() <= value <= self.maximum():
            return None
        return value

    def validate(self, text: str, position: int):
        """按严格词法返回 Qt 校验状态，同时保留可继续编辑的中间态。"""

        if self._parse_acceptable(text) is not None:
            return QValidator.State.Acceptable, text, position
        if not text:
            return QValidator.State.Intermediate, text, position
        if len(text) <= self._MAX_INPUT_LENGTH and all("0" <= char <= "9" for char in text):
            return QValidator.State.Intermediate, text, position
        return QValidator.State.Invalid, text, position

    def valueFromText(self, text: str) -> int:
        """仅转换完全合法的文本；非法文本保持当前业务值。"""

        parsed = self._parse_acceptable(text)
        return self.value() if parsed is None else parsed

    def textFromValue(self, value: int) -> str:
        """使用不受本地分组规则影响的 ASCII 十进制格式。"""

        return str(int(value))

    def input_is_acceptable(self) -> bool:
        """返回编辑器当前原文是否可作为业务整数提交。"""

        editor = self.lineEdit()
        assert editor is not None  # stub Optional 收窄
        return self._parse_acceptable(editor.text()) is not None

    def commit_value(self) -> bool:
        """提交当前合法原文；非法时保留原文和旧业务值。"""

        editor = self.lineEdit()
        assert editor is not None  # stub Optional 收窄
        parsed = self._parse_acceptable(editor.text())
        if parsed is None:
            self._set_input_validity(False)
            return False
        self.setValue(parsed)
        return True

    def focus_editor(self) -> None:
        """把键盘焦点交给内部文本编辑器。"""

        editor = self.lineEdit()
        assert editor is not None  # stub Optional 收窄
        editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def setValue(self, value: int) -> None:
        """设置业务值，并在同值调用时也清除非法编辑状态。"""

        editor = self.lineEdit()
        blocker = QSignalBlocker(editor)
        super().setValue(value)
        editor.setText(self.textFromValue(super().value()))
        del blocker
        self._set_input_validity(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """在 Enter 提交前执行严格校验，阻止 Qt 自动纠正非法原文。"""

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self.commit_value():
                event.accept()
                return
        super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        """失焦时提交合法文本，非法文本保持可见且维持无效状态。"""

        if self.commit_value():
            super().focusOutEvent(event)
            return
        self.editingFinished.emit()
        QWidget.focusOutEvent(self, event)

    def eventFilter(self, watched, event) -> bool:
        """在内部编辑器失焦前提交，覆盖 Tab 和鼠标切换焦点路径。"""

        if watched is self.lineEdit() and event.type() == QEvent.Type.FocusOut:
            self.commit_value()
        return False

    def _on_editor_text_changed(self, _text: str) -> None:
        self._set_input_validity(self.input_is_acceptable())

    def _set_input_validity(self, valid: bool) -> None:
        valid = bool(valid)
        changed = valid != self._input_valid
        self._input_valid = valid
        invalid = not valid
        if self.property("inputInvalid") != invalid:
            self.setProperty("inputInvalid", invalid)
            style = self.style()
            style.unpolish(self)
            style.polish(self)
            self.update()
        if changed:
            self.validityChanged.emit(valid)


class PresetSpinBox(QWidget):
    """组合严格整数输入框和可选预设菜单按钮。"""

    valueChanged = Signal(int)
    validityChanged = Signal(bool)

    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        *,
        presets: Iterable[int] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        preset_values = tuple(presets)
        if any(type(preset) is not int for preset in preset_values):
            raise TypeError("预设值必须是 int")
        if any(not minimum <= preset <= maximum for preset in preset_values):
            raise ValueError("预设值必须位于输入范围内")
        self._presets = preset_values

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._spin = StrictIntSpinBox(
            minimum=minimum,
            maximum=maximum,
            value=value,
            parent=self,
        )
        self._spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._spin.valueChanged.connect(self.valueChanged.emit)
        self._spin.validityChanged.connect(self.validityChanged.emit)
        layout.addWidget(self._spin, 1)

        if self._presets:
            self._add_preset_button(layout)

        editor = self._spin.lineEdit()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocusProxy(editor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _add_preset_button(self, layout: QHBoxLayout) -> None:
        button = QToolButton(self)
        button.setObjectName("presetMenuButton")
        button.setAccessibleName("Select a preset value")
        button.setToolTip("Select a preset value")
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))

        menu = QMenu(button)
        for preset in self._presets:
            action = menu.addAction(str(preset))
            action.setData(preset)
            action.triggered.connect(
                lambda _checked=False, selected=preset: self.setValue(selected)
            )
        button.setMenu(menu)
        layout.addWidget(button)

    def value(self) -> int:
        """返回已提交的业务整数。"""

        return self._spin.value()

    def setValue(self, value: int) -> None:
        """设置业务值并清理内部非法编辑状态。"""

        self._spin.setValue(value)

    def presets(self) -> tuple[int, ...]:
        """返回构造时固化的不可变预设。"""

        return self._presets

    def input_is_acceptable(self) -> bool:
        """返回内部编辑器当前原文是否可提交。"""

        return self._spin.input_is_acceptable()

    def commit_value(self) -> bool:
        """提交内部编辑器的合法原文。"""

        return self._spin.commit_value()

    def focus_editor(self) -> None:
        """把键盘焦点交给内部文本编辑器。"""

        self._spin.focus_editor()
