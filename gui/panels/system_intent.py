"""构建系统页内嵌 Intent 表单，只提交校验后的不可变请求。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox

from gui.i18n import tr
from gui.styles.icon_loader import get_fluent_icon
from services.intent_request import (
    IntentExtra,
    IntentRequest,
    validate_intent_request,
    validate_uri,
)

if TYPE_CHECKING:
    from gui.panels.system_panel import SystemPanel


@dataclass
class _ExtraRow:
    """由广播表单拥有的参数行，删除后不再参与后续请求。"""

    widget: QWidget
    key: QLineEdit
    value_type: ComboBox
    value: QLineEdit
    remove: QPushButton


class SystemIntentControls:
    """所有控件归属现有页面；编辑和校验均不产生设备或文件副作用。"""

    def __init__(self, panel: SystemPanel, layout: QBoxLayout) -> None:
        self.panel = panel
        self.extra_rows: list[_ExtraRow] = []
        self.activity_mode = panel._combo(["组件", "Action", "URI"])
        panel.activity_spec.setPlaceholderText(tr("包名/.Activity"))
        panel._add_responsive_row(
            layout, (self.activity_mode, 1), (panel.activity_spec, 3),
            (panel.btn_start_activity, 1), compact_columns=1, medium_columns=3, wide_columns=3,
        )
        self.advanced_toggle = panel._b(
            "高级参数", "arrow-down.svg", variant="ghost", tooltip="展开或收起 Activity 可选参数",
        )
        self.advanced_toggle.setCheckable(True)
        layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(6)
        self.data_uri = panel._in(tr("Data URI（可选）"))
        self.mime_type = panel._in(tr("MIME（可选，如 text/plain）"))
        self.flags = panel._in(tr("Flags（可选，十进制或 0x）"))
        self.wait = panel._checkbox("等待启动结果", "等待 Activity 启动完成并返回耗时信息")
        panel._add_responsive_row(
            advanced_layout, (self.data_uri, 2), (self.mime_type, 1),
            compact_columns=1, medium_columns=2, wide_columns=2,
        )
        panel._add_responsive_row(
            advanced_layout, (self.flags, 2), (self.wait, 1),
            compact_columns=1, medium_columns=2, wide_columns=2,
        )
        layout.addWidget(self.advanced)
        self.advanced.hide()
        panel.deep_link_uri.setPlaceholderText(tr("https://… 或 app://…"))
        panel.deep_link_uri.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"[A-Za-z][A-Za-z0-9+.-]*:\S+"), panel.deep_link_uri,
        ))
        panel._add_responsive_row(
            layout, (panel.deep_link_uri, 3), (panel.btn_deep_link, 1),
            compact_columns=1, medium_columns=2, wide_columns=2,
        )
        panel._add_responsive_row(
            layout, (panel.broadcast_action, 3), (panel.btn_broadcast, 1),
            compact_columns=1, medium_columns=2, wide_columns=2,
        )
        self.extras = QWidget()
        self.extras_layout = QVBoxLayout(self.extras)
        self.extras_layout.setContentsMargins(0, 0, 0, 0)
        self.extras_layout.setSpacing(6)
        layout.addWidget(self.extras)
        self.add_extra = panel._b(
            "添加广播参数", "file-plus.svg", variant="ghost",
            tooltip="添加带类型的广播附加参数，最多十六项",
        )
        layout.addWidget(self.add_extra)
        self.feedback = panel._label("", small=True)
        layout.addWidget(self.feedback)
        self.feedback.hide()
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.activity_mode.currentIndexChanged.connect(self._mode_changed)
        self.add_extra.clicked.connect(lambda: self.add_extra_row())
        for field in (self.data_uri, self.mime_type, self.flags):
            field.textChanged.connect(lambda _text: panel._update_action_states())
        self.wait.toggled.connect(lambda _checked: panel._update_action_states())

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced.setVisible(expanded)
        self.advanced_toggle.setText(tr("收起高级参数") if expanded else tr("高级参数"))
        icon = "arrow-up.svg" if expanded else "arrow-down.svg"
        self.advanced_toggle.setIcon(get_fluent_icon(icon))
        self.panel.apply_responsive_width(0)

    def _mode_changed(self, index: int) -> None:
        placeholders = ("包名/.Activity", "android.intent.action.VIEW", "https://… 或 app://…")
        self.panel.activity_spec.setPlaceholderText(tr(placeholders[index]))
        self.data_uri.setEnabled(index != 2)
        self.data_uri.setToolTip(tr("URI 模式使用上方输入的地址") if index == 2 else "")
        self.panel._update_action_states()

    def add_extra_row(self) -> _ExtraRow:
        """仅创建本地参数行；全部留空的行不进入请求，最多允许十六行。"""
        if len(self.extra_rows) >= 16:
            return self.extra_rows[-1]
        panel = self.panel
        widget = QWidget(self.extras)
        row_layout = QHBoxLayout(widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        key = panel._in(tr("参数名称"))
        value_type = panel._combo()
        for title, value in (
            ("字符串", "str"), ("布尔", "bool"), ("整数", "int"), ("小数", "float"),
        ):
            value_type.addItem(tr(title), userData=value)
        value_type.setMinimumWidth(panel._combo_closed_minimum_width(value_type, [tr("字符串")]))
        value = panel._in(tr("参数值"))
        remove = panel._b("移除", "trash.svg", variant="ghost", tooltip="移除此广播参数")
        for control, stretch in ((key, 2), (value_type, 1), (value, 3), (remove, 0)):
            row_layout.addWidget(control, stretch)
        row = _ExtraRow(widget, key, value_type, value, remove)
        self.extra_rows.append(row)
        self.extras_layout.addWidget(widget)
        for field in (key, value):
            field.textChanged.connect(lambda _text: panel._update_action_states())
        value_type.currentIndexChanged.connect(lambda _index: self._extra_type_changed(row))
        remove.clicked.connect(lambda: self._remove_extra(row))
        panel._update_action_states()
        return row

    def _extra_type_changed(self, row: _ExtraRow) -> None:
        placeholders = {
            "str": "参数值", "bool": "true 或 false", "int": "整数，如 3", "float": "小数，如 0.5",
        }
        row.value.setPlaceholderText(tr(placeholders[str(row.value_type.currentData())]))
        self.panel._update_action_states()

    def _remove_extra(self, row: _ExtraRow) -> None:
        if row not in self.extra_rows:
            return
        self.extra_rows.remove(row)
        self.extras_layout.removeWidget(row.widget)
        row.widget.hide()
        row.widget.deleteLater()
        self.panel._update_action_states()

    def request(self, kind: str) -> IntentRequest:
        """复制字段为校验后的请求，后续编辑不会改变已经提交的设备操作。"""
        panel = self.panel
        if kind == "broadcast":
            types: tuple[Literal["str", "bool", "int", "float"], ...] = (
                "str", "bool", "int", "float",
            )
            extras = tuple(
                IntentExtra(row.key.text(), types[row.value_type.currentIndex()], row.value.text())
                for row in self.extra_rows if row.key.text() or row.value.text()
            )
            return validate_intent_request(IntentRequest(
                kind="broadcast", action=panel.broadcast_action.text(), extras=extras,
            ))
        mode = self.activity_mode.currentIndex()
        spec = panel.activity_spec.text()
        if not spec.strip():
            raise ValueError(tr("请填写当前模式对应的组件、Action 或 URI。"))
        return validate_intent_request(IntentRequest(
            component=spec if mode == 0 else "", action=spec if mode == 1 else "",
            data_uri=spec if mode == 2 else self.data_uri.text(),
            mime_type=self.mime_type.text(), flags=self.flags.text(), wait=self.wait.isChecked(),
        ))

    def submit(self, kind: str) -> None:
        """程序化 clicked 也必须重新校验，不能依赖按钮禁用状态作为执行边界。"""
        if not self.panel.selected_devices:
            self.update_state()
            return
        try:
            request = self.request(kind)
        except ValueError:
            self.update_state()
            return
        self.panel.signals.execute_intent_requested.emit(self.panel.selected_devices, request)

    def submit_link(self) -> None:
        if not self.panel.selected_devices:
            return
        try:
            uri = validate_uri(self.panel.deep_link_uri.text())
        except ValueError:
            self.update_state()
            return
        self.panel.signals.open_deep_link_requested.emit(self.panel.selected_devices, uri)

    def update_state(self) -> None:
        """输入可在未选设备时编辑；只有有效请求且存在目标时才能执行。"""
        panel = self.panel
        has_device = bool(panel.selected_devices)
        errors = []
        for kind, field, button in (
            ("activity", panel.activity_spec, panel.btn_start_activity),
            ("broadcast", panel.broadcast_action, panel.btn_broadcast),
        ):
            try:
                self.request(kind)
            except ValueError as exc:
                button.setEnabled(False)
                if field.text().strip():
                    errors.append(tr(str(exc)))
            else:
                button.setEnabled(has_device)
        try:
            validate_uri(panel.deep_link_uri.text())
        except ValueError:
            panel.btn_deep_link.setEnabled(False)
            if panel.deep_link_uri.text().strip():
                errors.append(tr("链接需包含协议，如 https:// 或 app://，且不能包含空白。"))
        else:
            panel.btn_deep_link.setEnabled(has_device)
        self.feedback.setText("\n".join(dict.fromkeys(errors)))
        self.feedback.setVisible(bool(errors))
        self.advanced_toggle.setEnabled(True)
        self.add_extra.setEnabled(len(self.extra_rows) < 16)
        for row in self.extra_rows:
            row.remove.setEnabled(True)
