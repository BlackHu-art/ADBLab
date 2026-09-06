"""以缓存设备快照组织工作台，所有选择与设备动作交回主窗口协调。"""

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QEvent, QRect, QSignalBlocker, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QBoxLayout,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    FlowLayout,
    FluentIcon,
    IconWidget,
    PushButton,
    ToolButton,
    TransparentPushButton,
)

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import get_themed_icon


def _metadata_text(value: object) -> str:
    """过滤缓存中的占位值，不能把尚未取得的属性当作设备名称。"""
    text = value.strip() if isinstance(value, str) else ""
    return "" if text.casefold() in {"unknown", "n/a", "-", "detecting"} else text


def _connection_kind(device_id: str) -> str:
    if device_id.startswith("emulator-"):
        return tr("模拟器")
    return tr("无线") if ":" in device_id else "USB"


def _device_name(device_id: str, metadata: Mapping[str, object]) -> str:
    name = _metadata_text(metadata.get("name")) or _metadata_text(metadata.get("alias"))
    if name and name not in {device_id, f"device_{device_id}"}:
        return name
    brand = _metadata_text(metadata.get("Brand"))
    model = _metadata_text(metadata.get("Model"))
    if brand == "ADB":
        brand = ""
    if model:
        if brand and not model.casefold().startswith(brand.casefold()):
            return f"{brand} {model}"
        return model
    return (
        tr("{brand} Android 设备").format(brand=brand) if brand
        else tr("Android {value}设备").format(value=_connection_kind(device_id))
    )


