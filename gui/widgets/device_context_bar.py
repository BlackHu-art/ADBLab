"""全页设备上下文：批量目标与固定设备会话分别提交，弹层不拥有业务状态。"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QPoint, QRect, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    EditableComboBox,
    FluentIcon,
    Flyout,
    FlyoutViewBase,
    InfoBadge,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    ToolButton,
    TransparentPushButton,
    TransparentToolButton,
)

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import DEVICE_ICON
from utils.adb_targets import normalize_adb_connect_target


class _SessionComboBox(ComboBox):
    """只省略按钮上的长名称，候选、设备值和辅助技术保留完整内容。"""

    def setText(self, text: str) -> None:
        self.setAccessibleDescription(text)
        self._sync_display_text(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_display_text(self.currentText())

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._sync_display_text(self.currentText())

    def _sync_display_text(self, text: str) -> None:
        # 不调用 ComboBox.setText 的 adjustSize，避免显示文本反过来撑大布局。
        display = self.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideMiddle, max(0, self.width() - 48)
        )
        QPushButton.setText(self, display)


def _apply_popup_fonts(view: QWidget) -> None:
    """动态弹层跟随应用字体，并按真实字号同步输入和动作高度。"""

    font = BaseStyles.font_for_role(FontRole.UI)
    view.setFont(font)
    for widget in view.findChildren(QWidget):
        if isinstance(
            widget, (BodyLabel, StrongBodyLabel, PushButton, ComboBox,
                     EditableComboBox, CheckBox, ListWidget)
        ):
            applied = BaseStyles.font_for_role(FontRole.UI)
            applied.setBold(isinstance(widget, StrongBodyLabel))
            widget.setFont(applied)
        if isinstance(widget, (PushButton, ComboBox, EditableComboBox, CheckBox)):
            widget.setMaximumHeight(16777215)
            widget.setMinimumHeight(max(32, widget.fontMetrics().height() + 16))


class _DeviceCheckList(ListWidget):
    """让整行与复选框共享一次切换，键盘仍沿用 Qt 的标准勾选行为。"""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and item is not None:
            if item.data(Qt.ItemDataRole.UserRole):
                item.setCheckState(
                    Qt.CheckState.Unchecked
                    if item.checkState() == Qt.CheckState.Checked
                    else Qt.CheckState.Checked
                )
                event.accept()
                return
        super().mouseReleaseEvent(event)


class DevicePicker(FlyoutViewBase):
    """即时提交复选目标；刷新候选时阻断信号，避免反向覆盖真实选择。"""

    selection_requested = Signal(list)
    session_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rendered_devices: tuple[str, ...] | None = None
        self._labels: dict[str, str] = {}
        self._selected: tuple[str, ...] = ()
        self._single_selection = False
        self._selection_locked = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(StrongBodyLabel(tr("选择操作设备"), self))
        self.description = BodyLabel(tr("可多选。正在运行的会话继续使用原设备。"), self)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.session_box = QWidget(self)
        session_layout = QVBoxLayout(self.session_box)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.setSpacing(6)
        session_layout.addWidget(StrongBodyLabel(tr("当前页面查看的设备"), self.session_box))
        self.session_combo = _SessionComboBox(self.session_box)
        self.session_combo.setMinimumWidth(0)
        self.session_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.session_combo.setAccessibleName(tr("当前页面查看的设备"))
        session_layout.addWidget(self.session_combo)
        self.session_target = CheckBox(tr("允许操作此设备"), self.session_box)
        self.session_target.setToolTip(tr("允许对当前设备执行操作"))
        self.session_target.clicked.connect(self._toggle_current_target)
        session_layout.addWidget(self.session_target)
        self.session_combo.currentIndexChanged.connect(self._choose_session)
        self.session_box.hide()
        layout.addWidget(self.session_box)
        self.batch_heading = StrongBodyLabel(tr("批量操作设备"), self)
        self.batch_heading.hide()
        layout.addWidget(self.batch_heading)
        self.device_list = _DeviceCheckList(self)
        self.device_list.setAccessibleName(tr("操作设备多选列表"))
        self.device_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_list.setMinimumHeight(120)
        self.device_list.setMaximumHeight(240)
        self.device_list.itemChanged.connect(self._submit)
        layout.addWidget(self.device_list)
        actions = QHBoxLayout()
        self.select_all_button = PushButton(tr("全选"), self)
        self.clear_button = PushButton(tr("清空选择"), self)
        self.select_all_button.setToolTip(tr("勾选所有在线设备作为操作目标"))
        self.clear_button.setToolTip(tr("取消操作目标勾选，保留已打开的设备会话"))
        self.select_all_button.clicked.connect(lambda: self._set_all(True))
        self.clear_button.clicked.connect(lambda: self._set_all(False))
        actions.addWidget(self.select_all_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        BaseStyles.ui_font_changed.connect(self._apply_fonts)
        self._apply_fonts()

    def _apply_fonts(self, *_args) -> None:
        _apply_popup_fonts(self)
        self._sync_list_height()

    def set_selection_mode(self, *, single: bool, locked: bool = False) -> None:
        """同一设备列表按页面约束提交单选或多选，运行锁只阻止更换目标。"""
        self._single_selection = single
        self._selection_locked = locked
        self.select_all_button.setVisible(not single)
        self.device_list.setEnabled(not locked)
        self.select_all_button.setEnabled(bool(self._rendered_devices) and not locked)
        self.session_box.hide()
        self.batch_heading.hide()
        self.description.setText(
            tr("请选择一台操作设备；取消选择仍可查看缓存和停止任务。") if single
            else tr("可多选。正在运行的会话继续使用原设备。")
        )
        self.device_list.setAccessibleName(
            tr("操作设备单选列表") if single else tr("操作设备多选列表")
        )
        self._sync_list_height()

    def _sync_list_height(self) -> None:
        # 字体和行高也会触发 itemChanged，呈现更新不能提交新的操作目标。
        blocker = QSignalBlocker(self.device_list)
        row_height = max(40, self.device_list.fontMetrics().height() + 18)
        for row in range(self.device_list.count()):
            item = self.device_list.item(row)
            if item is not None:
                item.setFont(self.device_list.font())
                item.setSizeHint(QSize(0, row_height))
        maximum_rows = 4 if self.session_box.isHidden() else 3
        self.device_list.setFixedHeight(
            max(1, min(maximum_rows, self.device_list.count())) * row_height + 8
        )
        del blocker

    def set_context(
        self, selected: Iterable[str], connected: Iterable[str],
        names: dict[str, str] | None = None,
        *, labels: dict[str, str] | None = None,
    ) -> None:
        """只呈现在线目标；设备下线后的批量归属由共享设备状态决定。"""

        self._selected = tuple(selected)
        if self._single_selection:
            self._selected = self._selected[:1]
        self._labels.update(labels or {})
        checked = set(self._selected)
        blocker = QSignalBlocker(self.device_list)
        devices = tuple(dict.fromkeys(connected))
        if devices != self._rendered_devices:
            self.device_list.clear()
            for index, device in enumerate(devices, 1):
                item = QListWidgetItem(tr("设备 {number}").format(number=index), self.device_list)
                item.setData(Qt.ItemDataRole.UserRole, device)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if not devices:
                item = QListWidgetItem(tr("尚未发现设备，请连接或刷新"), self.device_list)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._rendered_devices = devices
        # 勾选回调会同步投影状态，保留同一批条目避免在原生点击事件中销毁发送方。
        for row, device in enumerate(devices):
            item = self.device_list.item(row)
            if item is None:
                continue
            label = (labels or {}).get(device, "")
            if not label:
                label = tr("设备 {number}").format(number=row + 1)
                name = (names or {}).get(device, "")
                if name and name != device:
                    label += " · " + name
            item.setText(label)
            self._labels[device] = label
            item.setToolTip(label)
            item.setCheckState(
                Qt.CheckState.Checked if device in checked else Qt.CheckState.Unchecked
            )
        del blocker
        self.select_all_button.setEnabled(bool(devices) and not self._selection_locked)
        self.clear_button.setEnabled(bool(checked))
        self._sync_list_height()

    def set_session_context(self, source: ComboBox | None, target: CheckBox) -> None:
        """会话查看与操作授权均来自统一设备栏的投影，弹层本身不保存任务状态。"""
        blocker = QSignalBlocker(self.session_combo)
        self.session_combo.clear()
        if source is not None:
            for index in range(source.count()):
                device = str(source.itemData(index) or "")
                label = self._labels.get(device, tr("设备 {number}").format(number=index + 1))
                self.session_combo.addItem(
                    label if device else source.itemText(index), userData=source.itemData(index),
                )
            self.session_combo.setCurrentIndex(source.currentIndex())
            self.session_combo.setEnabled(source.isEnabled())
            description = source.toolTip()
            for index in range(source.count()):
                device = str(source.itemData(index) or "")
                if device:
                    description = description.replace(device, self.session_combo.itemText(index))
            self.session_combo.setToolTip(description)
            self.session_combo.setAccessibleDescription(description)
        del blocker
        self.session_target.setChecked(target.isChecked())
        self.session_target.setEnabled(target.isEnabled())
        self.set_selection_mode(single=self._single_selection, locked=self._selection_locked)

    def _choose_session(self, _index: int) -> None:
        target = str(self.session_combo.currentData() or "")
        if target and self.session_combo.isEnabled():
            self.session_requested.emit(target)

    def _toggle_current_target(self, checked: bool) -> None:
        target = str(self.session_combo.currentData() or "")
        if not target or not self.session_target.isEnabled():
            return
        selected = [device for device in self._selected if device != target]
        if checked:
            selected.append(target)
        self.selection_requested.emit(selected)

    def _set_all(self, checked: bool) -> None:
        if checked and (self._single_selection or self._selection_locked):
            return
        blocker = QSignalBlocker(self.device_list)
        for row in range(self.device_list.count()):
            item = self.device_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole):
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        del blocker
        self._submit()

    def _submit(self, changed: QListWidgetItem | None = None) -> None:
        if (self._single_selection and changed is not None
                and changed.checkState() == Qt.CheckState.Checked):
            blocker = QSignalBlocker(self.device_list)
            for row in range(self.device_list.count()):
                item = self.device_list.item(row)
                if item is not None and item is not changed:
                    item.setCheckState(Qt.CheckState.Unchecked)
            del blocker
        selected = []
        for row in range(self.device_list.count()):
            item = self.device_list.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(str(item.data(Qt.ItemDataRole.UserRole)))
        self._selected = tuple(selected)
        self.clear_button.setEnabled(bool(selected))
        self.selection_requested.emit(selected)


class DeviceConnectionForm(FlyoutViewBase):
    """地址历史保留真实目标数据，连接前复用既有输入校验边界。"""

    connect_requested = Signal(str)

    def __init__(self, history: Iterable[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(StrongBodyLabel(tr("连接设备"), self))
        hint = BodyLabel(tr("USB 设备连接后点击刷新；无线设备填写 IP 地址及端口。"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.address = EditableComboBox(self)
        self.address.setAccessibleName(tr("设备地址"))
        self.address.setMinimumWidth(0)
        self.address.setPlaceholderText(tr("IP 地址:端口"))
        for label, target in history:
            self.address.addItem(label, userData=target)
        self.address.setCurrentIndex(-1)
        self.address.setText("")
        self.address.currentIndexChanged.connect(self._select_address)
        layout.addWidget(self.address)
        self.error_label = BodyLabel("", self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.connect_button = PrimaryPushButton(FluentIcon.CONNECT, tr("连接"), self)
        self.connect_button.setToolTip(tr("校验输入地址并连接无线设备"))
        self.connect_button.clicked.connect(self._connect)
        self.address.returnPressed.connect(self._connect)
        layout.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignRight)
        BaseStyles.ui_font_changed.connect(self._apply_fonts)
        self._apply_fonts()

    def _apply_fonts(self, *_args) -> None:
        _apply_popup_fonts(self)

    def _select_address(self, index: int) -> None:
        target = self.address.itemData(index) if index >= 0 else None
        if target:
            self.address.setText(str(target))

    def _connect(self) -> None:
        target, error = normalize_adb_connect_target(self.address.currentText())
        self.error_label.setText(tr(error) if error else "")
        self.error_label.setVisible(bool(error))
        if error:
            self.address.setFocus()
            return
        self.connect_requested.emit(target)


class DeviceContextBar(QWidget):
    """固定在应用内容区上方，不随页面滚动；视图切换不修改批量复选集。"""

    selection_requested = Signal(list)
    connect_requested = Signal(str)
    session_requested = Signal(str)
    close_session_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("globalDeviceContextBar")
        self._device_labels: dict[str, str] = {}
        self._device_numbers: dict[str, int] = {}
        self._has_session = False
        self._single_selection = False
        self._selection_locked = False
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._selected: tuple[str, ...] = ()
        self._connected: tuple[str, ...] = ()
        self._picker: DevicePicker | None = None
        self._connection: DeviceConnectionForm | None = None
        self._picker_flyout: Flyout | None = None
        self._connection_flyout: Flyout | None = None
        self._session_required = False
        self._session_signature: tuple | None = None
        self._target_text = ""
        self._close_text = tr("关闭会话")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 12, 32, 6)
        self._surface = QWidget(self)
        outer.addWidget(self._surface)
        self._layout = QHBoxLayout(self._surface)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        self.page_title = StrongBodyLabel(self)
        self.page_title.setMinimumWidth(0)
        self.page_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._layout.addWidget(self.page_title, 1)
        self.target_row = QWidget(self)
        target = QHBoxLayout(self.target_row)
        target.setContentsMargins(0, 0, 0, 0)
        target.setSpacing(8)
        self._target_layout = target
        self.targets_button = TransparentPushButton(DEVICE_ICON, tr("操作设备"), self)
        self.targets_button.setAccessibleName(tr("操作设备（支持多选）"))
        self.targets_button.clicked.connect(self.open_picker)
        self.status_label = BodyLabel(tr("未发现设备"), self)
        self.status_label.setWordWrap(False)
        self.status_label.setMinimumWidth(0)
        target.addWidget(self.targets_button)
        self.status_label.hide()

        self.session_row = QWidget(self)
        session = QHBoxLayout(self.session_row)
        self._session_layout = session
        session.setContentsMargins(0, 0, 0, 0)
        session.setSpacing(8)
        self.session_label = BodyLabel(tr("当前查看"), self)
        self.session_combo = _SessionComboBox(self)
        self.session_combo.setMinimumWidth(0)
        self.session_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.session_combo.setAccessibleName(tr("当前查看的会话设备"))
        self.session_combo.currentIndexChanged.connect(self._choose_session)
        self.session_label.setBuddy(self.session_combo)
        self.session_hint = InfoBadge(self)
        self.session_hint.setAccessibleName(tr("会话状态"))
        self.session_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.session_hint.hide()
        self.session_target = CheckBox(tr("操作目标"), self)
        self.session_target.setAccessibleName(tr("将当前查看的设备选为操作目标"))
        self.session_target.setToolTip(tr("勾选后允许对此设备执行操作；取消勾选仍可查看已加载内容和停止任务"))
        self.session_target.clicked.connect(self._toggle_session_target)
        self.close_button = TransparentToolButton(FluentIcon.CLOSE, self)
        self.close_button.clicked.connect(self.close_session_requested)
        self.close_button.setAccessibleName(tr("关闭当前功能会话"))
        self.close_button.setToolTip(tr("停止并关闭当前功能的设备会话"))
        self.session_label.hide()
        self.session_combo.hide()
        self.session_target.hide()
        session.addWidget(self.close_button)
        self._layout.addWidget(self.target_row)
        self._layout.addWidget(self.session_row)
        self.session_row.hide()
        BaseStyles.ui_font_changed.connect(self._apply_fonts)
        BaseStyles.theme_changed.connect(self._apply_theme)
        self._apply_theme()
        self._apply_fonts()
        self.set_context((), (), "empty")

    def _apply_fonts(self, *_args) -> None:
        font = BaseStyles.font_for_role(FontRole.UI)
        self.setFont(font)
        for widget in self.findChildren(QWidget):
            widget.setFont(font)
            if isinstance(widget, (ComboBox, PushButton, ToolButton, CheckBox)):
                widget.setMinimumHeight(max(32, widget.fontMetrics().height() + 14))
                widget.setMaximumHeight(16777215)
        title_font = BaseStyles.font_for_role(FontRole.TITLE)
        title_font.setBold(True)
        self.page_title.setFont(title_font)
        self._sync_compact_mode()

    def set_page_title(self, title: str) -> None:
        """页面名称用于定位当前任务，设备候选只负责切换当前会话。"""
        self.page_title.setText(title)
        self.page_title.setToolTip(title)
        self._sync_compact_mode()

    def _apply_theme(self, *_args) -> None:
        """同步控件调色板，设备栏背景由与页面共用的父级材质面提供。"""
        application = QApplication.instance()
        if not isinstance(application, QApplication):
            return
        palette = application.palette()
        self.setPalette(palette)
        self.setAutoFillBackground(False)
        self._surface.setPalette(palette)
        for widget in (self.target_row, self.session_row):
            widget.setPalette(palette)
            widget.setAutoFillBackground(False)
        # 状态标签由 Fluent 的明暗主题文字色管理，通用色板会覆盖其语义色。
        for widget in (self.targets_button, self.session_label,
                       self.session_combo, self.close_button):
            widget.setPalette(palette)
        self.update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            application = QApplication.instance()
            if isinstance(application, QApplication) and self.palette() != application.palette():
                # 原生窗口延迟重设旧色板时仍保持内容区使用当前应用主题。
                self.setPalette(application.palette())

    def set_context(self, selected: Iterable[str], connected: Iterable[str], state: str) -> None:
        self._selected = tuple(dict.fromkeys(selected))
        self._connected = tuple(dict.fromkeys(connected))
        for device in self._connected:
            self.device_label(device)
        text = {"scanning": tr("正在扫描"), "unavailable": tr("ADB 暂不可用")}.get(
            state, tr("在线 {count} 台").format(count=len(self._connected))
            if self._connected else tr("未发现设备")
        )
        self.status_label.setText(text)
        status_color = {"scanning": "LOG_INFO", "unavailable": "LOG_WARNING"}.get(
            state, "LOG_SUCCESS" if self._connected else "TEXT_SECONDARY"
        )
        self.status_label.setTextColor(
            QColor(BaseStyles.color_for("Light", status_color)),
            QColor(BaseStyles.color_for("Dark", status_color)),
        )
        self.targets_button.setAccessibleDescription(
            tr("{text}，已选 {count} 台").format(text=text, count=len(self._selected))
        )
        if self._picker is not None:
            self._picker.set_context(
                self._picker_selection(), self._connected, labels=self.device_labels(),
            )
        self._sync_session_target()
        self._sync_picker_session()
        self._sync_target_presentation()

    def device_label(self, device: str) -> str:
        """本次应用运行内设备序号不因下线或选择子集而改变，不持久化真实设备身份。"""
        if not device:
            return ""
        if device not in self._device_numbers:
            self._device_numbers[device] = len(self._device_numbers) + 1
        label = tr("设备 {number}").format(number=self._device_numbers[device])
        name = self._device_labels.get(device, "")
        return f"{label} · {name}" if name and name != device else label

    def device_labels(self) -> dict[str, str]:
        """向其他显示区域提供名称副本；调用方不得据此推导操作授权。"""
        return {device: self.device_label(device) for device in self._device_numbers}

    def _display_device_text(self, text: str) -> str:
        """宿主保留真实身份用于选路，展示说明统一替换为当前会话名称。"""
        for device in sorted(self._device_numbers, key=len, reverse=True):
            text = text.replace(device, self.device_label(device))
        return text

    def _sync_target_presentation(self) -> None:
        """同一入口明确显示本页作用范围，避免把全局多选数误认为单设备页执行范围。"""
        if self._single_selection:
            device = str(self.session_combo.currentData() or "")
            self._target_text = tr("当前设备 · {device}").format(
                device=self.device_label(device) if device else tr("未选择"),
            )
            if device and device not in self._connected:
                self._target_text += " · " + tr("离线")
            elif device and device not in self._selected:
                self._target_text += " · " + tr("未勾选")
            scope = tr("请选择一台操作设备；取消选择仍可查看缓存和停止任务。")
        else:
            self._target_text = (
                tr("操作设备 · {count} 台").format(count=len(self._selected))
                if self._selected else tr("操作设备 · 未选择")
            )
            scope = tr("操作会发送到全部已勾选设备；已运行任务保持原目标。")
        description = "\n".join(filter(None, (
            self._target_text, scope, self.status_label.text(),
            self._display_device_text(self.session_hint.toolTip()),
        )))
        self.targets_button.setAccessibleName(self._target_text)
        self.targets_button.setAccessibleDescription(description)
        self.targets_button.setToolTip(description)
        self._sync_compact_mode()

    def set_device_labels(self, labels: dict[str, str]) -> None:
        """设备名称只用于展示，选中值仍采用原始设备身份。"""
        self._device_labels.update(labels)
        if self._picker is not None:
            self._picker.set_context(
                self._picker_selection(), self._connected, labels=self.device_labels(),
            )
            self._sync_picker_session()
        self._sync_target_presentation()

    def _sync_picker_session(self) -> None:
        if self._picker is not None:
            self._picker.set_selection_mode(
                single=self._single_selection, locked=self._selection_locked,
            )
            self._picker.set_session_context(
                self.session_combo if self._has_session else None, self.session_target,
            )
            self._picker.set_context(
                self._picker_selection(), self._connected, labels=self.device_labels(),
            )

    def _picker_selection(self) -> tuple[str, ...]:
        """单设备页只投影当前会话的操作资格，切页本身不裁剪共享目标。"""
        if not self._single_selection:
            return self._selected
        current = str(self.session_combo.currentData() or "")
        return (current,) if current and current in self._selected else ()

    def set_session_context(
        self,
        source: ComboBox | None,
        close: PushButton | None,
        status: InfoBadge | None = None,
        *, single: bool | None = None, selection_locked: bool = False,
    ) -> None:
        """投影宿主的候选、锁、状态和关闭动作，不接管会话生命周期。

        宿主工具栏本身可隐藏；会话状态只进入悬停和辅助说明，不重复占用顶部空间。
        不保留源控件引用，切换会话后不会访问已释放的页面控件。
        """

        status_visible = status is not None and not status.isHidden()
        self._has_session = source is not None
        self._single_selection = source is not None if single is None else single
        self._selection_locked = selection_locked
        signature = (
            self._single_selection, selection_locked,
            tuple((source.itemText(i), source.itemData(i)) for i in range(source.count()))
            if source is not None
            else None,
            source.currentIndex() if source is not None else -1,
            source.isEnabled() if source is not None else False,
            source.toolTip() if source is not None else "",
            (close.text(), close.isEnabled(), close.toolTip()) if close is not None else None,
            (
                status.text(), status.level, status.toolTip(), status.accessibleName(),
                status.accessibleDescription(),
            ) if status_visible and status is not None else None,
        )
        if signature == self._session_signature:
            return
        self._session_signature = signature
        self._session_required = source is not None
        blocker = QSignalBlocker(self.session_combo)
        self.session_combo.clear()
        if source is not None:
            for index in range(source.count()):
                self.device_label(str(source.itemData(index) or ""))
                self.session_combo.addItem(source.itemText(index), userData=source.itemData(index))
            if source.count():
                self.session_combo.setCurrentIndex(source.currentIndex())
            else:
                self.session_combo.addItem(tr("请先连接设备"), userData="")
            self.session_combo.setEnabled(source.isEnabled())
        del blocker
        self.target_row.show()
        self.session_target.hide()
        self.session_combo.hide()
        self.session_hint.hide()
        if status_visible and status is not None:
            self.session_hint.setText(status.text())
            self.session_hint.setLevel(status.level)
            self.session_hint.setToolTip(status.toolTip())
            self.session_hint.setAccessibleName(status.accessibleName())
            self.session_hint.setAccessibleDescription(status.accessibleDescription())
        else:
            self.session_hint.clear()
            self.session_hint.setToolTip("")
            self.session_hint.setAccessibleDescription("")
        self.close_button.setVisible(close is not None)
        state_description = self._display_device_text("\n".join(dict.fromkeys(filter(None, (
            self.session_hint.text(), self.session_hint.toolTip(),
            self.session_hint.accessibleDescription(),
        )))))
        description = "\n".join(filter(None, (
            self.session_combo.currentText() if source is not None else "", state_description,
        )))
        self.session_combo.setAccessibleDescription(description)
        self.session_combo.setToolTip("\n".join(filter(None, (
            source.toolTip() if source is not None else "", description,
        ))))
        self.setAccessibleDescription(state_description)
        if close is not None:
            self._close_text = close.text()
            self.close_button.setAccessibleName(close.text())
            self.close_button.setEnabled(close.isEnabled())
            self.close_button.setToolTip("\n".join(filter(None, (
                close.text(), close.toolTip(), state_description,
            ))))
            self.close_button.setAccessibleDescription(state_description)
        else:
            self.close_button.setToolTip("")
            self.close_button.setAccessibleDescription("")
        self.session_row.setVisible(close is not None)
        self._sync_session_target()
        self._sync_picker_session()
        self._sync_target_presentation()

    def _sync_session_target(self) -> None:
        """操作授权只来自共享复选集，投影会话和候选不反向提交选择。"""
        target = str(self.session_combo.currentData() or "")
        blocker = QSignalBlocker(self.session_target)
        self.session_target.setChecked(bool(target and target in self._selected))
        self.session_target.setEnabled(bool(target and target in self._connected))
        del blocker

    def _toggle_session_target(self, checked: bool) -> None:
        """明确勾选仅更新当前设备归属，保留其他操作目标和已有会话。"""
        target = str(self.session_combo.currentData() or "")
        if not target or target not in self._connected:
            return
        selected = [device for device in self._selected if device != target]
        if checked:
            selected.append(target)
        self.selection_requested.emit(selected)

    def _choose_session(self, _index: int) -> None:
        target = str(self.session_combo.currentData() or "")
        if target:
            self.session_requested.emit(target)

    def open_picker(self) -> None:
        """打开符合当前页面单选或多选约束的弹层，同一时刻只保留一份。"""

        if self._picker is not None:
            return
        self.dismiss_popups()
        picker = DevicePicker()
        picker.setFixedWidth(self._popup_width(self.targets_button))
        picker.set_selection_mode(single=self._single_selection, locked=self._selection_locked)
        picker.set_context(self._picker_selection(), self._connected, labels=self.device_labels())
        picker.selection_requested.connect(self.selection_requested)
        picker.session_requested.connect(self.session_requested)
        self._picker = picker
        self._sync_picker_session()
        self._picker_flyout = self._show_popup(picker, self.targets_button, align_right=True)
        self._picker_flyout.closed.connect(self._forget_picker)

    def _forget_picker(self, *_args) -> None:
        self._picker = None
        self._picker_flyout = None

    def open_connection(
        self, history: Iterable[tuple[str, str]], anchor: QWidget
    ) -> None:
        """复用瞬态表单管理，连接入口与锚点由设备概览提供。"""

        if self._connection is not None:
            self._connection.address.setFocus()
            return
        self.dismiss_popups()
        form = DeviceConnectionForm(history)
        self._connection = form
        form.setFixedWidth(self._popup_width(anchor))
        flyout = self._show_popup(form, anchor, align_right=True)
        self._connection_flyout = flyout
        flyout.closed.connect(self._forget_connection)
        form.connect_requested.connect(self.connect_requested)
        form.connect_requested.connect(flyout.close)
        form.address.setFocus()

    def _forget_connection(self, *_args) -> None:
        self._connection = None
        self._connection_flyout = None

    def _popup_bounds(self, anchor: QWidget) -> QRect:
        window = anchor.window() or anchor
        bounds = QRect(window.mapToGlobal(QPoint()), window.size()).adjusted(8, 8, -8, -8)
        if self.isVisible():
            bounds.setLeft(max(bounds.left(), self.mapToGlobal(QPoint()).x() + 8))
            bounds.setRight(min(bounds.right(), self.mapToGlobal(QPoint(self.width(), 0)).x() - 8))
        screen = (
            QApplication.screenAt(anchor.mapToGlobal(anchor.rect().center())) or anchor.screen()
        )
        return bounds.intersected(screen.availableGeometry())

    def _popup_width(self, anchor: QWidget | None = None) -> int:
        anchor = anchor if anchor is not None else self.targets_button
        preferred = max(360, self.fontMetrics().horizontalAdvance("设") * 22 + 32)
        # 为 Fluent 的外侧阴影留出宽度；大字体优先扩展，窄窗口按内容边界收缩。
        return min(preferred, max(1, self._popup_bounds(anchor).width() - 30))

    def _show_popup(self, view: FlyoutViewBase, anchor: QWidget, *, align_right: bool) -> Flyout:
        """原生 Popup 处理焦点和 Esc，显式位置避免居中弹层越过应用内容边界。"""

        flyout = Flyout.make(view, parent=self)
        flyout.adjustSize()
        bounds = self._popup_bounds(anchor)
        margins = flyout.hBoxLayout.contentsMargins()
        target = anchor.mapToGlobal(QPoint())
        x = (
            target.x() + anchor.width() - view.width() - margins.left()
            if align_right else target.x() - margins.left()
        )
        y = target.y() + anchor.height() + 6 - margins.top()
        x = max(bounds.left(), min(x, bounds.right() - flyout.width() + 1))
        y = max(bounds.top(), min(y, bounds.bottom() - flyout.height() + 1))
        flyout.move(x, y)
        flyout.show()
        return flyout

    def dismiss_popups(self) -> None:
        """切换功能或隐藏设备栏时立即关闭瞬态界面，底层对象由 Qt 延后释放。"""

        for popup in (self._picker_flyout, self._connection_flyout):
            if popup is not None:
                popup.close()

    def hideEvent(self, event) -> None:
        self.dismiss_popups()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_mode()

    def _sync_compact_mode(self) -> None:
        """设备入口使用自然宽度，窄屏优先压缩标题和设备名称，始终保持单行。"""
        width = max(0, self.width() - 64)
        natural = self.targets_button.fontMetrics().horizontalAdvance(self._target_text) + 48
        height = max(32, self.session_combo.fontMetrics().height() + 14)
        self.close_button.setFixedSize(max(height, self.close_button.sizeHint().width()), height)
        fixed = self.close_button.width() + 12 if not self.close_button.isHidden() else 0
        title_width = self.page_title.sizeHint().width() + 24
        self.page_title.setVisible(width >= fixed + natural + title_width)
        available = max(56, width - fixed - (title_width if self.page_title.isVisible() else 0))
        self.targets_button.setFixedWidth(min(natural, available))
        self.targets_button.setFixedHeight(height)
        self.targets_button.setText(self.targets_button.fontMetrics().elidedText(
            self._target_text, Qt.TextElideMode.ElideRight, self.targets_button.width() - 48,
        ))
