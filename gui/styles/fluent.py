"""qfluentwidgets 参考控件的项目级度量与可访问性配置。

本模块只配置第三方或 Qt 控件实例，不定义控件子类。这样既保留 ADBLab 的可缩放
字体、键盘焦点和功能提示契约，也避免再次形成一套与 qfluentwidgets 并行的组件库。
"""

from __future__ import annotations

from collections.abc import Callable
from types import MethodType
from typing import TypeVar

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QColor, QFocusEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)
from qfluentwidgets import (
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SmoothMode,
    ToolButton,
    setCustomStyleSheet,
)

from gui.i18n import tr
from gui.styles.fonts import FontMixin
from gui.styles.icon_loader import cached_fluent_icon
from gui.styles.material import ensure_material_observer, is_mica_active
from gui.styles.theme import ThemeMixin
from gui.styles.typography import FontRole
from gui.widgets.settings_scroll import SettingsWheelScroll
from gui.widgets.transient_menu import TransientMenuFocusGuard

_WidgetT = TypeVar("_WidgetT", bound=QWidget)
_ButtonT = TypeVar("_ButtonT", bound=QAbstractButton)
_ScrollT = TypeVar("_ScrollT", bound=QAbstractScrollArea)


def _fluent_scroll_delegate(area: QWidget):
    """兼容 Fluent 的三种滚动代理字段，避免误认 ListWidget 的绘制 delegate。"""
    return next((
        candidate for name in ("scrollDelagate", "scrollDelegate", "delegate")
        if (candidate := getattr(area, name, None)) is not None
        and hasattr(candidate, "verticalSmoothScroll")
    ), None)


def use_instant_scroll(area: _WidgetT) -> _WidgetT:
    """关闭 Fluent 的默认缓动，供专用视图或局部滚轮控制器接管输入。"""

    setter = getattr(area, "setScrollAnimation", None)
    if callable(setter):
        setter(Qt.Orientation.Vertical, 0)
        setter(Qt.Orientation.Horizontal, 0)
        return area
    smooth_setter = getattr(area, "setSmoothMode", None)
    if callable(smooth_setter):
        smooth_setter(SmoothMode.NO_SMOOTH, Qt.Orientation.Vertical)
        smooth_setter(SmoothMode.NO_SMOOTH, Qt.Orientation.Horizontal)
    delegate = _fluent_scroll_delegate(area)
    if delegate is not None:
        delegate.vScrollBar.setScrollAnimation(0)
        delegate.hScrollBar.setScrollAnimation(0)
    return area


def use_smooth_scroll(area: _ScrollT) -> _ScrollT:
    """像素视图复用局部高刷滚轮；按行文本保留原生步长，重复安装不叠加时钟。

    只替换普通垂直鼠标刻度。触控板、水平滚动、修饰键、选区和外部定位仍交给
    原控件；图片查看器的缩放/翻页不从此入口接入。
    """
    use_instant_scroll(area)
    delegate = _fluent_scroll_delegate(area)
    if delegate is not None:
        # useAni=False 的表格和文本使用另一套引擎，仅将覆盖滚条时长设为零并不能停掉它。
        for engine in (delegate.verticalSmoothScroll, delegate.horizonSmoothScroll):
            engine.setSmoothMode(SmoothMode.NO_SMOOTH)
        delegate.vScrollBar.setScrollAnimation(0)
        delegate.hScrollBar.setScrollAnimation(0)
    if isinstance(area, QPlainTextEdit) or (
        isinstance(area, QAbstractItemView)
        and area.verticalScrollMode() != QAbstractItemView.ScrollMode.ScrollPerPixel
    ):
        return area
    controller = area.findChild(
        SettingsWheelScroll, "adblabWheelScroll", Qt.FindChildOption.FindDirectChildrenOnly,
    )
    if controller is None:
        controller = SettingsWheelScroll(area, delegate.vScrollBar if delegate else None)
    # SettingsPage 的关闭边界及历史调用仍可通过原字段访问同一控制器。
    setattr(area, "_wheel_scroll", controller)
    return area


def font_qss(font: QFont) -> str:
    """把项目 QFont 转为可覆盖第三方显式字体 QSS 的声明。"""

    family = font.family().replace("\\", "\\\\").replace("'", "\\'")
    if font.pointSizeF() > 0:
        size = f"{font.pointSizeF():g}pt"
    else:
        size = f"{max(1, font.pixelSize())}px"
    style = "italic" if font.italic() else "normal"
    return (
        f"font-family: '{family}'; font-size: {size}; "
        f"font-weight: {int(font.weight())}; font-style: {style};"
    )


