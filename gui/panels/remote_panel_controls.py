"""把远程参数的既有下拉数据投影为原生 Fluent 选择器，保留配置与信号契约。"""

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    HorizontalSeparator,
    Pivot,
    PushButton,
    Slider,
    SwitchButton,
    TransparentTogglePushButton,
    VerticalSeparator,
    themeColor,
)

from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    apply_font_role,
    apply_label_role,
    configure_fluent_control,
    font_qss,
    set_fluent_font_rule,
    set_function_tooltip,
)
from gui.styles.material import ensure_material_observer


def _refresh_session_surface(widget: QWidget, mica: bool) -> None:
    """会话底板随实际宿主材质更新；半透明色沿用原生 Fluent 卡片。"""
    dark = BaseStyles.resolved_theme() == "Dark"
    background = (
        f"rgba(255, 255, 255, {13 if dark else 170})" if mica
        else BaseStyles.color("PANEL_BG")
    )
    border = (
        "rgba(255, 255, 255, 28)" if dark else "rgba(0, 0, 0, 24)"
    ) if mica else BaseStyles.color("BORDER_COLOR")
    widget.setStyleSheet(
        "RemoteSection[remoteSectionSurface=true] {"
        f"background: {background}; border: 1px solid {border}; border-radius: 6px; }}"
    )


class RemoteWorkspaceDivider(VerticalSeparator):
    """双栏时分隔操作和参数；依据实际几何跟随回流，不占布局宽度。"""

    def __init__(self, parent: QWidget, sections: tuple[QWidget, ...]) -> None:
        super().__init__(parent)
        self.setObjectName("remoteWorkspaceDivider")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._sections = sections
        for section in sections:
            section.installEventFilter(self)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            left, right, *lower = (section.geometry() for section in self._sections)
            separate = right.left() > left.right() and abs(right.top() - left.top()) <= 2
            self.setVisible(separate)
            if separate:
                bottom = max(rect.bottom() for rect in (left, right, *lower))
                self.setGeometry(
                    (left.right() + right.left()) // 2 - 1, left.top(),
                    3, bottom - left.top() + 1,
                )
        return super().eventFilter(watched, event)


