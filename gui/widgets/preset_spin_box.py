"""提供严格整数输入控件。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QWidget
from qfluentwidgets import EditableComboBox, LineEdit


class StrictIntComboBox(EditableComboBox):
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
        super().__init__(parent=parent)
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
        self.addItems([str(preset) for preset in preset_values])
        editor = self
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
        editor = self
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
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched, event) -> bool:
        if watched is self:
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
        # EditableComboBox（LineEdit）用 setError 渲染错误态，替代旧 inputInvalid QSS。
        self.setError(not valid)
        if changed:
            self.validityChanged.emit(valid)

class StrictIntLineEdit(LineEdit):
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