def _font(role: FontRole | str, *, bold: bool = False) -> QFont:
    resolved = FontRole(role)
    # 通过 BaseStyles 取字体，确保运行时字号/字体覆盖与主题配置一致；
    # 直接调用 FontMixin 会绕过派生类的配置入口。
    from gui.styles import BaseStyles

    font = BaseStyles.font_for_role(resolved)
    if bold:
        font.setBold(True)
    return font


def apply_font_role(
    widget: _WidgetT,
    role: FontRole | str = FontRole.UI,
    *,
    bold: bool = False,
    ensure_height: bool = False,
) -> _WidgetT:
    """把项目字体角色应用到现有控件，并按需解除第三方固定像素高度。"""

    resolved = FontRole(role)
    widget.setFont(_font(resolved, bold=bold))
    widget.setProperty("fontRole", resolved.value)
    if ensure_height:
        safe_height = max(
            FontMixin.control_height(role=resolved),
            widget.minimumSizeHint().height(),
        )
        if widget.minimumHeight() == widget.maximumHeight() or widget.maximumHeight() < safe_height:
            widget.setFixedHeight(safe_height)
        else:
            widget.setMinimumHeight(safe_height)
    return widget


def apply_label_role(
    label: _WidgetT,
    role: FontRole | str = FontRole.UI,
    *,
    color_key: str = "TEXT_PRIMARY",
    bold: bool = False,
) -> _WidgetT:
    """配置 qfluentwidgets 标签的字体与明暗主题文字色。"""

    apply_font_role(label, role, bold=bold)
    set_text_color = getattr(label, "setTextColor", None)
    if callable(set_text_color):
        set_text_color(
            QColor(ThemeMixin.color_for("Light", color_key)),
            QColor(ThemeMixin.color_for("Dark", color_key)),
        )
    return label


def set_function_tooltip(widget: QWidget, tooltip: str | None) -> None:
    """保存功能提示与可访问描述；交互按钮不允许缺少提示。"""

    description = tr(str(tooltip or "").strip())
    if not description:
        raise ValueError("Interactive controls must provide a functional tooltip")
    widget.setToolTip(description)
    widget.setAccessibleDescription(description)
    widget.setProperty("functionalToolTip", description)


class _KeyboardFocusObserver(QObject):
    """随控件销毁的焦点来源观察器，不改变键盘导航或鼠标事件的业务路由。"""

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)
        self.setObjectName("adblabKeyboardFocusObserver")
        widget.setProperty("adblabKeyboardFocus", False)
        widget.installEventFilter(self)
        if isinstance(widget, QAbstractItemView):
            widget.viewport().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        owner = self.parent()
        if isinstance(owner, QAbstractItemView) and watched is owner.viewport():
            watched = owner
        if not isinstance(watched, QWidget) or not watched.property("adblabKeyboardFocusOnly"):
            return super().eventFilter(watched, event)
        keyboard = None
        if event.type() == QEvent.Type.FocusIn and isinstance(event, QFocusEvent):
            keyboard = event.reason() in (
                Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                Qt.FocusReason.ShortcutFocusReason,
            )
        elif event.type() == QEvent.Type.MouseButtonPress:
            keyboard = False
        elif event.type() == QEvent.Type.KeyPress:
            keyboard = True
        if keyboard is not None and watched.property("adblabKeyboardFocus") != keyboard:
            minimum, maximum = watched.minimumSize(), watched.maximumSize()
            watched.setProperty("adblabKeyboardFocus", keyboard)
            if isinstance(watched, QAbstractItemView):
                # Windows Fluent 表格持有独立原生样式，手工 unpolish 会触发原生崩溃。
                # 重用已合成的 QSS 只重新计算选择器，保留主题、字体与注册来源。
                watched.setStyleSheet(watched.styleSheet())
            else:
                watched.style().unpolish(watched)
                watched.style().polish(watched)
            # Fluent 复选框 QSS 自带最小尺寸；刷新焦点不能覆盖字号和行布局的约束。
            watched.setMinimumSize(minimum)
            watched.setMaximumSize(maximum)
            if isinstance(watched, QAbstractItemView):
                QWidget.update(watched)
            else:
                watched.update()
        return super().eventFilter(watched, event)