class RemoteSection(QWidget):
    """开放分区保留原有布局接口；仅会话区绘制底板，主题连接随控件销毁。"""

    def __init__(
        self, title: str, parent=None, *, surface: bool = False, divider: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setAccessibleName(title)
        self.setProperty("fontRole", FontRole.UI.value)
        self.setProperty("remoteSectionSurface", surface)
        self.headerView = QWidget(self)
        self.headerView.setMinimumHeight(36)
        self.headerView.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.headerLayout = QHBoxLayout(self.headerView)
        self.headerLayout.setContentsMargins(0, 0, 0, 0)
        self.headerLayout.setSpacing(12)
        self.headerLabel = BodyLabel(title, self.headerView)
        self.headerLabel.setWordWrap(True)
        apply_label_role(self.headerLabel, FontRole.UI, color_key="TITLE_COLOR", bold=True)
        self.headerLayout.addWidget(self.headerLabel)
        self.headerLayout.addStretch(1)
        self.view = QWidget(self)
        self.viewLayout = QVBoxLayout(self.view)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setSpacing(16)
        self.viewLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.vBoxLayout = QVBoxLayout(self)
        inset = 12 if surface else 0
        self.vBoxLayout.setContentsMargins(inset, inset, inset, inset)
        self.vBoxLayout.setSpacing(8)
        self.separator = HorizontalSeparator(self)
        if divider:
            self.vBoxLayout.addWidget(self.separator)
            self.vBoxLayout.addSpacing(8)
        else:
            self.separator.hide()
        self.vBoxLayout.addWidget(self.headerView)
        self.vBoxLayout.addWidget(self.view, 1)
        BaseStyles.fonts_changed.connect(self._refresh_header)
        if surface:
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            ensure_material_observer(self, _refresh_session_surface)

    @Slot()
    def _refresh_header(self) -> None:
        # 宿主先更新所有 fontRole 字体，此处恢复分区标题的强调并使隐藏页重新度量。
        apply_label_role(self.headerLabel, FontRole.UI, color_key="TITLE_COLOR", bold=True)
        self.headerLabel.updateGeometry()
        self.headerLayout.invalidate()
        self.headerLayout.activate()
        self.updateGeometry()

class RemoteWindowToggle(TransparentTogglePushButton):
    """透明选中态沿用普通图标配色，避免原生强调色底板的反色图标失去对比度。"""

    def _drawIcon(self, icon, painter, rect):
        PushButton._drawIcon(self, icon, painter, rect)


class RemoteSwitchButton(SwitchButton):
    """开关尺寸由响应式布局分配，状态文本更新不能自行缩回自然宽度。"""

    def setText(self, text: str) -> None:
        self._text = text
        self.label.setText(text)
        self.updateGeometry()

    def _updateText(self) -> None:
        # 原生实现两次 adjustSize 会在切换帧覆盖整行宽度，保留文本与度量更新即可。
        self.setText(self._onText if self.isChecked() else self._offText)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.indicator and event.type() in (
            QEvent.Type.FocusIn, QEvent.Type.FocusOut,
        ):
            # Indicator 自绘会绕过通用焦点边框，改用标签色调反馈且不改变文字度量。
            self.label.setProperty("remoteSwitchFocused", event.type() == QEvent.Type.FocusIn)
            self.label.style().unpolish(self.label)
            self.label.style().polish(self.label)
            self.label.update()
        return super().eventFilter(watched, event)


class _ParameterPivot(Pivot):
    """自定义参数没有预设归属，不能继续显示上一次预设的选中指示。"""

    def clear_selection(self) -> None:
        # 上游没有清空 API；同时清除路由和动画，保证再次点击同一个预设仍发出信号。
        self.slideAni.stop()
        self._currentRouteKey = None
        for item in self.items.values():
            item.setSelected(False)
        self.update()


class RemoteChoiceEditor(QWidget):
    """宽度足够时展开全部选项，窄窗使用同一下拉框；配置始终只有一个来源。"""

    def __init__(
        self, combo: ComboBox, parent: QWidget | None = None,
        *, prefer_combo: bool = False, separators: bool = False,
    ) -> None:
        super().__init__(parent)
        self._prefer_combo = prefer_combo
        self.combo = combo
        combo.setParent(self)
        self.pivot = _ParameterPivot(self)
        self.pivot.setAccessibleName(combo.accessibleName())
        self.pivot.hBoxLayout.setSpacing(6)
        self.pivot.setIndicatorLength(0)
        for index in range(combo.count()):
            value = str(combo.itemData(index))
            self.pivot.addItem(value, combo.itemText(index))
        if separators:
            for index in range(1, combo.count()):
                separator = VerticalSeparator(self.pivot)
                separator.setObjectName("remoteCommandSeparator")
                separator.setFixedHeight(14)
                self.pivot.hBoxLayout.insertWidget(
                    2 * index - 1, separator, 0, Qt.AlignmentFlag.AlignVCenter,
                )
        # 两种显示共用同一尺寸，切换不让父布局观察到双份高度或短暂空布局。
        self._layout = QStackedLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.pivot)
        self._layout.addWidget(combo)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pivot.currentItemChanged.connect(self._select)
        combo.currentIndexChanged.connect(self.sync_selection)
        self.refresh_metrics()
        self.sync_selection()

    def _select(self, key: str) -> None:
        self.combo.setCurrentIndex(self.combo.findData(key))

    def sync_selection(self, _index: int = -1) -> None:
        """程序加载和预设联动只更新投影，不重复触发配置保存。"""
        with QSignalBlocker(self.pivot):
            if self.combo.currentIndex() < 0:
                self.pivot.clear_selection()
            else:
                self.pivot.setCurrentItem(str(self.combo.currentData()))

    def refresh_metrics(self) -> None:
        """覆盖原生选项的固定像素字体，并按当前字号重新决定展开或下拉。"""
        for item in self.pivot.items.values():
            apply_font_role(item)
            set_function_tooltip(item, item.text())
            item.setAccessibleName(item.text())
            font = BaseStyles.font_for_role(FontRole.UI)
            set_fluent_font_rule(item, (
                f"PivotItem {{ {font_qss(font)} padding: 5px 10px 6px;"
                f"border: 1px solid {BaseStyles.color('BORDER_COLOR')}; border-radius: 6px;"
                f"background: {BaseStyles.color('BUTTON_BG')};"
                f"color: {BaseStyles.color('TEXT_PRIMARY')}; }}"
                f"PivotItem:hover {{ background: {BaseStyles.color('BUTTON_HOVER')}; }}"
                "PivotItem[isSelected=true] {"
                f"background: {BaseStyles.color('SELECTION_BG')};"
                f"color: {BaseStyles.color('SELECTION_TEXT')}; }}"
                f"PivotItem:focus {{ border-color: {themeColor().name()}; }}"
                f"PivotItem:disabled {{ color: {BaseStyles.color('TEXT_DISABLED')}; }}"
            ))
            # 隐藏的 Pivot 仍参与堆叠布局高度；FPS 保留原度量，不抬高相邻下拉字段。
            item.setMinimumHeight(max(
                0 if self._prefer_combo else 36,
                self.combo.minimumHeight(), item.fontMetrics().height() + 11,
            ))
        self.setMinimumWidth(self.combo.minimumWidth())
        self._update_mode()
        self.updateGeometry()

    def _update_mode(self) -> None:
        expanded = not self._prefer_combo and self.width() >= self.pivot.minimumSizeHint().width()
        self._layout.setCurrentWidget(self.pivot if expanded else self.combo)
        # 显隐发生在 resizeEvent 内，需把尺寸失效同步传到外层字段；只更新自身会让
        # 同一网格的兄弟字段保留旧尺寸，窄窗放大时甚至缓存为零高度。
        self.updateGeometry()
        if (parent := self.parentWidget()) is not None:
            parent.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_mode()

    def minimumSizeHint(self) -> QSize:
        return QSize(self.combo.minimumWidth(), self.combo.sizeHint().height())


