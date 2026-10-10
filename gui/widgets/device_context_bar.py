"""全页设备上下文：批量目标与固定设备会话分别提交，选择区不拥有业务状态。"""

from __future__ import annotations

from collections.abc import Iterable
from math import ceil
from typing import Literal

from PySide6.QtCore import QEvent, QPoint, QRect, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFontMetricsF,
    QKeyEvent,
    QMouseEvent,
    QPen,
    QWheelEvent,
)
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
    HorizontalSeparator,
    InfoBadge,
    ListItemDelegate,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    ToolButton,
    TransparentDropDownPushButton,
    TransparentPushButton,
    VerticalSeparator,
)

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.icon_loader import DEVICE_ICON
from utils.adb_targets import normalize_adb_connect_target


class _DeviceFlyout(Flyout):
    """保留原生弹层输入路由，避免 Windows 主窗口失活后云母退回实色。"""

    def showEvent(self, event) -> None:
        if QApplication.platformName() == "windows":
            # Qt.Popup 已接管弹层输入；上游额外 activateWindow 会抢走主 HWND 激活。
            QWidget.showEvent(self, event)
        else:
            super().showEvent(event)


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


class _SelectorButton(TransparentDropDownPushButton):
    """沿用无底色按钮，展开时以反向强调箭头和文案表达区域的实际状态。"""

    def _drawDropDownIcon(self, painter, rect) -> None:
        painter.save()
        if self.property("selectorExpanded"):
            painter.translate(rect.center())
            painter.rotate(180)
            painter.translate(-rect.center())
            FluentIcon.ARROW_DOWN.render(
                painter, rect, fill=BaseStyles.color("BUTTON_ACCENT"),
            )
        else:
            super()._drawDropDownIcon(painter, rect)
        painter.restore()


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
    """让整行与复选框共享一次切换，外层滚动区负责设备列表的可见范围。"""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and item is not None:
            if item.data(Qt.ItemDataRole.UserRole) and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                self.setCurrentItem(item)
                item.setCheckState(
                    Qt.CheckState.Unchecked
                    if item.checkState() == Qt.CheckState.Checked
                    else Qt.CheckState.Checked
                )
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        item = self.currentItem()
        if (event.key() == Qt.Key.Key_Space and item is not None
                and item.flags() & Qt.ItemFlag.ItemIsEnabled
                and item.data(Qt.ItemDataRole.UserRole)):
            item.setCheckState(
                Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            event.accept()
            return
        super().keyPressEvent(event)


class _DeviceRowDelegate(ListItemDelegate):
    """绘制悬停与键盘焦点背景，文字和动作由真实子控件承载。"""

    def __init__(self, parent: _DeviceCheckList) -> None:
        super().__init__(parent)
        # 单行高度已包含上下留白，不能再叠加 Fluent 默认边距产生内层滚动范围。
        self.margin = 0

    def paint(self, painter, option, index) -> None:
        owner = self.parent()
        if not isinstance(owner, _DeviceCheckList):
            return
        focused = owner.hasFocus() and owner.currentIndex() == index
        painter.save()
        if self.hoverRow == index.row() or focused:
            color = QColor(BaseStyles.color("TEXT_PRIMARY"))
            color.setAlpha(24 if focused else 12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(owner.visualRect(index).adjusted(1, 1, -1, -1), 4, 4)
        # 设备之间始终保留中性分隔；选中只由复选框表达，不绘制强调色外框。
        line = QColor(BaseStyles.color("TEXT_PRIMARY"))
        line.setAlpha(24)
        painter.setPen(QPen(line, 1))
        bounds = owner.visualRect(index)
        painter.drawLine(bounds.bottomLeft(), bounds.bottomRight())
        painter.restore()

    def updateEditorGeometry(self, editor, option, index) -> None:
        # setItemWidget 也走委托的编辑器定位；行控件必须覆盖整行，不能沿用文本框偏移。
        owner = self.parent()
        if isinstance(owner, _DeviceCheckList):
            editor.setGeometry(owner.visualRect(index))


class _DeviceNameLabel(BodyLabel):
    """完整名称仅存于显示投影，窄宽度省略文字而不增加行高。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width()),
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()


class _DeviceRow(QWidget):
    """设备行只镜像条目的选中状态，业务提交统一经 QListWidget.itemChanged。"""

    def __init__(self, item: QListWidgetItem, owner: DevicePicker) -> None:
        super().__init__(owner.device_list)
        self.item = item
        self.owner = owner
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)
        self.check_box = CheckBox(self)
        self.check_box.setFixedWidth(24)
        self.check_box.clicked.connect(self._check)
        self.brand_label = _DeviceNameLabel(self)
        self.brand_separator = VerticalSeparator(self)
        self.name_label = _DeviceNameLabel(self)
        self.name_separator = VerticalSeparator(self)
        self.version_label = _DeviceNameLabel(self)
        self.connection_separator = VerticalSeparator(self)
        self.connection_label = _DeviceNameLabel(self)
        for label in (self.brand_label, self.name_label, self.version_label, self.connection_label):
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.status_label = BodyLabel(self)
        self.status_label.setWordWrap(False)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.check_box, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.brand_label)
        layout.addWidget(self.brand_separator)
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_separator)
        layout.addWidget(self.version_label)
        layout.addWidget(self.connection_separator)
        layout.addWidget(self.connection_label)
        layout.addStretch(1)
        self.action_separator = VerticalSeparator(self)
        layout.addWidget(self.action_separator)
        layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.status_label.hide()
        self.action_separator.hide()
        for separator in (
            self.brand_separator, self.name_separator, self.connection_separator,
            self.action_separator,
        ):
            separator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _check(self, checked: bool) -> None:
        self.owner.device_list.setCurrentItem(self.item)
        self.item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.check_box.isEnabled():
            self.check_box.click()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DevicePicker(QWidget):
    """页内即时提交复选目标；刷新候选时阻断信号，避免覆盖共享选择。"""

    selection_requested = Signal(list)
    session_requested = Signal(str)
    close_session_requested = Signal()
    collapse_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rendered_devices: tuple[str, ...] | None = None
        self._connected: tuple[str, ...] = ()
        self._labels: dict[str, str] = {}
        self._details: dict[str, dict[str, str]] = {}
        self._rows: dict[str, _DeviceRow] = {}
        self._selected: tuple[str, ...] = ()
        self._single_selection = False
        self._selection_locked = False
        self._height_budget: int | None = None
        self._close_scope: Literal["session", "page"] = "session"
        self._close_visible = False
        self._close_text = ""
        self._scan_state = ""
        self._sizing = False
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setObjectName("inlineDeviceScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(
            "#inlineDeviceScrollArea { background: transparent; border: none; }"
        )
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.content = QWidget()
        self.content.setMinimumWidth(0)
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.content)
        # QScrollArea.setWidget 会主动开启自动填充；挂载后关闭才能透出共享云母材质。
        self.content.setAutoFillBackground(False)
        layout.addWidget(self.scroll_area)
        layout.addWidget(HorizontalSeparator(self))
        self.toolbar = QWidget(self.content)
        self._actions = QHBoxLayout(self.toolbar)
        self._actions.setContentsMargins(4, 0, 4, 0)
        self._actions.setSpacing(8)
        self.summary_label = _DeviceNameLabel(self.toolbar)
        self._actions.addWidget(self.summary_label, 1)
        self.select_all_button = TransparentPushButton(
            FluentIcon.CHECKBOX, tr("全选"), self.toolbar,
        )
        self.clear_button = TransparentPushButton(FluentIcon.CANCEL, tr("清空选择"), self.toolbar)
        self.select_all_button.setToolTip(tr("勾选所有在线设备作为操作目标"))
        self.clear_button.setToolTip(tr("取消操作目标勾选，保留已打开的设备会话"))
        self.select_all_button.setAccessibleName(tr("全选"))
        self.clear_button.setAccessibleName(tr("清空选择"))
        self.select_all_button.clicked.connect(lambda: self._set_all(True))
        self.clear_button.clicked.connect(lambda: self._set_all(False))
        self._actions.addWidget(self.select_all_button)
        self._actions.addWidget(self.clear_button)
        self._content_layout.addWidget(self.toolbar)
        self.device_list = _DeviceCheckList(self.content)
        self.device_list.setAccessibleName(tr("操作设备多选列表"))
        self.device_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_list.setItemDelegate(_DeviceRowDelegate(self.device_list))
        self.device_list.setSpacing(0)
        self.device_list.setContentsMargins(0, 0, 0, 0)
        self.device_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.device_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.device_list.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.device_list.viewport().setAutoFillBackground(False)
        self.device_list.itemChanged.connect(self._submit)
        self.device_list.currentItemChanged.connect(self._ensure_current_visible)
        self._content_layout.addWidget(self.device_list)
        # 兼容原会话投影接口；这些控件不再构成第二套可见设备入口。
        self.description = BodyLabel(self)
        self.description.hide()
        self.session_box = QWidget(self)
        self.session_box.hide()
        self.session_combo = _SessionComboBox(self.session_box)
        self.session_combo.currentIndexChanged.connect(self._choose_session)
        self.session_target = CheckBox(self.session_box)
        self.session_target.clicked.connect(self._toggle_current_target)
        self.batch_heading = StrongBodyLabel(self)
        self.batch_heading.hide()
        self.close_section = QWidget(self.content)
        close_layout = QHBoxLayout(self.close_section)
        close_layout.setContentsMargins(0, 0, 0, 0)
        self.close_button = TransparentPushButton(FluentIcon.CLOSE, "", self.close_section)
        self.close_button.clicked.connect(self.close_session_requested)
        close_layout.addWidget(self.close_button)
        self.close_section.hide()
        BaseStyles.ui_font_changed.connect(self._apply_fonts)
        self._apply_fonts()
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)
        self.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.device_list.viewport() and event.type() == QEvent.Type.Resize:
            # 页头先于内部视口收到 resize；按最终宽度更新列和行，避免旧行宽裁掉右侧动作。
            self._sync_compact_actions()
            self.device_list.doItemsLayout()
        if (isinstance(event, QWheelEvent) and isinstance(watched, QWidget)
                and self.device_list.isAncestorOf(watched)):
            # Fluent 列表自己的平滑滚动过滤器会消费事件，须先转交唯一外层滚动区。
            viewport = self.scroll_area.viewport()
            forwarded = QWheelEvent(
                watched.mapTo(viewport, event.position().toPoint()), event.globalPosition(),
                event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(),
                event.phase(), event.inverted(),
            )
            QApplication.sendEvent(viewport, forwarded)
            return True
        if (isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            self.collapse_requested.emit()
            return True
        if event.type() == QEvent.Type.FocusIn and isinstance(watched, QWidget):
            if watched is self.device_list:
                self._ensure_current_visible()
            elif self.content.isAncestorOf(watched):
                self.scroll_area.ensureWidgetVisible(watched, 0, 2)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_actions()

    def _apply_fonts(self, *_args) -> None:
        _apply_popup_fonts(self)
        for row in self._rows.values():
            row.check_box.setFixedWidth(24)
        self._sync_list_height()

    def set_selection_mode(self, *, single: bool, locked: bool = False) -> None:
        """真实运行锁只阻止更换目标；会话关闭和清空继续保留原入口。"""
        self._single_selection = single
        self._selection_locked = locked
        self.select_all_button.setVisible(not single)
        self.select_all_button.setEnabled(bool(self._connected) and not locked)
        self.description.setText(
            tr("请选择一台操作设备；取消选择仍可查看缓存和停止任务。") if single
            else tr("可多选。正在运行的会话继续使用原设备。")
        )
        self.device_list.setAccessibleName(
            tr("操作设备单选列表") if single else tr("操作设备多选列表")
        )
        self.device_list.setToolTip(self.description.text())
        self._sync_rows()

    def set_discovery_state(self, state: str) -> None:
        """扫描中或失败只展示短提示，不把保留的候选快照宣称为已确认在线。"""
        self._scan_state = state
        self._sync_summary()

    def _sync_summary(self) -> None:
        text = {"scanning": tr("正在扫描"), "unavailable": tr("ADB 暂不可用")}.get(
            self._scan_state,
            tr("单选") if self._single_selection
            else tr("已选 {count} 台").format(count=len(self._selected)),
        )
        self.summary_label.set_full_text(text)

    def _sync_list_height(self) -> None:
        if self._sizing:
            return
        self._sizing = True
        blocker = QSignalBlocker(self.device_list)
        row_height = max(40, self.device_list.fontMetrics().height() + 18)
        for index in range(self.device_list.count()):
            item = self.device_list.item(index)
            if item is not None:
                item.setFont(self.device_list.font())
                item.setSizeHint(QSize(0, row_height))
        count = max(1, self.device_list.count())
        self.device_list.setFixedHeight(count * row_height + 2)
        toolbar_height = max(32, self.fontMetrics().height() + 16)
        self.toolbar.setFixedHeight(toolbar_height)
        self.content.setMinimumHeight(toolbar_height + 4 + count * row_height + 2)
        preferred = toolbar_height + 4 + 5 * row_height + 2 + 7
        height = (
            min(preferred, self._height_budget) if self._height_budget is not None else preferred
        )
        self.setFixedHeight(max(8, height))
        self.scroll_area.setFixedHeight(max(1, height - 7))
        del blocker
        self._sizing = False
        self._sync_compact_actions()

    def set_height_budget(self, height: int) -> None:
        """外层统一承担滚动，短窗的可见高度不会改变内部设备行自然高度。"""
        self._height_budget = max(8, height)
        self._sync_list_height()

    def set_context(
        self, selected: Iterable[str], connected: Iterable[str],
        names: dict[str, str] | None = None,
        *, labels: dict[str, str] | None = None,
        details: dict[str, dict[str, str]] | None = None,
    ) -> None:
        """只呈现共享候选及必要的离线当前会话，不采集额外设备信息。"""
        self._selected = tuple(selected)
        if self._single_selection:
            self._selected = self._selected[:1]
        self._connected = tuple(dict.fromkeys(connected))
        self._labels.update(labels or {})
        self._labels.update(names or {})
        self._details.update(details or {})
        for device in self._connected:
            if not self._labels.get(device) or self._labels[device] == device:
                self._labels[device] = tr("Android {value}设备").format(value="")
        self._sync_rows()

    def _sync_rows(self) -> None:
        current = str(self.session_combo.currentData() or "")
        offline = bool(self._close_visible and self._close_scope == "session"
                       and current and current not in self._connected)
        devices = self._connected + ((current,) if offline else ())
        blocker = QSignalBlocker(self.device_list)
        if devices != self._rendered_devices:
            # 唯一关闭控件可能属于旧条目，重建前先移回稳定父级，避免随行销毁。
            self.close_section.hide()
            self.close_section.setParent(self.content)
            self.device_list.clear()
            self._rows.clear()
            for device in devices:
                item = QListWidgetItem(self.device_list)
                row = _DeviceRow(item, self)
                self.device_list.setItemWidget(item, row)
                self._rows[device] = row
                row.installEventFilter(self)
                row.check_box.installEventFilter(self)
            if not devices:
                item = QListWidgetItem(tr("尚未发现设备，请连接或刷新"), self.device_list)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                empty = _DeviceNameLabel(self.device_list)
                empty.set_full_text(item.text())
                self.device_list.setItemWidget(item, empty)
            self._rendered_devices = devices
            _apply_popup_fonts(self)
        for device, row in self._rows.items():
            connected = device in self._connected
            selectable = connected and not self._selection_locked
            item = row.item
            item.setData(Qt.ItemDataRole.UserRole, device if connected else "")
            item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                if selectable else Qt.ItemFlag.NoItemFlags
            )
            label = self._labels.get(device, tr("Android {value}设备").format(value=""))
            details = self._details.get(device, {})
            brand = details.get("brand", "")
            version = details.get("android_version", "")
            version_text = f"Android {version}" if version else tr("Android 版本未知")
            connection = details.get("connection", "") or "—"
            information = " | ".join(filter(None, (brand, label, version_text, connection)))
            item.setText(label)
            item.setToolTip(information)
            row.setToolTip(information)
            item.setCheckState(
                Qt.CheckState.Checked if device in self._selected and connected
                else Qt.CheckState.Unchecked
            )
            check_blocker = QSignalBlocker(row.check_box)
            row.check_box.setChecked(item.checkState() == Qt.CheckState.Checked)
            row.check_box.setEnabled(selectable)
            row.check_box.setAccessibleName(information)
            del check_blocker
            row.name_label.set_full_text(label)
            row.brand_label.set_full_text(brand)
            row.version_label.set_full_text(version_text)
            row.connection_label.set_full_text(connection)
            row.status_label.setText(
                tr("离线") if not connected else tr("当前")
                if self._single_selection and device == current else ""
            )
            row.status_label.setVisible(bool(row.status_label.text()))
        del blocker
        self.select_all_button.setEnabled(bool(self._connected) and not self._selection_locked)
        self.clear_button.setEnabled(bool(self._selected))
        self._place_close_action()
        self._sync_summary()
        self._sync_list_height()

    def set_session_context(self, source: ComboBox | None, target: CheckBox) -> None:
        """保留会话查看投影，不让行内关闭动作依赖最近一次点击的设备。"""
        blocker = QSignalBlocker(self.session_combo)
        self.session_combo.clear()
        if source is not None:
            for index in range(source.count()):
                device = str(source.itemData(index) or "")
                label = self._labels.get(device, tr("Android {value}设备").format(value=""))
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
        self._sync_rows()

    def set_close_context(
        self, action: QAction, *, scope: Literal["session", "page"] = "session",
    ) -> None:
        """明确区分当前设备会话关闭与页面级清除，不通过翻译文案猜测作用范围。"""
        self._close_scope = scope
        self._close_visible = action.isVisible()
        self._close_text = action.text()
        self.close_button.setText(action.text())
        self.close_button.setAccessibleName(action.text())
        self.close_button.setToolTip(action.toolTip() or action.text())
        self.close_button.setAccessibleDescription(action.statusTip())
        self.close_button.setEnabled(action.isEnabled())
        self._sync_rows()

    def _place_close_action(self) -> None:
        current = str(self.session_combo.currentData() or "")
        row = self._rows.get(current)
        parent = self.toolbar if self._close_scope == "page" else row
        if not self._close_visible or parent is None:
            self.close_section.hide()
            return
        if self.close_section.parentWidget() is not parent:
            layout = parent.layout()
            assert isinstance(layout, QHBoxLayout)
            layout.addWidget(self.close_section, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_section.show()
        if self._close_scope == "page":
            QWidget.setTabOrder(self.clear_button, self.close_button)
            QWidget.setTabOrder(self.close_button, self.device_list)
        elif row is not None:
            QWidget.setTabOrder(row.check_box, self.close_button)
        if row is not None and self._close_scope == "session" and not self.close_button.isEnabled():
            row.status_label.setText(tr("正在关闭"))
            row.status_label.show()

    def _sync_compact_actions(self) -> None:
        if not hasattr(self, "close_button"):
            return
        # 所有按钮先恢复自然文案，再按可用宽度退让为带完整辅助名称的图标按钮。
        actions = [
            (self.select_all_button, tr("全选")),
            (self.clear_button, tr("清空选择")),
        ]
        if self._close_visible and self._close_scope == "page":
            actions.append((self.close_button, self._close_text))
        visible = [(button, text) for button, text in actions if not button.isHidden()]
        for button, text in visible:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setText(text)
        needed = sum(button.sizeHint().width() for button, _ in visible) + 8 * len(visible) + 72
        compact = needed > max(0, self.width() - 20)
        for button, text in visible:
            button.setText("" if compact else text)
            if compact:
                button.setFixedWidth(max(36, button.minimumHeight()))
        current = str(self.session_combo.currentData() or "")
        row = self._rows.get(current)
        if self._close_visible and self._close_scope == "session" and row is not None:
            self.close_button.setMinimumWidth(0)
            self.close_button.setMaximumWidth(16777215)
            self.close_button.setText(self._close_text)
            narrow = self.close_button.sizeHint().width() + 440 > max(0, self.width() - 20)
            self.close_button.setText("" if narrow else self._close_text)
            if narrow:
                self.close_button.setFixedWidth(max(36, self.close_button.minimumHeight()))
            if row.status_label.text() == tr("当前"):
                row.status_label.setVisible(not narrow)
        self._sync_row_columns()

    def _sync_row_columns(self) -> None:
        """列表共用按内容计算的列宽，收缩预算包含最宽操作区，保证各行上下对齐。"""
        if not self._rows:
            return
        metrics = self.fontMetrics()
        current = str(self.session_combo.currentData() or "")
        show_brand = any(row.brand_label._full_text for row in self._rows.values())
        columns: list[list[_DeviceNameLabel]] = []
        available = self.device_list.viewport().width()
        for device, row in self._rows.items():
            # 部分设备缺品牌时保留同列空位；整列无数据才收起，避免后续字段左右跳动。
            row.brand_label.setVisible(show_brand)
            row.brand_separator.setVisible(show_brand)
            has_close = (self._close_visible and self._close_scope == "session"
                         and device == current)
            has_status = not row.status_label.isHidden()
            row.action_separator.setVisible(has_close or has_status)
            layout = row.layout()
            assert isinstance(layout, QHBoxLayout)
            spacing = layout.spacing()
            action_width = row.status_label.sizeHint().width() + spacing if has_status else 0
            if has_close:
                action_width += self.close_button.width() if not self.close_button.text() else (
                    self.close_button.sizeHint().width()
                )
                action_width += spacing
            if has_close or has_status:
                action_width += row.action_separator.width() + spacing
            for separator in (
                row.brand_separator, row.name_separator, row.connection_separator,
                row.action_separator,
            ):
                separator.setFixedHeight(max(16, metrics.height() - 4))
            labels = [row.name_label, row.version_label, row.connection_label]
            if show_brand:
                labels.insert(0, row.brand_label)
            columns.append(labels)
            # 每个字段前最多一条分隔及两处间距；额外保留信息组与右侧操作的最小间距。
            margins = layout.contentsMargins()
            fixed = (margins.left() + margins.right() + row.check_box.width()
                     + (len(labels) - 1) * row.name_separator.width()
                     + spacing * len(labels) * 2 + action_width)
            available = min(
                available, max(len(labels), self.device_list.viewport().width() - fixed),
            )
        desired = [
            min(
                max(ceil(QFontMetricsF(label.font()).horizontalAdvance(label._full_text)) + 2
                    for label in column),
                metrics.horizontalAdvance("M") * (10 if show_brand and index == 0 else 20),
            )
            for index, column in enumerate(zip(*columns))
        ]
        # 短字段只占同列最长文字的空间；超长字段有上限，窄窗所有行同步省略。
        minimum = [min(width, metrics.horizontalAdvance("…") + 4) for width in desired]
        if sum(desired) > available:
            if sum(minimum) >= available:
                widths = [max(1, available // len(desired))] * len(desired)
            else:
                ratio = (available - sum(minimum)) / (sum(desired) - sum(minimum))
                widths = [int(low + (width - low) * ratio)
                          for low, width in zip(minimum, desired)]
        else:
            widths = desired
        for row, labels in zip(self._rows.values(), columns):
            for label, width in zip(labels, widths):
                label.setFixedWidth(width)
            # 改变字体但列宽不变时不会触发 resizeEvent，须重算省略后的显示文字。
            for label in labels:
                label._elide()
            layout = row.layout()
            assert isinstance(layout, QHBoxLayout)
            layout.activate()

    def _ensure_current_visible(self, *_args) -> None:
        item = self.device_list.currentItem()
        if item is None:
            return
        rect = self.device_list.visualItemRect(item)
        point = self.device_list.viewport().mapTo(self.content, rect.center())
        self.scroll_area.ensureVisible(point.x(), point.y(), 0, rect.height() // 2 + 2)

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
                device = str(item.data(Qt.ItemDataRole.UserRole) or "")
                if device:
                    selected.append(device)
        self._selected = tuple(selected)
        # 先投影复选框再提交；同步宿主回调只更新同一批行，不销毁点击发送方。
        self._sync_rows()
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
        self._device_details: dict[str, dict[str, str]] = {}
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
        self._close_action = QAction(self)
        self._close_scope: Literal["session", "page"] = "session"
        self._discovery_state = "empty"
        self._close_action.setVisible(False)
        self._close_action.setEnabled(False)
        outer = QVBoxLayout(self)
        self._outer_layout = outer
        outer.setContentsMargins(32, 12, 32, 6)
        outer.setSpacing(6)
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
        self.targets_button = _SelectorButton(DEVICE_ICON, tr("操作设备"), self)
        self.targets_button.setCheckable(True)
        self.targets_button.setAccessibleName(tr("操作设备（支持多选）"))
        self.targets_button.clicked.connect(self.toggle_selector)
        self.status_label = BodyLabel(tr("未发现设备"), self)
        self.status_label.setWordWrap(False)
        self.status_label.setMinimumWidth(0)
        target.addWidget(self.targets_button)
        self.status_label.hide()

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
        self.session_label.hide()
        self.session_combo.hide()
        self.session_target.hide()
        self._layout.addWidget(self.target_row)
        BaseStyles.ui_font_changed.connect(self._apply_fonts)
        BaseStyles.theme_changed.connect(self._apply_theme)
        self._apply_theme()
        self._apply_fonts()
        self.set_context((), (), "empty")
        if parent is not None:
            parent.installEventFilter(self)

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
        if self._picker is not None:
            self._picker._apply_fonts()
            self._sync_selector_height()

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
        self.target_row.setPalette(palette)
        self.target_row.setAutoFillBackground(False)
        # 状态标签由 Fluent 的明暗主题文字色管理，通用色板会覆盖其语义色。
        for widget in (self.targets_button, self.session_label, self.session_combo):
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
        self._discovery_state = state
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
                self._picker_selection(), self._connected,
                names={device: self.device_display_name(device) for device in self._device_numbers},
                details=self._device_details,
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

    def device_display_name(self, device: str) -> str:
        """选择入口使用安全名称，任务记录的稳定编号仍由 device_label 提供。"""
        name = (self._device_details.get(device, {}).get("model", "")
                or self._device_labels.get(device, ""))
        return name if name and name != device else tr("Android {value}设备").format(value="")

    def _display_device_text(self, text: str) -> str:
        """宿主保留真实身份用于选路，展示说明统一替换为当前会话名称。"""
        for device in sorted(self._device_numbers, key=len, reverse=True):
            text = text.replace(device, self.device_label(device))
        return text

    def _sync_target_presentation(self) -> None:
        """同一入口明确显示本页作用范围，避免把全局多选数误认为单设备页执行范围。"""
        if self._single_selection:
            device = str(self.session_combo.currentData() or "")
            full_text = tr("当前设备 · {device}").format(
                device=self.device_display_name(device) if device else tr("未选择"),
            )
            self._target_text = self.device_display_name(device) if device else full_text
            status = ""
            if device and device not in self._connected:
                status = " · " + tr("离线")
            elif device and device not in self._selected:
                status = " · " + tr("未勾选")
            self._target_text += status
            full_text += status
            scope = tr("请选择一台操作设备；取消选择仍可查看缓存和停止任务。")
        else:
            self._target_text = (
                tr("操作设备 · {count} 台").format(count=len(self._selected))
                if self._selected else tr("操作设备 · 未选择")
            )
            full_text = self._target_text
            scope = tr("操作会发送到全部已勾选设备；已运行任务保持原目标。")
        description = "\n".join(filter(None, (
            full_text, scope, self.status_label.text(),
            self._display_device_text(self.session_hint.toolTip()),
        )))
        self.targets_button.setAccessibleName(
            full_text + " · " + tr("收起设备") if self.is_selector_expanded else full_text,
        )
        self.targets_button.setAccessibleDescription(description)
        self.targets_button.setToolTip(description)
        self._sync_compact_mode()

    def set_device_labels(self, labels: dict[str, str]) -> bool:
        """仅名称变化时刷新展示并返回真；选中值仍采用原始设备身份。"""
        if all(self._device_labels.get(device) == name for device, name in labels.items()):
            return False
        self._device_labels.update(labels)
        if self._picker is not None:
            self._sync_picker_session()
        self._sync_target_presentation()
        return True

    def set_device_details(self, details: dict[str, dict[str, str]]) -> None:
        """接收主窗口缓存中的展示字段，不查询设备、不改变操作选择或会话归属。"""
        if all(self._device_details.get(device) == value for device, value in details.items()):
            return
        self._device_details.update({device: dict(value) for device, value in details.items()})
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
                self._picker_selection(), self._connected,
                names={device: self.device_display_name(device) for device in self._device_numbers},
                details=self._device_details,
            )
            self._picker.set_close_context(self._close_action, scope=self._close_scope)
            self._picker.set_discovery_state(self._discovery_state)
            self._sync_selector_height()

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
        close_scope: Literal["session", "page"] = "session",
    ) -> None:
        """投影宿主的候选、锁、状态和关闭动作，不接管会话生命周期。

        宿主工具栏本身可隐藏；会话状态只进入悬停和辅助说明，不重复占用顶部空间。
        不保留源控件引用，切换会话后不会访问已释放的页面控件。
        """

        status_visible = status is not None and not status.isHidden()
        self._has_session = source is not None
        self._single_selection = source is not None if single is None else single
        self._selection_locked = selection_locked
        self._close_scope = close_scope
        signature = (
            self._single_selection, selection_locked, close_scope,
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
        had_close_action = self._close_action.isVisible()
        self._close_action.setVisible(close is not None)
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
            self._close_action.setText(close.text() if close.isEnabled() else tr("正在关闭"))
            self._close_action.setEnabled(close.isEnabled())
            self._close_action.setToolTip("\n".join(filter(None, (
                close.text(), close.toolTip(), state_description,
            ))))
            self._close_action.setStatusTip(state_description)
        else:
            self._close_action.setEnabled(False)
            self._close_action.setToolTip("")
            self._close_action.setStatusTip("")
        self._sync_session_target()
        self._sync_picker_session()
        self._sync_target_presentation()
        if had_close_action and close is None:
            self.dismiss_popups()

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
        """幂等展开唯一页内选择区；程序准入入口不会把已展开列表误收起。"""

        if self.is_selector_expanded:
            return
        if self._connection_flyout is not None:
            self._connection_flyout.close()
        if self._picker is None:
            picker = DevicePicker(self)
            picker.selection_requested.connect(self.selection_requested)
            picker.session_requested.connect(self.session_requested)
            picker.close_session_requested.connect(self._request_close_session)
            picker.collapse_requested.connect(self.collapse_selector)
            self._picker = picker
            self._outer_layout.addWidget(picker)
        self._sync_picker_session()
        self._picker.show()
        self.targets_button.setProperty("selectorExpanded", True)
        self.targets_button.setChecked(True)
        self._sync_target_presentation()
        self.targets_button.update()
        self._sync_selector_height()

    @property
    def is_selector_expanded(self) -> bool:
        """展开状态仅由当前控件可见性决定，不写入设备或持久化状态。"""
        return self._picker is not None and not self._picker.isHidden()

    def toggle_selector(self) -> None:
        """用户点击页头切换列表，保留程序调用 open_picker 的幂等契约。"""
        if self.is_selector_expanded:
            self.collapse_selector()
        else:
            self.open_picker()

    def collapse_selector(self) -> None:
        """隐藏列表并移出焦点链；原行对象保留，避免点击回调期间销毁发送方。"""
        if self._picker is None:
            return
        focus = QApplication.focusWidget()
        return_focus = focus is not None and (
            focus is self._picker or self._picker.isAncestorOf(focus)
        )
        self._picker.hide()
        self.targets_button.setProperty("selectorExpanded", False)
        self.targets_button.setChecked(False)
        self._sync_target_presentation()
        self.targets_button.update()
        if return_focus and self.isVisible():
            self.targets_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _sync_selector_height(self) -> None:
        if self._picker is None:
            return
        parent = self.parentWidget()
        host = parent if parent is not None else self.window() or self
        height = host.height()
        margins = self._outer_layout.contentsMargins()
        header = self._surface.sizeHint().height() + margins.top() + margins.bottom()
        self._picker.set_height_budget(max(8, int((height - header) * .45)))

    def minimumSizeHint(self) -> QSize:
        # 展开高度按宿主实时收缩，不能用上一次固定高度反过来锁住主窗口最小高度。
        margins = self._outer_layout.contentsMargins()
        return QSize(0, self._surface.sizeHint().height() + margins.top() + margins.bottom())

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._sync_selector_height()
        return super().eventFilter(watched, event)

    def _request_close_session(self) -> None:
        """只接受当前展开区的有效关闭动作，先禁用再交回宿主释放原会话。"""
        if (
            self.sender() is not self._picker
            or not self.is_selector_expanded
            or not self._close_action.isVisible()
            or not self._close_action.isEnabled()
        ):
            return
        self._close_action.setEnabled(False)
        self._close_action.setText(tr("正在关闭"))
        self._sync_picker_session()
        self.close_session_requested.emit()

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

        flyout = _DeviceFlyout.make(view, parent=self)
        bounds = self._popup_bounds(anchor)
        margins = flyout.hBoxLayout.contentsMargins()
        flyout.adjustSize()
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
        """兼容旧入口：收起页内选择区，并关闭仍使用浮层的旧连接表单。"""

        self.collapse_selector()
        if self._connection_flyout is not None:
            self._connection_flyout.close()

    def hideEvent(self, event) -> None:
        self.dismiss_popups()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_mode()
        self._sync_selector_height()

    def _sync_compact_mode(self) -> None:
        """设备入口使用自然宽度，窄屏优先压缩标题和设备名称，始终保持单行。"""
        width = max(0, self.width() - 64)
        # 设备图标和下拉箭头分别占用两端，省略区不能覆盖任一入口提示。
        text_padding = 68
        # 原生字体含小数宽度；取整舍入后再传给 elidedText 会误删仍放得下的末字。
        metrics = QFontMetricsF(self.targets_button.font(), self.targets_button)
        text = tr("收起设备") if self.is_selector_expanded else self._target_text
        natural = ceil(metrics.horizontalAdvance(text)) + text_padding
        height = max(32, self.session_combo.fontMetrics().height() + 14)
        title_width = self.page_title.sizeHint().width() + 24
        self.page_title.setVisible(width >= natural + title_width)
        available = max(72, width - (title_width if self.page_title.isVisible() else 0))
        self.targets_button.setFixedWidth(min(natural, available))
        self.targets_button.setFixedHeight(height)
        self.targets_button.setText(self.targets_button.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight,
            self.targets_button.width() - text_padding,
        ))
