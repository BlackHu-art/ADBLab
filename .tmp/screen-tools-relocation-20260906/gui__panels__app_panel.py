"""提供应用管理、Monkey 测试、诊断和录屏操作面板。"""

import re
import uuid
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    HeaderCardWidget,
    InfoBadge,
    InfoLevel,
    SimpleCardWidget,
)

from adblab.application.cancellation import CancellationToken
from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.i18n import tr
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
    span_tail_mode,
)
from gui.widgets.run_preset_bar import RunPresetBar
from utils.adb_values import normalize_android_package


@dataclass(frozen=True)
class _MonkeyPreparation:
    """保存一次只读查询的输入快照；UI 改动不修改已经提交给 worker 的目标。"""

    request_id: str
    devices: tuple[str, ...]
    package_name: str
    cancellation: CancellationToken
    parameters: dict | None = None


def _monkey_error_text(message: str) -> str:
    """只翻译包信息用例的已知错误模板，保留设备序号和其他原始诊断。"""

    templates = (
        "第 {index} 台设备无法获取前台应用，请输入测试包名后重试",
        "第 {index} 台设备无法查询已安装应用，请检查连接与调试授权",
        "第 {index} 台设备未安装目标应用，请先安装后重试",
        "第 {index} 台设备无法获取测试包信息，请重试",
        "第 {index} 台设备返回的包信息不匹配，请重新获取",
    )
    for template in templates:
        pattern = re.escape(template).replace(r"\{index\}", r"([0-9]+)")
        match = re.fullmatch(pattern, message)
        if match is not None:
            return tr(template).format(index=match.group(1))
    return tr(message)


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

        g_ts = self._card_group(tr("文本与屏幕"))
        gts_l = g_ts.viewLayout
        gts_l.setSpacing(2)
        self.email_text_sender = self._in(tr("输入邮箱、验证码或其他文本…"))
        self.btn_send_text = self._b(
            tr("发送文本"), "text-aa.svg", tooltip=tr("在所选设备上输入这段文本")
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
            tr("截图"), "camera.svg", tooltip=tr("截取所选设备屏幕")
        )
        self.record_duration = self._combo(["10s", "20s", "30s", "60s", "120s", "180s", "300s"])
        self.record_duration.setCurrentText("30s")
        self.btn_screen_record = self._b(
            tr("开始录屏"), "video-camera.svg", tooltip=tr("开始录制所选设备屏幕")
        )
        self.btn_stop_record = self._b(
            tr("停止录屏"), "stop-circle.svg", tooltip=tr("停止正在进行的屏幕录制")
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
        g_pm = self._card_group(tr("应用包管理"))
        self.package_tools_card = g_pm
        gl_pm = g_pm.viewLayout
        gl_pm.setSpacing(2)
        self.btn_batch_install = self._b(
            tr("批量安装 APK"), "stack-plus.svg", tooltip=tr("向所选设备安装 APK 文件")
        )
        self._add_responsive_row(gl_pm, self.btn_batch_install)
        self.program_edit = self._combo_editable(font_role=FontRole.MONO)
        self.program_edit.setAccessibleName(tr("应用包名"))
        self.program_edit.setMinimumHeight(28)
        self.program_edit.setFont(self._font_mono)
        self.program_edit.setProperty("fontRole", FontRole.MONO.value)
        self.program_edit.setPlaceholderText(tr("输入或选择应用包名"))
        self.program_edit.addItems(self.panel._package_history)
        self.program_edit.currentTextChanged.connect(lambda _text: self._update_action_states())
        self.btn_get_program = self._b(
            tr("获取当前应用"), "target.svg", tooltip=tr("读取前台应用包名")
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
            tr("卸载应用"), "trash.svg", tooltip=tr("从所选设备卸载输入包名对应的应用")
        )
        self.clear_app_data_btn = self._b(
            tr("清除数据"), "eraser.svg", tooltip=tr("清除输入包名对应应用的数据与缓存")
        )
        self.restart_app_btn = self._b(
            tr("重启应用"), "repeat.svg", tooltip=tr("强制停止并重新启动输入包名对应的应用")
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
            tr("Activity 信息"), "scroll.svg", tooltip=tr("查看所选设备当前前台窗口与 Activity")
        )
        self.parse_apk_info_btn = self._b(
            tr("解析 APK"), "magnifying-glass.svg", tooltip=tr("查看本地 APK 元数据")
        )
        self.btn_force_stop = self._b(
            tr("强制停止"), "stop-circle.svg", tooltip=tr("强制停止输入包名对应的应用")
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
            tr("停用应用"), "prohibit.svg", tooltip=tr("停用输入包名对应的应用")
        )
        self.btn_enable_app = self._b(
            tr("启用应用"), "check-circle.svg", tooltip=tr("启用输入包名对应的应用")
        )
        self.btn_disable_user = self._b(
            tr("对当前用户停用"),
            "user-switch.svg",
            tooltip=tr("仅为设备当前用户停用输入包名对应的应用"),
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
        self.monkey_section = g_m
        gm_l = g_m.viewLayout
        gm_l.setSpacing(16)
        self.monkey_package_card = SimpleCardWidget(g_m)
        package_info_layout = QVBoxLayout(self.monkey_package_card)
        package_info_layout.setContentsMargins(16, 16, 16, 16)
        package_info_layout.setSpacing(12)
        self.monkey_target_heading = self._monkey_group_heading(tr("测试目标"))
        self.monkey_target_summary = self._label("")
        self.monkey_target_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.monkey_target_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.monkey_target_summary.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.monkey_package_info = self._label(
            tr("开始前会核对每台目标设备上的测试包信息。包名为空时读取各设备前台应用。")
        )
        self.monkey_package_info.setTextFormat(Qt.TextFormat.PlainText)
        self.monkey_package_info.setAccessibleName(tr("测试包信息"))
        self.monkey_package_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.monkey_package_info.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        apply_label_role(self.monkey_package_info, FontRole.UI, color_key="TEXT_SECONDARY")
        self.monkey_get_package_btn = self._b(
            tr("获取包信息"), "target.svg", tooltip=tr("获取所选设备上的测试包安装状态与版本信息")
        )
        self.monkey_cancel_prepare_btn = self._b(
            tr("取消获取"), "x.svg", tooltip=tr("取消本次包信息查询，不会启动 Monkey")
        )
        self.monkey_prepare_actions = QWidget()
        prepare_actions_layout = QHBoxLayout(self.monkey_prepare_actions)
        prepare_actions_layout.setContentsMargins(0, 0, 0, 0)
        for button in (self.monkey_get_package_btn, self.monkey_cancel_prepare_btn):
            prepare_actions_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignRight)
        self.monkey_target_header_binding = self._add_responsive_row(
            package_info_layout,
            (self.monkey_target_heading, 1),
            self.monkey_prepare_actions,
            spacing=12,
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
            policies=(WidthPolicy.WRAPPING, WidthPolicy.NATURAL),
        )
        self.monkey_cancel_prepare_btn.hide()
        package_info_layout.addWidget(self.monkey_target_summary)
        package_info_layout.addWidget(self.monkey_package_info)
        gm_l.addWidget(self.monkey_package_card)

        self.monkey_parameters_card = SimpleCardWidget(g_m)
        parameter_layout = QVBoxLayout(self.monkey_parameters_card)
        parameter_layout.setContentsMargins(16, 16, 16, 16)
        parameter_layout.setSpacing(16)
        self.monkey_parameters_heading = self._monkey_group_heading(tr("运行参数"))
        self.monkey_preset_bar = RunPresetBar(
            "monkey", self.capture_run_parameters, self.apply_run_parameters,
            self.monkey_parameters_card,
        )
        # 方案栏自己按宽度换行；普通纵向布局保留完整行高，避免第二层网格裁剪按钮。
        preset_header = QVBoxLayout()
        preset_header.setSpacing(8)
        preset_header.addWidget(self.monkey_parameters_heading)
        preset_header.addWidget(self.monkey_preset_bar)
        parameter_layout.addLayout(preset_header)

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

        self.monkey_events_label = self._label(tr("事件数：").rstrip("：:"))
        self.monkey_events = _mk_combo(EVENTS_OPTS)
        self._set_combo_int_validator(self.monkey_events, 1, 1_000_000)
        self.monkey_throttle_label = self._label(tr("间隔：").rstrip("：:"))
        self.monkey_throttle = _mk_combo(THROTTLE_OPTS)
        self._set_combo_int_validator(self.monkey_throttle, 0, 60_000, suffix="ms")
        self._pct_total_lbl = self._status_text(tr("合计：--"))
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
            (tr("触摸"), "touch"),
            (tr("移动"), "motion"),
            (tr("轨迹球"), "trackball"),
            (tr("导航"), "nav"),
            (tr("主导航"), "majornav"),
            (tr("系统键"), "syskeys"),
            (tr("应用切换"), "appswitch"),
            (tr("其他"), "anyevent"),
            (tr("缩放"), "pinch"),
        ]
        self._monkey_pct_combos = {}
        self._monkey_pct_labels = {}
        pct_widgets = []
        for label, key in pct_configs:
            lbl = self._label(label)
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
        parameter_widgets = (
            self.monkey_events_label,
            self.monkey_events,
            self.monkey_throttle_label,
            self.monkey_throttle,
        )
        self.monkey_parameter_binding = self._add_responsive_row(
            parameter_layout,
            *parameter_widgets,
            spacing=10,
            policies=(
                WidthPolicy.NATURAL,
                WidthPolicy.SHRINKABLE,
                WidthPolicy.NATURAL,
                WidthPolicy.SHRINKABLE,
            ),
            modes=(
                self._monkey_field_mode("wide", 2, 0, 2),
                self._monkey_field_mode("stacked", 1, 1, 2),
            ),
        )
        self.monkey_seed_mode_label = self._label(tr("随机种子"))
        self.monkey_seed_mode = self._combo()
        self.monkey_seed_mode.addItem(tr("每次随机"), userData="random")
        self.monkey_seed_mode.addItem(tr("固定种子"), userData="fixed")
        self.monkey_seed_label = self._label(tr("种子值"))
        self.monkey_seed = _mk_combo(["1", "42", "2026"])
        self._set_combo_int_validator(self.monkey_seed, 0, 2147483647)
        self.monkey_seed.setText("1")
        self.monkey_seed.setToolTip(tr("固定种子可重复相同事件序列；实际种子会保存在运行记录中"))
        self.monkey_seed.setProperty(RESPONSIVE_SIZE_HINT_MINIMUM_PROPERTY, True)
        self.monkey_seed.setProperty(RESPONSIVE_MINIMUM_TEXT_PROPERTY, "2147483647")
        self._refresh_responsive_widget_minimum(self.monkey_seed)
        self.monkey_seed_binding = self._add_responsive_row(
            parameter_layout, self.monkey_seed_mode_label, self.monkey_seed_mode,
            self.monkey_seed_label, self.monkey_seed,
            spacing=10,
            policies=(WidthPolicy.NATURAL, WidthPolicy.SHRINKABLE) * 2,
            modes=(
                self._monkey_field_mode("wide", 2, 0, 2),
                self._monkey_field_mode("stacked", 1, 1, 2),
            ),
        )
        self.monkey_seed_mode.currentIndexChanged.connect(self._update_monkey_seed_state)
        self._update_monkey_seed_state()
        self.monkey_distribution_heading = self._monkey_group_heading(tr("事件分布"))
        self.monkey_distribution_header_binding = self._add_responsive_row(
            parameter_layout,
            (self.monkey_distribution_heading, 1),
            self._pct_total_lbl,
            spacing=8,
            compact_columns=1,
            medium_columns=2,
            wide_columns=2,
            policies=(WidthPolicy.WRAPPING, WidthPolicy.NATURAL),
        )
        self._pct_total_lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.monkey_percentage_binding = self._add_responsive_row(
            parameter_layout,
            *pct_widgets,
            spacing=10,
            policies=tuple(
                policy
                for _key in pct_configs
                for policy in (WidthPolicy.NATURAL, WidthPolicy.SHRINKABLE)
            ),
            modes=(
                self._monkey_field_mode("three", 3, 0, len(pct_configs)),
                self._monkey_field_mode("two", 2, 1, len(pct_configs)),
                self._monkey_field_mode("stacked", 1, 2, len(pct_configs)),
            ),
        )
        self.monkey_chk_crashes = self._checkbox(tr("忽略崩溃"))
        self.monkey_chk_timeouts = self._checkbox(tr("忽略超时"))
        self.monkey_chk_security = self._checkbox(tr("忽略安全异常"))
        self.monkey_exceptions_heading = self._monkey_group_heading(tr("异常处理"))
        parameter_layout.addWidget(self.monkey_exceptions_heading)
        self.monkey_exceptions_hint = self._label(tr("勾选后遇到相应异常仍继续测试。"))
        apply_label_role(self.monkey_exceptions_hint, FontRole.UI, color_key="TEXT_SECONDARY")
        self.monkey_exceptions_hint.hide()
        for checkbox in (
            self.monkey_chk_crashes, self.monkey_chk_timeouts, self.monkey_chk_security,
        ):
            checkbox.setToolTip(self.monkey_exceptions_hint.text())
            checkbox.setAccessibleDescription(self.monkey_exceptions_hint.text())
        self._add_responsive_row(
            parameter_layout,
            self.monkey_chk_crashes,
            self.monkey_chk_timeouts,
            self.monkey_chk_security,
            spacing=8,
            compact_columns=1,
            medium_columns=2,
            wide_columns=3,
        )
        gm_l.addWidget(self.monkey_parameters_card)

        self.start_monkey_btn = self._b(
            tr("开始测试"), "robot.svg", variant="accent", tooltip=tr("按当前配置启动 Monkey 测试")
        )
        self.kill_monkey_btn = self._b(
            tr("停止测试"), "skull.svg", tooltip=tr("停止正在运行的 Monkey 测试")
        )
        self.monkey_run_status = self._label("")
        self.monkey_run_status.setAccessibleName(tr("Monkey 运行状态"))
        apply_label_role(self.monkey_run_status, FontRole.UI, color_key="TEXT_SECONDARY")
        self.monkey_footer_binding = self._add_responsive_row(
            gm_l,
            (self.monkey_run_status, 1),
            self.start_monkey_btn,
            self.kill_monkey_btn,
            spacing=16,
            compact_columns=1,
            medium_columns=1,
            wide_columns=3,
            policies=(WidthPolicy.WRAPPING, WidthPolicy.NATURAL, WidthPolicy.NATURAL),
        )
        self.monkey_run_actions = self.monkey_footer_binding._container_ref()
        if (
            self.monkey_run_actions is not None
            and (footer_layout := self.monkey_run_actions.layout())
        ):
            footer_layout.setContentsMargins(16, 0, 16, 0)
        for button in (
            self.monkey_get_package_btn, self.monkey_cancel_prepare_btn,
            self.start_monkey_btn, self.kill_monkey_btn,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._set_monkey_running(False)
        g_r = self._card_group(tr("报告与日志"))
        gr_l = g_r.viewLayout
        gr_l.setSpacing(2)
        self.get_bugreport_btn = self._b(
            tr("生成 Bugreport"), "bug.svg", tooltip=tr("收集 Android bugreport")
        )
        self.get_anr_file_btn = self._b(
            tr("提取 ANR"), "warning.svg", tooltip=tr("提取应用无响应报告")
        )
        self.btn_retrieve_devices_logs = self._b(
            tr("提取日志"),
            "file-arrow-down.svg",
            tooltip=tr("从所选设备复制诊断日志"),
        )
        self.btn_cleanup_logs = self._b(
            tr("清理日志"), "broom.svg", tooltip=tr("删除所选设备上的已收集日志")
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
        g_perf = self._card_group(tr("性能诊断"))
        gl_perf = g_perf.viewLayout
        gl_perf.setSpacing(2)

        self.btn_meminfo = self._b(
            tr("内存"), "memory.svg", tooltip=tr("查看输入包名对应应用的内存用量")
        )
        self.btn_cpuinfo = self._b(
            tr("CPU 负载"), "cpu.svg", tooltip=tr("查看所选设备各进程的 CPU 负载")
        )
        self.btn_battery_info = self._b(
            tr("电池"), "battery-full.svg", tooltip=tr("显示电池诊断信息")
        )
        self.btn_uptime = self._b(
            tr("运行时长"), "clock.svg", tooltip=tr("查看设备开机时长与系统平均负载")
        )
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
            tr("进程快照"), "chart-bar.svg", tooltip=tr("采集进程资源占用快照")
        )
        self.btn_gfx = self._b(tr("GFX 信息"), "image.svg", tooltip=tr("显示帧渲染统计信息"))
        self.btn_wakelock = self._b(tr("唤醒锁"), "lock.svg", tooltip=tr("显示活动的电源唤醒锁"))
        self.btn_netstats = self._b(
            tr("网络统计"), "chart-line.svg", tooltip=tr("显示网络用量统计")
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
            "daily", tr("截图与诊断"), (g_pm, g_ts, g_m, g_r, g_perf)
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

    def _monkey_group_heading(self, text: str) -> BodyLabel:
        """沿用页面字体角色，以留白和字重区分 Monkey 内部表单组。"""

        label = BodyLabel(text, self)
        apply_label_role(label, FontRole.UI, color_key="TITLE_COLOR", bold=True)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _monkey_field_mode(name: str, columns: int, rank: int, count: int) -> GridMode:
        """标签始终在字段上方；按真实内容下限选择等宽的列数。"""

        placements = []
        for index in range(count):
            row = (index // columns) * 2
            column = index % columns
            placements.extend((
                GridPlacement(index * 2, row, column),
                GridPlacement(index * 2 + 1, row + 1, column),
            ))
        return GridMode(
            name, columns, rank,
            placements=tuple(placements),
            column_stretches=(1,) * columns,
            equal_column_groups=(tuple(range(columns)),) if columns > 1 else (),
        )

    def _update_monkey_presentation(self) -> None:
        """从既有准备与运行状态生成展示，不创建新的任务状态来源。"""

        if not hasattr(self, "monkey_run_status"):
            return
        package = self.package_text.strip()
        self.monkey_target_summary.setText(
            tr("测试包：{package}").format(package=package)
            if package else tr("未填写包名，将读取各设备前台应用。")
        )
        preparing = self._monkey_preparation is not None
        self.monkey_get_package_btn.setVisible(not preparing)
        self.monkey_cancel_prepare_btn.setVisible(preparing)
        if self._monkey_closed:
            status = tr("页面正在关闭")
        elif preparing:
            status = tr("正在核对测试包信息，可取消本次获取。")
        elif getattr(self, "_monkey_stopping", False):
            status = tr("正在停止 Monkey")
        elif getattr(self, "_monkey_running", False):
            status = tr("正在运行 · {count} 台设备").format(
                count=len(getattr(self, "_monkey_active_devices", ()))
            )
        elif not self.selected_devices:
            status = tr("请先选择设备")
        else:
            status = tr("开始时自动核对包信息，通过后执行当前参数。")
        self.monkey_run_status.setText(status)
        if actions_layout := self.monkey_prepare_actions.layout():
            actions_layout.invalidate()
        self.monkey_prepare_actions.updateGeometry()

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
            BodyLabel(tr("应用与自动化")), FontRole.TITLE, color_key="TITLE_COLOR"
        )
        self.apps_status_badge = InfoBadge(tr("未选择"), self)
        self.apps_status_badge.setObjectName("appsStatusBadge")
        self.apps_status_badge.setProperty("fontRole", FontRole.UI.value)
        self.apps_status_badge.setFont(self._font_sm)
        # InfoBadge 默认对鼠标透明，会吞掉 tooltip 的悬停事件，这里恢复接收。
        self.apps_status_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.apps_status_badge.setToolTip(tr("应用操作的设备选择状态"))
        title_row.addWidget(self.apps_title)
        title_row.addStretch(1)
        title_row.addWidget(self.apps_status_badge)
        self.apps_subtitle = apply_label_role(
            BodyLabel(tr("应用包、Monkey、屏幕采集与诊断工具")),
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
        self.apps_status_badge.setText(tr("可操作") if has_device else tr("未选择"))
        self.apps_status_badge.setLevel(InfoLevel.SUCCESS if has_device else InfoLevel.INFOAMTION)

    def _on_theme_changed_apps(self, _name: str) -> None:
        """主题切换时重建页头样式（分区 Card 自动跟随主题）。"""

        self._apply_apps_header_style()
        self._update_pct_total()

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
        seed_mode = self.monkey_seed_mode.currentData()
        if seed_mode == "fixed":
            fields.append(self.monkey_seed)
        if not self._validate_fields(*fields):
            return None
        p = {
            "events": int(self.monkey_events.currentText().strip()),
            "throttle": self._parse_monkey_throttle(self.monkey_throttle.currentText()),
            "ignore_crashes": self.monkey_chk_crashes.isChecked(),
            "ignore_timeouts": self.monkey_chk_timeouts.isChecked(),
            "ignore_security": self.monkey_chk_security.isChecked(),
            "seed_mode": seed_mode,
            "seed": int(self.monkey_seed.currentText().strip()) if seed_mode == "fixed" else None,
        }
        for key, c in self._monkey_pct_combos.items():
            p[key] = int(c.currentText().strip())
        return p

    def set_run_library(self, controller) -> None:
        """绑定共享测试库；方案读写继续由主窗口持有的控制器负责。"""
        self.monkey_preset_bar.set_library(controller)

    def _update_monkey_seed_state(self, *_args) -> None:
        """随机模式不校验未使用的固定值，切回固定模式后保留原输入。"""
        self.monkey_seed.setEnabled(self.monkey_seed_mode.currentData() == "fixed")

    def capture_run_parameters(self) -> dict | None:
        """复制可复用的 Monkey 表单值，省略设备身份、准备请求和运行代次。"""
        if self._monkey_closed or self._monkey_preparation is not None or self._monkey_running:
            return None
        parameters = self._collect_monkey_params()
        if parameters is None:
            return None
        if sum(parameters[key] for key in self._monkey_pct_combos) != 100:
            raise ValueError(tr("事件比例合计必须为 100%"))
        package = self.package_text.strip()
        parameters["package_name"] = normalize_android_package(package) if package else ""
        return parameters

    def apply_run_parameters(self, parameters: dict) -> None:
        """完整校验后仅载入表单，不更改设备选择、不查询设备，也不自动开始运行。"""
        if self._monkey_closed or self._monkey_preparation is not None or self._monkey_running:
            raise ValueError(tr("请等待当前 Monkey 操作结束后再载入方案"))
        if not isinstance(parameters, dict):
            raise ValueError(tr("Monkey 方案参数无效"))
        values = {}
        ranges = {"events": (1, 1000000), "throttle": (0, 60000)}
        ranges.update({key: (0, 100) for key in self._monkey_pct_combos})
        for key, (minimum, maximum) in ranges.items():
            value = parameters.get(key)
            if (isinstance(value, bool) or not isinstance(value, int)
                    or not minimum <= value <= maximum):
                raise ValueError(tr("Monkey 方案参数无效"))
            values[key] = value
        if sum(values[key] for key in self._monkey_pct_combos) != 100:
            raise ValueError(tr("事件比例合计必须为 100%"))
        flags = ("ignore_crashes", "ignore_timeouts", "ignore_security")
        if any(not isinstance(parameters.get(key, True), bool) for key in flags):
            raise ValueError(tr("Monkey 方案参数无效"))
        mode = parameters.get(
            "seed_mode", "fixed" if parameters.get("seed") is not None else "random",
        )
        seed = parameters.get("seed")
        if mode not in ("random", "fixed") or (mode == "fixed" and (
            isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647
        )):
            raise ValueError(tr("Monkey 方案参数无效"))
        package = parameters.get("package_name", "")
        package = normalize_android_package(package) if package else ""
        self.monkey_events.setText(str(values["events"]))
        self.monkey_throttle.setText(self._format_monkey_throttle(values["throttle"]))
        for key, field in self._monkey_pct_combos.items():
            field.setText(str(values[key]))
        for key, field in zip(flags, (
            self.monkey_chk_crashes, self.monkey_chk_timeouts, self.monkey_chk_security,
        )):
            field.setChecked(parameters.get(key, True))
        self.monkey_seed_mode.setCurrentIndex(1 if mode == "fixed" else 0)
        if mode == "fixed":
            self.monkey_seed.setText(str(seed))
        self.program_edit.setText(package)
        self._update_pct_total()
        self._update_action_states()

    def _update_pct_total(self, *_args):
        total = 0
        for c in self._monkey_pct_combos.values():
            try:
                total += int(c.currentText() or "0")
            except ValueError:
                pass
        self._pct_total_lbl.setText(tr("合计：{total}%").format(total=total))
        color_key = "LOG_SUCCESS" if total == 100 else "LOG_ERROR"
        apply_label_role(self._pct_total_lbl, FontRole.UI, color_key=color_key, bold=True)
        if total == 100:
            color = BaseStyles.color("LOG_SUCCESS")
            self._pct_total_lbl.setToolTip(tr("事件比例合计为 100%"))
            self._pct_total_lbl.setAccessibleDescription(tr("事件比例合计为百分之一百"))
        else:
            color = BaseStyles.color("LOG_ERROR")
            self._pct_total_lbl.setToolTip(tr("建议将事件比例调整为合计 100%"))
            self._pct_total_lbl.setAccessibleDescription(
                tr("当前事件比例合计为百分之 {total}，建议调整为百分之一百").format(total=total)
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
        dur = int(str(self.record_duration.currentData() or "30s").replace("s", ""))
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
                tr("事件比例未达到 100%"),
                tr(
                    "当前事件比例合计为 {total}%，不是 100%。\n"
                    "Monkey 仍会运行，但事件分布可能不符合预期。\n\n"
                    "建议调整各项比例，使合计达到 100%。"
                ).format(total=total),
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
        self.monkey_package_info.setText(
            tr("正在核对 {count} 台设备上的测试包信息…").format(count=len(devices))
        )
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
            self.monkey_package_info.setText(tr(message))
        self._update_action_states()

    def on_monkey_preparation_finished(self, request_id: str, result: dict) -> None:
        """仅接受同代次且输入仍匹配的完整结果，空包自动填充不触发第二次准备。"""
        pending = self._monkey_preparation
        if pending is None or pending.request_id != request_id or self._monkey_closed:
            return
        current_devices = tuple(dict.fromkeys(device for device in self.selected_devices if device))
        if pending.devices != current_devices or pending.package_name != self.package_text.strip():
            self._cancel_monkey_preparation(tr("操作目标或包名已改变，请重新获取测试包信息"))
            return
        self._monkey_preparation = None
        if pending.cancellation.is_cancelled or not result.get("success"):
            self.monkey_package_info.setText(
                _monkey_error_text(str(result.get("error") or "获取测试包信息失败，请重试"))
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
            self.monkey_package_info.setText(tr("测试包信息与本次目标不匹配，请重新获取"))
            self._update_action_states()
            return
        if not pending.package_name:
            self.add_package_to_history(package)
        self._monkey_information_signature = (pending.devices, package)
        lines = []
        for index, info in enumerate(packages, 1):
            version = info.get("version_name") or tr("版本名未提供")
            code = info.get("version_code") or "?"
            sdk = info.get("target_sdk") or "?"
            lines.append(
                tr("设备 {index}：已安装 · {version} ({code}) · target SDK {sdk}").format(
                    index=index, version=version, code=code, sdk=sdk
                )
            )
        self.monkey_package_info.setText("\n".join(lines))
        self._update_action_states()
        if pending.parameters is None:
            return
        if pending.parameters != self._collect_monkey_params():
            self.monkey_package_info.setText(tr("测试参数已改变，请重新开始以核对本次配置"))
            return
        metadata = {}
        for index, info in enumerate(packages, 1):
            version = str(info.get("version_name") or "")
            code = str(info.get("version_code") or "")
            metadata[str(info["device_ip"])] = {
                "device_label": tr("设备 {index}").format(index=index),
                "app_version": f"{version} ({code})" if version and code else version or code,
            }
        self._start_prepared_monkey(pending.devices, package, pending.parameters, metadata)

    def _start_prepared_monkey(
        self, devices: tuple[str, ...], package: str, parameters: dict,
        metadata: dict | None = None,
    ) -> None:
        """准备成功后使用原目标和参数快照启动，既有运行/停止批次归属保持不变。"""
        params: dict = dict(parameters, package_name=package)
        from core.settings_manager import AppSettings

        # 原全局设置保持既有字段；seed 和命名方案只通过独立测试库存储。
        AppSettings.instance().set("monkey_params", {
            key: value for key, value in params.items() if key not in ("seed", "seed_mode")
        })
        if metadata:
            params["_target_metadata"] = metadata
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
            self._cancel_monkey_preparation(tr("操作目标或包名已改变，请重新获取测试包信息"))
        if self._monkey_information_signature not in (None, signature):
            self._monkey_information_signature = None
            self.monkey_package_info.setText(tr("操作目标或包名已改变，请重新获取测试包信息"))
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
            self._set_action_enabled(name, has_device, tr("请先选择设备"))
        self._set_action_enabled(
            "btn_get_program", len(self.selected_devices) == 1 and not self._package_query_pending,
            (
                tr("正在读取当前应用，请等待完成")
                if self._package_query_pending
                else tr("请先选择设备") if not has_device else tr("请仅选择一台设备读取当前应用")
            ),
        )
        for name in package_names:
            reason = tr("请先选择设备") if not has_device else tr("请先输入应用包名")
            self._set_action_enabled(name, has_device and has_package, reason)

        self._set_action_enabled(
            "btn_screenshot",
            has_device and not self._screenshot_running,
            tr("请先选择设备") if not has_device else tr("正在截图，请稍候"),
        )
        self._set_action_enabled(
            "btn_screen_record",
            has_device and not bool(getattr(self, "_recording_running", False)),
            tr("请先选择设备") if not has_device else tr("屏幕录制已在运行"),
        )
        self._set_action_enabled(
            "btn_stop_record",
            bool(getattr(self, "_recording_active_devices", ()))
            and bool(getattr(self, "_recording_running", False))
            and not bool(getattr(self, "_recording_stopping", False)),
            (
                tr("正在停止录屏")
                if getattr(self, "_recording_stopping", False)
                else tr("当前没有正在运行的录屏")
            ),
        )
        monkey_running = bool(getattr(self, "_monkey_running", False))
        preparing = self._monkey_preparation is not None
        self.monkey_parameters_card.setEnabled(
            not (monkey_running or preparing or self._monkey_closed)
        )
        if self._monkey_closed:
            monkey_blocked_reason = tr("页面正在关闭")
        elif preparing:
            monkey_blocked_reason = tr("正在获取测试包信息，请等待完成或取消获取")
        elif monkey_running:
            monkey_blocked_reason = tr("Monkey 测试正在运行，请先停止测试")
        else:
            monkey_blocked_reason = tr("请先选择设备")
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
            "monkey_cancel_prepare_btn", preparing, tr("当前没有进行中的包信息查询")
        )
        self._set_action_enabled(
            "kill_monkey_btn",
            monkey_running
            and bool(getattr(self, "_monkey_active_devices", ()))
            and not bool(getattr(self, "_monkey_stopping", False)),
            (
                tr("正在停止 Monkey")
                if getattr(self, "_monkey_stopping", False)
                else tr("Monkey 当前未运行")
            ),
        )
        self._update_monkey_presentation()

    def _set_action_enabled(self, name: str, enabled: bool, disabled_reason: str) -> None:
        """不可用原因补充功能说明，恢复后不保留过期状态或影响辅助技术描述。"""

        button = getattr(self, name, None)
        if button is None:
            return
        button.setEnabled(enabled)
        description = str(button.property("functionalToolTip") or "")
        if not enabled:
            description = tr("{description}\n不可用：{disabled_reason}").format(
                description=description, disabled_reason=disabled_reason
            )
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