class RemoteBitrateEditor(QWidget):
    """滑块索引映射既有码率枚举，不引入新的持久化值或命令参数。"""

    def __init__(
        self, combo: ComboBox, value_label: QLabel, parent=None,
        *, title_label: QLabel | None = None,
    ) -> None:
        super().__init__(parent)
        self.combo = combo
        self.value_label = value_label
        self.title_label = title_label
        # 数值与单位必须保持单行，否则切换两位数会折行并推移下方操作按钮。
        self.value_label.setWordWrap(False)
        combo.setParent(self)
        combo.hide()
        self.slider = Slider(Qt.Orientation.Horizontal, self)
        configure_fluent_control(self.slider, ensure_height=False)
        self.slider.setRange(0, combo.count() - 1)
        self.slider.setAccessibleName(combo.accessibleName())
        self.slider.setMinimumWidth(80)
        layout = QVBoxLayout(self) if title_label is not None else QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if title_label is not None:
            title_label.setWordWrap(False)
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.addWidget(title_label, 1)
            header.addWidget(value_label)
            layout.addLayout(header)
            layout.addWidget(self.slider)
        else:
            layout.addWidget(self.slider, 1)
            layout.addWidget(value_label)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.currentIndexChanged.connect(self.sync_selection)
        self.slider.valueChanged.connect(combo.setCurrentIndex)
        self.refresh_metrics()
        self.sync_selection()

    def refresh_metrics(self) -> None:
        """按全部合法值保留读数宽度，切换一位与两位码率不挤动滑轨。"""
        self.value_label.setMinimumWidth(max(
            self.value_label.fontMetrics().size(
                Qt.TextFlag.TextSingleLine, f"{self.combo.itemData(index)} Mbps",
            ).width()
            for index in range(self.combo.count())
        ))
        if self.title_label is not None:
            title_width = self.title_label.fontMetrics().horizontalAdvance(self.title_label.text())
            self.title_label.setMinimumWidth(title_width)
            self.setMinimumWidth(max(80, title_width + self.value_label.minimumWidth() + 4))
            self.slider.setFixedHeight(max(36, self.value_label.fontMetrics().height() + 14))

    def sync_selection(self, _index: int = -1) -> None:
        """同步码率及原生圆点；同索引回写不发出下拉变化，保持预设归属。"""
        # Fluent 圆点也监听 valueChanged，不能为阻止业务回写而屏蔽整个滑块信号。
        self.slider.setValue(max(0, self.combo.currentIndex()))
        text = f"{self.combo.currentData()} Mbps"
        self.value_label.setText(text)
        self.slider.setToolTip(text)
        self.slider.setAccessibleDescription(text)
