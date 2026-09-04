"""提供标签页共享的控件工厂和设备、包名访问接口。"""

from typing import Any, cast

from PySide6.QtCore import QLocale, QSize, Qt, QTimer
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    EditableComboBox,
    HeaderCardWidget,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    TransparentPushButton,
)

from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    apply_focus_indicator,
    apply_label_role,
    configure_button,
    configure_fluent_control,
)
from gui.styles.icon_loader import get_themed_icon
from gui.widgets.responsive_controller import (
    ReflowReason,
    ResponsiveCoordinator,
    ResponsiveGridBinding,
)
from gui.widgets.responsive_layout import (
    RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY,
    RESPONSIVE_MINIMUM_TEXT_PROPERTY,
    RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY,
    GridMode,
    LayoutContext,
    WidthPolicy,
    row_major_mode,
    span_tail_mode,
)


class _SuffixedIntValidator(QIntValidator):
    """接受纯整数或带固定单位后缀的同一整数范围。"""

    def __init__(self, minimum: int, maximum: int, suffix: str, parent=None):
        super().__init__(minimum, maximum, parent)
        self._suffix = str(suffix).strip()
        locale = self.locale()
        locale.setNumberOptions(locale.numberOptions() | QLocale.NumberOption.RejectGroupSeparator)
        self.setLocale(locale)

    def validate(self, input_text: str, position: int):
        numeric_text = input_text.strip()
        if self._suffix and numeric_text.casefold().endswith(self._suffix.casefold()):
            numeric_text = numeric_text[: -len(self._suffix)].rstrip()
        state = cast(Any, super().validate(numeric_text, position))[0]
        return state, input_text, position


