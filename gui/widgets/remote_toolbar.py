"""提供只发出设备操作意图的投屏侧栏；目标绑定和外部窗口归属由调用方管理。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFocusEvent,
    QHideEvent,
    QKeyEvent,
    QMoveEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_font_role
from gui.styles.icon_loader import ResourceIcon, get_themed_icon


@dataclass(frozen=True)
class _Command:
    """沿用远程输入协议；标签和图标只负责界面呈现，不推导目标。"""

    label: str
    code: str
    icon: str
    is_key: bool = True


_COMMON = (
    _Command("返回", "BACK", "arrow-left.svg"),
    _Command("主页", "HOME", "house.svg"),
    _Command("最近", "RECENTS", "remote-recents.svg"),
    _Command("音量 +", "VOL_UP", "remote-volume-up.svg"),
    _Command("音量 −", "VOL_DOWN", "remote-volume-down.svg"),
    _Command("电源", "POWER", "power.svg"),
)
_MORE_GROUPS = (
    ("屏幕与通知", (
        _Command("竖屏", "rotate_portrait", "remote-portrait.svg", False),
        _Command("横屏", "rotate_landscape", "remote-landscape.svg", False),
        _Command("展开通知", "notif_expand", "remote-notification-expand.svg", False),
        _Command("收起通知", "notif_collapse", "remote-notification-collapse.svg", False),
    )),
    ("滑动手势", (
        _Command("上滑", "swipe_up", "arrow-up.svg", False),
        _Command("下滑", "swipe_down", "arrow-down.svg", False),
        _Command("左滑", "swipe_left", "arrow-left.svg", False),
        _Command("右滑", "swipe_right", "arrow-right.svg", False),
    )),
    ("系统操作", (
        _Command("菜单", "MENU", "list.svg"),
        _Command("回车", "ENTER", "remote-enter.svg"),
        _Command("退格", "DEL", "remote-backspace.svg"),
        _Command("设置", "SETTINGS", "gear.svg"),
        _Command("相机", "CAMERA", "camera.svg"),
        _Command("搜索", "SEARCH", "magnifying-glass.svg"),
    )),
    ("媒体控制", (
        _Command("上一个", "MEDIA_PREV", "remote-media-prev.svg"),
        _Command("播放/暂停", "MEDIA_PLAY", "remote-play-pause.svg"),
        _Command("下一个", "MEDIA_NEXT", "remote-media-next.svg"),
    )),
)


def _paint_floating_surface(widget: QWidget) -> None:
    """透明顶层显式绘制 QSS 表面，保留主题底色且不填满四角透明区域。"""
    option = QStyleOption()
    option.initFrom(widget)
    painter = QPainter(widget)
    try:
        widget.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, widget)
    finally:
        painter.end()


class _ButtonFocusFilter(QObject):
    """仅跟踪所属按钮的输入方式，让鼠标反馈与键盘焦点提示分开呈现。"""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not isinstance(watched, QAbstractButton):
            return False
        if isinstance(event, QFocusEvent) and event.type() == QEvent.Type.FocusIn:
            visible = event.reason() in (
                Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                Qt.FocusReason.ShortcutFocusReason,
            )
        elif event.type() == QEvent.Type.KeyPress:
            visible = True
        elif event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.FocusOut):
            visible = False
        else:
            return False
        if watched.property("remoteKeyboardFocus") != visible:
            watched.setProperty("remoteKeyboardFocus", visible)
            watched.style().unpolish(watched)
            watched.style().polish(watched)
            watched.update()
        return False


class _MorePopup(QFrame):
    """更多面板属于侧栏；关闭或 Escape 只收起面板，不结束投屏会话。"""

    dismissed = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("remoteToolbarPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event: QPaintEvent) -> None:
        _paint_floating_surface(self)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self.dismissed.emit()
        super().hideEvent(event)


class RemoteToolbar(QWidget):
    """单个会话的紧凑操作入口，不查询设备或管理 scrcpy 窗口。

    调用方负责按固定会话目标解释信号，并提供不含设备标识的友好标签。侧栏初始不可用；
    目标失效时调用 ``set_available(False)``，释放时调用幂等的 ``dispose()``。
    浮窗显示不激活应用，设备命令交由所属会话处理。
    """

    key_requested = Signal(str)
    action_requested = Signal(str)
    layout_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("remoteToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowTitle(tr("设备操作"))
        self.setAccessibleName(tr("设备操作"))
        self._available = False
        self._disposed = False
        self._collapsed = False
        self._watching_application = False
        self._target_label = tr("当前投屏设备")
        self._commands: dict[str, tuple[_Command, QToolButton | QPushButton]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 7, 5, 7)
        layout.setSpacing(4)
        self._indicator = QLabel("•", self)
        self._indicator.setObjectName("remoteToolbarIndicator")
        self._indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._indicator.setFixedHeight(12)
        layout.addWidget(self._indicator)
        self._common_buttons = []
        for command in _COMMON:
            button = self._make_button(command, self, compact=True)
            self._common_buttons.append(button)
            layout.addWidget(button)
        self._more_button = QToolButton(self)
        self._more_button.setObjectName("remoteToolbarMore")
        self._more_button.setCheckable(True)
        self._more_button.setIconSize(QSize(20, 20))
        self._more_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._more_button.setFixedSize(44, 38)
        self._more_button.clicked.connect(self._toggle_popup)
        layout.addWidget(self._more_button)
        self._collapse_button = QToolButton(self)
        self._collapse_button.setObjectName("remoteToolbarCollapse")
        self._collapse_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._collapse_button.setIconSize(QSize(20, 20))
        self._collapse_button.setFixedSize(44, 28)
        self._collapse_button.clicked.connect(self._toggle_collapsed)
        layout.addWidget(self._collapse_button)
        self.setFixedWidth(56)

        self._popup = _MorePopup(self)
        self._popup.dismissed.connect(self._popup_dismissed)
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(14, 12, 14, 12)
        popup_layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel(tr("更多操作"), self._popup)
        title.setObjectName("remoteToolbarHeading")
        header.addWidget(title)
        header.addStretch()
        close_button = QToolButton(self._popup)
        close_button.setIcon(get_themed_icon("x.svg"))
        close_button.setToolTip(tr("关闭更多操作"))
        close_button.setAccessibleName(tr("关闭更多操作"))
        close_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        close_button.clicked.connect(self.dismiss_popup)
        header.addWidget(close_button)
        popup_layout.addLayout(header)
        self._target = QLabel(self._target_label, self._popup)
        self._target.setObjectName("remoteToolbarTarget")
        self._target.setTextFormat(Qt.TextFormat.PlainText)
        self._target.setWordWrap(True)
        popup_layout.addWidget(self._target)
        scroll = QScrollArea(self._popup)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._popup_content = QWidget(scroll)
        content_layout = QVBoxLayout(self._popup_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        # 滚动内容保留全部分组的自然下限；可用高度不足时滚动，不压缩操作行。
        content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._group_grids: list[QGridLayout] = []
        for heading, commands in _MORE_GROUPS:
            label = QLabel(tr(heading), self._popup_content)
            label.setObjectName("remoteToolbarGroup")
            content_layout.addWidget(label)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)
            for index, command in enumerate(commands):
                grid.addWidget(
                    self._make_button(command, self._popup_content), index // 2, index % 2,
                )
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            self._group_grids.append(grid)
            content_layout.addLayout(grid)
        content_layout.addStretch()
        scroll.setWidget(self._popup_content)
        self._popup_scroll = scroll
        popup_layout.addWidget(scroll, 1)
        self._button_focus_filter = _ButtonFocusFilter(self)
        for button in self.findChildren(QAbstractButton):
            button.installEventFilter(self._button_focus_filter)

        BaseStyles.theme_changed.connect(self._refresh_style)
        BaseStyles.accent_color_changed.connect(self._refresh_style)
        BaseStyles.fonts_changed.connect(self._refresh_style)
        self._refresh_style()
        self.set_available(False)
        self.adjustSize()

    @property
    def collapsed(self) -> bool:
        """返回用户选择的收起状态，不随暂时隐藏或目标可用性变化。"""
        return self._collapsed

    @property
    def popup_window(self) -> QWidget:
        """向宿主提供同属此会话的工具窗，供原生窗口归属设置使用。"""
        return self._popup

    def set_target_label(self, text: str) -> None:
        """显示调用方已脱敏的友好设备名；不接受 HTML，也不据此解析设备目标。"""
        if self._disposed:
            return
        self._target_label = " ".join(str(text).split())[:80] or tr("当前投屏设备")
        self._target.setText(self._target_label)
        self._target.setToolTip(self._target_label)
        self.setAccessibleDescription(self._target_label)
        self._refresh_tooltips()
        if self._popup.isVisible():
            self._position_popup()

    def set_available(self, available: bool) -> None:
        """关闭操作准入时同时收起面板；收起按钮仍可用于管理侧栏外观。"""
        self._available = bool(available) and not self._disposed
        for _command, button in self._commands.values():
            button.setEnabled(self._available)
        self._more_button.setEnabled(self._available)
        if not self._available:
            self.dismiss_popup()
        self._refresh_tooltips()

    @Slot()
    def dismiss_popup(self) -> None:
        """只关闭本侧栏的更多面板，不改变会话、目标或侧栏收起状态。"""
        self._popup.hide()
        self._popup_dismissed()

    def dispose(self) -> None:
        """停止信号准入并断开全局样式订阅；QObject 的销毁仍由宿主负责。"""
        if self._disposed:
            return
        self._disposed = True
        self.set_available(False)
        self.hide()
        BaseStyles.theme_changed.disconnect(self._refresh_style)
        BaseStyles.accent_color_changed.disconnect(self._refresh_style)
        BaseStyles.fonts_changed.disconnect(self._refresh_style)

    def _make_button(
        self, command: _Command, parent: QWidget, *, compact: bool = False,
    ) -> QToolButton | QPushButton:
        button = QToolButton(parent) if compact else QPushButton(tr(command.label), parent)
        button.setObjectName(f"remoteToolbarCommand_{command.code}")
        button.setProperty("remoteKey" if command.is_key else "remoteAction", command.code)
        button.setAccessibleName(tr(command.label))
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIconSize(QSize(20 if compact else 18, 20 if compact else 18))
        if compact:
            button.setFixedSize(44, 40)
        else:
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda _checked=False, item=command: self._request(item))
        self._commands[command.code] = (command, button)
        return button

    def _request(self, command: _Command) -> None:
        if self._disposed or not self._available:
            return
        # 保留面板供连续操作；下游可能同步释放侧栏，发出信号后不再访问控件。
        if command.is_key:
            self.key_requested.emit(command.code)
        else:
            self.action_requested.emit(command.code)

    def _refresh_tooltips(self) -> None:
        for command, button in self._commands.values():
            tooltip = tr("{action}（作用于{target}）").format(
                action=tr(command.label), target=self._target_label,
            ) if self._available else tr("当前投屏设备不可用")
            if command.code == "POWER" and self._available:
                tooltip += "\n" + tr("点按电源键，切换屏幕开关")
            button.setToolTip(tooltip)
            button.setAccessibleDescription(tooltip)

    @Slot()
    def _toggle_popup(self) -> None:
        if self._disposed or not self._available or self._collapsed:
            self.dismiss_popup()
            return
        if self._popup.isVisible():
            self.dismiss_popup()
            return
        self._position_popup()
        app = QApplication.instance()
        if app is not None and not self._watching_application:
            app.installEventFilter(self)
            self._watching_application = True
        self._popup.show()
        self._sync_more_button()

    def _sync_more_button(self) -> None:
        opened = self._popup.isVisible()
        self._more_button.setChecked(opened)
        self._more_button.setIcon(
            get_themed_icon("x.svg") if opened else FluentIcon.MORE.qicon(),
        )
        text = tr("关闭更多操作" if opened else "更多设备操作")
        self._more_button.setToolTip(text)
        self._more_button.setAccessibleName(text)
        self._more_button.setAccessibleDescription(text)

    @Slot()
    def _popup_dismissed(self) -> None:
        self._sync_more_button()
        app = QApplication.instance()
        if app is not None and self._watching_application:
            app.removeEventFilter(self)
            self._watching_application = False

    @Slot()
    def _toggle_collapsed(self) -> None:
        if self._disposed:
            return
        self.dismiss_popup()
        self._collapsed = not self._collapsed
        for widget in (self._indicator, *self._common_buttons, self._more_button):
            widget.setVisible(not self._collapsed)
        self.setFixedWidth(32 if self._collapsed else 56)
        self._collapse_button.setFixedWidth(20 if self._collapsed else 44)
        self._update_collapse_label()
        self.adjustSize()
        self.layout_changed.emit()

    def _update_collapse_label(self) -> None:
        self._collapse_button.setIcon(ResourceIcon(
            "caret-double-down.svg" if self._collapsed else "caret-double-up.svg",
        ).qicon())
        text = tr("展开侧栏" if self._collapsed else "收起侧栏")
        self._collapse_button.setToolTip(text)
        self._collapse_button.setAccessibleName(text)

    def _position_popup(self) -> None:
        bounds = self.screen().availableGeometry()
        frame = self.frameGeometry()
        width = min(max(280, self._popup_content.sizeHint().width() + 48), bounds.width())
        height = min(self._popup_content.sizeHint().height() + 100, bounds.height() - 16)
        self._popup.resize(width, max(120, height))
        x = frame.right() + 9
        if x + width > bounds.right() + 1:
            x = frame.left() - width - 8
        x = max(bounds.left(), min(x, bounds.right() - width + 1))
        y = max(bounds.top(), min(frame.top(), bounds.bottom() - self._popup.height() + 1))
        self._popup.move(x, y)

    @Slot()
    def _refresh_style(self) -> None:
        if self._disposed:
            return
        foreground = BaseStyles.color("TEXT_PRIMARY")
        secondary = BaseStyles.color("TEXT_SECONDARY")
        background = BaseStyles.color("TOOLBAR_BG")
        border = BaseStyles.color("BORDER_COLOR")
        hover = BaseStyles.color("BUTTON_HOVER")
        pressed = BaseStyles.color("BUTTON_PRESSED")
        accent = BaseStyles.color("BORDER_FOCUS")
        # 展开态轻染当前强调色；不借用固定蓝色的全局文本选区颜色。
        selection = QColor(accent)
        selection.setAlphaF(0.24 if BaseStyles.resolved_theme() == "Dark" else 0.18)
        selected = (
            f"rgba({selection.red()}, {selection.green()}, {selection.blue()}, {selection.alpha()})"
        )
        disabled = BaseStyles.color("TEXT_DISABLED")
        scroll_background = BaseStyles.color("SCROLLBAR_BG")
        scroll_handle = BaseStyles.color("SCROLLBAR_HANDLE")
        scroll_hover = BaseStyles.color("SCROLLBAR_HANDLE_HOVER")
        style = f"""
        QWidget#remoteToolbar, QFrame#remoteToolbarPopup {{
            background: {background}; border: 1px solid {border}; border-radius: 10px;
        }}
        QLabel {{ color: {foreground}; background: transparent; border: none; }}
        QLabel#remoteToolbarTarget, QLabel#remoteToolbarGroup {{ color: {secondary}; }}
        QLabel#remoteToolbarIndicator {{ color: {accent}; }}
        QToolButton, QPushButton {{ color: {foreground}; background: transparent;
            border: 1px solid transparent; border-radius: 6px; padding: 4px; }}
        QToolButton#remoteToolbarCollapse {{ padding: 0; }}
        QPushButton {{ text-align: left; padding: 7px 9px; border-color: {border}; }}
        QToolButton:hover, QPushButton:hover {{ background: {hover}; border-color: {border}; }}
        QToolButton:pressed, QPushButton:pressed {{ background: {pressed}; }}
        QToolButton#remoteToolbarMore:checked {{ background: {selected}; }}
        QToolButton[remoteKeyboardFocus="true"]:focus,
        QPushButton[remoteKeyboardFocus="true"]:focus {{ border-color: {accent}; }}
        QToolButton:disabled, QPushButton:disabled {{ color: {disabled}; }}
        QScrollArea, QScrollArea > QWidget > QWidget {{ background: {background}; border: none; }}
        QScrollBar:vertical {{ background: {scroll_background}; width: 8px;
            margin: 0; border: none; border-radius: 4px; }}
        QScrollBar::handle:vertical {{ background: {scroll_handle};
            min-height: 24px; border-radius: 4px; }}
        QScrollBar::handle:vertical:hover {{ background: {scroll_hover}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0; border: none; background: transparent; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent; }}
        """
        self.setStyleSheet(style)
        self._popup.setStyleSheet(style)
        apply_font_role(self, FontRole.UI)
        apply_font_role(self._popup, FontRole.UI)
        for command, button in self._commands.values():
            apply_font_role(button, FontRole.UI)
            button.setIcon(get_themed_icon(command.icon))
            button.ensurePolished()
            button.updateGeometry()
        # 首次显示或字号变化时，嵌套网格仍可能保留旧样式的尺寸缓存。
        # 在计算浮窗尺寸前同步自然下限，避免首帧把系统操作三行挤成图标高度。
        for grid in self._group_grids:
            grid.invalidate()
        content_layout = self._popup_content.layout()
        assert content_layout is not None
        content_layout.invalidate()
        content_layout.activate()
        self._sync_more_button()
        self._update_collapse_label()
        self.adjustSize()
        if self._popup.isVisible():
            self._position_popup()
        self.layout_changed.emit()

    def eventFilter(self, watched, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            # QWidget 的祖先判断止于顶层窗口；更多面板是独立 Tool，须单独认领。
            # 否则内部按下会提前隐藏弹层，原生释放事件无法再交回原按钮。
            if watched.window() not in (self, self._popup):
                self.dismiss_popup()
        elif event.type() == QEvent.Type.ApplicationDeactivate:
            self.dismiss_popup()
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        _paint_floating_surface(self)

    def hideEvent(self, event: QHideEvent) -> None:
        self.dismiss_popup()
        super().hideEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.dismiss_popup()
        super().changeEvent(event)

    def moveEvent(self, event: QMoveEvent) -> None:
        if self._popup.isVisible():
            self._position_popup()
        super().moveEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        if self._popup.isVisible():
            self._position_popup()
        super().resizeEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.dismiss_popup()
        super().closeEvent(event)
