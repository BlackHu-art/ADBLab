"""提供应用管理、Monkey 测试、诊断和录屏操作面板。"""

import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, HeaderCardWidget, InfoBadge, InfoLevel

from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.panels.base_panel import BasePanel
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role
from gui.widgets.category_stack import AdaptiveCategoryStack
from gui.widgets.responsive_layout import (
    RESPONSIVE_MINIMUM_TEXT_PROPERTY,
    RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY,
    GridMode,
    GridPlacement,
    WidthPolicy,
    paired_mode,
    span_tail_mode,
)


class AppPanel(BasePanel):
    """集中构建应用管理控件，并通过 SidePanelSignals 转发用户操作。"""

    def build_ui(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(1)
        lo.setContentsMargins(0, 0, 0, 0)
        self._apps_section_groups: list[HeaderCardWidget] = []
        self._build_apps_header(lo)
        self.category_stack = AdaptiveCategoryStack("apps", w)

        g_ts = self._card_group("文本与屏幕")
        gts_l = g_ts.viewLayout
        gts_l.setSpacing(2)
        self.email_text_sender = self._in("输入邮箱、验证码或其他文本…")
        self.btn_send_text = self._b(
            "发送文本", "text-aa.svg", tooltip="在所选设备上输入这段文本"
        )
        self._screenshot_running = False
        self._add_responsive_row(
            gts_l,
            (self.email_text_sender, 3),
            (self.btn_send_text, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.btn_screenshot = self._b(
            "截图", "camera.svg", tooltip="截取所选设备屏幕"
        )
        self.record_duration = self._combo(["10s", "20s", "30s", "60s", "120s", "180s", "300s"])
        self.record_duration.setCurrentText("30s")
        self.btn_screen_record = self._b(
            "开始录屏", "video-camera.svg", tooltip="开始录制所选设备屏幕"
        )
        self.btn_stop_record = self._b(
            "停止录屏", "stop-circle.svg", tooltip="停止正在进行的屏幕录制"
        )
        self.btn_stop_record.setEnabled(False)
        self._add_responsive_row(
            gts_l,
            (self.btn_screenshot, 1),
            (self.record_duration, 1),
            (self.btn_screen_record, 1),
            (self.btn_stop_record, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        g_pm = self._card_group("应用包管理")
        gl_pm = g_pm.viewLayout
        gl_pm.setSpacing(2)
        self.program_edit = self._combo_editable(font_role=FontRole.MONO)
        self.program_edit.setAccessibleName("应用包名")
        self.program_edit.setMinimumHeight(28)
        self.program_edit.setFont(self._font_mono)
        self.program_edit.setProperty("fontRole", FontRole.MONO.value)
        self.program_edit.setPlaceholderText("输入或选择应用包名")
        self.program_edit.addItems(self.panel._package_history)
        self.program_edit.currentTextChanged.connect(lambda _text: self._update_action_states())
        self.btn_get_program = self._b(
            "获取当前应用", "target.svg", tooltip="读取前台应用包名"
        )
        self._add_responsive_row(
            gl_pm,
            (self.program_edit, 2),
            (self.btn_get_program, 1),
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
        )
        self.uninstall_btn = self._b(
            "卸载应用", "trash.svg", tooltip="卸载选中的应用包"
        )
        self.clear_app_data_btn = self._b(
            "清除数据", "eraser.svg", tooltip="清除选中应用包的数据"
        )
        self.restart_app_btn = self._b(
            "重启应用", "repeat.svg", tooltip="强制停止并重新启动选中的应用包"
        )
        package_modes = (
            span_tail_mode("three", 3, 0, column_stretches=(1, 1, 1)),
            span_tail_mode("two", 2, 1, column_stretches=(1, 1)),
            span_tail_mode("one", 1, 2, column_stretches=(1,)),
        )
        first_package_binding = self._add_responsive_row(
            gl_pm,
            (self.uninstall_btn, 1),
            (self.clear_app_data_btn, 1),
            (self.restart_app_btn, 1),
            modes=package_modes,
            span_tail=True,
        )
        self.print_activity_btn = self._b(
            "Activity 信息", "scroll.svg", tooltip="显示选中应用包的 Activity 详情"
        )
        self.parse_apk_info_btn = self._b(
            "解析 APK", "magnifying-glass.svg", tooltip="查看本地 APK 元数据"
        )
        self.btn_force_stop = self._b(
            "强制停止", "stop-circle.svg", tooltip="强制停止选中的应用包"
        )
        second_package_binding = self._add_responsive_row(
            gl_pm,
            (self.print_activity_btn, 1),
            (self.parse_apk_info_btn, 1),
            (self.btn_force_stop, 1),
            modes=package_modes,
            span_tail=True,
        )
        self.btn_disable_app = self._b(
            "停用应用", "prohibit.svg", tooltip="停用选中的应用包"
        )
        self.btn_enable_app = self._b(
            "启用应用", "check-circle.svg", tooltip="启用选中的应用包"
        )
        self.btn_disable_user = self._b(
            "对当前用户停用",
            "user-switch.svg",
            tooltip="仅对当前用户停用该应用包",
        )
        third_package_binding = self._add_responsive_row(
            gl_pm,
            (self.btn_disable_app, 1),
            (self.btn_enable_app, 1),
            (self.btn_disable_user, 1),
            modes=package_modes,
            span_tail=True,
        )
        self.package_action_bindings = (
            first_package_binding,
            second_package_binding,
            third_package_binding,
        )
        self.package_action_binding = first_package_binding
        g_m = self._card_group("Monkey")
        gm_l = g_m.viewLayout
        gm_l.setSpacing(3)

        EVENTS_OPTS = ["100", "500", "1000", "5000", "10000", "50000", "100000", "500000"]
        THROTTLE_OPTS = [
            "0 ms",
            "100 ms",
            "200 ms",
            "300 ms",
            "500 ms",
            "1000 ms",
            "2000 ms",
        ]
        PCT_OPTS = ["0", "5", "10", "15", "20", "25", "30", "40", "50"]

        def _mk_combo(items):
            return self._combo_editable(items)

        self.monkey_events_label = self._label("事件数：")
        self.monkey_events = _mk_combo(EVENTS_OPTS)
        self._set_combo_int_validator(self.monkey_events, 1, 1_000_000)
        self.monkey_throttle_label = self._label("间隔：")
        self.monkey_throttle = _mk_combo(THROTTLE_OPTS)
        self._set_combo_int_validator(self.monkey_throttle, 0, 60_000, suffix="ms")
        self._pct_total_lbl = self._status_text("合计：--")
        # 使用 EditableComboBox 文本区精确覆盖合法上限；固定 em 会把下拉按钮
        # 留白重复计入，导致 Monkey 在仍有空间时过早从三组降成两组或一组。
        for field, maximum_text in (
            (self.monkey_events, "1000000"),
            (self.monkey_throttle, "60000 ms"),
        ):
            field.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
            field.setProperty(RESPONSIVE_MINIMUM_TEXT_PROPERTY, maximum_text)
            self._refresh_responsive_widget_minimum(field)

        pct_configs = [
            ("触摸", "touch"),
            ("移动", "motion"),
            ("轨迹球", "trackball"),
            ("导航", "nav"),
            ("主导航", "majornav"),
            ("系统键", "syskeys"),
            ("应用切换", "appswitch"),
            ("其他", "anyevent"),
            ("缩放", "pinch"),
        ]
        self._monkey_pct_combos = {}
        self._monkey_pct_labels = {}
        pct_widgets = []
        for label, key in pct_configs:
            lbl = self._label(f"{label}:")
            c = _mk_combo(PCT_OPTS)
            self._set_combo_int_validator(c, 0, 100)
            c.currentTextChanged.connect(self._update_pct_total)
            # 100 未列入常用预设，但仍是合法值；精确文本下限既保证可读，
            # 又保留默认三组、最小 1:1 两组、继续压窄一组的视觉节奏。
            c.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
            c.setProperty(RESPONSIVE_MINIMUM_TEXT_PROPERTY, "100")
            self._refresh_responsive_widget_minimum(c)
            self._monkey_pct_labels[key] = lbl
            self._monkey_pct_combos[key] = c
            pct_widgets.extend((lbl, c))
        # 参数行和百分比行共享标签轨道；Throttle 的单位已进入下拉值，
        # 不再占用第三组的标签列。
        label_width = (
            QFontMetrics(BaseStyles.font_for_role(FontRole.UI)).horizontalAdvance("应用切换：") + 4
        )
        for _lbl in (self.monkey_events_label, self.monkey_throttle_label):
            _lbl.setMinimumWidth(label_width)
        for _lbl in self._monkey_pct_labels.values():
            _lbl.setMinimumWidth(label_width)
        parameter_widgets = (
            self.monkey_events_label,
            self.monkey_events,
            self.monkey_throttle_label,
            self.monkey_throttle,
            self._pct_total_lbl,
        )
        parameter_modes = (
            GridMode(
                "wide",
                6,
                0,
                placements=(
                    GridPlacement(0, 0, 0),
                    GridPlacement(1, 0, 1),
                    GridPlacement(2, 0, 2),
                    GridPlacement(3, 0, 3),
                    GridPlacement(4, 0, 4, column_span=2),
                ),
                column_stretches=(0, 1, 0, 1, 0, 1),
                equal_column_groups=((0, 2, 4), (1, 3, 5)),
            ),
            GridMode(
                "medium",
                4,
                1,
                placements=(
                    GridPlacement(0, 0, 0),
                    GridPlacement(1, 0, 1),
                    GridPlacement(2, 0, 2),
                    GridPlacement(3, 0, 3),
                    GridPlacement(4, 1, 0, column_span=4),
                ),
                column_stretches=(0, 1, 0, 1),
                equal_column_groups=((0, 2), (1, 3)),
            ),
            GridMode(
                "compact",
                2,
                2,
                placements=(
                    GridPlacement(0, 0, 0),
                    GridPlacement(1, 0, 1),
                    GridPlacement(2, 1, 0),
                    GridPlacement(3, 1, 1),
                    GridPlacement(4, 2, 0, column_span=2),
                ),
                column_stretches=(0, 1),
            ),
            # 极窄宽度下标签与字段上下堆叠：行最小宽从"标签+字段"降为
            # max(标签, 字段)，保证字段值在最小面板宽度下仍贴左可见，
            # 而不是被并排布局推到视口右侧外。
            GridMode(
                "stacked",
                1,
                3,
                placements=tuple(
                    GridPlacement(index, index, 0) for index in range(len(parameter_widgets))
                ),
                column_stretches=(1,),
            ),
        )
        self.monkey_parameter_binding = self._add_responsive_row(
            gm_l,
            *parameter_widgets,
            spacing=3,
            policies=(
                WidthPolicy.NATURAL,
                WidthPolicy.SHRINKABLE,
                WidthPolicy.NATURAL,
                WidthPolicy.SHRINKABLE,
                WidthPolicy.WRAPPING,
            ),
            modes=parameter_modes,
        )
        self.monkey_percentage_binding = self._add_responsive_row(
            gm_l,
            *pct_widgets,
            spacing=3,
            policies=tuple(
                policy
                for _key in pct_configs
                for policy in (WidthPolicy.NATURAL, WidthPolicy.SHRINKABLE)
            ),
            modes=(
                paired_mode("three", 3, 0),
                paired_mode("two", 2, 1),
                paired_mode("one", 1, 2),
                # 同参数行：极窄宽度下每个标签/字段对独立成行、上下堆叠，
                # 字段值贴左可见。
                GridMode(
                    "stacked",
                    1,
                    3,
                    placements=tuple(
                        GridPlacement(index, index, 0) for index in range(len(pct_widgets))
                    ),
                    column_stretches=(1,),
                ),
            ),
        )
        self.monkey_chk_crashes = self._checkbox("忽略崩溃")
        self.monkey_chk_timeouts = self._checkbox("忽略超时")
        self.monkey_chk_security = self._checkbox("忽略安全异常")
        self._add_responsive_row(
            gm_l,
            self.monkey_chk_crashes,
            self.monkey_chk_timeouts,
            self.monkey_chk_security,
            spacing=8,
            compact_columns=1,
            medium_columns=2,
            wide_columns=3,
        )

        self.start_monkey_btn = self._b(
            "开始测试", "robot.svg", tooltip="按当前配置启动 Monkey 测试"
        )
        self.kill_monkey_btn = self._b(
            "停止测试", "skull.svg", tooltip="停止正在运行的 Monkey 测试"
        )
        self._set_monkey_running(False)
        self._add_responsive_row(
            gm_l,
            (self.start_monkey_btn, 1),
            (self.kill_monkey_btn, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=2,
        )
        g_r = self._card_group("报告与日志")
        gr_l = g_r.viewLayout
        gr_l.setSpacing(2)
        self.get_bugreport_btn = self._b(
            "生成 Bugreport", "bug.svg", tooltip="收集 Android bugreport"
        )
        self.get_anr_file_btn = self._b(
            "提取 ANR", "warning.svg", tooltip="提取应用无响应报告"
        )
        self.btn_retrieve_devices_logs = self._b(
            "提取日志",
            "file-arrow-down.svg",
            tooltip="从所选设备复制诊断日志",
        )
        self.btn_cleanup_logs = self._b(
            "清理日志", "broom.svg", tooltip="删除所选设备上的已收集日志"
        )
        self._add_responsive_row(
            gr_l,
            (self.get_bugreport_btn, 1),
            (self.get_anr_file_btn, 1),
            (self.btn_retrieve_devices_logs, 1),
            (self.btn_cleanup_logs, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        g_perf = self._card_group("性能诊断")
        gl_perf = g_perf.viewLayout
        gl_perf.setSpacing(2)

        self.btn_meminfo = self._b(
            "内存", "memory.svg", tooltip="显示选中应用包的内存用量"
        )
        self.btn_cpuinfo = self._b(
            "CPU 负载", "cpu.svg", tooltip="显示选中应用包的 CPU 用量"
        )
        self.btn_battery_info = self._b(
            "电池", "battery-full.svg", tooltip="显示电池诊断信息"
        )
        self.btn_uptime = self._b("运行时长", "clock.svg", tooltip="显示设备与进程运行时长")
        self._add_responsive_row(
            gl_perf,
            (self.btn_meminfo, 1),
            (self.btn_cpuinfo, 1),
            (self.btn_battery_info, 1),
            (self.btn_uptime, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )

        self.btn_top = self._b(
            "进程快照", "chart-bar.svg", tooltip="采集进程资源占用快照"
        )
        self.btn_gfx = self._b("GFX 信息", "image.svg", tooltip="显示帧渲染统计信息")
        self.btn_wakelock = self._b("唤醒锁", "lock.svg", tooltip="显示活动的电源唤醒锁")
        self.btn_netstats = self._b(
            "网络统计", "chart-line.svg", tooltip="显示网络用量统计"
        )
        self._add_responsive_row(
            gl_perf,
            (self.btn_top, 1),
            (self.btn_gfx, 1),
            (self.btn_wakelock, 1),
            (self.btn_netstats, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=4,
        )
        self.category_stack.add_category("daily", "日常操作", (g_ts,))
        self.category_stack.add_category("packages", "应用包", (g_pm,))
        self.category_stack.add_category("monkey", "Monkey 测试", (g_m,))
        self.category_stack.add_category(
            "diagnostics",
            "诊断工具",
            (g_r, g_perf),
        )
        self.category_stack.current_changed.connect(
            lambda _key: self.apply_responsive_width(0)
        )
        lo.addWidget(self.category_stack)
        lo.addStretch()

        # 恢复上次使用的 Monkey 参数，避免切换页签后丢失测试配置。
        self._load_monkey_params()
        self._recording_running = False
        self._recording_active_devices = ()
        self._recording_pending_count = 0
        self._recording_pending_devices = set()
        self._recording_batch_id = ""
        self._recording_stopping = False
        self._monkey_active_devices = ()
        self._monkey_pending_count = 0
        self._monkey_pending_devices = set()
        self._monkey_batch_id = ""
        self._monkey_stopping = False
        BaseStyles.theme_changed.connect(self._on_theme_changed_apps)
        self._update_action_states()
        return w

    # ── 卡片化页头与分区视觉 ─────────────────────────────────────────────

    def _card_group(self, t: str) -> HeaderCardWidget:
        """创建 qfluentwidgets Card 分区；标题与内容区由 Card 提供。"""

        card = self._card(t)
        self._apps_section_groups.append(card)
        return card

    def _build_apps_header(self, lo) -> None:
        """构建页头：标题、副标题与设备可用性状态徽标。"""

        header = QWidget()
        header.setObjectName("appsHeader")
        self.panel_header = header
        hl = QVBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 4)
        hl.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.apps_title = apply_label_role(
            BodyLabel("应用与自动化"), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self.apps_status_badge = InfoBadge("未选择", self)
        self.apps_status_badge.setObjectName("appsStatusBadge")
        self.apps_status_badge.setProperty("fontRole", FontRole.UI.value)
        self.apps_status_badge.setFont(self._font_sm)
        # InfoBadge 默认对鼠标透明，会吞掉 tooltip 的悬停事件，这里恢复接收。
        self.apps_status_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.apps_status_badge.setToolTip("应用操作的设备选择状态")
        title_row.addWidget(self.apps_title)
        title_row.addStretch(1)
        title_row.addWidget(self.apps_status_badge)
        self.apps_subtitle = apply_label_role(
            BodyLabel("应用包、Monkey、屏幕采集与诊断工具"),
            FontRole.UI,
            color_key="TEXT_SECONDARY",
        )
        # 页签字体爆发测试断言面板内不存在 UI_SMALL 角色控件（历史不变式），
        # 副标题用 UI 角色 + 次级文字色维持视觉层级。
        self.apps_subtitle.setWordWrap(True)
        hl.addLayout(title_row)
        hl.addWidget(self.apps_subtitle)
        lo.addWidget(header)
        self._apply_apps_header_style()

    def _apply_apps_header_style(self) -> None:
        """按当前主题刷新页头徽标颜色。"""

        if not hasattr(self, "apps_title"):
            return
        self._refresh_apps_status_badge()

    def _refresh_apps_status_badge(self) -> None:
        """按设备选中状态刷新徽标；绿=可用，灰=未选择设备。"""

        if not hasattr(self, "apps_status_badge"):
            return
        has_device = bool(self.selected_devices)
        self.apps_status_badge.setText("可操作" if has_device else "未选择")
        self.apps_status_badge.setLevel(InfoLevel.SUCCESS if has_device else InfoLevel.INFOAMTION)

    def _on_theme_changed_apps(self, _name: str) -> None:
        """主题切换时重建页头样式（分区 Card 自动跟随主题）。"""

        self._apply_apps_header_style()

    # ── Monkey 参数持久化 ───────────────────────────────────────────────

    @staticmethod
    def _parse_monkey_throttle(text: object) -> int:
        """把下拉框中可见的毫秒单位还原为持久化和命令使用的整数。"""

        normalized = str(text).strip()
        if normalized.casefold().endswith("ms"):
            normalized = normalized[:-2].rstrip()
        return int(normalized)

    @classmethod
    def _format_monkey_throttle(cls, value: object) -> str:
        """用带单位的稳定形式显示 Monkey 节流间隔。"""

        return f"{cls._parse_monkey_throttle(value)} ms"

    def _load_monkey_params(self):
        from core.settings_manager import AppSettings

        p = AppSettings.instance().get("monkey_params", {})

        _events = int(p.get("events", 10000))
        self.monkey_events.setText(str(_events))
        try:
            throttle_text = self._format_monkey_throttle(p.get("throttle", 300))
        except (TypeError, ValueError):
            throttle_text = "300 ms"
        self.monkey_throttle.setText(throttle_text)
        # 针对各事件类型的默认值优化，从源头减少跳出
        _pct_defaults = {
            "touch": 40,
            "motion": 18,
            "trackball": 0,
            "nav": 10,
            "majornav": 10,
            "syskeys": 2,
            "appswitch": 0,
            "anyevent": 15,
            "pinch": 5,
        }
        for key, c in self._monkey_pct_combos.items():
            c.setText(str(p.get(key, _pct_defaults.get(key, 20))))
        self.monkey_chk_crashes.setChecked(p.get("ignore_crashes", True))
        self.monkey_chk_timeouts.setChecked(p.get("ignore_timeouts", True))
        self.monkey_chk_security.setChecked(p.get("ignore_security", True))
        self._update_pct_total()

    def reload_from_settings(self) -> bool:
        """幂等重载 Monkey 设置，供恢复默认值后的协调层调用。"""

        self._load_monkey_params()
        self._update_action_states()
        return True

    def _collect_monkey_params(self) -> dict | None:
        fields = [self.monkey_events, self.monkey_throttle, *self._monkey_pct_combos.values()]
        if not self._validate_fields(*fields):
            return None
        p = {
            "events": int(self.monkey_events.currentText().strip()),
            "throttle": self._parse_monkey_throttle(self.monkey_throttle.currentText()),
            "ignore_crashes": self.monkey_chk_crashes.isChecked(),
            "ignore_timeouts": self.monkey_chk_timeouts.isChecked(),
            "ignore_security": self.monkey_chk_security.isChecked(),
        }
        for key, c in self._monkey_pct_combos.items():
            p[key] = int(c.currentText().strip())
        return p

    def _update_pct_total(self, *_args):
        total = 0
        for c in self._monkey_pct_combos.values():
            try:
                total += int(c.currentText() or "0")
            except ValueError:
                pass
        self._pct_total_lbl.setText(f"合计：{total}%")
        if total == 100:
            color = BaseStyles.color("LOG_SUCCESS")
            self._pct_total_lbl.setToolTip("事件比例合计为 100%")
            self._pct_total_lbl.setAccessibleDescription("事件比例合计为百分之一百")
        else:
            color = BaseStyles.color("LOG_ERROR")
            self._pct_total_lbl.setToolTip("建议将事件比例调整为合计 100%")
            self._pct_total_lbl.setAccessibleDescription(
                f"当前事件比例合计为百分之 {total}，建议调整为百分之一百"
            )
        self._pct_total_lbl.setStyleSheet(
            f"color: {color}; font-weight: 600;"
            f" border: 1px solid {color}; border-radius: 7px; padding: 0 8px;"
        )

    def _on_record_start(self):
        if getattr(self, "_recording_running", False):
            return
        devices = tuple(dict.fromkeys(device for device in self.selected_devices if device))
        if not devices:
            self._update_action_states()
            return
        self._recording_active_devices = devices
        self._recording_pending_count = len(devices)
        self._recording_pending_devices = set(devices)
        self._recording_batch_id = uuid.uuid4().hex
        self._recording_stopping = False
        self._recording_running = True
        self._update_action_states()
        dur = int(self.record_duration.currentText().replace("s", ""))
        self.signals.screen_record_batch_requested.emit(
            list(devices),
            dur,
            self._recording_batch_id,
        )

    def _on_record_stop(self):
        if getattr(self, "_recording_stopping", False):
            return
        targets = tuple(getattr(self, "_recording_active_devices", ()))
        batch_id = getattr(self, "_recording_batch_id", "")
        if not targets or not batch_id:
            return
        self._recording_stopping = True
        self._update_action_states()
        self.signals.stop_screen_record_batch_requested.emit(list(targets), batch_id)

    def on_recording_target_finished(self, batch_id: str, device: str) -> None:
        """仅消费当前批次中尚未完成的设备终态。"""

        if batch_id != getattr(self, "_recording_batch_id", ""):
            return
        pending_devices = getattr(self, "_recording_pending_devices", set())
        if device not in pending_devices:
            return
        pending_devices.discard(device)
        self._recording_pending_count = len(pending_devices)
        if pending_devices:
            return
        self._recording_pending_count = 0
        self._recording_pending_devices = set()
        self._recording_active_devices = ()
        self._recording_batch_id = ""
        self._recording_stopping = False
        self._recording_running = False
        self._update_action_states()

    def on_recording_finished(self, *_legacy_args) -> None:
        """保留旧接口名称；无批次信息的终态不会改变当前任务。"""

        if len(_legacy_args) == 2:
            self.on_recording_target_finished(*_legacy_args)

    def on_operation_completed(self, operation: str, _success: bool, _message: str):
        if operation == "screenshot":
            if _message.startswith("Screenshot completed:"):
                self._set_screenshot_running(False)
            elif _message in {"⚠️ No devices selected", "Unable to prepare screenshot directory"}:
                self._set_screenshot_running(False)
        elif operation == "stop_recording" and not _success:
            self._recording_stopping = False
            self._update_action_states()
        elif operation == "kill_monkey" and not _success:
            self._monkey_stopping = False
            self._update_action_states()

    def _on_screenshot(self):
        if self._screenshot_running:
            return
        self._set_screenshot_running(True)
        self.signals.screenshot_requested.emit(self.selected_devices)

    def _set_screenshot_running(self, running: bool):
        self._screenshot_running = running
        self._update_action_states()

    def _on_start_monkey(self):
        if getattr(self, "_monkey_running", False):
            return
        params = self._collect_monkey_params()
        if params is None:
            return
        # Monkey 允许非 100% 的事件比例，但必须提示分布不可预测。
        total = sum(int(c.currentText() or "0") for c in self._monkey_pct_combos.values())
        if total != 100:
            FluentMessageBox.warning(
                self,
                "事件比例未达到 100%",
                f"当前事件比例合计为 {total}%，不是 100%。\n"
                "Monkey 仍会运行，但事件分布可能不符合预期。\n\n"
                "建议调整各项比例，使合计达到 100%。",
            )
        params["package_name"] = self.package_text
        from core.settings_manager import AppSettings

        AppSettings.instance().set("monkey_params", params)
        devices = tuple(dict.fromkeys(device for device in self.selected_devices if device))
        if not devices:
            self._update_action_states()
            return
        self._monkey_active_devices = devices
        self._monkey_pending_count = len(devices)
        self._monkey_pending_devices = set(devices)
        self._monkey_batch_id = uuid.uuid4().hex
        self._monkey_stopping = False
        self._set_monkey_running(True)
        self.signals.start_monkey_batch_requested.emit(
            list(devices),
            params,
            self._monkey_batch_id,
        )

    def on_monkey_target_finished(self, batch_id: str, device: str) -> None:
        """按批次和设备去重 Monkey 终态，忽略迟到结果。"""

        if batch_id != getattr(self, "_monkey_batch_id", ""):
            return
        pending_devices = getattr(self, "_monkey_pending_devices", set())
        if device not in pending_devices:
            return
        pending_devices.discard(device)
        self._monkey_pending_count = len(pending_devices)
        if pending_devices:
            return
        self._monkey_pending_count = 0
        self._monkey_pending_devices = set()
        self._monkey_active_devices = ()
        self._monkey_batch_id = ""
        self._monkey_stopping = False
        self._set_monkey_running(False)

    def _on_kill_monkey(self):
        if getattr(self, "_monkey_stopping", False):
            return
        targets = tuple(getattr(self, "_monkey_active_devices", ()))
        if not targets:
            targets = tuple(dict.fromkeys(device for device in self.selected_devices if device))
        if not targets:
            return
        batch_id = getattr(self, "_monkey_batch_id", "")
        if not batch_id:
            self.signals.kill_monkey_requested.emit(list(targets))
            return
        self._monkey_stopping = True
        self._update_action_states()
        self.signals.kill_monkey_batch_requested.emit(list(targets), batch_id)

    def _set_monkey_running(self, running: bool):
        self._monkey_running = running
        if hasattr(self, "program_edit"):
            self._update_action_states()

    def _update_action_states(self) -> None:
        """根据设备、包名和任务状态统一更新应用页操作可用性。"""

        self._refresh_apps_status_badge()
        if not hasattr(self, "program_edit"):
            return
        has_device = bool(self.selected_devices)
        has_package = bool(self.package_text.strip())

        device_only_names = (
            "btn_get_program",
            "btn_send_text",
            "print_activity_btn",
            "get_bugreport_btn",
            "get_anr_file_btn",
            "btn_retrieve_devices_logs",
            "btn_cleanup_logs",
            "btn_meminfo",
            "btn_cpuinfo",
            "btn_battery_info",
            "btn_uptime",
            "btn_top",
            "btn_wakelock",
            "btn_netstats",
        )
        package_names = (
            "uninstall_btn",
            "clear_app_data_btn",
            "restart_app_btn",
            "btn_force_stop",
            "btn_disable_app",
            "btn_enable_app",
            "btn_disable_user",
            "btn_gfx",
        )
        for name in device_only_names:
            self._set_action_enabled(name, has_device, "请先选择设备")
        for name in package_names:
            reason = "请先选择设备" if not has_device else "请先输入应用包名"
            self._set_action_enabled(name, has_device and has_package, reason)

        self._set_action_enabled(
            "btn_screenshot",
            has_device and not self._screenshot_running,
            "请先选择设备" if not has_device else "正在截图，请稍候",
        )
        self._set_action_enabled(
            "btn_screen_record",
            has_device and not bool(getattr(self, "_recording_running", False)),
            "请先选择设备" if not has_device else "屏幕录制已在运行",
        )
        self._set_action_enabled(
            "btn_stop_record",
            bool(getattr(self, "_recording_active_devices", ()))
            and bool(getattr(self, "_recording_running", False))
            and not bool(getattr(self, "_recording_stopping", False)),
            (
                "正在停止录屏"
                if getattr(self, "_recording_stopping", False)
                else "当前没有正在运行的录屏"
            ),
        )
        monkey_running = bool(getattr(self, "_monkey_running", False))
        self._set_action_enabled(
            "start_monkey_btn",
            has_device and has_package and not monkey_running,
            "请先选择设备并输入应用包名",
        )
        self._set_action_enabled(
            "kill_monkey_btn",
            monkey_running
            and bool(getattr(self, "_monkey_active_devices", ()))
            and not bool(getattr(self, "_monkey_stopping", False)),
            (
                "正在停止 Monkey"
                if getattr(self, "_monkey_stopping", False)
                else "Monkey 当前未运行"
            ),
        )

    def _set_action_enabled(self, name: str, enabled: bool, disabled_reason: str) -> None:
        button = getattr(self, name, None)
        if button is None:
            return
        button.setEnabled(enabled)
        button.setToolTip(
            str(button.property("functionalToolTip") or "") if enabled else disabled_reason
        )

    @property
    def package_text(self) -> str:
        return self.program_edit.currentText() if hasattr(self, "program_edit") else ""

    def add_package_to_history(self, pkg: str):
        if self.program_edit.findText(pkg) < 0:
            self.program_edit.addItem(pkg)
        self.program_edit.setText(pkg)

    def connect_signals(self):
        """将本页控件连接到统一的 SidePanelSignals。"""
        LP = self.signals
        self.btn_get_program.clicked.connect(
            lambda: LP.get_program_requested.emit(self.selected_devices)
        )
        self.uninstall_btn.clicked.connect(
            lambda: LP.uninstall_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.clear_app_data_btn.clicked.connect(
            lambda: LP.clear_app_data_requested.emit(self.selected_devices, self.package_text)
        )
        self.restart_app_btn.clicked.connect(
            lambda: LP.restart_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.print_activity_btn.clicked.connect(
            lambda: LP.print_activity_requested.emit(self.selected_devices)
        )
        self.parse_apk_info_btn.clicked.connect(lambda: LP.parse_apk_info_requested.emit())
        self.btn_disable_app.clicked.connect(
            lambda: LP.disable_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_enable_app.clicked.connect(
            lambda: LP.enable_app_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_force_stop.clicked.connect(
            lambda: LP.force_stop_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_disable_user.clicked.connect(
            lambda: LP.disable_app_for_user_requested.emit(self.selected_devices, self.package_text)
        )
        # Monkey 测试
        self.start_monkey_btn.clicked.connect(lambda: self._on_start_monkey())
        self.kill_monkey_btn.clicked.connect(self._on_kill_monkey)
        # 诊断报告
        self.get_bugreport_btn.clicked.connect(
            lambda: LP.capture_bugreport_requested.emit(self.selected_devices)
        )
        self.get_anr_file_btn.clicked.connect(
            lambda: LP.pull_anr_file_requested.emit(self.selected_devices)
        )
        self.btn_retrieve_devices_logs.clicked.connect(
            lambda: LP.retrieve_logs_requested.emit(self.selected_devices)
        )
        self.btn_cleanup_logs.clicked.connect(
            lambda: LP.cleanup_logs_requested.emit(self.selected_devices)
        )
        # 性能诊断
        self.btn_meminfo.clicked.connect(
            lambda: LP.dumpsys_meminfo_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_cpuinfo.clicked.connect(
            lambda: LP.dumpsys_cpuinfo_requested.emit(self.selected_devices)
        )
        self.btn_battery_info.clicked.connect(
            lambda: LP.dumpsys_battery_requested.emit(self.selected_devices)
        )
        self.btn_uptime.clicked.connect(
            lambda: LP.device_uptime_requested.emit(self.selected_devices)
        )
        self.btn_top.clicked.connect(lambda: LP.top_snapshot_requested.emit(self.selected_devices))
        self.btn_gfx.clicked.connect(
            lambda: LP.gfxinfo_requested.emit(self.selected_devices, self.package_text)
        )
        self.btn_wakelock.clicked.connect(
            lambda: LP.wakelocks_requested.emit(self.selected_devices)
        )
        self.btn_netstats.clicked.connect(
            lambda: LP.netstats_detail_requested.emit(self.selected_devices)
        )
        # 文本与媒体操作
        self.btn_screenshot.clicked.connect(self._on_screenshot)
        self.btn_screen_record.clicked.connect(lambda: self._on_record_start())
        self.btn_stop_record.clicked.connect(lambda: self._on_record_stop())
        self.btn_send_text.clicked.connect(lambda: self._submit_text(self.email_text_sender))
        self.email_text_sender.returnPressed.connect(
            lambda: self._submit_text(self.email_text_sender)
        )

    def _submit_text(self, field) -> None:
        """让按钮和 Return 路径共享同一必填及设备校验。"""

        devices = list(dict.fromkeys(device for device in self.selected_devices if device))
        if not devices or not self._validate_fields(field):
            self._update_action_states()
            return
        self.signals.send_text_requested.emit(devices, field.text().strip())