class BasePanel(QWidget):
    """所有标签页的抽象基类。通过 `panel` 属性访问 SidePanel 的共享状态。"""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self._responsive_rows: list[ResponsiveGridBinding] = []
        # PySide 的 Qt 父子关系负责 C++ 生命周期；这里额外保留 Python 包装器，避免
        # 仅在局部变量中创建的控件被回收后令 binding 的弱引用提前失效。
        self._responsive_row_owners: list[tuple[QWidget, tuple[QWidget, ...]]] = []
        self._responsive_inset_cache: dict[int, tuple[int, int]] = {}
        coordinator = getattr(panel, "_responsive_coordinator", None)
        if coordinator is None:
            coordinator = ResponsiveCoordinator()
            self._local_responsive_coordinator = coordinator
        self._responsive_coordinator = coordinator
        self._responsive_bindings_activated = False

    # ── 共享属性快捷访问 ────────────────────────────────────────────────

    @property
    def signals(self):
        return self.panel.signals

    @property
    def selected_devices(self):
        return self.panel.selected_devices

    @property
    def current_package(self):
        """当前选中的包名（来自 AppPanel 的 program_edit）。"""
        if hasattr(self.panel, "_apps_tab") and self.panel._apps_tab:
            return self.panel._apps_tab.package_text
        return ""

    @property
    def _font_sm(self):
        return self.panel._font_sm

    @property
    def _font_mono(self):
        return self.panel._font_mono

    @property
    def _font_base(self):
        return self.panel._font_base

    def _sh(self, cmd: str):
        """为当前选中设备发出 Shell 命令请求。"""
        self.signals.shell_command_requested.emit(self.selected_devices, cmd)

    # ── 界面控件工厂 ────────────────────────────────────────────────────

    def _card(self, title: str, *, parent=None) -> HeaderCardWidget:
        """按参考项目直接创建 HeaderCardWidget 分区。"""

        card = HeaderCardWidget(title, parent)
        card.viewLayout.setDirection(QBoxLayout.Direction.TopToBottom)
        card.viewLayout.setContentsMargins(16, 12, 16, 14)
        card.viewLayout.setSpacing(8)
        apply_label_role(card.headerLabel, FontRole.TITLE, color_key="TITLE_COLOR")
        card.setProperty("fontRole", FontRole.UI.value)
        card.setToolTip(title)
        card.setAccessibleName(title)
        return card

    def _g(self, t: str) -> HeaderCardWidget:
        """创建 qfluentwidgets 标题卡片，不再使用 QGroupBox。"""

        g = self._card(t)
        g.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return g

    def _label(self, text: str, *, small: bool = False, align=None) -> QLabel:
        role = FontRole.UI_SMALL if small else FontRole.UI
        label = BodyLabel(text, self)
        apply_label_role(label, role)
        label.setWordWrap(True)
        if align is not None:
            label.setAlignment(align)
        return label

    def _status_text(self, text: str = "") -> QLabel:
        label = self._label(text)
        label.setObjectName("statusLabel")
        return label

    def _checkbox(self, text: str, tooltip: str | None = None) -> QCheckBox:
        cb = CheckBox()
        cb.setText(text)
        cb.setAccessibleName(text)
        configure_fluent_control(cb)
        if tooltip:
            cb.setToolTip(tooltip)
        return cb

    def _b(self, t, i, variant="", tooltip=None):
        """直接创建 qfluentwidgets 图标按钮并配置项目语义。"""
        if variant == "accent":
            b = PrimaryPushButton()
        elif variant == "ghost":
            b = TransparentPushButton()
        elif variant == "danger":
            b = PrimaryPushButton()
        else:
            b = PushButton()
        configure_button(
            b,
            text=t,
            tooltip=tooltip,
            danger=variant == "danger",
        )
        b.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        b.setIcon(get_themed_icon(i))
        b.setIconSize(QSize(16, 16))
        b.setAccessibleName(t)
        b.setProperty("iconName", i)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _refresh_button_style(self, button: QPushButton):
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _set_button_enabled(self, button: QPushButton | None, enabled: bool):
        if button is None:
            return
        button.setEnabled(enabled)
        self._refresh_button_style(button)

    def _row(self, *items, spacing=4):
        """创建紧凑的水平控件行。

        每个参数可以是控件或 ``(widget, stretch)``，用于统一重复面板行的布局规则。
        """
        row = QHBoxLayout()
        row.setSpacing(spacing)
        for item in items:
            if isinstance(item, tuple):
                widget, stretch = item
            else:
                widget, stretch = item, 0
            row.addWidget(widget, stretch)
        return row

    def _add_responsive_row(
        self,
        layout,
        *items,
        spacing=4,
        compact_columns=2,
        medium_columns=2,
        wide_columns=None,
        policies=None,
        modes=None,
        span_tail=False,
    ) -> ResponsiveGridBinding:
        """在真实视觉树中创建一行 binding，并注册到面板级协调器。"""

        widgets = tuple(item[0] if isinstance(item, tuple) else item for item in items)
        stretches = tuple(item[1] if isinstance(item, tuple) else 0 for item in items)
        row_container = QWidget()
        row_container.setMinimumWidth(0)
        row_policy = row_container.sizePolicy()
        row_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        row_policy.setVerticalPolicy(QSizePolicy.Policy.Preferred)
        row_container.setSizePolicy(row_policy)
        row = QGridLayout(row_container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(spacing)
        row.setVerticalSpacing(spacing)
        mode_items = (
            tuple(modes)
            if modes is not None
            else self._responsive_modes(
                len(widgets),
                stretches,
                compact_columns=compact_columns,
                medium_columns=medium_columns,
                wide_columns=wide_columns or len(widgets),
                span_tail=bool(span_tail),
            )
        )
        policy_items = (
            tuple(policies)
            if policies is not None
            else tuple(self._responsive_policy(widget) for widget in widgets)
        )
        for widget, width_policy in zip(widgets, policy_items):
            if width_policy not in (WidthPolicy.SHRINKABLE, WidthPolicy.WRAPPING):
                continue
            if width_policy is WidthPolicy.WRAPPING and widget.minimumWidth() <= 0:
                # 空状态或短标签也必须保留一个稳定、与字体相关的可见单元；
                # 该下限不读取运行时文案，因此不会让状态文本推动全页断点漂移。
                widget.setProperty(RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY, 6)
                self._refresh_responsive_widget_minimum(widget)
            elif width_policy is WidthPolicy.SHRINKABLE and widget.minimumWidth() <= 0:
                # 输入字段可以收缩，但不能被自然宽度更大的相邻动作挤成零宽。
                widget.setProperty(RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY, 2)
                self._refresh_responsive_widget_minimum(widget)
            # 规划器已经为可收缩/可换行项给出下限；Qt 侧同步忽略会随文本
            # 变化的 sizeHint，避免父布局在空间充足时仍把相邻网格列挤到重叠。
            widget_policy = widget.sizePolicy()
            widget_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            widget.setSizePolicy(widget_policy)
        # 构建阶段先以最保守的一列把既有控件挂入真实视觉树；内容进入
        # QScrollArea 后，唯一 coordinator 再按最终 viewport 原子应用计划。
        for index, widget in enumerate(widgets):
            row.addWidget(widget, index, 0)
        binding = ResponsiveGridBinding(
            row_container,
            row,
            widgets,
            policy_items,
            mode_items,
            self._responsive_coordinator,
            context_provider=self._responsive_context,
            use_provided_geometry=True,
            adaptive_spacing=True,
        )
        self._responsive_rows.append(binding)
        self._responsive_row_owners.append((row_container, widgets))
        self._link_form_labels(widgets)
        layout.addWidget(row_container)
        return binding

    @staticmethod
    def _refresh_responsive_widget_minimum(widget: QWidget) -> None:
        """按控件当前字体刷新由响应布局托管的稳定最小宽度。"""

        if bool(widget.property(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY)):
            # 以当前字体和 qfluentwidgets 的 sizeHint 为起点，并按真实文本补足净宽。
            minimum_width = max(1, widget.sizeHint().width())
            if isinstance(widget, (ComboBox, EditableComboBox)):
                texts = [widget.itemText(index) for index in range(widget.count())]
                minimum_text = widget.property(RESPONSIVE_MINIMUM_TEXT_PROPERTY)
                if minimum_text not in (None, ""):
                    # 业务合法上限未必属于预设项；显式文本只参与稳定下限，
                    # 不把用户当前输入带入响应式断点。
                    texts.append(str(minimum_text))
                elif widget.currentText():
                    texts.append(widget.currentText())
                required_text_width = max(
                    (widget.fontMetrics().horizontalAdvance(text) for text in texts),
                    default=0,
                )
                minimum_width = max(minimum_width, required_text_width + 44)
            widget.setMinimumWidth(minimum_width)
            return
        em_count = int(widget.property(RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY) or 0)
        if em_count > 0:
            widget.setMinimumWidth(max(1, widget.fontMetrics().horizontalAdvance("M" * em_count)))

    def refresh_responsive_metrics(self) -> bool:
        """刷新所有自动下限，并返回是否有控件宽度实际变化。"""

        seen: set[int] = set()
        changed = False
        for _container, widgets in self._responsive_row_owners:
            for widget in widgets:
                key = id(widget)
                if key in seen:
                    continue
                seen.add(key)
                previous_width = widget.minimumWidth()
                self._refresh_responsive_widget_minimum(widget)
                changed = changed or widget.minimumWidth() != previous_width
        return changed

    def _uses_visual_size_hint_minimum(self) -> bool:
        """返回当前页面是否需要在首次视觉 polish 后复测原生尺寸。"""

        return any(
            bool(widget.property(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY))
            for _container, widgets in self._responsive_row_owners
            for widget in widgets
        )

    def responsive_geometry_is_applied(self) -> bool:
        """返回所有响应行的水平计划是否覆盖当前几何与样式。"""

        if not self._responsive_bindings_activated or not self._responsive_rows:
            return False
        for binding in self._responsive_rows:
            plan = binding.applied_plan
            if plan is None:
                return False
            try:
                context = binding.responsive_context()
            except RuntimeError:
                return False
            planned_context = plan.context_fingerprint
            current_context = context.fingerprint
            # 行高是网格应用后的 Qt 反馈，不参与水平断点决策；
            # 与 GridPlan.settling_fingerprint 保持一致，避免两帧行高被误判为新宽度。
            if len(planned_context) == 5 and len(current_context) == 5:
                planned_context = (planned_context[0], *planned_context[2:])
                current_context = (current_context[0], *current_context[2:])
            if plan.available_width != context.width or planned_context != current_context:
                return False
        return True

    @staticmethod
    def _responsive_mode_name(columns: int) -> str:
        names = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
        return names.get(columns, f"columns-{columns}")

    @classmethod
    def _responsive_modes(
        cls,
        widget_count: int,
        stretches: tuple[int, ...],
        *,
        compact_columns: int,
        medium_columns: int,
        wide_columns: int,
        span_tail: bool,
    ) -> tuple[GridMode, ...]:
        """从兼容列数声明生成按真实度量选择的严格候选序列。"""

        columns = sorted(
            {
                max(1, min(widget_count, int(value)))
                for value in (wide_columns, medium_columns, compact_columns, 1)
            },
            reverse=True,
        )
        result = []
        for rank, column_count in enumerate(columns):
            column_stretches = tuple(
                max(
                    (stretches[index] for index in range(column, widget_count, column_count)),
                    default=1,
                )
                for column in range(column_count)
            )
            factory = span_tail_mode if span_tail else row_major_mode
            result.append(
                factory(
                    cls._responsive_mode_name(column_count),
                    column_count,
                    rank,
                    column_stretches=column_stretches,
                )
            )
        return tuple(result)

    @staticmethod
    def _responsive_policy(widget: QWidget) -> WidthPolicy:
        """按控件语义选择稳定宽度来源，不读取用户当前输入文本。"""

        if isinstance(widget, QLineEdit):
            return WidthPolicy.SHRINKABLE
        if isinstance(widget, QLabel) and widget.wordWrap():
            return WidthPolicy.WRAPPING
        if isinstance(widget, QWidget) and not isinstance(
            widget,
            (QCheckBox, QPushButton, QLabel),
        ):
            return WidthPolicy.SHRINKABLE
        return WidthPolicy.NATURAL

    def _responsive_context(self, container: QWidget) -> LayoutContext:
        """返回 viewport 内该行的真实可用宽度、受限状态和样式代次。"""

        rect = container.contentsRect()
        available_width = rect.width()
        ancestor = container.parentWidget()
        scroll = None
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea):
                scroll = ancestor
                break
            ancestor = ancestor.parentWidget()
        if scroll is not None and (content := scroll.widget()) is not None:
            left_inset, right_inset = self._responsive_horizontal_insets(container, content)
            available_width = max(
                0,
                scroll.viewport().contentsRect().width() - left_inset - right_inset,
            )
        return LayoutContext(
            available_width,
            rect.height(),
            bool(getattr(self.panel, "_restricted_width_mode", False)),
            (self._font_base.family(), self._font_base.pointSizeF()),
            int(getattr(self.panel, "_responsive_style_generation", 0)),
        )

    def _responsive_horizontal_insets(
        self,
        container: QWidget,
        content: QWidget,
    ) -> tuple[int, int]:
        """从父布局内容矩形累加稳定边距，不把行自身限宽后的空白算作边距。"""

        left = 0
        right = 0
        geometry_is_current = True
        child = container
        while child is not content:
            parent = child.parentWidget()
            if parent is None:
                break
            parent_layout = parent.layout()
            if parent_layout is not None and parent_layout.indexOf(child) >= 0:
                inner = parent_layout.contentsRect()
                candidate_left = max(0, inner.left())
                candidate_right = max(0, parent.width() - inner.right() - 1)
                # resize/layout 请求刚到达时，QLayout 可能仍持有上一帧几何；此时
                # 巨大的尾部空白不是结构边距，先退回声明 margins，下一轮再读取实值。
                candidate_total = candidate_left + candidate_right
                segment_is_current = inner.width() > 0 and candidate_total <= max(
                    64, parent.width() // 4
                )
                if segment_is_current:
                    left += candidate_left
                    right += candidate_right
                else:
                    geometry_is_current = False
                    margins = parent_layout.contentsMargins()
                    left += max(0, margins.left())
                    right += max(0, margins.right())
            else:
                margins = parent.contentsMargins()
                left += max(0, margins.left())
                right += max(0, margins.right())
            child = parent
        key = id(container)
        if geometry_is_current:
            result = (left, right)
            self._responsive_inset_cache[key] = result
            return result
        return self._responsive_inset_cache.get(key, (left, right))

    def activate_responsive_bindings(self) -> None:
        """在内容进入 QScrollArea 视觉树后只请求一次初始规划。"""

        if self._responsive_bindings_activated:
            return
        # 此时祖先 QSS 与原生样式已经生效，基于 sizeHint 的
        # 可读下限必须在进入最终视觉树后再度量。
        self.refresh_responsive_metrics()
        self._responsive_bindings_activated = True
        self._request_responsive_reflow(ReflowReason.EXPLICIT)
        # SidePanel 可能在顶层窗口 show() 前完成懒页挂载；等首轮 polish/QSS
        # 提交后再量一次原生 sizeHint，避免使用未套用最终样式的下拉框宽度。
        if self._uses_visual_size_hint_minimum():
            QTimer.singleShot(0, self._refresh_metrics_after_visual_polish)

    def _refresh_metrics_after_visual_polish(self) -> None:
        """在首次视觉 polish 后刷新精确控件下限并启动最终布局代次。"""

        if not self._responsive_bindings_activated:
            return
        try:
            if getattr(self.window(), "_closing", False):
                return
            changed = self.refresh_responsive_metrics()
        except RuntimeError:
            return
        if changed:
            self._request_responsive_reflow(ReflowReason.EXPLICIT)

    def _request_responsive_reflow(self, reason: ReflowReason) -> None:
        request = getattr(self.panel, "request_responsive_reflow", None)
        if callable(request):
            request(reason)
        else:
            self._responsive_coordinator.request_reflow(reason)

    def apply_responsive_width(self, width: int) -> None:
        """保留旧宽度门面；实际规划只读取行容器的真实 contentsRect。"""

        del width
        self._request_responsive_reflow(ReflowReason.RESIZE)

    def _atomic_form_pair(self, label: QLabel, field: QWidget) -> QWidget:
        """把真实标签与 buddy 字段放进不可拆分的水平语义单元。"""

        container = QWidget()
        pair_layout = QHBoxLayout(container)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.setSpacing(4)
        pair_layout.addWidget(label)
        pair_layout.addWidget(field, 1)
        label.setBuddy(self._input_widget(field))
        container.setMinimumWidth(0)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return container

    def _in(self, p, w=0):
        """创建 qfluentwidgets 输入框。"""
        i = LineEdit()
        configure_fluent_control(i)
        i.setPlaceholderText(p)
        i.setAccessibleName(p)
        i.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if w:
            i.setMaximumWidth(w)
        return i

    def _in_int(self, placeholder: str, minimum: int, maximum: int, width: int = 0):
        """创建带业务范围约束的整数输入框。"""

        field = self._in(placeholder, width)
        field.setValidator(QIntValidator(minimum, maximum, field))
        return field

    def _in_float(
        self,
        placeholder: str,
        minimum: float,
        maximum: float,
        decimals: int = 6,
        width: int = 0,
    ):
        """创建带业务范围约束的浮点输入框。"""

        field = self._in(placeholder, width)
        validator = QDoubleValidator(minimum, maximum, decimals, field)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        field.setValidator(validator)
        return field

    @staticmethod
    def _input_widget(widget):
        return widget

    def _link_form_labels(self, widgets) -> None:
        """把行内标签与紧随其后的输入控件关联，并补全可访问名称。"""

        for index, label in enumerate(widgets[:-1]):
            if not isinstance(label, QLabel):
                continue
            for candidate in widgets[index + 1 :]:
                target = self._input_widget(candidate)
                if not isinstance(target, (QLineEdit, QCheckBox, QPushButton)):
                    continue
                label.setBuddy(target)
                name = label.text().strip().rstrip(":")
                if name and not target.accessibleName():
                    target.setAccessibleName(name)
                break

    def _validate_fields(self, *fields, focus_invalid: bool = True) -> bool:
        """统一验证必填字段和 Qt validator，失败时不进入业务信号层。"""

        for field in fields:
            target = cast(Any, self._input_widget(field))
            text = target.text().strip() if hasattr(target, "text") else ""
            acceptable = bool(text) and (
                not hasattr(target, "hasAcceptableInput") or target.hasAcceptableInput()
            )
            target.setProperty("inputInvalid", not acceptable)
            if not acceptable:
                if focus_invalid:
                    target.setFocus(Qt.FocusReason.OtherFocusReason)
                return False
        return True

    def _set_combo_int_validator(
        self,
        combo: EditableComboBox,
        minimum: int,
        maximum: int,
        *,
        suffix: str = "",
    ) -> None:
        """为可编辑整数下拉框安装范围 validator，可接受固定单位后缀。"""

        validator = (
            _SuffixedIntValidator(minimum, maximum, suffix, combo)
            if suffix
            else QIntValidator(minimum, maximum, combo)
        )
        combo.setValidator(validator)

    def _combo(self, items=None, font=None, *, font_role=FontRole.UI):
        """创建 qfluentwidgets 只读下拉框。"""
        role = FontRole(font_role)
        c = ComboBox()
        configure_fluent_control(c, role)
        if font is not None:
            c.setFont(font)
        c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if items:
            c.addItems(items)
            # 最小宽度容纳最长项，避免闭合态文本被响应式网格压窄裁剪。
            max_text = max(c.fontMetrics().horizontalAdvance(str(item)) for item in items)
            c.setMinimumWidth(max_text + 44)
        return c

    def _combo_editable(self, items=None, font=None, *, font_role=FontRole.UI):
        """创建 qfluentwidgets 原生 EditableComboBox。"""
        role = FontRole(font_role)
        role_font = self._font_sm if role is FontRole.UI else BaseStyles.font_for_role(role)
        resolved_font = font or role_font
        c = EditableComboBox()
        configure_fluent_control(c, role)
        c.setFont(resolved_font)
        c.dropButton.setAccessibleName("展开选项")
        apply_focus_indicator(c.dropButton)
        if items:
            c.addItems(items)
        return c