class _DeviceIdentifier(CaptionLabel):
    """只省略标识的展示文本，提示和无障碍描述始终保留完整值。"""

    def __init__(self, device_id: str, parent: QWidget) -> None:
        self._device_id = device_id
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setToolTip(device_id)
        self.setAccessibleName(tr("设备标识"))
        self.setAccessibleDescription(device_id)
        self._refresh_text()

    def _refresh_text(self) -> None:
        self.setText(self.fontMetrics().elidedText(
            self._device_id, Qt.TextElideMode.ElideMiddle, max(1, self.width())
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._refresh_text()


class _DeviceField(QWidget):
    """无边框的参数标签与数值，字段缺失时整体隐藏且保留控件实例。"""

    def __init__(self, title: str, parent: QWidget, value=None, *, icon=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
        self.caption = CaptionLabel(title, self)
        self.caption.setTextColor(
            QColor(BaseStyles.color_for("Light", "TEXT_SECONDARY")),
            QColor(BaseStyles.color_for("Dark", "TEXT_SECONDARY")),
        )
        self.icon = IconWidget(icon, self) if icon is not None else None
        self.value = value if value is not None else BodyLabel(self)
        self.value.setTextFormat(Qt.TextFormat.PlainText)
        self.value.setMinimumWidth(0)
        if not isinstance(self.value, _DeviceIdentifier):
            self.value.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(5)
        if self.icon is not None:
            heading.addWidget(self.icon)
        heading.addWidget(self.caption)
        heading.addStretch(1)
        layout.addLayout(heading)
        layout.addWidget(self.value)
        self.value.installEventFilter(self)
        self.apply_fonts()

    def apply_fonts(self) -> None:
        self.caption.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        role = FontRole.MONO if isinstance(self.value, _DeviceIdentifier) else FontRole.UI
        self.value.setFont(BaseStyles.font_for_role(role))
        self.caption.setMinimumHeight(self.caption.fontMetrics().height())
        if self.icon is not None:
            edge = max(18, min(24, self.caption.fontMetrics().height() - 3))
            self.icon.setFixedSize(edge, edge)
        self._sync_height()

    def set_value(self, text: str) -> None:
        self.value.setText(text)
        self.setVisible(bool(text))
        self._sync_height()

    def _sync_height(self) -> None:
        height = self.value.fontMetrics().height()
        if not isinstance(self.value, _DeviceIdentifier):
            height = max(height, self.value.fontMetrics().boundingRect(
                QRect(0, 0, max(1, self.value.width()), 0), Qt.TextFlag.TextWordWrap,
                self.value.text(),
            ).height())
        self.value.setMinimumHeight(height)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.value and event.type() == QEvent.Type.Resize:
            self._sync_height()
        return super().eventFilter(watched, event)


class _DeviceCard(QWidget):
    """复用设备行，以外部快照驱动选择；双击非操作区只提交一次切换意图。"""

    selection_toggled = Signal(str, bool)
    action_requested = Signal(str, str, str)

    def __init__(self, device_id: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self._selected = False
        self.setObjectName("deviceWorkCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.selection = CheckBox(self)
        self.selection.setToolTip(tr("勾选为批量操作目标，不切换已打开的设备会话"))
        self.selection.clicked.connect(
            lambda checked: self.selection_toggled.emit(self.device_id, checked)
        )
        self.icon = IconWidget(get_themed_icon("device-mobile.svg"), self)
        self.icon.setFixedSize(28, 28)
        self.name_label = BodyLabel(self)
        self.status_label = CaptionLabel(self)
        self.battery_label = CaptionLabel(self)
        self.status_label.setTextColor(
            QColor(BaseStyles.color_for("Light", "TEXT_SECONDARY")),
            QColor(BaseStyles.color_for("Dark", "TEXT_SECONDARY")),
        )
        for label in (self.name_label, self.status_label, self.battery_label):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setMinimumWidth(0)
        self.identity = QWidget(self)
        identity_layout = QHBoxLayout(self.identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(12)
        identity_layout.addWidget(self.selection, 0, Qt.AlignmentFlag.AlignTop)
        identity_layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        identity_layout.addWidget(self.name_label, 1, Qt.AlignmentFlag.AlignTop)
        self.status_container = QWidget(self)
        status_layout = QVBoxLayout(self.status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(3)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.battery_label)
        self._header_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._header_layout.setSpacing(16)
        self._header_layout.addWidget(self.identity, 1)
        self._header_layout.addWidget(self.status_container)
        self.summary_container = QWidget(self)
        self._summary_layout = QGridLayout(self.summary_container)
        self._summary_layout.setContentsMargins(0, 0, 0, 0)
        self._summary_layout.setHorizontalSpacing(16)
        self._summary_layout.setVerticalSpacing(8)
        self.summary_fields = {
            key: _DeviceField(title, self.summary_container, icon=icon)
            for key, title, icon in (
                ("system", tr("系统"), FluentIcon.APPLICATION),
                ("screen", tr("屏幕"), FluentIcon.FULL_SCREEN),
                ("memory", tr("内存"), FluentIcon.SPEED_HIGH),
                ("storage", tr("存储"), FluentIcon.FOLDER),
            )
        }
        self.details_label = self.summary_fields["system"].value
        self.screen_label = self.summary_fields["screen"].value
        self.memory_label = self.summary_fields["memory"].value
        self.details_container = QWidget(self)
        self.detail_parameters = QWidget(self.details_container)
        self._details_layout = QGridLayout(self.detail_parameters)
        self._details_layout.setContentsMargins(0, 0, 0, 0)
        self._details_layout.setHorizontalSpacing(16)
        self._details_layout.setVerticalSpacing(8)
        self.detail_fields = {
            key: _DeviceField(title, self.detail_parameters)
            for key, title in (
                ("Brand", tr("品牌")), ("Model", tr("型号")),
                ("CPU Architecture", tr("CPU 架构")), ("Hardware", tr("硬件平台")),
                ("Density", tr("屏幕密度")), ("Available Memory", tr("可用内存")),
                ("Storage Available", tr("可用存储")),
            )
        }
        self.identifier = _DeviceIdentifier(device_id, self.detail_parameters)
        self.identifier_field = _DeviceField(
            tr("设备标识"), self.detail_parameters, self.identifier
        )
        self.copy_details_button = TransparentPushButton(
            FluentIcon.COPY, tr("复制详情"), self.details_container
        )
        self.copy_details_button.setToolTip(tr("复制此设备当前已获取的全部详情"))
        self.copy_details_button.setAccessibleName(tr("复制此设备当前已获取的全部详情"))
        self.copy_details_button.clicked.connect(self._copy_details)
        self._copy_feedback_timer = QTimer(self)
        self._copy_feedback_timer.setSingleShot(True)
        self._copy_feedback_timer.timeout.connect(
            lambda: self.copy_details_button.setText(tr("复制详情"))
        )
        details_layout = QVBoxLayout(self.details_container)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(8)
        details_layout.addWidget(self.detail_parameters)
        details_layout.addWidget(self.copy_details_button, 0, Qt.AlignmentFlag.AlignRight)
        self.properties_label = self.detail_fields["CPU Architecture"].value
        self.details_container.hide()
        self.details_button = TransparentPushButton(tr("详细信息"), self)
        self.details_button.setCheckable(True)
        self.details_button.setAccessibleName(tr("展开或收起此设备的详细信息"))
        self.details_button.toggled.connect(self._set_details_expanded)
        self.action_container = QWidget(self)
        self._action_layout = FlowLayout(self.action_container)
        self._action_layout.setContentsMargins(0, 0, 0, 0)
        self._action_layout.setHorizontalSpacing(8)
        self._action_layout.setVerticalSpacing(8)
        self.files_button = self._action_button(FluentIcon.FOLDER, tr("文件"), "devices", "files")
        self.remote_button = self._action_button(
            FluentIcon.PROJECTOR, tr("远程"), "devices", "remote"
        )
        self.apps_button = self._action_button(
            FluentIcon.APPLICATION, tr("应用管理"), "apps", "manager"
        )
        self._buttons = (self.files_button, self.remote_button, self.apps_button)
        self._footer_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._footer_layout.setSpacing(14)
        self._footer_layout.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._footer_layout.addStretch(1)
        self._footer_layout.addWidget(self.action_container, 0)
        self._body_layout = QVBoxLayout(self)
        self._body_layout.setContentsMargins(14, 12, 14, 12)
        self._body_layout.setSpacing(12)
        self._body_layout.addLayout(self._header_layout)
        self._body_layout.addWidget(self.summary_container)
        self._body_layout.addLayout(self._footer_layout)
        self._body_layout.addWidget(self.details_container)
        for widget in self.findChildren(QWidget):
            if not isinstance(widget, QAbstractButton):
                widget.installEventFilter(self)
        self.setAccessibleDescription(tr("双击设备名称或空白处选择、取消操作目标"))
        self.apply_fonts()

    def _action_button(self, icon, text: str, section: str, feature: str) -> PushButton:
        button = TransparentPushButton(icon, text, self.action_container)
        button.clicked.connect(
            lambda: self.action_requested.emit(section, feature, self.device_id)
        )
        self._action_layout.addWidget(button)
        return button

    def set_snapshot(self, metadata: Mapping[str, object], selected: bool, state: str) -> None:
        """接收状态源回传的快照，不在卡片内持久化第二份选中集合。"""
        available = state == "ready"
        self._selected = selected
        name = _device_name(self.device_id, metadata)
        self.name_label.setText(name)
        self.name_label.setToolTip(name)
        version = (
            _metadata_text(metadata.get("Aversion"))
            or _metadata_text(metadata.get("Android Version"))
        )
        sdk = _metadata_text(metadata.get("SDK Version"))
        self.summary_fields["system"].set_value(" · ".join(filter(None, (
            f"Android {version}" if version else "", f"API {sdk}" if sdk else "",
        ))))
        self.summary_fields["screen"].set_value(_metadata_text(metadata.get("Resolution")))
        self.summary_fields["memory"].set_value(_metadata_text(metadata.get("Total Memory")))
        self.summary_fields["storage"].set_value(_metadata_text(metadata.get("Storage Total")))
        for key, field in self.detail_fields.items():
            field.set_value(_metadata_text(metadata.get(key)))
        battery = _metadata_text(metadata.get("Battery Level"))
        charging = _metadata_text(metadata.get("Battery Status"))
        if charging in {"充电中", "使用电池", "未充电", "已充满"}:
            charging = tr(charging)
        self.battery_label.setText(" · ".join(filter(None, (
            tr("电量 {battery}").format(battery=battery) if battery else "", charging,
        ))))
        self.battery_label.setVisible(bool(battery or charging))
        connection_state = {
            "ready": tr("在线"), "scanning": tr("扫描中"), "unavailable": tr("连接待确认"),
        }.get(state, tr("已离线"))
        self.status_label.setText(" · ".join(filter(None, (
            _connection_kind(self.device_id), connection_state, tr("已选") if selected else "",
        ))))
        self.selection.setAccessibleName(tr("将 {name} 设为操作目标").format(name=name))
        blocker = QSignalBlocker(self.selection)
        self.selection.setChecked(selected)
        del blocker
        self.selection.setEnabled(available)
        for button, action in zip(
            self._buttons, (tr("管理文件"), tr("打开远程控制"), tr("管理应用"))
        ):
            button.setEnabled(available and selected)
            description = (
                tr("为 {name} {action}；保留其他已选设备").format(name=name, action=action)
                if selected
                else tr("请先选中 {name}，再{action}").format(name=name, action=action)
            )
            button.setToolTip(description)
            button.setAccessibleName(f"{name}：{action}")
        self._reflow()
        self.update()

    def _set_details_expanded(self, expanded: bool) -> None:
        self.details_button.setText(tr("收起详情") if expanded else tr("详细信息"))
        self.details_container.setVisible(expanded)
        self._reflow()

    def _copy_details(self) -> None:
        """只在用户点击时复制当前卡片快照，不查询设备或导出未经筛选的原始属性。"""
        entries = [
            (tr("设备名称"), self.name_label.text()),
            (tr("设备标识"), self.device_id),
            (tr("连接状态"), self.status_label.text()),
            (tr("电池"), self.battery_label.text()),
        ]
        entries.extend(
            (field.caption.text(), field.value.text())
            for field in (*self.summary_fields.values(), *self.detail_fields.values())
        )
        QApplication.clipboard().setText("\n".join(
            f"{title}：{value}" for title, value in entries if value
        ))
        self.copy_details_button.setText(tr("已复制"))
        self._copy_feedback_timer.start(1800)

    def _toggle_from_double_click(self, event: QMouseEvent) -> None:
        # 禁用按钮上的鼠标事件可能落到父容器；仍按命中区域排除操作控件。
        target = self.childAt(self.mapFromGlobal(event.globalPosition().toPoint()))
        while target is not None and target is not self:
            if isinstance(target, QAbstractButton):
                event.accept()
                return
            target = target.parentWidget()
        if event.button() == Qt.MouseButton.LeftButton and self.selection.isEnabled():
            self.selection.click()
        event.accept()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonDblClick and isinstance(event, QMouseEvent):
            self._toggle_from_double_click(event)
            return True
        if (
            event.type() == QEvent.Type.Resize
            and isinstance(watched, (BodyLabel, CaptionLabel))
            and watched in (
                self.name_label, self.status_label, self.battery_label,
            )
        ):
            self._sync_label_height(watched)
        return super().eventFilter(watched, event)

    def _sync_label_height(self, label: BodyLabel | CaptionLabel) -> None:
        # 横纵重排后嵌套布局可能沿用单行高度，实际换行文本必须先参与最小高度约束。
        height = label.fontMetrics().boundingRect(
            QRect(0, 0, max(1, label.width()), 0), Qt.TextFlag.TextWordWrap, label.text()
        ).height()
        label.setMinimumHeight(max(label.fontMetrics().height(), height))

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._toggle_from_double_click(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        if self._selected:
            painter.fillRect(0, 10, 3, max(0, self.height() - 20),
                             QColor(BaseStyles.color("BORDER_FOCUS")))
        painter.setPen(QColor(BaseStyles.color("BORDER_COLOR")))
        painter.drawLine(14, self.height() - 1, self.width() - 14, self.height() - 1)

    def apply_fonts(self) -> None:
        font = BaseStyles.font_for_role(FontRole.UI)
        title_font = BaseStyles.font_for_role(FontRole.UI)
        title_font.setBold(True)
        self.name_label.setFont(title_font)
        self.status_label.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        self.battery_label.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        for label in (self.name_label, self.status_label, self.battery_label):
            label.setMinimumHeight(label.fontMetrics().height())
        self.selection.setFont(font)
        self.selection.setFixedWidth(self.selection.sizeHint().height())
        for field in (
            *self.summary_fields.values(), *self.detail_fields.values(), self.identifier_field,
        ):
            field.apply_fonts()
        for button in (*self._buttons, self.details_button, self.copy_details_button):
            button.setFont(font)
            button.setMinimumHeight(
                max(32, button.sizeHint().height(), button.fontMetrics().height() + 16)
            )
        self._reflow()

    def _reflow(self) -> None:
        available = max(1, self.width() - 28)
        action_width = sum(button.sizeHint().width() for button in self._buttons) + 18
        compact = available < self.details_button.sizeHint().width() + action_width + 28
        self._footer_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        )
        self.action_container.setMinimumWidth(0 if compact else action_width)
        self.action_container.setMaximumWidth(16777215 if compact else action_width)
        width = available if compact else action_width
        self.action_container.setMinimumHeight(self._action_layout.heightForWidth(width))
        status_width = max(
            self.status_label.fontMetrics().horizontalAdvance(self.status_label.text()),
            self.battery_label.fontMetrics().horizontalAdvance(self.battery_label.text()),
        )
        title_required = (
            status_width
            + self.name_label.fontMetrics().horizontalAdvance(self.name_label.text())
            + self.selection.sizeHint().width() + self.icon.width() + 32
        )
        stacked_header = available < title_required
        self._header_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if stacked_header
            else QBoxLayout.Direction.LeftToRight
        )
        self.status_container.setMinimumWidth(0 if stacked_header else status_width)
        metrics = self.name_label.fontMetrics()
        metric_width = max(160, metrics.horizontalAdvance("Android 14 · API 34") + 20)
        columns = max(1, min(4, (available + 16) // (metric_width + 16)))
        # 四项摘要在大字号下成对换行，避免三项之后只剩一个孤立指标。
        if columns == 3:
            columns = 2
        self._place_fields(self._summary_layout, tuple(self.summary_fields.values()), columns)
        self.summary_container.setVisible(any(
            not field.isHidden() for field in self.summary_fields.values()
        ))
        detail_width = max(
            160, metrics.horizontalAdvance("1080 × 2400") + 20,
            *(field.caption.fontMetrics().horizontalAdvance(field.caption.text())
              for field in (*self.detail_fields.values(), self.identifier_field)),
        )
        detail_columns = max(1, min(3, (available + 16) // (detail_width + 16)))
        self._place_fields(
            self._details_layout, (*self.detail_fields.values(), self.identifier_field),
            detail_columns,
        )
        for label in (self.name_label, self.status_label, self.battery_label):
            if not label.isHidden():
                self._sync_label_height(label)
        self._body_layout.invalidate()
        self.updateGeometry()

    @staticmethod
    def _place_fields(layout: QGridLayout, fields: tuple[_DeviceField, ...], columns: int) -> None:
        for field in fields:
            layout.removeWidget(field)
        for column in range(4):
            layout.setColumnStretch(column, 1 if column < columns else 0)
        for index, field in enumerate(field for field in fields if not field.isHidden()):
            layout.addWidget(field, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()


class DeviceHubPage(QWidget):
    """投影发现与元数据缓存；选择、导航和设备执行的所有权仍在主窗口。"""

    choose_requested = Signal()
    connect_requested = Signal()
    refresh_requested = Signal()
    selection_requested = Signal(list)
    device_action_requested = Signal(str, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("deviceHubPage")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._selected: tuple[str, ...] = ()
        self._connected: tuple[str, ...] = ()
        self._state = "empty"
        self._metadata: dict[str, dict[str, object]] = {}
        self._cards: dict[str, _DeviceCard] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.summary = BodyLabel(self)
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setMinimumWidth(0)
        self.toolbar = QWidget(self)
        self.toolbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._toolbar_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.toolbar)
        self._toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._toolbar_layout.setSpacing(12)
        self._toolbar_layout.addWidget(self.summary, 1)
        self._toolbar_actions = QWidget(self.toolbar)
        action_layout = QHBoxLayout(self._toolbar_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        self.connect_button = PushButton(FluentIcon.CONNECT, tr("连接设备"), self._toolbar_actions)
        self.connect_button.setToolTip(tr("输入无线调试地址，或使用已保存的连接历史"))
        self.connect_button.clicked.connect(self.connect_requested)
        self.refresh_button = ToolButton(FluentIcon.SYNC, self._toolbar_actions)
        self.refresh_button.setAccessibleName(tr("刷新设备"))
        self.refresh_button.setToolTip(tr("重新扫描 USB 与无线设备的在线状态"))
        self.refresh_button.clicked.connect(self.refresh_requested)
        action_layout.addWidget(self.connect_button)
        action_layout.addWidget(self.refresh_button)
        self._toolbar_layout.addWidget(self._toolbar_actions, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.toolbar)
        self.cards_container = QWidget(self)
        self._cards_layout = QVBoxLayout(self.cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.cards_container)
        self.empty_card = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(12)
        self.empty_title = BodyLabel(self.empty_card)
        self.empty_description = BodyLabel(self.empty_card)
        self.empty_description.setWordWrap(True)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_description)
        layout.addWidget(self.empty_card)
        BaseStyles.ui_font_changed.connect(self._apply_fonts)
        BaseStyles.theme_changed.connect(self._apply_theme)
        self._apply_fonts()
        self.set_device_context([], [], "empty")

    @property
    def device_cards(self) -> tuple[_DeviceCard, ...]:
        """按当前发现顺序返回可见设备卡，不包含仅存在于历史缓存的设备。"""
        return tuple(self._cards[device_id] for device_id in self._connected)

    def set_device_metadata(self, records: Iterable[Mapping[str, object]]) -> None:
        """只接收主窗口提供的内存元数据副本，不加载存储或执行设备查询。"""
        self._metadata = {
            str(record["ip"]): dict(record) for record in records if record.get("ip")
        }
        self._refresh_cards()
        self._refresh_summary()

    def set_device_context(self, selected, connected, state) -> None:
        """保持原三参数接口；同设备刷新原位更新，移除卡片延迟释放以避开信号栈。"""
        self._selected = tuple(dict.fromkeys(str(device) for device in selected if device))
        self._connected = tuple(dict.fromkeys(str(device) for device in connected if device))
        self._state = str(state)
        for device_id in tuple(self._cards):
            if device_id not in self._connected:
                card = self._cards.pop(device_id)
                card.set_snapshot(self._metadata.get(device_id, {}), False, "offline")
                self._cards_layout.removeWidget(card)
                card.hide()
                card.deleteLater()
        for index, device_id in enumerate(self._connected):
            if device_id not in self._cards:
                card = _DeviceCard(device_id, self.cards_container)
                card.selection_toggled.connect(self._request_selection)
                card.action_requested.connect(self._request_device_action)
                self._cards[device_id] = card
            self._cards_layout.insertWidget(index, self._cards[device_id])
        self._refresh_cards()
        self._refresh_summary()

    def _refresh_cards(self) -> None:
        for device_id, card in self._cards.items():
            card.set_snapshot(
                self._metadata.get(device_id, {}), device_id in self._selected,
                self._state,
            )

    def _refresh_summary(self) -> None:
        count = len(self._connected)
        selected = sum(device in self._connected for device in self._selected)
        if self._state == "unavailable":
            self.summary.setText(
                tr("连接状态待确认 · 保留上次发现的 {count} 台设备").format(count=count)
            )
        elif self._state == "scanning":
            self.summary.setText(tr("正在发现设备… · 上次发现 {count} 台").format(count=count))
        else:
            self.summary.setText(
                tr("{count} 台设备在线 · {selected} 台已选为操作目标").format(
                    count=count, selected=selected
                )
            )
        self.empty_card.setVisible(not count)
        self.cards_container.setVisible(bool(count))
        self.empty_title.setText({
            "scanning": tr("正在查找 Android 设备"),
            "unavailable": tr("暂时无法连接 ADB"),
        }.get(self._state, tr("连接第一台 Android 设备")))
        self.empty_description.setText({
            "scanning": tr("请稍候。使用 USB 连接时，请在设备上允许 USB 调试。"),
            "unavailable": tr(
                "点击设备列表旁的刷新按钮重试；若仍无法发现设备，可在设置中重启 ADB。"
            ),
        }.get(self._state, tr("使用 USB 连接并允许设备上的调试授权，或输入无线调试地址。")))
        self.connect_button.setEnabled(self._state != "scanning")
        self.refresh_button.setEnabled(self._state != "scanning")
        self._reflow_toolbar()
        self.updateGeometry()

    def _request_selection(self, device_id: str, checked: bool) -> None:
        if device_id not in self._connected or self._state != "ready":
            return
        selected = [
            device for device in self._selected if device != device_id and device in self._connected
        ]
        if checked:
            selected.append(device_id)
        self.selection_requested.emit(selected)

    def _request_device_action(self, section: str, feature: str, device_id: str) -> None:
        if device_id in self._connected and device_id in self._selected and self._state == "ready":
            self.device_action_requested.emit(section, feature, device_id)

    @Slot()
    def _apply_theme(self) -> None:
        for card in self._cards.values():
            card.icon.setIcon(get_themed_icon("device-mobile.svg"))
            card.update()

    @Slot()
    def _apply_fonts(self) -> None:
        font = BaseStyles.font_for_role(FontRole.UI)
        for widget in (
            self.summary, self.empty_description, self.connect_button, self.refresh_button
        ):
            widget.setFont(font)
        title_font = BaseStyles.font_for_role(FontRole.UI)
        title_font.setBold(True)
        self.empty_title.setFont(title_font)
        self.connect_button.setMinimumHeight(max(
            32, self.connect_button.sizeHint().height(),
            self.connect_button.fontMetrics().height() + 16,
        ))
        self.refresh_button.setFixedSize(
            self.connect_button.minimumHeight(), self.connect_button.minimumHeight()
        )
        for card in self._cards.values():
            card.apply_fonts()
        self._reflow_toolbar()

    def _reflow_toolbar(self) -> None:
        """摘要和连接动作按实际字体换行，窄窗仍保留唯一连接与刷新入口。"""

        required = (
            self.summary.fontMetrics().horizontalAdvance(self.summary.text())
            + self._toolbar_actions.sizeHint().width() + 12
        )
        self._toolbar_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if self.width() < required
            else QBoxLayout.Direction.LeftToRight
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_toolbar()