def apply_focus_indicator(
    widget: QWidget, *, selector: str | None = None, keyboard_only: bool = False,
    content_qss: str | None = None,
) -> None:
    """合成焦点和局部内容样式；内容规则在主题、强调色和字体刷新后保留。

    ``content_qss=None`` 沿用原规则，空字符串清除规则；keyboard_only 仅显示键盘焦点。
    """

    name = selector or type(widget).__name__
    widget.setProperty("adblabFocusSelector", name)
    widget.setProperty("adblabKeyboardFocusOnly", keyboard_only)
    if content_qss is not None:
        widget.setProperty("adblabContentQss", content_qss)
    if widget.property("adblabReadingSurface") and isinstance(widget, (QPlainTextEdit, QTextEdit)):
        from gui.styles.reading_surface import ensure_reading_surface

        ensure_reading_surface(widget)
        return
    light = ThemeMixin.color_for("Light", "BORDER_FOCUS")
    dark = ThemeMixin.color_for("Dark", "BORDER_FOCUS")
    radius = ThemeMixin.RADIUS_MD
    base = ""
    focus_selector = name
    if keyboard_only:
        observer = widget.findChild(
            _KeyboardFocusObserver, "adblabKeyboardFocusObserver",
            Qt.FindChildOption.FindDirectChildrenOnly,
        )
        if observer is None:
            _KeyboardFocusObserver(widget)
        focus_selector += '[adblabKeyboardFocus="true"]'
        # 预留相同边宽，鼠标与键盘切换不能改变文字位置或挤动相邻按钮。
        base = f"{name} {{ border: 2px solid transparent; border-radius: {radius}px; }}"
    setCustomStyleSheet(
        widget,
        base + f"{focus_selector}:focus {{ border: 2px solid {light}; border-radius: {radius}px; }}"
        + str(widget.property("adblabFontQss") or "")
        + str(widget.property("adblabContentQss") or ""),
        base + f"{focus_selector}:focus {{ border: 2px solid {dark}; border-radius: {radius}px; }}"
        + str(widget.property("adblabFontQss") or "")
        + str(widget.property("adblabContentQss") or ""),
    )


def set_fluent_font_rule(widget: QWidget, rule: str) -> None:
    """保存局部字号声明，统一刷新时与焦点及材质合成，避免相互覆盖。"""
    widget.setProperty("adblabFontQss", rule)
    refresh_fluent_widget_style(widget)
    if not widget.property("adblabConfiguredButton") and not widget.property("adblabFocusSelector"):
        setCustomStyleSheet(widget, rule, rule)


def apply_reading_surface(widget: _WidgetT) -> _WidgetT:
    """只读长正文跟随宿主云母；编辑状态与关闭云母时使用 Fluent 原生表面。

    不改变正文内容、字体、只读属性或选择复制能力；重复应用复用同一控制器。
    """
    if not isinstance(widget, (QPlainTextEdit, QTextEdit)):
        raise TypeError("阅读表面仅支持 QPlainTextEdit 和 QTextEdit")
    from gui.styles.reading_surface import ensure_reading_surface

    selector = widget.property("adblabFocusSelector")
    widget.setProperty("adblabFocusSelector", str(selector) if selector else type(widget).__name__)
    ensure_reading_surface(widget)
    use_smooth_scroll(widget)
    return widget


def _apply_button_custom_style(button: QAbstractButton, *, danger: bool) -> None:
    """重建按钮的项目级焦点和危险态 QSS，确保主题与强调色即时生效。"""

    selector = type(button).__name__
    light_focus = ThemeMixin.color_for("Light", "BORDER_FOCUS")
    dark_focus = ThemeMixin.color_for("Dark", "BORDER_FOCUS")
    radius = ThemeMixin.RADIUS_MD
    font_rule = str(button.property("adblabFontQss") or "")

    def finish(style: str, theme: str) -> str:
        if is_mica_active(button) and (isinstance(button, PrimaryPushButton) or danger):
            dark = theme == "Dark"
            background = "rgba(255, 255, 255, 0.0419)" if dark else "rgba(249, 249, 249, 0.3)"
            text = "rgba(255, 255, 255, 0.3628)" if dark else "rgba(0, 0, 0, 0.36)"
            border = "rgba(255, 255, 255, 0.053)" if dark else "rgba(0, 0, 0, 0.06)"
            style += (
                f"{selector}:disabled {{ background: {background}; color: {text}; "
                f"border: 1px solid {border}; }}"
            )
        return style + font_rule
    if danger:

        def danger_qss(theme: str, focus_color: str) -> str:
            background = ThemeMixin.color_for(theme, "BUTTON_DANGER")
            hover = ThemeMixin.color_for(theme, "BUTTON_DANGER_HOVER")
            disabled = ThemeMixin.color_for(theme, "INPUT_BG")
            disabled_text = ThemeMixin.color_for(theme, "TEXT_DISABLED")
            border = ThemeMixin.color_for(theme, "BORDER_COLOR")
            return (
                f"{selector} {{ color: white; background: {background}; "
                f"border: 1px solid {background}; border-radius: {radius}px; }}"
                f"{selector}:hover {{ background: {hover}; }}"
                f"{selector}:focus {{ border: 2px solid {focus_color}; }}"
                f"{selector}:disabled {{ color: {disabled_text}; background: {disabled}; "
                f"border-color: {border}; }}"
            )

        setCustomStyleSheet(
            button,
            finish(danger_qss("Light", light_focus), "Light"),
            finish(danger_qss("Dark", dark_focus), "Dark"),
        )
        return

    setCustomStyleSheet(
        button,
        finish(
            f"{selector}:focus {{ border: 2px solid {light_focus}; border-radius: {radius}px; }}",
            "Light",
        ),
        finish(
            f"{selector}:focus {{ border: 2px solid {dark_focus}; border-radius: {radius}px; }}",
            "Dark",
        ),
    )


