"""设备概览内的连接视图；配对任务和进程仍归主窗口协调器所有。"""

from __future__ import annotations

import math
import re
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QBoxLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FlowLayout,
    HyperlinkButton,
    IndeterminateProgressRing,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
    StrongBodyLabel,
    TransparentPushButton,
    VerticalSeparator,
)

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_focus_indicator, apply_font_role, apply_label_role
from gui.widgets.adaptive_navigation import AdaptiveNavigation
from utils.adb_targets import normalize_adb_connect_target


class _EqualHeightStack(QStackedWidget):
    """各页共享当前宽度下的自然高度，隐藏页不限制面板最小宽度。"""

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        margins = self.contentsMargins()
        width = max(1, width - margins.left() - margins.right())
        heights = []
        for index in range(self.count()):
            page = self.widget(index)
            layout = page.layout()
            assert layout is not None
            value = layout.totalHeightForWidth(width)
            heights.append(
                max(
                    layout.minimumSize().height(),
                    value if value >= 0 else layout.sizeHint().height(),
                )
            )
        return max(heights, default=0) + margins.top() + margins.bottom()

    def sizeHint(self):
        return QSize(600, self.heightForWidth(max(1, self.width())))

    def minimumSizeHint(self):
        return QSize(0, self.heightForWidth(max(1, self.width())))


class _HistoryText(BodyLabel):
    """历史仅占一行；优先展示地址，完整设备名保留在行提示中。"""

    def __init__(self, name, endpoint, parent):
        self._name = name
        self._endpoint = endpoint
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._sync_text()

    def _sync_text(self):
        metrics = self.fontMetrics()
        suffix = f" · {self._endpoint}"
        available = max(0, self.width())
        name_width = available - metrics.horizontalAdvance(suffix)
        name = metrics.elidedText(self._name, Qt.TextElideMode.ElideRight, max(0, name_width))
        text = name + suffix if name else self._endpoint
        self.setText(metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, available))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_text()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._sync_text()


class _AddressForm(QWidget):
    """显式提交合法地址；历史记录仅填入输入框，不隐式发起连接。"""

    connect_requested = Signal(str)

    def __init__(self, history, parent):
        super().__init__(parent)
        self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.columns.setContentsMargins(0, 0, 0, 0)
        self.columns.setSpacing(24)
        entry = QWidget(self)
        form = QVBoxLayout(entry)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        title = StrongBodyLabel(tr("连接已配对的设备"), entry)
        title.setWordWrap(True)
        form.addWidget(title)
        hint = BodyLabel(tr("填写手机无线调试主页上的 IP 地址和端口。"), entry)
        hint.setWordWrap(True)
        form.addWidget(hint)
        label = StrongBodyLabel(tr("设备地址"), entry)
        form.addWidget(label)
        self.entry_row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.address = LineEdit(entry)
        self.address.setMinimumWidth(0)
        self.address.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.address.setAccessibleName(tr("设备地址"))
        self.address.setPlaceholderText("192.168.1.10:37123")
        label.setBuddy(self.address)
        self.connect_button = PrimaryPushButton(tr("连接"), entry)
        self.connect_button.setToolTip(tr("校验输入地址并连接无线设备"))
        self.entry_row.addWidget(self.address, 1)
        self.entry_row.addWidget(self.connect_button)
        form.addLayout(self.entry_row)
        self.error_label = BodyLabel("", entry)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        form.addWidget(self.error_label)
        form.addStretch()
        self.columns.addWidget(entry, 1)
        self.history_box = QWidget(self)
        history_layout = QVBoxLayout(self.history_box)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(8)
        history_layout.addWidget(StrongBodyLabel(tr("设备连接历史"), self.history_box))
        self.history_scroll = SmoothScrollArea(self.history_box)
        self.history_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.history_scroll.viewport().setAutoFillBackground(False)
        self.history_content = QWidget()
        self.history_layout = QVBoxLayout(self.history_content)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(0)
        self.history_scroll.setWidget(self.history_content)
        self.history_content.setAutoFillBackground(False)
        history_layout.addWidget(self.history_scroll, 1)
        self.columns.addWidget(self.history_box, 1)
        self.history_rows = []
        self.connect_button.clicked.connect(self._connect)
        self.address.returnPressed.connect(self._connect)
        self.set_history(history)

    def set_history(self, history):
        """刷新展示快照并保留用户输入；历史不会成为另一份持久化状态。"""
        while self.history_layout.count():
            item = self.history_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.history_rows = []
        for name, endpoint in history:
            # 旧列表名称已拼接端点，仅清理精确后缀，不更改历史数据及连接目标。
            name = name.strip()
            if endpoint and name.endswith(endpoint):
                name = name[:-len(endpoint)].rstrip(" ·")
            description = f"{name} · {endpoint}" if name else endpoint
            row = TransparentPushButton(self.history_content)
            row.setMinimumWidth(0)
            row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            row.setAccessibleName(
                tr("填入 {name} 的连接地址 {address}").format(name=name, address=endpoint)
            )
            row.setToolTip(tr("点击填入地址：{address}").format(address=endpoint))
            row.setAccessibleDescription(description)
            apply_focus_indicator(row)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 5, 8, 5)
            row_layout.addWidget(_HistoryText(name, endpoint, row), 1)
            row.clicked.connect(lambda _checked=False, target=endpoint: self._fill(target))
            self.history_rows.append(row)
            self.history_layout.addWidget(row)
        self.empty_history = BodyLabel(tr("暂无连接记录"), self.history_content)
        self.empty_history.setWordWrap(True)
        self.history_layout.addWidget(self.empty_history)
        self.empty_history.setVisible(not self.history_rows)
        self.history_layout.addStretch()
        self._size_history()

    def _size_history(self):
        row_height = max(36, self.address.fontMetrics().height() + 16)
        for row in self.history_rows:
            row.setFixedHeight(row_height)
        self.history_scroll.setMinimumHeight(row_height * (4 if self.history_rows else 1))

    def _fill(self, endpoint):
        self.address.setText(endpoint)
        self.address.setFocus()

    def _connect(self):
        if not self.isEnabled():
            return
        target, error = normalize_adb_connect_target(self.address.text())
        self.error_label.setText(tr(error) if error else "")
        self.error_label.setVisible(bool(error))
        if error:
            self.address.setFocus()
            return
        self.connect_requested.emit(target)

    def reflow(self, width):
        self.columns.setDirection(
            QBoxLayout.Direction.TopToBottom if width <= 580 else QBoxLayout.Direction.LeftToRight
        )
        self.columns.setSpacing(12 if width <= 580 else 24)
        required = self.connect_button.sizeHint().width() + 170
        self.entry_row.setDirection(
            QBoxLayout.Direction.TopToBottom
            if width < required
            else QBoxLayout.Direction.LeftToRight
        )
        self._size_history()


