"""全页设备上下文：批量目标与固定设备会话分别提交，弹层不拥有业务状态。"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QPoint, QRect, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    ComboBox,
    EditableComboBox,
    FluentIcon,
    Flyout,
    FlyoutViewBase,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    StrongBodyLabel,
    ToolButton,
    TransparentDropDownToolButton,
    TransparentPushButton,
)

from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import DEVICE_ICON
from utils.adb_targets import normalize_adb_connect_target


def _apply_popup_fonts(view: QWidget) -> None:
    """动态弹层跟随应用字体，并按真实字号同步输入和动作高度。"""

    font = BaseStyles.font_for_role(FontRole.UI)
    view.setFont(font)
    for widget in view.findChildren(QWidget):
        if isinstance(
            widget, (BodyLabel, StrongBodyLabel, PushButton, EditableComboBox, ListWidget)
        ):
            applied = BaseStyles.font_for_role(FontRole.UI)
            applied.setBold(isinstance(widget, StrongBodyLabel))
            widget.setFont(applied)
        if isinstance(widget, (PushButton, EditableComboBox)):
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rendered_devices: tuple[str, ...] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(StrongBodyLabel("选择操作设备", self))
        self.description = BodyLabel("可多选。正在运行的会话继续使用原设备。", self)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.device_list = _DeviceCheckList(self)
        self.device_list.setAccessibleName("操作设备多选列表")
        self.device_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_list.setMinimumHeight(120)
        self.device_list.setMaximumHeight(240)
        self.device_list.itemChanged.connect(self._submit)
        layout.addWidget(self.device_list)
        actions = QHBoxLayout()
        self.select_all_button = PushButton("全选", self)
        self.clear_button = PushButton("清空选择", self)
        self.select_all_button.setToolTip("勾选所有在线设备作为操作目标")
        self.clear_button.setToolTip("取消操作目标勾选，保留已打开的设备会话")
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

    def _sync_list_height(self) -> None:
        # 字体和行高也会触发 itemChanged，呈现更新不能提交新的操作目标。
        blocker = QSignalBlocker(self.device_list)
        row_height = max(40, self.device_list.fontMetrics().height() + 18)
        for row in range(self.device_list.count()):
            item = self.device_list.item(row)
            if item is not None:
                item.setFont(self.device_list.font())
                item.setSizeHint(QSize(0, row_height))
        self.device_list.setFixedHeight(max(1, min(4, self.device_list.count())) * row_height + 8)
        del blocker

    def set_context(self, selected: Iterable[str], connected: Iterable[str]) -> None:
        """只呈现在线目标；设备下线后的批量归属由共享设备状态决定。"""

        checked = set(selected)
        blocker = QSignalBlocker(self.device_list)
        devices = tuple(dict.fromkeys(connected))
        if devices != self._rendered_devices:
            self.device_list.clear()
            for device in devices:
                item = QListWidgetItem(device, self.device_list)
                item.setData(Qt.ItemDataRole.UserRole, device)
                item.setToolTip(device)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if not devices:
                item = QListWidgetItem("尚未发现设备，请连接或刷新", self.device_list)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._rendered_devices = devices
        # 勾选回调会同步投影状态，保留同一批条目避免在原生点击事件中销毁发送方。
        for row, device in enumerate(devices):
            item = self.device_list.item(row)
            if item is None:
                continue
            item.setCheckState(
                Qt.CheckState.Checked if device in checked else Qt.CheckState.Unchecked
            )
        del blocker
        self.select_all_button.setEnabled(bool(devices))
        self.clear_button.setEnabled(bool(checked))
        self._sync_list_height()

    def _set_all(self, checked: bool) -> None:
        blocker = QSignalBlocker(self.device_list)
        for row in range(self.device_list.count()):
            item = self.device_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole):
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        del blocker
        self._submit()

    def _submit(self, *_args) -> None:
        selected = []
        for row in range(self.device_list.count()):
            item = self.device_list.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(str(item.data(Qt.ItemDataRole.UserRole)))
        self.selection_requested.emit(selected)


class DeviceConnectionForm(FlyoutViewBase):
    """地址历史保留真实目标数据，连接前复用既有输入校验边界。"""

    connect_requested = Signal(str)

    def __init__(self, history: Iterable[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(StrongBodyLabel("连接设备", self))
        hint = BodyLabel("USB 设备连接后点击刷新；无线设备填写 IP 地址及端口。", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.address = EditableComboBox(self)
        self.address.setAccessibleName("设备地址")
        self.address.setMinimumWidth(0)
        self.address.setPlaceholderText("IP 地址:端口")
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
        self.connect_button = PrimaryPushButton(FluentIcon.CONNECT, "连接", self)
        self.connect_button.setToolTip("校验输入地址并连接无线设备")
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
        self.error_label.setText(error or "")
        self.error_label.setVisible(bool(error))
        if error:
            self.address.setFocus()
            return
        self.connect_requested.emit(target)


class DeviceContextBar(QWidget):
    """固定在应用内容区上方，不随页面滚动；视图切换不修改批量复选集。"""

    selection_requested = Signal(list)
    connect_requested = Signal(str)
    refresh_requested = Signal()
    connection_requested = Signal()
    info_requested = Signal()
    disconnect_requested = Signal()
    session_requested = Signal(str)
    close_session_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("globalDeviceContextBar")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._selected: tuple[str, ...] = ()
        self._connected: tuple[str, ...] = ()
        self._picker: DevicePicker | None = None
        self._connection: DeviceConnectionForm | None = None
        self._picker_flyout: Flyout | None = None
        self._connection_flyout: Flyout | None = None
        self._session_required = False
        self._session_signature: tuple | None = None
        self._session_wrapped = False
        self._layout_mode: tuple[bool, bool] | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 8, 16, 8)
        self._surface = QWidget(self)
        outer.addWidget(self._surface)
        self._layout = QGridLayout(self._surface)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setHorizontalSpacing(16)
        self._layout.setVerticalSpacing(8)
        self.target_row = QWidget(self)
        target = QHBoxLayout(self.target_row)
        target.setContentsMargins(0, 0, 0, 0)
        target.setSpacing(8)
        self._target_layout = target
        self._actions = QWidget(self)
        action_layout = QHBoxLayout(self._actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        self.targets_button = PushButton(DEVICE_ICON, "操作设备", self)
        self.targets_button.setAccessibleName("操作设备（支持多选）")
        self.targets_button.clicked.connect(self.open_picker)
        self.status_label = BodyLabel("未发现设备", self)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        self.connect_button = TransparentPushButton(FluentIcon.CONNECT, "连接", self)
        self.connect_button.setToolTip("输入无线地址，或使用已保存的连接历史")
        self.connect_button.clicked.connect(self.connection_requested)
        self.refresh_button = ToolButton(FluentIcon.SYNC, self)
        self.refresh_button.setAccessibleName("刷新设备")
        self.refresh_button.setToolTip("重新扫描 USB 与无线设备的在线状态")
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.info_button = TransparentPushButton(FluentIcon.INFO, "设备信息", self)
        self.info_button.setAccessibleName("查看所选设备信息")
        self.info_button.setToolTip("在任务中心运行记录中查看所选设备信息")
        self.info_button.clicked.connect(self.info_requested)
        self.disconnect_button = TransparentPushButton(FluentIcon.CANCEL, "断开所选设备", self)
        self.disconnect_button.setAccessibleName("断开所选设备")
        self.disconnect_button.setToolTip("断开已勾选设备的 ADB 连接")
        self.disconnect_button.clicked.connect(self.disconnect_requested)
        self.more_button = TransparentDropDownToolButton(FluentIcon.MORE, self)
        self.more_button.setAccessibleName("更多设备操作")
        self.more_button.setToolTip("查看所选设备信息或断开所选设备")
        self._more_menu = RoundMenu(parent=self)
        self.info_action = Action(FluentIcon.INFO, "设备信息", self)
        self.disconnect_action = Action(FluentIcon.CANCEL, "断开所选设备", self)
        self.info_action.triggered.connect(self.info_requested)
        self.disconnect_action.triggered.connect(self.disconnect_requested)
        # 菜单项直接发出业务信号；旧按钮只保留兼容入口，不参与菜单尺寸与可用状态判断。
        for button, action in (
            (self.info_button, self.info_action),
            (self.disconnect_button, self.disconnect_action),
        ):
            button.hide()
            button.clicked.connect(self._more_menu.close)
            action.setToolTip(button.toolTip())
            self._more_menu.addAction(action)
        self.more_button.setMenu(self._more_menu)
        target.addWidget(self.targets_button)
        target.addWidget(self.status_label)
        target.addStretch(1)
        for button in (self.connect_button, self.refresh_button, self.more_button):
            action_layout.addWidget(button)

        self.session_row = QWidget(self)
        session = QGridLayout(self.session_row)
        self._session_layout = session
        session.setContentsMargins(0, 0, 0, 0)
        session.setSpacing(8)
        self.session_label = BodyLabel("当前查看", self)
        self.session_combo = ComboBox(self)
        self.session_combo.setMinimumWidth(0)
        self.session_combo.setAccessibleName("当前查看的会话设备")
        self.session_combo.currentIndexChanged.connect(self._choose_session)
        self.session_label.setBuddy(self.session_combo)
        self.session_hint = BodyLabel("", self)
        self.close_button = PushButton("关闭会话", self)
        self.close_button.clicked.connect(self.close_session_requested)
        self.close_button.setAccessibleName("关闭当前功能会话")
        self.close_button.setToolTip("停止并关闭当前功能的设备会话")
        session.addWidget(self.session_label, 0, 0)
        session.addWidget(self.session_combo, 0, 1)
        session.addWidget(self.session_hint, 0, 2)
        session.addWidget(self.close_button, 0, 3)
        session.setColumnStretch(1, 1)
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
            if isinstance(widget, (ComboBox, PushButton, ToolButton)):
                widget.setMinimumHeight(max(32, widget.fontMetrics().height() + 14))
                widget.setMaximumHeight(16777215)
        self._more_menu.setItemHeight(max(32, self.fontMetrics().height() + 14))
        for action in (self.info_action, self.disconnect_action):
            action.setFont(font)
        self._more_menu.view.adjustSize()
        self._more_menu.adjustSize()
        self._sync_compact_mode()

    def _apply_theme(self, *_args) -> None:
        """原生透明壳层会保留旧 palette，设备栏主动同步不透明主题底色。"""
        application = QApplication.instance()
        if not isinstance(application, QApplication):
            return
        palette = application.palette()
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self._surface.setPalette(palette)
        for widget in (self.target_row, self._actions, self.session_row):
            widget.setPalette(palette)
            widget.setAutoFillBackground(False)
        for widget in (self.targets_button, self.status_label, self.connect_button,
                       self.refresh_button, self.more_button, self.session_label,
                       self.session_combo, self.session_hint, self.close_button):
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
        self.targets_button.setText(
            f"操作设备 · {len(self._selected)} 台" if self._selected else "操作设备 · 未选择"
        )
        self.targets_button.setToolTip("选择一台或多台设备；已运行的会话保持原设备")
        text = {"scanning": "正在扫描", "unavailable": "ADB 暂不可用"}.get(
            state, f"在线 {len(self._connected)} 台" if self._connected else "未发现设备"
        )
        self.status_label.setText(text)
        self.targets_button.setAccessibleDescription(f"{text}，已选 {len(self._selected)} 台")
        self.refresh_button.setEnabled(state != "scanning")
        self.info_button.setEnabled(bool(self._selected))
        self.disconnect_button.setEnabled(bool(self._selected))
        self.info_action.setEnabled(bool(self._selected))
        self.disconnect_action.setEnabled(bool(self._selected))
        if self._picker is not None:
            self._picker.set_context(self._selected, self._connected)
        self._sync_compact_mode()

    def set_session_context(self, source: ComboBox | None, close: PushButton | None) -> None:
        """投影宿主的候选、锁和关闭状态，不接管会话生命周期。"""

        signature = (
            tuple((source.itemText(i), source.itemData(i)) for i in range(source.count()))
            if source is not None
            else None,
            source.currentIndex() if source is not None else -1,
            source.isEnabled() if source is not None else False,
            source.toolTip() if source is not None else "",
            (close.text(), close.isEnabled(), close.toolTip()) if close is not None else None,
        )
        if signature == self._session_signature:
            return
        self._session_signature = signature
        self._session_required = source is not None
        blocker = QSignalBlocker(self.session_combo)
        self.session_combo.clear()
        if source is not None:
            for index in range(source.count()):
                self.session_combo.addItem(source.itemText(index), userData=source.itemData(index))
            if source.count():
                self.session_combo.setCurrentIndex(source.currentIndex())
            else:
                self.session_combo.addItem("请先连接设备", userData="")
            self.session_combo.setEnabled(source.isEnabled())
            self.session_combo.setToolTip(source.toolTip())
        del blocker
        self.session_label.setVisible(source is not None)
        self.session_combo.setVisible(source is not None)
        self.session_hint.setText("")
        self.close_button.setVisible(close is not None)
        if close is not None:
            self.close_button.setText(close.text())
            self.close_button.setEnabled(close.isEnabled())
            self.close_button.setToolTip(close.toolTip())
        self.session_row.setVisible(source is not None or close is not None)
        self._sync_compact_mode()

    def _choose_session(self, _index: int) -> None:
        target = str(self.session_combo.currentData() or "")
        if target:
            self.session_requested.emit(target)

    def open_picker(self) -> None:
        """打开即时提交的多选弹层，同一时刻只保留一份选择视图。"""

        if self._picker is not None:
            return
        self.dismiss_popups()
        picker = DevicePicker()
        picker.setFixedWidth(self._popup_width(self.targets_button))
        picker.set_context(self._selected, self._connected)
        picker.selection_requested.connect(self.selection_requested)
        self._picker = picker
        self._picker_flyout = self._show_popup(picker, self.targets_button, align_right=False)
        self._picker_flyout.closed.connect(self._forget_picker)

    def _forget_picker(self, *_args) -> None:
        self._picker = None
        self._picker_flyout = None

    def open_connection(
        self, history: Iterable[tuple[str, str]], anchor: QWidget | None = None
    ) -> None:
        """以可见入口为锚点连接设备；概览可在设备栏隐藏时共用此表单。"""

        if self._connection is not None:
            self._connection.address.setFocus()
            return
        self.dismiss_popups()
        anchor = anchor if anchor is not None else self.connect_button
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
        self._more_menu.close()

    def hideEvent(self, event) -> None:
        self.dismiss_popups()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_mode()

    def _sync_compact_mode(self) -> None:
        width = max(0, self.width() - 56)
        target_width = (
            self.targets_button.sizeHint().width()
            + self.status_label.fontMetrics().horizontalAdvance(self.status_label.text()) + 8
        )
        actions_width = self._actions.sizeHint().width()
        self.session_hint.hide()
        label_width = self.session_label.sizeHint().width() if self._session_required else 0
        combo_width = (
            self.session_combo.fontMetrics().horizontalAdvance(self.session_combo.currentText())
            + 48
            if self._session_required
            else 0
        )
        close_width = (
            self.close_button.sizeHint().width() if not self.close_button.isHidden() else 0
        )
        self.close_button.setMinimumWidth(close_width)
        session_width = label_width + combo_width + close_width + 24
        actions_below = target_width + actions_width + 16 > width
        session_below = actions_below or target_width + actions_width + session_width + 32 > width
        mode = (actions_below, session_below)
        if mode != self._layout_mode:
            self._layout_mode = mode
            for widget in (self.target_row, self.session_row, self._actions):
                self._layout.removeWidget(widget)
            for column in range(3):
                self._layout.setColumnStretch(column, 0)
            if actions_below:
                self._layout.addWidget(self.target_row, 0, 0, 1, 3)
                self._layout.addWidget(self._actions, 1, 0, 1, 3, Qt.AlignmentFlag.AlignRight)
            else:
                self._layout.addWidget(self.target_row, 0, 0)
                self._layout.addWidget(self._actions, 0, 2)
            if session_below:
                self._layout.addWidget(self.session_row, 2 if actions_below else 1, 0, 1, 3)
                self._layout.setColumnStretch(0, 1)
            else:
                self._layout.addWidget(self.session_row, 0, 1)
                self._layout.setColumnStretch(1, 1)
        session_available = width if session_below else width - target_width - actions_width - 32
        self.session_combo.setMinimumWidth(
            min(combo_width, max(40, session_available - label_width - 16))
        )
        wrapped = self._session_required and session_width > session_available
        if wrapped != self._session_wrapped:
            self._session_wrapped = wrapped
            self._session_layout.removeWidget(self.close_button)
            if wrapped:
                self._session_layout.addWidget(
                    self.close_button, 1, 0, 1, 4, Qt.AlignmentFlag.AlignRight
                )
            else:
                self._session_layout.addWidget(self.close_button, 0, 3)