def refresh_fluent_widget_style(widget: QWidget) -> None:
    """强调色变化后刷新项目注入的 widget 级 QSS，不改动控件业务状态。"""

    if isinstance(widget, QAbstractButton) and bool(
        widget.property("adblabConfiguredButton")
    ):
        _apply_button_custom_style(
            widget,
            danger=widget.property("buttonVariant") == "danger",
        )
        return
    selector = widget.property("adblabFocusSelector")
    if selector:
        apply_focus_indicator(
            widget, selector=str(selector),
            keyboard_only=bool(widget.property("adblabKeyboardFocusOnly")),
        )


def configure_fluent_control(
    widget: _WidgetT,
    role: FontRole | str = FontRole.UI,
    *,
    focus: bool = True,
    ensure_height: bool = True,
) -> _WidgetT:
    """统一配置直接使用的 qfluentwidgets 控件。"""

    apply_font_role(widget, role, ensure_height=ensure_height)
    if focus:
        apply_focus_indicator(widget)
    from gui.styles.combo_menu import configure_combo_menu

    configure_combo_menu(widget)
    return widget


def _refresh_button_material(widget: QWidget, _mica: bool) -> None:
    """材质变化仅重建本按钮的样式，不更改业务启用状态。"""
    if isinstance(widget, QAbstractButton):
        _apply_button_custom_style(widget, danger=widget.property("buttonVariant") == "danger")


def _draw_material_icon(button, icon, painter, rect, state=QIcon.State.Off):
    """半透明禁用主按钮沿用普通按钮图标，避免浅色材质上强制绘制白色图标。"""
    if not button.isEnabled() and is_mica_active(button):
        PushButton._drawIcon(button, icon, painter, rect, state)
    else:
        PrimaryPushButton._drawIcon(button, icon, painter, rect, state)


def configure_button(
    button: _ButtonT,
    *,
    text: str,
    tooltip: str | None,
    role: FontRole | str = FontRole.UI,
    danger: bool = False,
) -> _ButtonT:
    """配置直接使用的 qfluentwidgets 按钮；危险色使用 light/dark 自定义 QSS。"""

    button.setText(tr(text))
    if isinstance(button, (PushButton, ToolButton)):
        icon = cached_fluent_icon(button._icon)
        if icon is not button._icon:
            button.setIcon(icon)
    button.setAccessibleName(tr(text or str(tooltip or "")))
    set_function_tooltip(button, tooltip)
    apply_font_role(button, role, ensure_height=True)
    button.setProperty("adblabConfiguredButton", True)
    if danger:
        button.setProperty("buttonVariant", "danger")
    else:
        button.setProperty("buttonVariant", "")
    _apply_button_custom_style(button, danger=danger)
    if isinstance(button, PrimaryPushButton) or danger:
        ensure_material_observer(button, _refresh_button_material)
    if type(button) is PrimaryPushButton:
        button._drawIcon = MethodType(_draw_material_icon, button)
    return button


def create_transient_menu(parent: QWidget) -> RoundMenu:
    """创建关闭后释放的菜单；非阻塞 exec 返回时仍保留控件和动作。

    菜单私有动作可直接加入；页面共享 QAction 必须通过 add_shared_menu_action
    隔离第三方保存的菜单行指针，避免其它菜单在本菜单释放后访问悬空行。
    """
    menu = RoundMenu(parent=parent)
    menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    TransientMenuFocusGuard(menu)
    apply_font_role(menu)
    return menu


def add_menu_action(
    menu: RoundMenu,
    text: str,
    *,
    callback: Callable[[], object] | None = None,
    data: object | None = None,
    checkable: bool = False,
    checked: bool = False,
) -> QAction:
    """向 qfluentwidgets RoundMenu 添加带业务数据的 QAction。"""

    action = QAction(tr(text), menu)
    action.setData(data)
    action.setCheckable(checkable)
    action.setChecked(checked)
    if callback is not None:
        action.triggered.connect(lambda _checked=False, fn=callback: fn())
    menu.addAction(action)
    return action


__all__ = [
    "font_qss",
    "add_menu_action",
    "apply_focus_indicator",
    "apply_font_role",
    "apply_label_role",
    "apply_reading_surface",
    "configure_button",
    "configure_fluent_control",
    "create_transient_menu",
    "refresh_fluent_widget_style",
    "set_function_tooltip",
]
