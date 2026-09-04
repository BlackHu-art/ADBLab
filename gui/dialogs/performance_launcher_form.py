"""提供 MobilePerf 配置表单构建、控件交互与数字输入校验。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
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
from gui.styles import BaseStyles
from gui.styles.fluent import apply_label_role, configure_button
from gui.styles.icon_loader import get_themed_icon
from gui.styles.typography import FontRole
from gui.widgets.preset_spin_box import StrictIntComboBox, StrictIntLineEdit
from services.mobileperf_runner import MobilePerfMonkeyConfig

CONFIG_HINTS = {
    "package": (
        "Test process. Example: package=com.alibaba.ailabs.genie.contacts. "
        "Supports multiple processes separated by ';'; if child processes are included, "
        "put the main process first."
    ),
    "frequency": "Collect frequency. Integer, unit: second.",
    "timeout": "Collect timeout. Integer, unit: minute. Example: 72 hours = 4320.",
    "dumpheap_freq": "Dumpheap frequency. Integer, unit: minute.",
    "serialnum": "ADB serialnum comes from the selected device in the window title.",
    "exceptionlog": (
        "Exception log tags checked in logcat. Matching logs are saved to exception.log; "
        "multiple tags are separated by ';'."
    ),
    "monkey": (
        "Monkey test switch. When enabled, Monkey uses the same timeout as "
        "MobilePerf collection and is stopped when the run finishes or Stop is clicked."
    ),
    "save_path": (
        "Test results save path. Avoid spaces. A device-name folder is appended automatically."
    ),
    "phone_log_path": "Device paths pulled to PC when the test ends; multiple paths use ';'.",
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
        """嵌入主工作区时移除配置区的纵向滚动嵌套。"""

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
        root.setSpacing(8)
        self._frame._root_layout = root

        # ── 页头卡片：标题、副标题与设备连接状态徽标 ─────────────────────
        # 视觉重设计：页面内容顶部统一为 Fluent CardWidget 卡片页头。
        # 副标题保持 UI 字体角色并以 TEXT_SECONDARY 次级文字色维持视觉层级。
        self._frame.header_card = CardWidget()
        self._frame.header_card.setObjectName("dialogHeaderCard")
        self._frame.header_card.setBorderRadius(BaseStyles.RADIUS_LG)
        hl = QVBoxLayout(self._frame.header_card)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._frame.dialog_title = apply_label_role(
            BodyLabel("Performance Launcher"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self._frame.dialog_title.setObjectName("dialogTitle")
        self._frame.status_badge = InfoBadge.info("No device", self._frame.header_card)
        self._frame.status_badge.setProperty("fontRole", FontRole.UI.value)
        self._frame.status_badge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self._frame.status_badge.setToolTip("Device availability for performance capture")
        title_row.addWidget(self._frame.dialog_title)
        title_row.addStretch(1)
        title_row.addWidget(self._frame.status_badge)
        self._frame.dialog_subtitle = apply_label_role(
            BodyLabel("Configure and launch device performance capture"),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        self._frame.dialog_subtitle.setObjectName("dialogSubtitle")
        self._frame.dialog_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self._frame.dialog_subtitle)
        root.addWidget(self._frame.header_card)

        self._frame._config_group = self._build_config_section(package_name)
        # 长提示和 Monkey 选项的自然尺寸不得反向顶高原生窗口；滚动视口隔离
        # 配置卡的 sizeHint，并在二级窗口被小屏适配器压窄时保留横纵到达路径。
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
        self._frame._config_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._frame._config_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._frame._config_scroll.setMinimumSize(QSize())
        self._frame._config_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._frame._config_scroll.setWidget(self._frame._config_group)
        root.addWidget(self._frame._config_scroll, 1)
        self._frame.log_view = self._build_log_view()
        self._frame.log_view.setFixedHeight(96)
        # P3 图表双视图：日志/图表用可折叠容器承载，SegmentedControl 切换（集成契约：
        # _build_chart_toggle 由页面注入切换回调，默认隐藏图表视图）。
        self._frame._chart_toggle, self._frame._chart_stack = self._build_chart_toggle()
        self._frame._chart_stack.addWidget(self._frame.log_view)
        root.addWidget(self._frame._chart_toggle)
        root.addWidget(self._frame._chart_stack)
        self._frame._action_row = self._build_actions()
        root.addWidget(self._frame._action_row)

    def _build_config_section(self, package_name: str) -> HeaderCardWidget:
        """按分页前版本的九项纵向表单构建配置区。"""

        group = HeaderCardWidget("MobilePerf Config")
        group.viewLayout.setDirection(QBoxLayout.Direction.TopToBottom)
        apply_label_role(group.headerLabel, FontRole.TITLE, color_key="TITLE_COLOR")
        group.setObjectName("performanceConfig")
        grid = QGridLayout()
        group.viewLayout.addLayout(grid)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)

        self._frame.package_edit = LineEdit()
        self._frame.package_edit.setText(package_name)
        self._frame.package_edit.setPlaceholderText("com.example.app")
        self._frame.get_package_btn = PushButton()
        self._frame.get_package_btn.setText("Get Current Package")
        self._frame.get_package_btn.setIcon(get_themed_icon("target.svg"))
        self._frame.get_package_btn.setIconSize(QSize(14, 14))
        self._frame.get_package_btn.setProperty("iconName", "target.svg")
        self._frame.get_package_btn.setToolTip("Fetch current foreground app package")
        self._frame.get_package_btn.clicked.connect(self._frame.fetch_current_package)
        self._frame.frequency_input = StrictIntComboBox(
            1,
            2_147_483_647,
            5,
            presets=(1, 2, 5, 10),
        )
        self._frame.timeout_input = StrictIntComboBox(
            1,
            2_147_483_647,
            600,
            presets=(10, 30, 60, 120, 600, 4320),
        )
        self._frame.dumpheap_input = StrictIntComboBox(
            1,
            2_147_483_647,
            60,
            presets=(5, 10, 30, 60, 120),
        )
        self._frame.frequency_combo = self._frame.frequency_input
        self._frame.timeout_combo = self._frame.timeout_input
        self._frame.dumpheap_combo = self._frame.dumpheap_input
        self._frame.frequency_unit_label = self._unit_label("s", "seconds")
        self._frame.timeout_unit_label = self._unit_label("min", "minutes")
        self._frame.dumpheap_unit_label = self._unit_label("min", "minutes")
        for unit_label in (
            self._frame.frequency_unit_label,
            self._frame.timeout_unit_label,
            self._frame.dumpheap_unit_label,
        ):
            unit_label.setParent(group)
            unit_label.hide()

        self._frame.exception_edit = LineEdit()
        self._frame.exception_edit.setText("fatal exception;has died")
        self._frame.phone_log_edit = LineEdit()
        self._frame.phone_log_edit.setText("/data/anr")
        self._frame.monkey_check = CheckBox()
        self._frame.monkey_check.setText("Enable monkey")
        self._frame.monkey_check.toggled.connect(self._frame._on_monkey_enabled_changed)
        monkey_row = self._build_monkey_row()
        self._frame.save_path_edit = LineEdit()
        self._frame.save_path_edit.setText(self._frame._default_save_path())
        self._frame.save_path_edit.setPlaceholderText("Result root")
        self._frame.pick_save_btn = PushButton()
        self._frame.pick_save_btn.setText("Browse")
        self._frame.pick_save_btn.setToolTip("Select the MobilePerf result directory")
        self._frame.pick_save_btn.setIcon(get_themed_icon("folder.svg"))
        self._frame.pick_save_btn.setIconSize(QSize(14, 14))
        self._frame.pick_save_btn.setProperty("iconName", "folder.svg")
        self._frame.pick_save_btn.clicked.connect(self._frame._pick_save_path)
        save_row = self._row_widget(self._frame.save_path_edit, self._frame.pick_save_btn)

        self._frame.serialnum_label = apply_label_role(
            BodyLabel(self._frame.device_ip or "-"),
            FontRole.MONO,
            color_key="LOG_SUCCESS",
            bold=True,
        )
        self._frame.serialnum_label.setObjectName("onlineDeviceLabel")
        self._frame.serialnum_label.setToolTip(
            f"Selected online device: {self._frame.device_ip or '-'}"
        )
        self._frame.serialnum_label.setAccessibleName(
            f"Selected device: {self._frame.device_ip or '-'}"
        )
        self._frame.serialnum_label.setAccessibleDescription(
            f"Selected device: {self._frame.device_ip or '-'}"
        )

        row = self._add_config_row(
            grid,
            0,
            "package",
            self._row_widget(self._frame.package_edit, self._frame.get_package_btn),
            CONFIG_HINTS["package"],
        )
        row = self._add_config_row(
            grid,
            row,
            "serialnum",
            self._frame.serialnum_label,
            CONFIG_HINTS["serialnum"],
        )
        row = self._add_config_row(
            grid,
            row,
            "frequency",
            self._frame.frequency_input,
            CONFIG_HINTS["frequency"],
        )
        row = self._add_config_row(
            grid,
            row,
            "timeout",
            self._frame.timeout_input,
            CONFIG_HINTS["timeout"],
        )
        row = self._add_config_row(
            grid,
            row,
            "dumpheap_freq",
            self._frame.dumpheap_input,
            CONFIG_HINTS["dumpheap_freq"],
        )
        row = self._add_config_row(
            grid,
            row,
            "exceptionlog",
            self._frame.exception_edit,
            CONFIG_HINTS["exceptionlog"],
        )
        row = self._add_config_row(
            grid,
            row,
            "monkey",
            monkey_row,
            CONFIG_HINTS["monkey"],
        )
        row = self._add_config_row(
            grid,
            row,
            "save_path",
            save_row,
            CONFIG_HINTS["save_path"],
        )
        self._add_config_row(
            grid,
            row,
            "phone_log_path",
            self._frame.phone_log_edit,
            CONFIG_HINTS["phone_log_path"],
        )

        self._frame._configuration_sections = (group,)
        self._on_monkey_enabled_changed(self._frame.monkey_check.isChecked())
        self._frame._apply_monkey_control_widths()
        return group

    def _build_monkey_row(self) -> QWidget:
        container = QWidget()
        container.setObjectName("performanceMonkeyOptions")
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        self._frame.monkey_throttle_input = StrictIntComboBox(
            1,
            2_147_483_647,
            500,
            presets=(100, 200, 300, 500, 1000, 2000),
        )
        self._frame.monkey_throttle_combo = self._frame.monkey_throttle_input
        self._frame.monkey_seed_input = StrictIntLineEdit(
            minimum=0,
            maximum=2_147_483_647,
            value=1_000_000,
        )
        self._frame.monkey_seed_edit = self._frame.monkey_seed_input
        self._frame.monkey_throttle_unit_label = self._unit_label("ms")
        self._frame.monkey_throttle_unit_label.setParent(container)
        self._frame.monkey_throttle_unit_label.hide()

        throttle_hint = "Monkey --throttle interval in milliseconds."
        seed_hint = "Monkey -s random seed."
        self._frame.monkey_check.setAccessibleName("Enable Monkey test")
        self._apply_hint(self._frame.monkey_check, CONFIG_HINTS["monkey"])
        self._apply_hint(self._frame.monkey_throttle_input, throttle_hint)
        self._apply_hint(self._frame.monkey_seed_input, seed_hint)
        self._frame.monkey_throttle_input.setAccessibleName("Monkey throttle interval")
        self._frame.monkey_seed_input.setAccessibleName("Monkey random seed")
        layout.addWidget(self._frame.monkey_check, 0, 0)
        layout.addWidget(
            self._inline_label("Throttle (ms)", throttle_hint),
            0,
            1,
        )
        layout.addWidget(self._frame.monkey_throttle_input, 0, 2)
        layout.addWidget(self._inline_label("Seed", seed_hint), 0, 3)
        layout.addWidget(self._frame.monkey_seed_input, 0, 4)

        self._frame.monkey_total_label = apply_label_role(
            BodyLabel("Total: 100%"), FontRole.UI, color_key="LOG_SUCCESS", bold=True
        )
        self._frame.monkey_total_label.setObjectName("monkeyTotalLabel")
        self._frame.monkey_total_label.setMinimumWidth(92)
        self._frame.monkey_total_label.setToolTip("Total: 100%")
        self._frame.monkey_total_label.setAccessibleName("Total: 100%")
        self._frame.monkey_total_label.setAccessibleDescription(
            "Monkey event percentage total: 100%"
        )
        self._frame._monkey_total_labels = [self._frame.monkey_total_label]
        layout.addWidget(self._frame.monkey_total_label, 0, 5)

        self._frame.monkey_pct_inputs = {}
        self._frame.monkey_pct_combos = self._frame.monkey_pct_inputs
        defaults = MobilePerfMonkeyConfig()
        for index, (label, attr, option_name) in enumerate(MONKEY_PERCENT_FIELDS):
            event_row, column = divmod(index, 2)
            field = StrictIntComboBox(
                0,
                100,
                getattr(defaults, attr),
                presets=(0, 5, 10, 15, 20, 25, 30, 40, 50, 100),
            )
            field.setMinimumWidth(64)
            tooltip = f"{label} percentage ({option_name})."
            self._apply_hint(field, tooltip)
            field.setAccessibleName(f"{label} percentage")
            field.valueChanged.connect(self._frame._update_monkey_total)
            field.validityChanged.connect(self._frame._update_monkey_total)
            self._frame.monkey_pct_inputs[attr] = field
            layout.addWidget(self._inline_label(label, tooltip), event_row + 1, column * 3)
            layout.addWidget(field, event_row + 1, column * 3 + 1)

        self._frame.monkey_ignore_crashes = CheckBox()
        self._frame.monkey_ignore_crashes.setText("Ignore crashes")
        self._frame.monkey_ignore_timeouts = CheckBox()
        self._frame.monkey_ignore_timeouts.setText("Ignore timeouts")
        self._frame.monkey_ignore_security = CheckBox()
        self._frame.monkey_ignore_security.setText("Ignore security")
        self._frame.monkey_kill_after_error = CheckBox()
        self._frame.monkey_kill_after_error.setText("Kill after error")
        monkey_flags = (
            self._frame.monkey_ignore_crashes,
            self._frame.monkey_ignore_timeouts,
            self._frame.monkey_ignore_security,
            self._frame.monkey_kill_after_error,
        )
        flag_hints = (
            "Continue after an application crash.",
            "Continue after an application-not-responding timeout.",
            "Continue after a security exception.",
            "Stop Monkey after the first error.",
        )
        flag_names = (
            "Ignore application crashes",
            "Ignore application timeouts",
            "Ignore security exceptions",
            "Kill Monkey after error",
        )
        for checkbox, hint, accessible_name in zip(monkey_flags, flag_hints, flag_names):
            checkbox.setChecked(True)
            self._apply_hint(checkbox, hint)
            checkbox.setAccessibleName(accessible_name)
        flags_row = self._row_widget(*monkey_flags)
        layout.addWidget(flags_row, 6, 0, 1, 6)
        layout.setColumnStretch(5, 1)
        self._update_monkey_total()
        self._frame._apply_monkey_control_widths()
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
        container = QWidget()
        container.setObjectName("inlineRow")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, 1 if index == 0 else 0)
        return container

    def _build_log_view(self) -> PlainTextEdit:
        log_view = PlainTextEdit()
        log_view.setObjectName("performanceLog")
        log_view.setReadOnly(True)
        log_view.setUndoRedoEnabled(False)
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
        return segmented, stack

    def _build_actions(self) -> QWidget:
        container = QWidget()
        container.setObjectName("performanceActionRow")
        container.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._frame.status_label = apply_label_role(
            BodyLabel("Idle"), FontRole.UI, color_key="TEXT_SECONDARY"
        )
        self._frame.status_label.setObjectName("statusLabel")
        self._frame.status_label.setMinimumWidth(92)
        row.addWidget(self._frame.status_label, 0)

        self._frame.progress_bar = ProgressBar()
        self._frame.progress_bar.setObjectName("performanceProgress")
        self._frame.progress_bar.setRange(0, 100)
        self._frame.progress_bar.setValue(0)
        self._frame.progress_bar.setFormat("0%")
        self._frame.progress_bar.setTextVisible(True)
        self._frame.progress_bar.setMinimumWidth(160)
        row.addWidget(self._frame.progress_bar, 1)

        self._frame.perfetto_action = QAction(
            get_themed_icon("speedometer.svg"),
            "Open Perfetto",
            self._frame,
        )
        self._frame.perfetto_action.setObjectName("performancePerfettoAction")
        self._frame.perfetto_action.setToolTip("Open Perfetto trace viewer")
        self._frame.perfetto_action.triggered.connect(self._frame._trigger_open_perfetto)
        self._frame.result_action = QAction(
            get_themed_icon("folder-open.svg"),
            "Open Result",
            self._frame,
        )
        self._frame.result_action.setObjectName("performanceResultAction")
        self._frame.result_action.setToolTip("Open the latest MobilePerf result")
        self._frame.result_action.triggered.connect(self._frame._trigger_open_result)
        self._frame.result_action.setEnabled(False)

        self._frame.perfetto_btn = PushButton()
        self._frame.perfetto_btn.setText("Open Perfetto")
        self._frame.perfetto_btn.setIcon(get_themed_icon("speedometer.svg"))
        self._frame.perfetto_btn.setIconSize(QSize(14, 14))
        self._frame.perfetto_btn.setProperty("iconName", "speedometer.svg")
        self._frame.perfetto_btn.clicked.connect(self._frame.perfetto_action.trigger)
        self._frame.perfetto_action.changed.connect(self._frame._sync_perfetto_button)
        row.addWidget(self._frame.perfetto_btn)

        self._frame.result_btn = PushButton()
        self._frame.result_btn.setText("Open Result")
        self._frame.result_btn.setIcon(get_themed_icon("folder-open.svg"))
        self._frame.result_btn.setIconSize(QSize(14, 14))
        self._frame.result_btn.setProperty("iconName", "folder-open.svg")
        self._frame.result_btn.clicked.connect(self._frame.result_action.trigger)
        self._frame.result_action.changed.connect(self._frame._sync_result_button)
        row.addWidget(self._frame.result_btn)

        self._frame.stop_btn = PrimaryPushButton()
        configure_button(
            self._frame.stop_btn,
            text="Stop",
            tooltip="Stop the active performance collection",
            danger=True,
        )
        self._frame.stop_btn.setIcon(get_themed_icon("stop-circle.svg"))
        self._frame.stop_btn.setIconSize(QSize(14, 14))
        self._frame.stop_btn.setProperty("iconName", "stop-circle.svg")
        self._frame.stop_btn.clicked.connect(self._frame.stop_mobileperf)
        self._frame.stop_btn.setEnabled(False)
        row.addWidget(self._frame.stop_btn)

        self._frame.start_btn = PrimaryPushButton()
        self._frame.start_btn.setText("Start")
        self._frame.start_btn.setToolTip("Start performance collection with this configuration")
        self._frame.start_btn.setIcon(get_themed_icon("play.svg"))
        self._frame.start_btn.setIconSize(QSize(14, 14))
        self._frame.start_btn.setProperty("iconName", "play.svg")
        self._frame.start_btn.clicked.connect(self._frame.start_mobileperf)
        row.addWidget(self._frame.start_btn)
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
        """只锁定唯一配置分组，并保留严格输入的非法原文。"""

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
            self._frame.get_package_btn.setEnabled(not worker_running)
        for field, raw_text in pending_invalid.items():
            editor = self._numeric_editor(field)
            if editor is not None and editor.text() != raw_text:
                editor.setText(raw_text)
