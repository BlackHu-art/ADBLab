"""把远程参数的既有下拉数据投影为原生 Fluent 选择器，保留配置与信号契约。"""

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSignalBlocker, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBox,
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
    configure_fluent_control,
    font_qss,
    set_fluent_font_rule,
    set_function_tooltip,
)


class RemoteWorkspace(QWidget):
    """分隔线只占栏间留白，不参与宽度规划；切为单栏时自动隐藏。"""

    def __init__(self, mirroring: QWidget, controls: QWidget, parent=None) -> None:
        super().__init__(parent)
        self._sections = (mirroring, controls)
        self.separator = VerticalSeparator(self)
        self.separator.setObjectName("remoteWorkspaceSeparator")
        self.separator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.separator.hide()
        for section in self._sections:
            section.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show):
            self._place_separator()
        return super().eventFilter(watched, event)

    def _place_separator(self) -> None:
        left, right = (
            QRect(section.mapTo(self, QPoint()), section.size()) for section in self._sections
        )
        side_by_side = left.right() < right.left() and left.top() == right.top()
        self.separator.setVisible(side_by_side)
        if side_by_side:
            top, bottom = min(left.top(), right.top()), max(left.bottom(), right.bottom())
            center = (left.right() + right.left()) // 2
            self.separator.setGeometry(center - 1, top, 3, bottom - top + 1)
            self.separator.raise_()


class RemoteCommandSeparators(QObject):
    """相邻动作同排时显示短竖线，换行后不在行首尾遗留装饰或占据网格列。"""

    def __init__(self, container: QWidget, buttons: tuple[QWidget, ...]) -> None:
        super().__init__(container)
        self._container = container
        self._buttons = buttons
        self._separators = []
        for _ in buttons[1:]:
            separator = VerticalSeparator(container)
            separator.setObjectName("remoteCommandSeparator")
            separator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            separator.setFixedHeight(14)
            separator.hide()
            self._separators.append(separator)
        for button in buttons:
            button.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show):
            for before, after, separator in zip(
                self._buttons, self._buttons[1:], self._separators,
            ):
                left, right = before.geometry(), after.geometry()
                same_row = left.top() == right.top() and left.right() < right.left()
                separator.setVisible(same_row)
                if same_row:
                    center = (left.right() + right.left()) // 2
                    separator.setGeometry(center - 1, left.center().y() - 7, 3, 14)
                    separator.raise_()
        return super().eventFilter(watched, event)


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
            # Pivot 用原生指示条表示选中，按钮焦点边框会改变内容尺寸并让整栏跳动。
            apply_font_role(item)
            set_function_tooltip(item, item.text())
            item.setAccessibleName(item.text())
            font = BaseStyles.font_for_role(FontRole.UI)
            set_fluent_font_rule(item, (
                f"PivotItem {{ {font_qss(font)} padding-top: 5px; padding-bottom: 6px; }}"
                f"PivotItem:focus {{ color: {themeColor().name()}; }}"
            ))
            # 默认上下各 10 像素会让隐藏的 Pivot 撑高下拉框；保留文字与底线所需
            # 空间，并和相邻原生下拉框使用同一行高，切换模式无需改变外层字段高度。
            item.setMinimumHeight(max(
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

    def sync_selection(self, _index: int = -1) -> None:
        """同步码率及原生圆点；同索引回写不发出下拉变化，保持预设归属。"""
        # Fluent 圆点也监听 valueChanged，不能为阻止业务回写而屏蔽整个滑块信号。
        self.slider.setValue(max(0, self.combo.currentIndex()))
        text = f"{self.combo.currentData()} Mbps"
        self.value_label.setText(text)
        self.slider.setToolTip(text)
        self.slider.setAccessibleDescription(text)