class DeviceConnectionPanel(QWidget):
    """常驻页内单会话视图；收起立即隐藏，资源空闲前拒绝新一轮配对。"""

    connect_requested = Signal(str)
    expanded_changed = Signal(bool)
    PAGES = ("qr", "manual", "address")

    def __init__(self, coordinator, history=(), parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        self.current_page = "qr"
        self._expanded = False
        self._pending_page = None
        self._pending_refresh = False
        self._closed = True
        self._submitted_address = False
        self._shutting_down = False
        self._pair_started = False
        self._qr_image = QImage()
        self._qr_modules = 0
        self._qr_request = None
        self._qr_acknowledged = False
        self._scan_deadline = 0.0
        self._reflow_pending = False
        self._countdown = QTimer(self)
        self._countdown.setInterval(1000)
        self._countdown.timeout.connect(self._tick)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 12)
        self._layout.setSpacing(14)
        self.navigation = AdaptiveNavigation("connection", accessible_name="连接方式", parent=self)
        for key, text in zip(self.PAGES, ("扫码", "配对码", "IP 连接")):
            self.navigation.add_item(key, tr(text))
        for index in (1, 3):
            separator = VerticalSeparator(self.navigation.pivot)
            separator.setFixedSize(3, 14)
            separator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.navigation.pivot.hBoxLayout.insertWidget(
                index, separator, 0, Qt.AlignmentFlag.AlignVCenter
            )
        navigation_layout = self.navigation.layout()
        assert navigation_layout is not None
        navigation_layout.setAlignment(self.navigation.pivot, Qt.AlignmentFlag.AlignLeft)
        self.navigation.current_requested.connect(self.request_page)
        self._layout.addWidget(self.navigation)
        self.stack = _EqualHeightStack(self)
        # 内容与设备卡内沿对齐；页签自带文字留白，保持现有导航位置。
        self.stack.setContentsMargins(14, 0, 14, 0)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._build_qr_page()
        self._build_manual_page()
        self.address_form = _AddressForm(history, self.stack)
        self.address_form.connect_requested.connect(self._submit_address)
        self.stack.addWidget(self.address_form)
        self._layout.addWidget(self.stack)
        self.status_box = QWidget(self)
        status = QVBoxLayout(self.status_box)
        status.setContentsMargins(0, 0, 0, 0)
        status.setSpacing(6)
        self.status_row = QWidget(self.status_box)
        status_line = FlowLayout(self.status_row, isTight=True)
        status_line.setContentsMargins(0, 0, 0, 0)
        self.progress_ring = IndeterminateProgressRing(self.status_row)
        self.progress_ring.setFixedSize(20, 20)
        status_line.addWidget(self.progress_ring)
        self.status_label = StrongBodyLabel("", self.status_row)
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        status_line.addWidget(self.status_label)
        self.countdown_label = BodyLabel("", self.status_row)
        self.countdown_label.setWordWrap(True)
        status_line.addWidget(self.countdown_label)
        self.refresh_button = PushButton(tr("生成二维码"), self.status_row)
        self.cancel_button = PushButton(tr("停止"), self.status_row)
        self.retry_stop_button = PushButton(tr("重试停止"), self.status_row)
        for button in (self.refresh_button, self.cancel_button, self.retry_stop_button):
            status_line.addWidget(button)
        status.addWidget(self.status_row)
        self.status_detail = BodyLabel("", self.status_box)
        self.status_detail.setWordWrap(True)
        self.status_detail.setTextFormat(Qt.TextFormat.PlainText)
        status.addWidget(self.status_detail)
        self._build_continuation(status)
        self.qr_status_layout.addWidget(self.status_box)
        self.refresh_button.clicked.connect(self.refresh_qr)
        self.cancel_button.clicked.connect(self.cancel_current)
        self.retry_stop_button.clicked.connect(coordinator.retry_stop)
        coordinator.progress.connect(self._on_progress)
        coordinator.qr_ready.connect(self._on_qr)
        coordinator.outcome_ready.connect(self._on_outcome)
        coordinator.busy_changed.connect(self._update_controls)
        coordinator.continuation_changed.connect(self._update_controls)
        coordinator.idle.connect(self._on_idle)
        BaseStyles.ui_font_changed.connect(self._apply_fonts)
        for sequence, step in (("Ctrl+Tab", 1), ("Ctrl+Shift+Tab", -1)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda step=step: self._cycle_page(step))
        self._apply_fonts()
        self._update_controls()
        self.setFixedHeight(0)
        self.hide()

    @property
    def is_expanded(self):
        """返回用户展开意图；祖先隐藏会同步撤销此意图。"""
        return self._expanded

    @property
    def scroll_area(self):
        """查找页面宿主滚动区，面板本身不嵌套整页滚动。"""
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def expand(self, history=()):
        """仅显式展开启动扫码；清理未结束时只显示停止状态，不排队自动重启。"""
        if self._expanded or self._shutting_down:
            return
        self.address_form.set_history(history)
        self._apply_fonts()
        self._expanded = True
        self._closed = False
        self._submitted_address = False
        self._pending_page = None
        self._pending_refresh = False
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self._show_page("qr", start=False)
        self.show()
        self._reflow()
        area = self.scroll_area
        if area is not None:
            area.viewport().installEventFilter(self)
        self.expanded_changed.emit(True)
        if self.coordinator.busy:
            self._project_state(self.coordinator.state, self.coordinator.reason)
        else:
            self.coordinator.start_qr()
            self._update_controls()

    def collapse(self):
        """隐藏和清空秘密立即发生；取消资源由协调器异步完成，视图保持存活。"""
        if not self._expanded:
            return
        self._expanded = False
        self._closed = True
        self._pending_page = None
        self._pending_refresh = False
        self._clear_secrets()
        self.progress_ring.stop()
        self.setFixedHeight(0)
        self.hide()
        if not self._shutting_down:
            self.coordinator.cancel()
        self.expanded_changed.emit(False)

    def _label(self, text, parent, layout, *, strong=False):
        label = (StrongBodyLabel if strong else BodyLabel)(tr(text), parent)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setMinimumWidth(0)
        layout.addWidget(label)
        return label

    def _build_qr_page(self):
        self.qr_page = QWidget(self.stack)
        self.qr_columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.qr_page)
        self.qr_columns.setContentsMargins(0, 0, 0, 0)
        self.qr_columns.setSpacing(24)
        self.qr_text = QWidget(self.qr_page)
        self.qr_text_layout = QVBoxLayout(self.qr_text)
        self.qr_text_layout.setContentsMargins(0, 0, 0, 0)
        self.qr_text_layout.setSpacing(10)
        self._label("扫码连接新设备", self.qr_text, self.qr_text_layout, strong=True)
        self._label("手机与电脑连接同一局域网。", self.qr_text, self.qr_text_layout)
        self._label(
            "1  打开手机的“开发者选项 → 无线调试”\n2  选择“使用二维码配对设备”，扫描二维码",
            self.qr_text,
            self.qr_text_layout,
        )
        code_option = QWidget(self.qr_text)
        code_option_layout = FlowLayout(code_option, isTight=True)
        code_option_layout.setContentsMargins(0, 0, 0, 0)
        self.code_hint = self._label("没有扫码入口？", code_option, code_option_layout)
        self.code_hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.code_button = HyperlinkButton(code_option)
        self.code_button.setText(tr("使用配对码"))
        self.code_button.setToolTip(tr("使用配对码连接"))
        self.code_button.setAccessibleDescription(tr("使用配对码连接"))
        apply_focus_indicator(self.code_button)
        self.code_button.clicked.connect(lambda: self.request_page("manual"))
        code_option_layout.addWidget(self.code_button)
        self.qr_text_layout.addWidget(code_option)
        self.qr_status_slot = QWidget(self.qr_text)
        self.qr_status_layout = QVBoxLayout(self.qr_status_slot)
        self.qr_status_layout.setContentsMargins(0, 0, 0, 0)
        self.qr_text_layout.addWidget(self.qr_status_slot)
        self.qr_text_layout.addStretch()
        self.qr_columns.addWidget(self.qr_text, 1)
        self.qr_label = QLabel(self.qr_page)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setAccessibleName(tr("无线调试配对二维码"))
        self.qr_label.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.qr_label.setFixedSize(196, 196)
        self.qr_columns.addWidget(
            self.qr_label, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        self.stack.addWidget(self.qr_page)

    def _build_manual_page(self):
        self.manual_page = QWidget(self.stack)
        self.manual_layout = QVBoxLayout(self.manual_page)
        self.manual_layout.setContentsMargins(0, 0, 0, 0)
        self.manual_layout.setSpacing(10)
        self._label(
            "在手机“无线调试”中选择“使用配对码配对设备”，填写其中的地址和配对码。",
            self.manual_page,
            self.manual_layout,
        )
        self.manual_fields = QGridLayout()
        self.manual_fields.setSpacing(10)
        self.address_field = QWidget(self.manual_page)
        address_layout = QVBoxLayout(self.address_field)
        address_layout.setContentsMargins(0, 0, 0, 0)
        label = self._label("配对地址", self.address_field, address_layout, strong=True)
        self.pairing_address = LineEdit(self.address_field)
        self.pairing_address.setMinimumWidth(0)
        self.pairing_address.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.pairing_address.setPlaceholderText("192.168.1.10:37123")
        self.pairing_address.setAccessibleName(tr("配对地址"))
        label.setBuddy(self.pairing_address)
        address_layout.addWidget(self.pairing_address)
        self.code_field = QWidget(self.manual_page)
        code_layout = QVBoxLayout(self.code_field)
        code_layout.setContentsMargins(0, 0, 0, 0)
        label = self._label("配对码", self.code_field, code_layout, strong=True)
        self.pairing_code = LineEdit(self.code_field)
        self.pairing_code.setMinimumWidth(0)
        self.pairing_code.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.pairing_code.setEchoMode(QLineEdit.EchoMode.Password)
        self.pairing_code.setPlaceholderText(tr("手机显示的 6 位数字"))
        self.pairing_code.setAccessibleName(tr("配对码"))
        label.setBuddy(self.pairing_code)
        code_layout.addWidget(self.pairing_code)
        self.pair_button = PrimaryPushButton(tr("配对并连接"), self.manual_page)
        self.manual_fields.addWidget(self.address_field, 0, 0)
        self.manual_fields.addWidget(self.code_field, 0, 1)
        self.manual_fields.addWidget(self.pair_button, 0, 2, Qt.AlignmentFlag.AlignBottom)
        self.manual_layout.addLayout(self.manual_fields)
        self.manual_status_slot = QWidget(self.manual_page)
        self.manual_status_layout = QVBoxLayout(self.manual_status_slot)
        self.manual_status_layout.setContentsMargins(0, 0, 0, 0)
        self.manual_layout.addWidget(self.manual_status_slot)
        self.manual_layout.addStretch()
        self.pair_button.clicked.connect(self._submit_code)
        self.pairing_code.returnPressed.connect(self._submit_code)
        self.pairing_address.returnPressed.connect(self._submit_code)
        self.pairing_code.textChanged.connect(self._update_controls)
        self.pairing_address.textChanged.connect(self._update_controls)
        self.stack.addWidget(self.manual_page)

    def _build_continuation(self, status):
        self.continuation_box = QWidget(self.status_box)
        layout = QVBoxLayout(self.continuation_box)
        layout.setContentsMargins(0, 8, 0, 0)
        self._label(
            tr("返回手机“无线调试”首页，填写“IP 地址和端口”。该端口通常与刚才的配对端口不同。"),
            self.continuation_box,
            layout,
        )
        label = self._label(tr("连接地址"), self.continuation_box, layout, strong=True)
        self.connection_address = LineEdit(self.continuation_box)
        self.connection_address.setPlaceholderText("192.168.1.10:37123")
        self.connection_address.setAccessibleName(tr("连接地址"))
        label.setBuddy(self.connection_address)
        layout.addWidget(self.connection_address)
        self.continue_button = PrimaryPushButton(tr("继续连接"), self.continuation_box)
        self.use_address_button = PushButton(tr("使用地址连接"), self.continuation_box)
        layout.addWidget(self.continue_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.use_address_button, 0, Qt.AlignmentFlag.AlignRight)
        self.continue_button.clicked.connect(self._continue)
        self.connection_address.returnPressed.connect(self._continue)
        self.connection_address.textChanged.connect(self._update_controls)
        self.use_address_button.clicked.connect(lambda: self.request_page("address"))
        status.addWidget(self.continuation_box)

    def _apply_fonts(self, *_args):
        for widget in self.findChildren(QWidget):
            if isinstance(widget, _HistoryText):
                apply_label_role(widget, FontRole.UI)
            elif isinstance(widget, StrongBodyLabel):
                apply_label_role(widget, FontRole.UI, bold=True)
            elif isinstance(widget, BodyLabel):
                apply_label_role(widget, FontRole.UI, color_key="TEXT_SECONDARY")
            elif isinstance(widget, (LineEdit, PushButton)):
                apply_font_role(widget, FontRole.UI)
            if isinstance(widget, (LineEdit, PushButton)):
                widget.setMaximumHeight(16777215)
                widget.setMinimumHeight(max(32, widget.fontMetrics().height() + 16))
            if isinstance(widget, PushButton):
                widget.setAutoDefault(False)
                widget.setDefault(False)
        self.code_hint.setMinimumHeight(
            max(self.code_button.minimumHeight(), self.code_button.sizeHint().height())
        )
        self._schedule_reflow()

    def _submit_address(self, target):
        if (
            not self._expanded
            or self._shutting_down
            or self._submitted_address
            or self.current_page != "address"
            or self.coordinator.busy
        ):
            return
        self._submitted_address = True
        self.address_form.setEnabled(False)
        self.connect_requested.emit(target)
        self.collapse()

    def _submit_code(self):
        if (
            not self._expanded
            or self._shutting_down
            or self.current_page != "manual"
            or not self.pair_button.isEnabled()
        ):
            return
        if self.coordinator.start_code(self.pairing_address.text(), self.pairing_code.text()):
            self.pairing_code.clear()
            self._update_controls()

    def _continue(self):
        if (
            not self._expanded
            or self._shutting_down
            or not self.continuation_box.isVisible()
            or not self.continue_button.isEnabled()
        ):
            return
        self.coordinator.continue_connection(self.connection_address.text())
        self._update_controls()

    def request_page(self, page):
        """换页只记录一个意图，清理期间保留原页且拒绝新的非关闭意图。"""
        if (
            not self._expanded
            or self._shutting_down
            or page not in self.PAGES
            or page == self.current_page
            or self._has_pending()
            or self.coordinator.state in ("Stopping", "CleanupFailed")
        ):
            return
        self._clear_secrets()
        if self.coordinator.busy:
            self._pending_page = page
            self.coordinator.cancel()
            self._update_controls()
            return
        self.coordinator.cancel()
        self._show_page(page)

    def _show_page(self, page, *, start=True):
        self.current_page = page
        self.stack.setCurrentIndex(self.PAGES.index(page))
        self.navigation.set_current(page)
        destination = self.qr_status_layout if page == "qr" else self.manual_status_layout
        destination.addWidget(self.status_box)
        self.status_box.setVisible(page != "address")
        self.stack.updateGeometry()
        self.connection_address.clear()
        self._pair_started = False
        if page == "qr":
            if start:
                self.coordinator.start_qr()
            self.navigation.setFocus()
        elif page == "manual":
            self.pairing_address.setFocus()
        else:
            self.address_form.address.setFocus()
        self._update_controls()

    def refresh_qr(self):
        if (
            not self._expanded
            or self._shutting_down
            or self.current_page != "qr"
            or self._has_pending()
            or self.coordinator.state
            in ("Pairing", "WaitingForConnection", "Stopping", "CleanupFailed")
        ):
            return
        self._clear_secrets()
        if self.coordinator.busy:
            self._pending_refresh = True
            self.coordinator.cancel()
        else:
            self._pair_started = False
            self.coordinator.start_qr()
        self._update_controls()

    def cancel_current(self):
        if not self._expanded or self._shutting_down or self._has_pending():
            return
        self._clear_secrets()
        self.coordinator.cancel()
        self._update_controls()

    def _has_pending(self):
        return self._pending_refresh or self._pending_page is not None

    def _on_idle(self):
        if self._closed or self._shutting_down or self.coordinator.busy:
            return
        if self._pending_page is not None:
            page, self._pending_page = self._pending_page, None
            self._show_page(page)
        elif self._pending_refresh:
            self._pending_refresh = False
            self._pair_started = False
            self.coordinator.start_qr()
        self._update_controls()

        if (
            self.current_page == "manual"
            and self.coordinator.reason == "pair_failed"
            and not self._has_pending()
        ):
            self.pairing_code.setFocus()

    def _on_progress(self, progress):
        if self._closed or self._shutting_down:
            return
        self._project_state(progress.state, progress.reason, progress.remaining_seconds)

    def _project_state(self, state, reason, remaining_seconds=0):
        """重开时从协调器快照恢复状态；隐藏期间的消息不恢复秘密或触发工作。"""
        if state == "Pairing":
            self._pair_started = True
        if state not in ("Checking", "WaitingForScan"):
            self._clear_qr()
        if state in (
            "Connected",
            "PairedOnly",
            "Failed",
            "Uncertain",
            "Idle",
            "Stopping",
            "CleanupFailed",
        ):
            self.pairing_code.clear()
        if state == "WaitingForScan" and remaining_seconds and not self._qr_image.isNull():
            self._scan_deadline = time.monotonic() + remaining_seconds
            self._countdown.start()
            self._tick()
        states = {
            "Checking": tr("正在准备扫码") if self.current_page == "qr" else tr("正在检查连接环境"),
            "WaitingForScan": tr("等待手机扫码"),
            "Pairing": tr("正在配对"),
            "WaitingForConnection": tr("已配对，正在确认连接"),
            "Connected": tr("设备已连接"),
            "PairedOnly": tr("已配对，连接尚未确认"),
            "Failed": tr("连接未完成"),
            "Uncertain": tr("未能确认配对结果，请检查手机。"),
            "Stopping": tr("正在停止，请稍候。"),
            "CleanupFailed": tr("连接任务尚未结束，暂时无法开始新操作。"),
            "Idle": tr("本次操作已停止") if reason else "",
        }
        reasons = {
            "adb_unavailable": tr("当前 ADB 客户端不可用，请在设置中检查客户端。"),
            "unsupported_client": tr("当前 ADB 不支持无线配对，请在设置中选择较新的客户端。"),
            "mdns_unavailable": tr("无法自动发现手机，请尝试使用配对码。"),
            "mdns_timeout": tr("无法自动发现手机，请尝试使用配对码。"),
            "mdns_unrecognized": tr("无法自动发现手机，请尝试使用配对码。"),
            "scan_timeout": tr("二维码已过期，请重新生成。"),
            "prepare_timeout": tr("准备超时，请检查连接环境后重试。"),
            "service_conflict": tr("发现结果存在冲突，请重新生成二维码后再试。"),
            "pair_failed": (
                tr("配对未成功，请检查手机显示的配对码后重新输入。")
                if self.current_page == "manual"
                else tr("连接未完成，请检查无线调试与网络后重试。")
            ),
            "pair_uncertain": tr("未能确认配对结果，请检查手机。"),
            "identity_mismatch": tr("此连接地址与本次配对设备不一致，请核对地址。"),
            "connection_timeout": tr("已配对，连接尚未确认。可填写无线调试首页的连接地址继续。"),
            "guid_unavailable": tr("可以使用地址连接继续。"),
            "context_changed": tr("ADB 连接环境已变更，请重新开始配对。"),
            "invalid_request": tr("请检查地址与六位配对码。"),
            "command_failed": tr("连接未完成，请检查无线调试与网络后重试。"),
        }
        self.status_label.setText(states.get(state, tr("连接未完成")))
        detail = reasons.get(reason, "")
        if state == "Connected":
            detail = tr("连接已确认，可返回设备列表选择操作设备。")
        elif state == "Idle" and reason == "cancelled" and self._pair_started:
            detail = tr("手机可能已保存配对记录，可在无线调试中查看。")
        self.status_detail.setText(detail)
        self.status_label.setAccessibleDescription(self.status_label.text())
        self._update_controls()
        if state == "PairedOnly":
            QTimer.singleShot(0, self._reveal_continuation)

    def _reveal_continuation(self):
        """结果展开时让续连字段进入视口，不抢走用户当前键盘焦点。"""
        if not self._closed and self.continuation_box.isVisible():
            area = self.scroll_area
            if area is not None:
                area.ensureWidgetVisible(self.connection_address)

    def _on_outcome(self, outcome):
        if self._closed or self._shutting_down or self._has_pending():
            return
        if outcome.state == "PairedOnly" and outcome.connection_endpoint:
            self.connection_address.setText(outcome.connection_endpoint)
        self._update_controls()

    def _update_controls(self, *_args):
        if not hasattr(self, "continue_button"):
            return
        state = self.coordinator.state
        stopping = state in ("Stopping", "CleanupFailed") or self._has_pending()
        busy = self.coordinator.busy
        self.navigation.setEnabled(not stopping and not self._shutting_down)
        self.status_box.setVisible(self.current_page != "address")
        paired = state == "PairedOnly" or (
            state == "WaitingForConnection" and self.continuation_box.isVisible()
        )
        self.continuation_box.setVisible(paired)
        self.connection_address.setEnabled(not busy)
        self.continue_button.setEnabled(
            bool(
                paired
                and self.coordinator.continuation is not None
                and not busy
                and not stopping
                and not normalize_adb_connect_target(self.connection_address.text())[1]
            )
        )
        valid_code = re.fullmatch(r"[0-9]{6}", self.pairing_code.text()) is not None
        self.pair_button.setEnabled(
            bool(
                self.current_page == "manual"
                and not busy
                and not stopping
                and valid_code
                and not normalize_adb_connect_target(self.pairing_address.text())[1]
            )
        )
        self.pairing_address.setEnabled(not busy)
        self.pairing_code.setEnabled(not busy)
        self.use_address_button.setEnabled(not stopping)
        if not hasattr(self, "refresh_button"):
            return
        qr = self.current_page == "qr"
        self.refresh_button.setVisible(qr)
        self.refresh_button.setText(
            tr("刷新二维码") if state == "WaitingForScan" else tr("生成二维码")
        )
        self.refresh_button.setEnabled(
            not stopping and state not in ("Pairing", "WaitingForConnection")
        )
        self.code_button.setVisible(True)
        self.code_button.setEnabled(not stopping)
        self.cancel_button.setVisible(busy and not stopping)
        self.retry_stop_button.setVisible(state == "CleanupFailed")
        show_progress = (
            qr
            and self.isVisible()
            and state in ("Checking", "Pairing", "WaitingForConnection", "Stopping")
        )
        self.progress_ring.setVisible(show_progress)
        if show_progress:
            self.progress_ring.start()
        else:
            self.progress_ring.stop()
        self.qr_label.setVisible(True)
        self.address_form.setEnabled(not busy and not stopping and not self._submitted_address)
        self.status_detail.setVisible(bool(self.status_detail.text()))
        self.countdown_label.setVisible(bool(self.countdown_label.text()))
        self._schedule_reflow()

    def _on_qr(self, request_id, png, modules):
        if (
            self.current_page != "qr"
            or self._has_pending()
            or self._closed
            or self._shutting_down
            or not self.isVisible()
            or self.coordinator.state not in ("Checking", "WaitingForScan")
        ):
            return
        image = QImage.fromData(png)
        if image.isNull() or modules <= 0:
            return
        self._qr_image, self._qr_modules, self._qr_request = image, modules, request_id
        self._qr_acknowledged = False
        self._render_qr()
        QTimer.singleShot(0, lambda: self._ack_qr(request_id))

    def _qr_can_ack(self, request_id):
        window = self.window()
        return (
            self._expanded
            and not self._shutting_down
            and not self._has_pending()
            and not self._qr_acknowledged
            and self._qr_request == request_id
            and self.isVisible()
            and window is not None
            and not window.isMinimized()
            and self.qr_label.isVisible()
        )

    def _ack_qr(self, request_id, attempts=0):
        """先滚动页面宿主，让完整二维码进入视口，再确认扫码预算可以开始。"""
        if not self._qr_can_ack(request_id):
            return
        self._render_qr()
        area = self.scroll_area
        if area is not None:
            viewport = area.viewport()
            bar = area.verticalScrollBar()
            offset = self.qr_label.mapTo(viewport, QPoint()).y()
            bar.setValue(bar.value() + offset - max(0, (viewport.height() - 196) // 2))
        QTimer.singleShot(0, lambda: self._confirm_qr_visible(request_id, attempts))

    def _confirm_qr_visible(self, request_id, attempts):
        """可见意图、请求身份与像素可见范围必须同时成立，收起后的回调无效。"""
        if not self._qr_can_ack(request_id):
            return
        area = self.scroll_area
        viewport = area.viewport() if area is not None else self.window()
        if viewport is None:
            return
        pixmap = self.qr_label.pixmap()
        if pixmap.isNull():
            return
        side = pixmap.width() / pixmap.devicePixelRatioF()
        origin = self.qr_label.mapTo(viewport, QPoint())
        left = origin.x() + (self.qr_label.width() - side) / 2
        top = origin.y() + (self.qr_label.height() - side) / 2
        if (
            left >= 0
            and top >= 0
            and left + side <= viewport.width()
            and top + side <= viewport.height()
        ):
            self.qr_label.repaint()
            self._qr_acknowledged = True
            self.coordinator.acknowledge_qr(request_id)
        elif attempts < 30:
            QTimer.singleShot(10, lambda: self._ack_qr(request_id, attempts + 1))

    def _render_qr(self):
        if self._qr_image.isNull():
            return
        dpr = self.devicePixelRatioF()
        scale = max(1, int(196 * dpr / self._qr_modules))
        side = scale * self._qr_modules
        pixmap = QPixmap.fromImage(
            self._qr_image.scaled(
                side,
                side,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )
        pixmap.setDevicePixelRatio(dpr)
        self.qr_label.setPixmap(pixmap)

    def _clear_qr(self):
        self._countdown.stop()
        self._qr_image = QImage()
        self._qr_request = None
        self._qr_acknowledged = False
        self.qr_label.clear()
        self.countdown_label.clear()

    def _clear_secrets(self):
        self._clear_qr()
        self.pairing_code.clear()

    def _tick(self):
        remaining = max(0, math.ceil(self._scan_deadline - time.monotonic()))
        self.countdown_label.setText(f"{remaining // 60}:{remaining % 60:02}")
        self.countdown_label.setAccessibleName(
            tr("二维码将在 {time} 后过期").format(time=self.countdown_label.text())
        )
        if remaining == 0:
            self._clear_qr()
        self._schedule_reflow()

    def _cycle_page(self, step):
        self.request_page(
            self.PAGES[(self.PAGES.index(self.current_page) + step) % len(self.PAGES)]
        )

    def _schedule_reflow(self):
        if not self._reflow_pending:
            self._reflow_pending = True
            QTimer.singleShot(0, self._reflow)

    def _status_text_size(self, text, width, height):
        metrics = self.status_label.fontMetrics()
        text_width = min(width, max(1, metrics.horizontalAdvance(text)))
        bounds = metrics.boundingRect(
            QRect(0, 0, text_width, 10000), Qt.TextFlag.TextWordWrap, text
        )
        return QSize(text_width, max(height, bounds.height()))

    def _normal_qr_status_height(self, width, control_height):
        """正常扫码提示按实际字体换行；只预留常规操作行，不预留错误或续连表单。"""
        metrics = self.refresh_button.fontMetrics()
        padding = self.refresh_button.sizeHint().width() - metrics.horizontalAdvance(
            self.refresh_button.text()
        )
        refresh_width = padding + max(
            metrics.horizontalAdvance(tr(text)) for text in ("生成二维码", "刷新二维码")
        )
        sizes = (
            self._status_text_size(tr("等待手机扫码"), width, control_height),
            QSize(self.countdown_label.fontMetrics().horizontalAdvance("0:00"), control_height),
            QSize(refresh_width, control_height),
            QSize(self.cancel_button.sizeHint().width(), control_height),
        )
        x, total, row_height = 0, 0, 0
        for size in sizes:
            if x and x + size.width() > width:
                total += row_height + 10
                x, row_height = 0, 0
            x += size.width() + 10
            row_height = max(row_height, size.height())
        return total + row_height

    def _reflow(self):
        """断点使用实际可用宽度；字号增大时提前换行，三页按自然高度共用空间。"""
        self._reflow_pending = False
        if not hasattr(self, "address_form"):
            return
        margins = self.stack.contentsMargins()
        width = max(1, self.width() - margins.left() - margins.right())
        status_height = max(32, self.refresh_button.fontMetrics().height() + 16)
        compact = (
            width <= 440 or width < 196 + self.fontMetrics().horizontalAdvance("无线调试连接") + 48
        )
        qr_spacing = 12 if compact else (16 if width <= 580 else 24)
        qr_text_width = width if compact else max(1, width - 196 - qr_spacing)
        normal_status_height = self._normal_qr_status_height(qr_text_width, status_height)
        active_status_width = qr_text_width if self.current_page == "qr" else width
        label_size = self._status_text_size(
            self.status_label.text(), active_status_width, status_height
        )
        self.status_label.setFixedSize(label_size)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.countdown_label.setFixedHeight(status_height)
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.qr_status_slot.setMinimumHeight(normal_status_height)
        self.qr_status_slot.setMaximumHeight(
            16777215 if self.current_page == "qr" else normal_status_height
        )
        self.manual_status_slot.setMinimumHeight(status_height)
        self.manual_status_slot.setMaximumHeight(
            16777215 if self.current_page == "manual" else status_height
        )
        self.qr_columns.setDirection(
            QBoxLayout.Direction.BottomToTop if compact else QBoxLayout.Direction.LeftToRight
        )
        self.qr_columns.setSpacing(qr_spacing)
        for widget in (self.address_field, self.code_field, self.pair_button):
            self.manual_fields.removeWidget(widget)
        for column in range(3):
            self.manual_fields.setColumnStretch(column, 0)
        code_width = max(140, self.pairing_code.fontMetrics().horizontalAdvance("000000") + 44)
        if width <= 440 or width < code_width + 180:
            self.manual_fields.addWidget(self.address_field, 0, 0)
            self.manual_fields.addWidget(self.code_field, 1, 0)
            self.manual_fields.addWidget(self.pair_button, 2, 0)
            self.manual_fields.setColumnStretch(0, 1)
        elif width <= 580 or width < code_width + self.pair_button.sizeHint().width() + 200:
            self.manual_fields.addWidget(self.address_field, 0, 0)
            self.manual_fields.addWidget(self.code_field, 0, 1)
            self.manual_fields.addWidget(self.pair_button, 1, 0, 1, 2)
            self.manual_fields.setColumnStretch(0, 3)
            self.manual_fields.setColumnStretch(1, 2)
        else:
            self.manual_fields.addWidget(self.address_field, 0, 0)
            self.manual_fields.addWidget(self.code_field, 0, 1)
            self.manual_fields.addWidget(self.pair_button, 0, 2, Qt.AlignmentFlag.AlignBottom)
            self.manual_fields.setColumnStretch(0, 3)
            self.manual_fields.setColumnStretch(1, 2)
        self.address_form.reflow(width)
        self.navigation.refresh_mode()
        for layout in reversed(list(self.stack.findChildren(QLayout))):
            layout.invalidate()
        stack_layout = self.stack.layout()
        assert stack_layout is not None
        stack_layout.invalidate()
        self._layout.invalidate()
        if self._expanded:
            height = self.stack.heightForWidth(self.width())
            self.stack.setFixedHeight(height)
            self.setFixedHeight(
                height
                + self.navigation.sizeHint().height()
                + self._layout.spacing()
                + self._layout.contentsMargins().bottom()
            )
            self._layout.activate()
        self._render_qr()
        self.updateGeometry()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QColor(BaseStyles.color("BORDER_COLOR")))
        painter.drawLine(14, self.height() - 1, self.width() - 14, self.height() - 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_reflow()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self._render_qr()
        return super().eventFilter(watched, event)

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, "_qr_image"):
            self._render_qr()
        return result

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._expanded:
            self.collapse()

    def prepare_shutdown(self):
        """应用监督器接管取消和等待；视图只清空秘密、停止视觉更新并关闭准入。"""
        self._shutting_down = True
        self._pending_page = None
        self._pending_refresh = False
        self._clear_secrets()
        self.progress_ring.stop()
        self.setEnabled(False)

    def closeEvent(self, event):
        self.collapse()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.collapse()
            event.accept()
            return
        super().keyPressEvent(event)
