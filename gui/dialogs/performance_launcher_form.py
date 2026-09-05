"""提供 MobilePerf 配置表单构建、控件交互与数字输入校验。"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QBoxLayout,
    QFrame,
    QGridLayout,
    QLayout,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    HeaderCardWidget,
    InfoBadge,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SegmentedWidget,
    SmoothScrollArea,
)

from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.styles.fluent import apply_label_role, configure_button
from gui.styles.icon_loader import get_fluent_icon, get_themed_icon
from gui.styles.typography import FontRole
from gui.widgets.content_section import ContentSection
from gui.widgets.preset_spin_box import StrictIntComboBox, StrictIntLineEdit
from services.mobileperf_runner import MobilePerfMonkeyConfig


class _PerformanceGrid(QWidget):
    """随可用宽度与字体重排现有字段，保持编辑器身份和键盘焦点。"""

    def __init__(self, widgets: Sequence[QWidget], *, columns: int = 3, parent=None):
        super().__init__(parent)
        self._widgets = widgets
        self._maximum_columns = columns
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._reflow()

    def _reflow(self) -> None:
        if not hasattr(self, "_grid"):
            return
        cell_width = max(176, self.fontMetrics().horizontalAdvance("M" * 15))
        columns = max(1, min(self._maximum_columns, (self.width() + 12) // (cell_width + 12)))
        if columns == self._columns:
            return
        while self._grid.count():
            self._grid.takeAt(0)
        for column in range(self._maximum_columns):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, widget in enumerate(self._widgets):
            self._grid.addWidget(widget, index // columns, index % columns)
        self._columns = columns
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._columns = 0
            self._reflow()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())


class _PerformanceRow(QWidget):
    """字段与动作按自然尺寸并排，空间不足时移至下一行。"""

    def __init__(self, widgets: tuple[QWidget, ...], *, stretch_first: bool = True):
        super().__init__()
        self._widgets = widgets
        self._box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(8)
        for index, widget in enumerate(widgets):
            self._box.addWidget(widget, 1 if index == 0 and stretch_first else 0)
        if not stretch_first:
            self._box.addStretch(1)
        self.setMinimumWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        required = sum(
            max(widget.minimumWidth(), widget.sizeHint().width()) for widget in self._widgets
        )
        required += self._box.spacing() * (len(self._widgets) - 1)
        self._box.setDirection(
            QBoxLayout.Direction.TopToBottom
            if self.width() < required
            else QBoxLayout.Direction.LeftToRight
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())


CONFIG_HINTS = {
    "package": "多个进程用分号分隔；包含子进程时，将主进程放在第一项。",
    "frequency": "每次采样的间隔，填写正整数。",
    "timeout": "填写正整数；72 小时为 4320 分钟。",
    "dumpheap_freq": "生成堆快照的间隔，填写正整数。",
    "serialnum": "使用当前性能采集页绑定的设备会话。",
    "exceptionlog": "多个关键字用分号分隔；命中日志保存到 exception.log。",
    "monkey": "与性能采集同时启动，沿用采集时长；结束或停止采集时一并停止。",
    "save_path": "路径请避免空格；自动追加设备名称目录以区分结果。",
    "phone_log_path": "多个设备路径用分号分隔；采集结束后复制到结果目录。",
}

MONKEY_PERCENT_FIELDS = [
    ("Touch events", "pct_touch", "--pct-touch"),
    ("Motion events", "pct_motion", "--pct-motion"),
    ("Trackball events", "pct_trackball", "--pct-trackball"),
    ("Navigation events", "pct_nav", "--pct-nav"),
    ("Major navigation events", "pct_majornav", "--pct-majornav"),
    ("System key events", "pct_syskeys", "--pct-syskeys"),
    ("App switch events", "pct_appswitch", "--pct-appswitch"),
    ("Any events", "pct_anyevent", "--pct-anyevent"),
    ("Keyboard flip events", "pct_flip", "--pct-flip"),
    ("Pinch/zoom events", "pct_pinchzoom", "--pct-pinchzoom"),
]


class PerformanceLauncherForm:
    """组合进 PerformancePage 的表单控制器，通过 ``self._frame`` 访问页面。"""

    def __init__(self, frame):
        self._frame = frame

    def use_workspace_scroll_container(self) -> None:
        """嵌入时复用工作区页头和滚动，保留启动、停止等功能操作。"""

        self._frame._header_title_row.hide()
        self._frame.dialog_subtitle.hide()
        if bool(getattr(self._frame, "_workspace_scroll_prepared", False)):
            return
        scroll = self._frame._config_scroll
        content = scroll.takeWidget()
        if content is None:
            return
        root = self._frame._root_layout
        index = root.indexOf(scroll)
        root.removeWidget(scroll)
        scroll.hide()
        content.setParent(self._frame)
        root.insertWidget(max(0, index), content)
        content.show()
        self._frame._workspace_scroll_prepared = True

    def _build_ui(self, package_name: str):
        root = QVBoxLayout(self._frame)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)
        self._frame._root_layout = root

        self._frame.header_card = QWidget()
        self._frame.header_card.setObjectName("dialogHeaderCard")
        header = QVBoxLayout(self._frame.header_card)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        self._frame.dialog_title = apply_label_role(
            BodyLabel("性能采集"), FontRole.TITLE, color_key="TITLE_COLOR", bold=True
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.dialog_title.setWordWrap(True)
        self._frame.status_badge = InfoBadge.info("未选择设备", self._frame.header_card)
        self._frame.status_badge.setToolTip("当前性能采集会话的设备连接状态")
        self._frame._header_title_row = self._row_widget(
            self._frame.dialog_title, self._frame.status_badge
        )
        header.addWidget(self._frame._header_title_row)
        self._frame.dialog_subtitle = apply_label_role(
            BodyLabel("设置采样计划，运行后在此查看日志与结果。"),
            FontRole.UI_SMALL,
            color_key="TEXT_SECONDARY",
        )
        self._frame.dialog_subtitle.setObjectName("dialogSubtitle")
        self._frame.dialog_subtitle.setWordWrap(True)
        header.addWidget(self._frame.dialog_subtitle)
        self._frame._action_row = self._build_actions()
        header.addWidget(self._frame._action_row)
        root.addWidget(self._frame.header_card)

        # 独立页面由一个滚动容器承载配置和结果；嵌入时将同一内容交给工作区，
        # 避免配置、页面与结果形成三层互相争抢滚轮的视口。
        self._frame._config_group = self._build_config_section(package_name)
        self._frame._config_scroll = SmoothScrollArea()
        self._frame._config_scroll.setObjectName("performanceConfigScroll")
        self._frame._config_scroll.setWidgetResizable(True)
        self._frame._config_scroll.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self._frame._config_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._frame._config_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._frame._config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._frame._config_scroll.setMinimumSize(QSize())
        self._frame._config_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._frame._config_scroll.setWidget(self._frame._config_group)
        root.addWidget(self._frame._config_scroll, 1)

        self._frame._results_group = self._section_card("运行日志与结果", "performanceResults")
        results = self._frame._results_group.viewLayout
        result_actions = _PerformanceRow(
            (self._frame.perfetto_btn, self._frame.result_btn), stretch_first=False
        )
        results.addWidget(result_actions)
        self._frame.log_view = self._build_log_view()
        self._frame._chart_toggle, self._frame._chart_stack = self._build_chart_toggle()
        self._frame._chart_stack.addWidget(self._frame.log_view)
        results.addWidget(self._frame._chart_toggle)
        results.addWidget(self._frame._chart_stack)
        self._frame._content_layout.addWidget(self._frame._results_group)

    def _section_card(self, title: str, name: str) -> HeaderCardWidget:
        card = ContentSection(title)
        card.setObjectName(name)
        card.setMinimumWidth(0)
        card.viewLayout.setDirection(QBoxLayout.Direction.TopToBottom)
        card.viewLayout.setContentsMargins(0, 8, 0, 18)
        card.viewLayout.setSpacing(12)
        apply_label_role(card.headerLabel, FontRole.TITLE, color_key="TITLE_COLOR", bold=True)
        card.headerLabel.setWordWrap(True)
        return card

    def _field(self, key: str, title: str, field: QWidget, hint: str) -> QWidget:
        container = QWidget()
        container.setMinimumWidth(0)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = apply_label_role(BodyLabel(title), FontRole.UI, bold=True)
        label.setObjectName("fieldLabel")
        label.setProperty("configurationKey", key)
        label.setWordWrap(True)
        target = (
            field
            if field.focusPolicy() & Qt.FocusPolicy.TabFocus
            else next(
                (
                    child
                    for child in field.findChildren(QWidget)
                    if child.focusPolicy() & Qt.FocusPolicy.TabFocus
                ),
                None,
            )
        )
        if target is not None:
            label.setBuddy(target)
            if not target.accessibleName():
                target.setAccessibleName(title)
        layout.addWidget(label)
        field.setMinimumWidth(0)
        layout.addWidget(field)
        if hint:
            # 字段说明归输入目标所有，同一行的辅助按钮保留各自的操作提示。
            self._apply_hint(target if target is not None else field, hint)
            help_label = apply_label_role(BodyLabel(hint), FontRole.UI, color_key="TEXT_SECONDARY")
            help_label.setObjectName("configHint")
            help_label.setWordWrap(True)
            help_label.setMinimumWidth(0)
            help_label.setAccessibleName(f"{title}说明")
            layout.addWidget(help_label)
        return container

    def _build_config_section(self, package_name: str) -> QWidget:
        """将采集目标、采样、输出与可选压力测试分为持久配置卡片。"""

        content = QWidget()
        content.setObjectName("performanceConfig")
        content.setMinimumWidth(0)
        layout = QVBoxLayout(content)
        self._frame._content_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        target = self._section_card("采集目标", "performanceTarget")
        sampling = self._section_card("采样与诊断", "performanceSampling")
        output = self._section_card("结果输出", "performanceOutput")
        monkey = self._section_card("Monkey 压力测试", "performanceMonkey")
        for section in (target, sampling, output, monkey):
            layout.addWidget(section)

        self._frame.package_edit = LineEdit()
        self._frame.package_edit.setText(package_name)
        self._frame.package_edit.setPlaceholderText("com.example.app")
        self._frame.get_package_btn = PushButton()
        configure_button(
            self._frame.get_package_btn, text="获取当前应用", tooltip="读取所选设备的前台应用包名"
        )
        self._frame.get_package_btn.setIcon(get_fluent_icon("target.svg"))
        self._frame.get_package_btn.setProperty("iconName", "target.svg")
        self._frame.get_package_btn.clicked.connect(self._frame.fetch_current_package)
        target.viewLayout.addWidget(
            self._field(
                "package",
                "应用包名",
                self._row_widget(self._frame.package_edit, self._frame.get_package_btn),
                CONFIG_HINTS["package"],
            )
        )
        self._frame.serialnum_label = apply_label_role(
            BodyLabel(self._frame.device_ip or "未选择"), FontRole.MONO, color_key="LOG_SUCCESS"
        )
        self._frame.serialnum_label.setObjectName("onlineDeviceLabel")
        self._frame.serialnum_label.setWordWrap(True)
        self._frame.serialnum_label.setAccessibleName(
            f"采集设备：{self._frame.device_ip or '未选择'}"
        )
        target.viewLayout.addWidget(
            self._field(
                "serialnum",
                "会话设备",
                self._frame.serialnum_label,
                CONFIG_HINTS["serialnum"],
            )
        )

        self._frame.frequency_input = StrictIntComboBox(1, 2_147_483_647, 5, presets=(1, 2, 5, 10))
        self._frame.timeout_input = StrictIntComboBox(
            1, 2_147_483_647, 600, presets=(10, 30, 60, 120, 600, 4320)
        )
        self._frame.dumpheap_input = StrictIntComboBox(
            1, 2_147_483_647, 60, presets=(5, 10, 30, 60, 120)
        )
        self._frame.frequency_combo = self._frame.frequency_input
        self._frame.timeout_combo = self._frame.timeout_input
        self._frame.dumpheap_combo = self._frame.dumpheap_input
        self._frame.frequency_unit_label = self._unit_label("s", "seconds")
        self._frame.timeout_unit_label = self._unit_label("min", "minutes")
        self._frame.dumpheap_unit_label = self._unit_label("min", "minutes")
        sampling.viewLayout.addWidget(
            _PerformanceGrid(
                [
                    self._field(
                        "frequency",
                        "采样间隔",
                        self._row_widget(
                            self._frame.frequency_input, self._frame.frequency_unit_label
                        ),
                        CONFIG_HINTS["frequency"],
                    ),
                    self._field(
                        "timeout",
                        "采集时长",
                        self._row_widget(self._frame.timeout_input, self._frame.timeout_unit_label),
                        CONFIG_HINTS["timeout"],
                    ),
                    self._field(
                        "dumpheap_freq",
                        "堆快照间隔",
                        self._row_widget(
                            self._frame.dumpheap_input, self._frame.dumpheap_unit_label
                        ),
                        CONFIG_HINTS["dumpheap_freq"],
                    ),
                ]
            )
        )
        self._frame.exception_edit = LineEdit()
        self._frame.exception_edit.setText("fatal exception;has died")
        sampling.viewLayout.addWidget(
            self._field(
                "exceptionlog",
                "异常日志关键字",
                self._frame.exception_edit,
                CONFIG_HINTS["exceptionlog"],
            )
        )

        self._frame.save_path_edit = LineEdit()
        self._frame.save_path_edit.setText(self._frame._default_save_path())
        self._frame.pick_save_btn = PushButton()
        configure_button(
            self._frame.pick_save_btn, text="选择目录", tooltip="选择性能采集结果的保存目录"
        )
        self._frame.pick_save_btn.setIcon(get_fluent_icon("folder.svg"))
        self._frame.pick_save_btn.setProperty("iconName", "folder.svg")
        self._frame.pick_save_btn.clicked.connect(self._frame._pick_save_path)
        output.viewLayout.addWidget(
            self._field(
                "save_path",
                "保存位置",
                self._row_widget(self._frame.save_path_edit, self._frame.pick_save_btn),
                CONFIG_HINTS["save_path"],
            )
        )
        self._frame.phone_log_edit = LineEdit()
        self._frame.phone_log_edit.setText("/data/anr")
        output.viewLayout.addWidget(
            self._field(
                "phone_log_path",
                "结束后拉取的设备日志",
                self._frame.phone_log_edit,
                CONFIG_HINTS["phone_log_path"],
            )
        )

        self._frame.monkey_check = CheckBox("同时运行 Monkey")
        self._frame.monkey_check.toggled.connect(self._frame._on_monkey_enabled_changed)
        monkey.viewLayout.addWidget(
            self._field(
                "monkey", "随机操作压力测试", self._frame.monkey_check, CONFIG_HINTS["monkey"]
            )
        )
        self._frame._monkey_details = self._build_monkey_row()
        monkey.viewLayout.addWidget(self._frame._monkey_details)
        self._frame._configuration_sections = (target, sampling, output, monkey)
        self._on_monkey_enabled_changed(self._frame.monkey_check.isChecked())
        return content

    def _build_monkey_row(self) -> QWidget:
        container = QWidget()
        container.setObjectName("performanceMonkeyOptions")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._frame.monkey_throttle_input = StrictIntComboBox(
            1, 2_147_483_647, 500, presets=(100, 200, 300, 500, 1000, 2000)
        )
        self._frame.monkey_throttle_combo = self._frame.monkey_throttle_input
        self._frame.monkey_seed_input = StrictIntLineEdit(
            minimum=0, maximum=2_147_483_647, value=1_000_000
        )
        self._frame.monkey_seed_edit = self._frame.monkey_seed_input
        self._frame.monkey_throttle_unit_label = self._unit_label("ms")
        layout.addWidget(
            _PerformanceGrid(
                [
                    self._field(
                        "monkey_throttle",
                        "操作间隔",
                        self._row_widget(
                            self._frame.monkey_throttle_input,
                            self._frame.monkey_throttle_unit_label,
                        ),
                        "",
                    ),
                    self._field("monkey_seed", "随机种子", self._frame.monkey_seed_input, ""),
                ],
                columns=2,
            )
        )
        self._frame.monkey_total_label = apply_label_role(
            BodyLabel("Total: 100%"), FontRole.UI, color_key="LOG_SUCCESS", bold=True
        )
        self._frame.monkey_total_label.setObjectName("monkeyTotalLabel")
        self._frame.monkey_total_label.setWordWrap(True)
        self._frame._monkey_total_labels = [self._frame.monkey_total_label]
        layout.addWidget(self._frame.monkey_total_label)
        self._frame.monkey_pct_inputs = {}
        self._frame.monkey_pct_combos = self._frame.monkey_pct_inputs
        defaults = MobilePerfMonkeyConfig()
        percent_fields = []
        event_titles = (
            "触摸",
            "滑动",
            "轨迹球",
            "导航",
            "主要导航",
            "系统按键",
            "应用切换",
            "其他事件",
            "键盘翻转",
            "双指缩放",
        )
        for display_title, (title, attr, option_name) in zip(event_titles, MONKEY_PERCENT_FIELDS):
            field = StrictIntComboBox(
                0, 100, getattr(defaults, attr), presets=(0, 5, 10, 15, 20, 25, 30, 40, 50, 100)
            )
            self._apply_hint(field, f"{display_title}占比（{option_name}），单位为百分比。")
            field.setAccessibleName(f"{title} percentage")
            field.valueChanged.connect(self._frame._update_monkey_total)
            field.validityChanged.connect(self._frame._update_monkey_total)
            self._frame.monkey_pct_inputs[attr] = field
            percent_fields.append(self._field(attr, f"{display_title}（%）", field, ""))
        layout.addWidget(_PerformanceGrid(percent_fields, columns=3))

        self._frame.monkey_ignore_crashes = CheckBox("忽略应用崩溃")
        self._frame.monkey_ignore_timeouts = CheckBox("忽略无响应")
        self._frame.monkey_ignore_security = CheckBox("忽略安全异常")
        self._frame.monkey_kill_after_error = CheckBox("出错后结束 Monkey")
        flags = [
            self._frame.monkey_ignore_crashes,
            self._frame.monkey_ignore_timeouts,
            self._frame.monkey_ignore_security,
            self._frame.monkey_kill_after_error,
        ]
        accessible_names = (
            "Ignore application crashes", "Ignore application timeouts",
            "Ignore security exceptions", "Kill Monkey after error",
        )
        for checkbox, accessible_name in zip(flags, accessible_names):
            checkbox.setChecked(True)
            checkbox.setAccessibleName(accessible_name)
            checkbox.setToolTip(checkbox.text())
        layout.addWidget(_PerformanceGrid(flags, columns=2))
        self._update_monkey_total()
        return container

    def _inline_label(self, text: str, tooltip: str = "") -> BodyLabel:
        label = apply_label_role(BodyLabel(text), FontRole.UI)
        label.setObjectName("inlineLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setMinimumWidth(136)
        if tooltip:
            label.setToolTip(tooltip)
            label.setAccessibleDescription(tooltip)
        return label

    @staticmethod
    def _unit_label(text: str, semantic_name: str | None = None) -> BodyLabel:
        """创建不会参与严格数字解析的可见单位标签。"""

        label = apply_label_role(BodyLabel(text), FontRole.UI_SMALL, color_key="TEXT_SECONDARY")
        label.setObjectName("unitLabel")
        label.setAccessibleName(f"Unit: {semantic_name or text}")
        return label

    def _monkey_option_widgets(self) -> list[QWidget]:
        widgets: list[QWidget] = [
            self._frame.monkey_throttle_combo,
            self._frame.monkey_seed_edit,
            self._frame.monkey_ignore_crashes,
            self._frame.monkey_ignore_timeouts,
            self._frame.monkey_ignore_security,
            self._frame.monkey_kill_after_error,
        ]
        widgets.extend(
            getattr(self._frame, "_monkey_total_labels", (self._frame.monkey_total_label,))
        )
        widgets.extend(self._frame.monkey_pct_combos.values())
        return widgets

    def _on_monkey_enabled_changed(self, checked: bool):
        details = getattr(self._frame, "_monkey_details", None)
        if details is not None:
            details.setVisible(checked)
        pending_invalid = {}
        for field in getattr(self._frame, "monkey_pct_combos", {}).values():
            editor = self._numeric_editor(field)
            if editor is not None and not field.input_is_acceptable():
                pending_invalid[field] = editor.text()
        for widget in self._monkey_option_widgets():
            widget.setEnabled(checked)
        for field, raw_text in pending_invalid.items():
            editor = self._numeric_editor(field)
            if editor is not None and editor.text() != raw_text:
                editor.setText(raw_text)
        self._update_monkey_total()

    @staticmethod
    def _numeric_editor(field: QWidget) -> QLineEdit | None:
        if isinstance(field, QLineEdit):
            return field
        return field.findChild(QLineEdit)

    def _update_monkey_total(self, *_args):
        if not hasattr(self._frame, "monkey_total_label"):
            return
        if self._frame.monkey_check.isChecked() and any(
            not field.input_is_acceptable() for field in self._frame.monkey_pct_combos.values()
        ):
            for label in getattr(
                self._frame, "_monkey_total_labels", (self._frame.monkey_total_label,)
            ):
                label.setText("Total: Invalid")
                label.setToolTip("Total: Invalid")
                label.setAccessibleName("Total: Invalid")
                label.setAccessibleDescription("Monkey event percentage total is invalid")
                apply_label_role(label, FontRole.UI, color_key="LOG_ERROR", bold=True)
            return
        total = sum(field.value() for field in self._frame.monkey_pct_combos.values())
        color_key = "LOG_SUCCESS" if total == 100 else "LOG_ERROR"
        for label in getattr(
            self._frame, "_monkey_total_labels", (self._frame.monkey_total_label,)
        ):
            full_text = f"Total: {total}%"
            label.setText(full_text)
            label.setToolTip(full_text)
            label.setAccessibleName(full_text)
            label.setAccessibleDescription(f"Monkey event percentage total: {total}%")
            apply_label_role(label, FontRole.UI, color_key=color_key, bold=True)

    def _collect_monkey_config(self) -> MobilePerfMonkeyConfig:
        values = {attr: field.value() for attr, field in self._frame.monkey_pct_combos.items()}
        return MobilePerfMonkeyConfig(
            throttle_ms=self._frame.monkey_throttle_input.value(),
            seed=self._frame.monkey_seed_input.value(),
            ignore_crashes=self._frame.monkey_ignore_crashes.isChecked(),
            ignore_timeouts=self._frame.monkey_ignore_timeouts.isChecked(),
            ignore_security=self._frame.monkey_ignore_security.isChecked(),
            kill_after_error=self._frame.monkey_kill_after_error.isChecked(),
            **values,
        )

    def _add_config_row(
        self,
        grid: QGridLayout,
        row: int,
        key: str,
        field: QWidget,
        hint: str,
    ) -> int:
        label = apply_label_role(BodyLabel(key), FontRole.UI, bold=True)
        label.setObjectName("fieldLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        buddy = field
        if not field.focusPolicy() & Qt.FocusPolicy.TabFocus:
            buddy = next(
                (
                    child
                    for child in field.findChildren(QWidget)
                    if child.focusPolicy() & Qt.FocusPolicy.TabFocus
                ),
                field,
            )
        if buddy is not field or field.focusPolicy() & Qt.FocusPolicy.TabFocus:
            label.setBuddy(buddy)
            if not buddy.accessibleName():
                buddy.setAccessibleName(key.replace("_", " ").title())
        if hint:
            self._apply_hint(label, hint)
            self._apply_hint(field, hint)
            for child in field.findChildren(QWidget):
                if child.focusPolicy() & Qt.FocusPolicy.TabFocus:
                    self._apply_hint(child, hint)
        grid.addWidget(label, row, 0)
        grid.addWidget(field, row, 1)
        hint_label = apply_label_role(BodyLabel(hint), FontRole.UI, color_key="TEXT_SECONDARY")
        hint_label.setObjectName("configHint")
        hint_label.setWordWrap(True)
        hint_label.setAccessibleName(f"{key} help")
        hint_label.setAccessibleDescription(hint)
        grid.addWidget(hint_label, row + 1, 1)
        return row + 2

    @staticmethod
    def _apply_hint(widget: QWidget, hint: str):
        current = widget.toolTip().strip()
        if not current:
            widget.setToolTip(hint)
        elif hint not in current:
            widget.setToolTip(f"{current}\n\n{hint}")
        if not widget.accessibleDescription().strip():
            widget.setAccessibleDescription(hint)

    def _row_widget(self, *widgets: QWidget) -> QWidget:
        container = _PerformanceRow(widgets)
        container.setObjectName("inlineRow")
        return container

    def _build_log_view(self) -> PlainTextEdit:
        log_view = PlainTextEdit()
        log_view.setObjectName("performanceLog")
        log_view.setReadOnly(True)
        log_view.setUndoRedoEnabled(False)
        log_view.setPlaceholderText("启动采集后，运行日志会显示在这里。")
        log_view.document().setMaximumBlockCount(self._frame._max_log_lines)
        return log_view

    def _build_chart_toggle(self) -> tuple[QWidget, QStackedWidget]:
        """构建日志/图表切换条与承载栈（P3）：图表视图由页面注入到栈内。"""

        segmented = SegmentedWidget()
        segmented.addItem("log", "日志")
        segmented.addItem("chart", "图表")
        segmented.setCurrentItem("log")
        # 功能提示契约：分段按钮提供英文短描述（tooltip 契约测试）。
        for button, tip in zip(segmented.items.values(), ("Show run logs", "Show result charts")):
            button.setToolTip(tip)
            button.setProperty("functionalToolTip", tip)
        stack = QStackedWidget()
        segmented.currentItemChanged.connect(
            lambda route_key: stack.setCurrentIndex(1 if route_key == "chart" else 0)
        )
        stack.currentChanged.connect(self.refresh_result_view_height)
        return segmented, stack

    def refresh_result_view_height(self, _index: int | None = None) -> None:
        """按当前结果视图测高，图表为大字体图例与坐标轴保留绘图空间。"""

        stack = getattr(self._frame, "_chart_stack", None)
        if stack is None or not hasattr(self._frame, "log_view"):
            return
        if stack.currentIndex() == 1:
            height = max(260, self._frame.fontMetrics().height() * 10)
        else:
            height = max(180, self._frame.log_view.fontMetrics().height() * 8 + 24)
        stack.setFixedHeight(height)

    def _build_actions(self) -> QWidget:
        container = QWidget()
        container.setObjectName("performanceActionRow")
        container.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row = QVBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._frame.status_label = apply_label_role(
            BodyLabel("Idle"), FontRole.UI, color_key="TEXT_SECONDARY"
        )
        self._frame.status_label.setObjectName("statusLabel")
        self._frame.status_label.setMinimumWidth(0)
        self._frame.status_label.setWordWrap(True)

        self._frame.progress_bar = ProgressBar()
        self._frame.progress_bar.setObjectName("performanceProgress")
        self._frame.progress_bar.setRange(0, 100)
        self._frame.progress_bar.setValue(0)
        self._frame.progress_bar.setFormat("0%")
        self._frame.progress_bar.setTextVisible(True)
        self._frame.progress_bar.setMinimumWidth(0)

        self._frame.perfetto_action = QAction(
            get_themed_icon("speedometer.svg"),
            "打开 Perfetto",
            self._frame,
        )
        self._frame.perfetto_action.setObjectName("performancePerfettoAction")
        self._frame.perfetto_action.setToolTip("Open Perfetto trace viewer")
        self._frame.perfetto_action.triggered.connect(self._frame._trigger_open_perfetto)
        self._frame.result_action = QAction(
            get_themed_icon("folder-open.svg"),
            "查看结果目录",
            self._frame,
        )
        self._frame.result_action.setObjectName("performanceResultAction")
        self._frame.result_action.setToolTip("Open the latest MobilePerf result")
        self._frame.result_action.triggered.connect(self._frame._trigger_open_result)
        self._frame.result_action.setEnabled(False)

        self._frame.perfetto_btn = PushButton()
        self._frame.perfetto_btn.setText("Open Perfetto")
        self._frame.perfetto_btn.setIcon(get_fluent_icon("speedometer.svg"))
        self._frame.perfetto_btn.setIconSize(QSize(14, 14))
        self._frame.perfetto_btn.setProperty("iconName", "speedometer.svg")
        self._frame.perfetto_btn.clicked.connect(self._frame.perfetto_action.trigger)
        self._frame.perfetto_action.changed.connect(self._frame._sync_perfetto_button)

        self._frame.result_btn = PushButton()
        self._frame.result_btn.setText("Open Result")
        self._frame.result_btn.setIcon(get_fluent_icon("folder-open.svg"))
        self._frame.result_btn.setIconSize(QSize(14, 14))
        self._frame.result_btn.setProperty("iconName", "folder-open.svg")
        self._frame.result_btn.clicked.connect(self._frame.result_action.trigger)
        self._frame.result_action.changed.connect(self._frame._sync_result_button)

        self._frame.stop_btn = PrimaryPushButton()
        configure_button(
            self._frame.stop_btn,
            text="停止采集",
            tooltip="Stop the active performance collection",
            danger=True,
        )
        self._frame.stop_btn.setIcon(get_fluent_icon("stop-circle.svg"))
        self._frame.stop_btn.setIconSize(QSize(14, 14))
        self._frame.stop_btn.setProperty("iconName", "stop-circle.svg")
        self._frame.stop_btn.clicked.connect(self._frame.stop_mobileperf)
        self._frame.stop_btn.setEnabled(False)

        self._frame.start_btn = PrimaryPushButton()
        self._frame.start_btn.setText("开始采集")
        self._frame.start_btn.setToolTip("Start performance collection with this configuration")
        self._frame.start_btn.setIcon(get_fluent_icon("play.svg"))
        self._frame.start_btn.setIconSize(QSize(14, 14))
        self._frame.start_btn.setProperty("iconName", "play.svg")
        self._frame.start_btn.clicked.connect(self._frame.start_mobileperf)
        row.addWidget(
            self._row_widget(self._frame.status_label, self._frame.stop_btn, self._frame.start_btn)
        )
        row.addWidget(self._frame.progress_bar)
        self._sync_perfetto_button()
        self._sync_result_button()
        return container

    def _sync_perfetto_button(self) -> None:
        self._frame.perfetto_btn.setEnabled(self._frame.perfetto_action.isEnabled())
        self._frame.perfetto_btn.setText(self._frame.perfetto_action.text())
        self._frame.perfetto_btn.setIcon(self._frame.perfetto_action.icon())
        self._frame.perfetto_btn.setToolTip(self._frame.perfetto_action.toolTip())
        self._frame.perfetto_btn.setAccessibleName(self._frame.perfetto_action.text())
        self._frame.perfetto_btn.setAccessibleDescription(self._frame.perfetto_action.toolTip())

    def _sync_result_button(self) -> None:
        self._frame.result_btn.setEnabled(self._frame.result_action.isEnabled())
        self._frame.result_btn.setText(self._frame.result_action.text())
        self._frame.result_btn.setIcon(self._frame.result_action.icon())
        self._frame.result_btn.setToolTip(self._frame.result_action.toolTip())
        self._frame.result_btn.setAccessibleName(self._frame.result_action.text())
        self._frame.result_btn.setAccessibleDescription(self._frame.result_action.toolTip())

    def _enabled_numeric_inputs(
        self,
    ) -> tuple[tuple[str, StrictIntComboBox | StrictIntLineEdit], ...]:
        """返回当前业务语义下必须有效并提交的数字字段。"""

        fields: tuple[tuple[str, StrictIntComboBox | StrictIntLineEdit], ...] = (
            ("frequency", self._frame.frequency_input),
            ("timeout", self._frame.timeout_input),
            ("dumpheap frequency", self._frame.dumpheap_input),
        )
        if self._frame.monkey_check.isChecked():
            fields += (
                ("Monkey throttle", self._frame.monkey_throttle_input),
                ("Monkey seed", self._frame.monkey_seed_input),
            )
            fields += tuple(
                (
                    f"Monkey {name.replace('pct_', '').replace('_', ' ')} percentage",
                    field,
                )
                for name, field in self._frame.monkey_pct_combos.items()
            )
        return fields

    def _commit_numeric_inputs(self) -> bool:
        """先校验全部启用字段，再统一提交，避免产生半提交配置。"""

        fields = self._enabled_numeric_inputs()
        for label, field in fields:
            if field.input_is_acceptable():
                continue
            FluentMessageBox.warning(
                self._frame,
                "Invalid Number",
                f"Please enter a valid {label} value within the allowed range.",
            )
            field.focus_editor()
            self._update_monkey_total()
            return False
        for _label, field in fields:
            if not field.commit_value():
                field.focus_editor()
                self._update_monkey_total()
                return False
        return True

    def _all_numeric_inputs(self) -> tuple[StrictIntComboBox | StrictIntLineEdit, ...]:
        return (
            self._frame.frequency_input,
            self._frame.timeout_input,
            self._frame.dumpheap_input,
            self._frame.monkey_throttle_input,
            self._frame.monkey_seed_input,
            *self._frame.monkey_pct_inputs.values(),
        )

    def _set_configuration_enabled(self, enabled: bool) -> None:
        """只锁定配置卡片，保留日志、运行操作和严格输入的非法原文。"""

        self._frame._configuration_locked = not enabled
        pending_invalid = {}
        for field in self._all_numeric_inputs():
            editor = self._numeric_editor(field)
            if editor is not None and not field.input_is_acceptable():
                pending_invalid[field] = editor.text()
        for section in self._frame._configuration_sections:
            section.setEnabled(enabled)
        if enabled:
            self._on_monkey_enabled_changed(self._frame.monkey_check.isChecked())
            worker_running = (
                self._frame._package_worker is not None and self._frame._package_worker.isRunning()
            )
            self._frame.get_package_btn.setEnabled(
                not worker_running and self._frame._can_operate_device()
            )
        for field, raw_text in pending_invalid.items():
            editor = self._numeric_editor(field)
            if editor is not None and editor.text() != raw_text:
                editor.setText(raw_text)
