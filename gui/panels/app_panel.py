"""提供应用管理、Monkey 测试、诊断和录屏操作面板。"""

import uuid
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, HeaderCardWidget, InfoBadge, InfoLevel

from adblab.application.cancellation import CancellationToken
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


@dataclass(frozen=True)
class _MonkeyPreparation:
    """保存一次只读查询的输入快照；UI 改动不修改已经提交给 worker 的目标。"""

    request_id: str
    devices: tuple[str, ...]
    package_name: str
    cancellation: CancellationToken
    parameters: dict | None = None


class AppPanel(BasePanel):
    """集中构建应用管理控件，并通过 SidePanelSignals 转发用户操作。"""

    monkey_preparation_requested = Signal(list, str, str, object)

    def build_ui(self) -> QWidget:
        self._monkey_preparation: _MonkeyPreparation | None = None
        self._monkey_information_signature: tuple | None = None
        self._monkey_closed = False
        self._package_query_pending = False
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
        self.package_tools_card = g_pm
        gl_pm = g_pm.viewLayout
        gl_pm.setSpacing(2)
        self.btn_batch_install = self._b(
            "批量安装 APK", "stack-plus.svg", tooltip="向所选设备安装 APK 文件"
        )
        self._add_responsive_row(gl_pm, self.btn_batch_install)
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
            "卸载应用", "trash.svg", tooltip="从所选设备卸载输入包名对应的应用"
        )
        self.clear_app_data_btn = self._b(
            "清除数据", "eraser.svg", tooltip="清除输入包名对应应用的数据与缓存"
        )
        self.restart_app_btn = self._b(
            "重启应用", "repeat.svg", tooltip="强制停止并重新启动输入包名对应的应用"
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
            "Activity 信息", "scroll.svg", tooltip="查看所选设备当前前台窗口与 Activity"
        )
        self.parse_apk_info_btn = self._b(
            "解析 APK", "magnifying-glass.svg", tooltip="查看本地 APK 元数据"
        )
        self.btn_force_stop = self._b(
            "强制停止", "stop-circle.svg", tooltip="强制停止输入包名对应的应用"
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
            "停用应用", "prohibit.svg", tooltip="停用输入包名对应的应用"
        )
        self.btn_enable_app = self._b(
            "启用应用", "check-circle.svg", tooltip="启用输入包名对应的应用"
        )
        self.btn_disable_user = self._b(
            "对当前用户停用",
            "user-switch.svg",
            tooltip="仅为设备当前用户停用输入包名对应的应用",
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
        self.monkey_package_info = self._label(
            "开始前会核对每台目标设备上的测试包信息。包名为空时读取各设备前台应用。"
        )
        self.monkey_package_info.setTextFormat(Qt.TextFormat.PlainText)
        self.monkey_package_info.setAccessibleName("测试包信息")
        gm_l.addWidget(self.monkey_package_info)
        self.monkey_get_package_btn = self._b(
            "获取包信息", "target.svg", tooltip="获取所选设备上的测试包安装状态与版本信息"
        )
        self.monkey_cancel_prepare_btn = self._b(
            "取消获取", "x.svg", tooltip="取消本次包信息查询，不会启动 Monkey"
        )
        self._add_responsive_row(
            gm_l, self.monkey_get_package_btn, self.monkey_cancel_prepare_btn,
            compact_columns=1, medium_columns=2, wide_columns=2,
        )

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
            "内存", "memory.svg", tooltip="查看输入包名对应应用的内存用量"
        )
        self.btn_cpuinfo = self._b(
            "CPU 负载", "cpu.svg", tooltip="查看所选设备各进程的 CPU 负载"
        )
        self.btn_battery_info = self._b(
            "电池", "battery-full.svg", tooltip="显示电池诊断信息"
        )
        self.btn_uptime = self._b("运行时长", "clock.svg", tooltip="查看设备开机时长与系统平均负载")
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
        self.category_stack.add_category(
            "daily", "截图与诊断", (g_pm, g_ts, g_m, g_r, g_perf)
        )
        self.category_stack.add_alias("monkey", "daily")
        self.category_stack.add_alias("packages", "daily")
        self.category_stack.add_alias("diagnostics", "daily")
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
        devices = self.selected_devices
        if not devices:
            self._update_action_states()
            return
        self._set_screenshot_running(True)
        self.signals.screenshot_requested.emit(devices)

    def _set_screenshot_running(self, running: bool):
        self._screenshot_running = running
        self._update_action_states()

    def _on_start_monkey(self):
        if (getattr(self, "_monkey_running", False) or self._monkey_preparation is not None
                or self._monkey_closed or not self.selected_devices):
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
        self._begin_monkey_preparation(params)

    def _begin_monkey_preparation(self, parameters: dict | None = None) -> None:
        """获取与开始共用只读准备；只有开始意图携带参数并在核对后提交原批次信号。"""
        if self._monkey_closed or self._monkey_preparation is not None or self._monkey_running:
            return
        devices = tuple(dict.fromkeys(device for device in self.selected_devices if device))
        if not devices:
            self._update_action_states()
            return
        preparation = _MonkeyPreparation(
            uuid.uuid4().hex, devices, self.package_text.strip(), CancellationToken(),
            dict(parameters) if parameters is not None else None,
        )
        self._monkey_preparation = preparation
        self._monkey_information_signature = None
        self.monkey_package_info.setText(f"正在核对 {len(devices)} 台设备上的测试包信息…")
        self._update_action_states()
        self.monkey_preparation_requested.emit(
            list(devices), preparation.package_name, preparation.request_id,
            preparation.cancellation,
        )

    def _cancel_monkey_preparation(self, message: str = "已取消获取测试包信息") -> None:
        """先撤销界面请求身份再通知 worker；已在途的查询结果不能恢复旧启动意图。"""
        pending = self._monkey_preparation
        self._monkey_preparation = None
        if pending is not None:
            pending.cancellation.request()
            self.monkey_package_info.setText(message)
        self._update_action_states()

    def on_monkey_preparation_finished(self, request_id: str, result: dict) -> None:
        """仅接受同代次且输入仍匹配的完整结果，空包自动填充不触发第二次准备。"""
        pending = self._monkey_preparation
        if pending is None or pending.request_id != request_id or self._monkey_closed:
            return
        current_devices = tuple(dict.fromkeys(device for device in self.selected_devices if device))
        if pending.devices != current_devices or pending.package_name != self.package_text.strip():
            self._cancel_monkey_preparation("操作目标或包名已改变，请重新获取测试包信息")
            return
        self._monkey_preparation = None
        if pending.cancellation.is_cancelled or not result.get("success"):
            self.monkey_package_info.setText(
                str(result.get("error") or "获取测试包信息失败，请重试")
            )
            self._update_action_states()
            return
        package = str(result.get("package_name", ""))
        packages = result.get("packages", [])
        if (not package or not isinstance(packages, list)
                or not all(isinstance(item, dict) for item in packages)
                or result.get("devices") != list(pending.devices)
                or [item.get("device_ip") for item in packages] != list(pending.devices)
                or any(item.get("package_name") != package for item in packages)
                or (pending.package_name and pending.package_name != package)):
            self.monkey_package_info.setText("测试包信息与本次目标不匹配，请重新获取")
            self._update_action_states()
            return
        if not pending.package_name:
            self.add_package_to_history(package)
        self._monkey_information_signature = (pending.devices, package)
        lines = [f"测试包：{package}"]
        for index, info in enumerate(packages, 1):
            version = info.get("version_name") or "版本名未提供"
            code = info.get("version_code") or "?"
            sdk = info.get("target_sdk") or "?"
            lines.append(f"设备 {index}：已安装 · {version} ({code}) · target SDK {sdk}")
        self.monkey_package_info.setText("\n".join(lines))
        self._update_action_states()
        if pending.parameters is None:
            return
        if pending.parameters != self._collect_monkey_params():
            self.monkey_package_info.setText("测试参数已改变，请重新开始以核对本次配置")
            return
        self._start_prepared_monkey(pending.devices, package, pending.parameters)

    def _start_prepared_monkey(
        self, devices: tuple[str, ...], package: str, parameters: dict,
    ) -> None:
        """准备成功后使用原目标和参数快照启动，既有运行/停止批次归属保持不变。"""
        params = dict(parameters, package_name=package)
        from core.settings_manager import AppSettings

        AppSettings.instance().set("monkey_params", params)
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

    def shutdown(self) -> None:
        """关闭准备准入并取消只读查询；实际 Monkey 进程由 Controller/model 统一停止。"""
        self._monkey_closed = True
        self._cancel_monkey_preparation()

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
        pending = self._monkey_preparation
        signature = (
            tuple(dict.fromkeys(device for device in self.selected_devices if device)),
            self.package_text.strip(),
        )
        if pending is not None and signature != (pending.devices, pending.package_name):
            self._cancel_monkey_preparation("操作目标或包名已改变，请重新获取测试包信息")
        if self._monkey_information_signature not in (None, signature):
            self._monkey_information_signature = None
            self.monkey_package_info.setText("操作目标或包名已改变，请重新获取测试包信息")
        has_device = bool(self.selected_devices)
        has_package = bool(self.package_text.strip())

        device_only_names = (
            "btn_batch_install",
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
        self._set_action_enabled(
            "btn_get_program", len(self.selected_devices) == 1 and not self._package_query_pending,
            (
                "正在读取当前应用，请等待完成"
                if self._package_query_pending
                else "请先选择设备" if not has_device else "请仅选择一台设备读取当前应用"
            ),
        )
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
        preparing = self._monkey_preparation is not None
        if self._monkey_closed:
            monkey_blocked_reason = "页面正在关闭"
        elif preparing:
            monkey_blocked_reason = "正在获取测试包信息，请等待完成或取消获取"
        elif monkey_running:
            monkey_blocked_reason = "Monkey 测试正在运行，请先停止测试"
        else:
            monkey_blocked_reason = "请先选择设备"
        self._set_action_enabled(
            "start_monkey_btn",
            has_device and not monkey_running and not preparing and not self._monkey_closed,
            monkey_blocked_reason,
        )
        self._set_action_enabled(
            "monkey_get_package_btn",
            has_device and not preparing and not monkey_running and not self._monkey_closed,
            monkey_blocked_reason,
        )
        self._set_action_enabled(
            "monkey_cancel_prepare_btn", preparing, "当前没有进行中的包信息查询"
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
        """不可用原因补充功能说明，恢复后不保留过期状态或影响辅助技术描述。"""

        button = getattr(self, name, None)
        if button is None:
            return
        button.setEnabled(enabled)
        description = str(button.property("functionalToolTip") or "")
        if not enabled:
            description = f"{description}\n不可用：{disabled_reason}"
        button.setToolTip(description)
        button.setAccessibleDescription(description)

    @property
    def package_text(self) -> str:
        return self.program_edit.currentText() if hasattr(self, "program_edit") else ""

    def set_package_query_pending(self, pending: bool) -> None:
        """由查询所有者同步运行态，阻止读取期间重复提交唯一包名输入的查询。"""

        self._package_query_pending = bool(pending)
        self._update_action_states()

    def _request_current_package(self) -> None:
        """只为一个明确目标发起包名读取，查询中的按钮和直接调用共享准入。"""

        if not self._package_query_pending:
            self._emit_device_action(self.signals.get_program_requested, single_device=True)

    def add_package_to_history(self, pkg: str):
        """更新唯一包名输入的历史候选，诊断与 Monkey 共用当前值。"""

        if self.program_edit.findText(pkg) < 0:
            self.program_edit.addItem(pkg)
        self.program_edit.setText(pkg)

    def connect_signals(self):
        """将本页控件连接到统一的 SidePanelSignals。"""
        LP = self.signals
        self.btn_batch_install.clicked.connect(
            lambda: self._emit_device_action(LP.batch_install_requested)
        )
        self.btn_get_program.clicked.connect(self._request_current_package)
        self.uninstall_btn.clicked.connect(
            lambda: self._emit_device_action(
                LP.uninstall_app_requested, self.package_text, fields=(self.program_edit,)
            )
        )
        self.clear_app_data_btn.clicked.connect(
            lambda: self._emit_device_action(
                LP.clear_app_data_requested, self.package_text, fields=(self.program_edit,)
            )
        )
        self.restart_app_btn.clicked.connect(
            lambda: self._emit_device_action(
                LP.restart_app_requested, self.package_text, fields=(self.program_edit,)
            )
        )
        self.print_activity_btn.clicked.connect(
            lambda: self._emit_device_action(LP.print_activity_requested)
        )
        self.parse_apk_info_btn.clicked.connect(lambda: LP.parse_apk_info_requested.emit())
        self.btn_disable_app.clicked.connect(
            lambda: self._emit_device_action(
                LP.disable_app_requested, self.package_text, fields=(self.program_edit,)
            )
        )
        self.btn_enable_app.clicked.connect(
            lambda: self._emit_device_action(
                LP.enable_app_requested, self.package_text, fields=(self.program_edit,)
            )
        )
        self.btn_force_stop.clicked.connect(
            lambda: self._emit_device_action(
                LP.force_stop_requested, self.package_text, fields=(self.program_edit,)
            )
        )
        self.btn_disable_user.clicked.connect(
            lambda: self._emit_device_action(
                LP.disable_app_for_user_requested, self.package_text, fields=(self.program_edit,)
            )
        )
        # Monkey 测试
        self.monkey_get_package_btn.clicked.connect(lambda: self._begin_monkey_preparation())
        self.monkey_cancel_prepare_btn.clicked.connect(lambda: self._cancel_monkey_preparation())
        self.start_monkey_btn.clicked.connect(lambda: self._on_start_monkey())
        self.kill_monkey_btn.clicked.connect(self._on_kill_monkey)
        # 诊断报告
        self.get_bugreport_btn.clicked.connect(
            lambda: self._emit_device_action(LP.capture_bugreport_requested)
        )
        self.get_anr_file_btn.clicked.connect(
            lambda: self._emit_device_action(LP.pull_anr_file_requested)
        )
        self.btn_retrieve_devices_logs.clicked.connect(
            lambda: self._emit_device_action(LP.retrieve_logs_requested)
        )
        self.btn_cleanup_logs.clicked.connect(
            lambda: self._emit_device_action(LP.cleanup_logs_requested)
        )
        # 性能诊断
        self.btn_meminfo.clicked.connect(
            lambda: self._emit_device_action(LP.dumpsys_meminfo_requested, self.package_text)
        )
        self.btn_cpuinfo.clicked.connect(
            lambda: self._emit_device_action(LP.dumpsys_cpuinfo_requested)
        )
        self.btn_battery_info.clicked.connect(
            lambda: self._emit_device_action(LP.dumpsys_battery_requested)
        )
        self.btn_uptime.clicked.connect(
            lambda: self._emit_device_action(LP.device_uptime_requested)
        )
        self.btn_top.clicked.connect(lambda: self._emit_device_action(LP.top_snapshot_requested))
        self.btn_gfx.clicked.connect(
            lambda: self._emit_device_action(
                LP.gfxinfo_requested, self.package_text, fields=(self.program_edit,)
            )
        )
        self.btn_wakelock.clicked.connect(
            lambda: self._emit_device_action(LP.wakelocks_requested)
        )
        self.btn_netstats.clicked.connect(
            lambda: self._emit_device_action(LP.netstats_detail_requested)
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
