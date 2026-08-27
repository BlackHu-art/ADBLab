"""提供应用管理、Monkey 测试、诊断和录屏操作面板。"""

import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCompleter,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base_panel import BasePanel
from gui.styles import BaseStyles, FontRole
from gui.widgets.responsive_layout import (
    RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY,
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

        g_ts = self._g("Text & Screen Capture")
        gts_l = QVBoxLayout(g_ts)
        gts_l.setSpacing(2)
        self.email_text_sender = self._in("Email, verification code, or text...")
        self.btn_send_text = self._b(
            "Send", "text-aa.svg", tooltip="Type the entered text on selected devices"
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
            "Screenshot", "camera.svg", tooltip="Capture selected device screens"
        )
        self.record_duration = self._combo(["10s", "20s", "30s", "60s", "120s", "180s", "300s"])
        self.record_duration.setCurrentText("30s")
        self.btn_screen_record = self._b(
            "Record", "video-camera.svg", tooltip="Start screen recording on selected devices"
        )
        self.btn_stop_record = self._b(
            "Stop Rec", "stop-circle.svg", tooltip="Stop the active screen recordings"
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
        lo.addWidget(g_ts)

        g_pm = self._g("Package Manager")
        gl_pm = QVBoxLayout(g_pm)
        gl_pm.setSpacing(2)
        self.program_edit = self._combo_editable(font_role=FontRole.MONO)
        self.program_edit.setAccessibleName("Package name")
        self.program_edit.setMinimumHeight(28)
        line_edit = self.program_edit.lineEdit()
        assert line_edit is not None  # stub Optional 收窄
        line_edit.setFont(self._font_mono)
        line_edit.setProperty("fontRole", FontRole.MONO.value)
        line_edit.setAccessibleName("Package name")
        line_edit.setPlaceholderText("Package name")
        self.program_edit.currentTextChanged.connect(lambda _text: self._update_action_states())
        self.completer = QCompleter(self.panel._package_history)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.panel._apply_completer_style(self.completer)
        self.program_edit.setCompleter(self.completer)
        self.btn_get_program = self._b(
            "Get Current Package", "target.svg", tooltip="Read the foreground app package"
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
            "Uninstall App", "trash.svg", tooltip="Remove the selected package"
        )
        self.clear_app_data_btn = self._b(
            "Clear Data", "eraser.svg", tooltip="Erase data for the selected package"
        )
        self.restart_app_btn = self._b(
            "Restart App", "repeat.svg", tooltip="Force stop and relaunch the selected package"
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
            "Activity Info", "scroll.svg", tooltip="Show activity details for the selected package"
        )
        self.parse_apk_info_btn = self._b(
            "Parse APK", "magnifying-glass.svg", tooltip="Inspect metadata from a local APK"
        )
        self.btn_force_stop = self._b(
            "Force Stop App", "stop-circle.svg", tooltip="Force stop the selected package"
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
            "Disable App", "prohibit.svg", tooltip="Disable the selected package"
        )
        self.btn_enable_app = self._b(
            "Enable App", "check-circle.svg", tooltip="Enable the selected package"
        )
        self.btn_disable_user = self._b(
            "Disable for User",
            "user-switch.svg",
            tooltip="Disable the package for the current user",
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
        lo.addWidget(g_pm)

        g_m = self._g("Monkey")
        gm_l = QVBoxLayout(g_m)
        gm_l.setSpacing(3)

        EVENTS_OPTS = ["100", "500", "1000", "5000", "10000", "50000", "100000", "500000"]
        THROTTLE_OPTS = ["0", "100", "200", "300", "500", "1000", "2000"]
        PCT_OPTS = ["0", "5", "10", "15", "20", "25", "30", "40", "50"]

        def _mk_combo(items):
            return self._combo_editable(items)

        self.monkey_events_label = self._label("Events:")
        self.monkey_events = _mk_combo(EVENTS_OPTS)
        self._set_combo_int_validator(self.monkey_events, 1, 1_000_000)
        self.monkey_throttle_label = self._label("Throttle:")
        self.monkey_throttle = _mk_combo(THROTTLE_OPTS)
        self._set_combo_int_validator(self.monkey_throttle, 0, 60_000)
        self.monkey_ms_label = self._label("ms")
        self._pct_total_lbl = self._status_text("Total: --")
        # Events/Throttle 值为最多 6 位数字，字段下限取 8em，保证并排档下
        # 组合框内完整显示选项值而不是只剩下拉箭头（截图确认 2em 下限时
        # wide 档字段宽仅为箭头宽度，值不可见）。
        for field in (self.monkey_events, self.monkey_throttle):
            field.setProperty(RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY, 8)
            self._refresh_responsive_widget_minimum(field)

        pct_configs = [
            ("Touch", "touch"),
            ("Motion", "motion"),
            ("Trackball", "trackball"),
            ("Nav", "nav"),
            ("MjNav", "majornav"),
            ("Syskey", "syskeys"),
            ("AppSw", "appswitch"),
            ("Any", "anyevent"),
            ("Pinch", "pinch"),
        ]
        self._monkey_pct_combos = {}
        self._monkey_pct_labels = {}
        pct_widgets = []
        for label, key in pct_configs:
            lbl = self._label(f"{label}:")
            c = _mk_combo(PCT_OPTS)
            self._set_combo_int_validator(c, 0, 100)
            c.currentTextChanged.connect(self._update_pct_total)
            # 百分比字段保持 6em 稳定下限，避免窄宽度下并排小字段挤到不可读。
            c.setProperty(RESPONSIVE_AUTO_MINIMUM_EM_PROPERTY, 6)
            self._refresh_responsive_widget_minimum(c)
            self._monkey_pct_labels[key] = lbl
            self._monkey_pct_combos[key] = c
            pct_widgets.extend((lbl, c))
        # 统一标签列宽，使上排 Events/Throttle/ms 与下方百分比标签对齐。
        label_width = QFontMetrics(BaseStyles.font_for_role(FontRole.UI)).horizontalAdvance(
            "Trackball:"
        ) + 4
        for _lbl in (self.monkey_events_label, self.monkey_throttle_label, self.monkey_ms_label):
            _lbl.setMinimumWidth(label_width)
        for _lbl in self._monkey_pct_labels.values():
            _lbl.setMinimumWidth(label_width)
        parameter_widgets = (
            self.monkey_events_label,
            self.monkey_events,
            self.monkey_throttle_label,
            self.monkey_throttle,
            self.monkey_ms_label,
            self._pct_total_lbl,
        )
        parameter_modes = (
            GridMode(
                "wide",
                6,
                0,
                placements=tuple(GridPlacement(index, 0, index) for index in range(6)),
                column_stretches=(0, 1, 0, 1, 0, 1),
            ),
            GridMode(
                "medium",
                5,
                1,
                placements=(
                    GridPlacement(0, 0, 0),
                    GridPlacement(1, 0, 1),
                    GridPlacement(2, 0, 2),
                    GridPlacement(3, 0, 3),
                    GridPlacement(4, 0, 4),
                    GridPlacement(5, 1, 0, column_span=5),
                ),
                column_stretches=(0, 1, 0, 1, 0),
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
                    GridPlacement(4, 2, 0),
                    GridPlacement(5, 2, 1),
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
                WidthPolicy.NATURAL,
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
        self._monkey_config_layout = self.monkey_percentage_binding

        self.monkey_chk_crashes = self._checkbox("Ignore crashes")
        self.monkey_chk_timeouts = self._checkbox("Ignore timeouts")
        self.monkey_chk_security = self._checkbox("Ignore security")
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
            "Start", "robot.svg", tooltip="Start the configured Monkey test"
        )
        self.kill_monkey_btn = self._b("Stop", "skull.svg", tooltip="Stop the active Monkey test")
        self._set_monkey_running(False)
        self._add_responsive_row(
            gm_l,
            (self.start_monkey_btn, 1),
            (self.kill_monkey_btn, 1),
            compact_columns=2,
            medium_columns=2,
            wide_columns=2,
        )
        lo.addWidget(g_m)

        g_r = self._g("Reports")
        gr_l = QVBoxLayout(g_r)
        gr_l.setSpacing(2)
        self.get_bugreport_btn = self._b(
            "Bugreport", "bug.svg", tooltip="Collect an Android bug report"
        )
        self.get_anr_file_btn = self._b(
            "ANR Files", "warning.svg", tooltip="Retrieve application-not-responding reports"
        )
        self.btn_retrieve_devices_logs = self._b(
            "Retrieve Logs",
            "file-arrow-down.svg",
            tooltip="Copy diagnostic logs from selected devices",
        )
        self.btn_cleanup_logs = self._b(
            "Cleanup Logs", "broom.svg", tooltip="Remove collected logs from selected devices"
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
        lo.addWidget(g_r)

        g_perf = self._g("Performance Diagnostics")
        gl_perf = QVBoxLayout(g_perf)
        gl_perf.setSpacing(2)

        self.btn_meminfo = self._b(
            "Memory", "memory.svg", tooltip="Show memory usage for the selected package"
        )
        self.btn_cpuinfo = self._b(
            "CPU Load", "cpu.svg", tooltip="Show CPU usage for the selected package"
        )
        self.btn_battery_info = self._b(
            "Battery", "battery-full.svg", tooltip="Show battery diagnostics"
        )
        self.btn_uptime = self._b("Uptime", "clock.svg", tooltip="Show device and process uptime")
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
            "Top Snapshot", "chart-bar.svg", tooltip="Capture a process usage snapshot"
        )
        self.btn_gfx = self._b("GFX Info", "image.svg", tooltip="Show frame rendering statistics")
        self.btn_wakelock = self._b("Wakelocks", "lock.svg", tooltip="Show active power wake locks")
        self.btn_netstats = self._b(
            "Net Stats", "chart-line.svg", tooltip="Show network usage statistics"
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
        lo.addWidget(g_perf)

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
        self._update_action_states()
        return w

    # ── Monkey 参数持久化 ───────────────────────────────────────────────

    def _load_monkey_params(self):
        from core.settings_manager import AppSettings

        p = AppSettings.instance().get("monkey_params", {})

        _events = int(p.get("events", 10000))
        self.monkey_events.setCurrentText(str(_events))
        self.monkey_throttle.setCurrentText(str(p.get("throttle", 300)))
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
            c.setCurrentText(str(p.get(key, _pct_defaults.get(key, 20))))
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
            "throttle": int(self.monkey_throttle.currentText().strip()),
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
        self._pct_total_lbl.setText(f"Total: {total}%")
        if total == 100:
            color = BaseStyles.color("LOG_SUCCESS")
            self._pct_total_lbl.setToolTip("Event percentages total 100%")
            self._pct_total_lbl.setAccessibleDescription("Event percentages total 100 percent")
        else:
            color = BaseStyles.color("LOG_ERROR")
            self._pct_total_lbl.setToolTip("Event percentages must total 100%")
            self._pct_total_lbl.setAccessibleDescription(
                f"Event percentages total {total} percent; 100 percent is recommended"
            )
        self._pct_total_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")

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
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Event Mix Invalid",
                f"Event percentages sum to {total}%, not 100%.\n"
                "Monkey will still run but event distribution may be unexpected.\n\n"
                "Adjust values to sum to 100% for predictable results.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.NoButton,
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
            self._set_action_enabled(name, has_device, "Select a device first")
        for name in package_names:
            reason = "Select a device first" if not has_device else "Enter a package name first"
            self._set_action_enabled(name, has_device and has_package, reason)

        self._set_action_enabled(
            "btn_screenshot",
            has_device and not self._screenshot_running,
            "Select a device first" if not has_device else "Screenshot is in progress",
        )
        self._set_action_enabled(
            "btn_screen_record",
            has_device and not bool(getattr(self, "_recording_running", False)),
            "Select a device first" if not has_device else "Recording is already running",
        )
        self._set_action_enabled(
            "btn_stop_record",
            bool(getattr(self, "_recording_active_devices", ()))
            and bool(getattr(self, "_recording_running", False))
            and not bool(getattr(self, "_recording_stopping", False)),
            (
                "Stopping recording"
                if getattr(self, "_recording_stopping", False)
                else "No recording is running"
            ),
        )
        monkey_running = bool(getattr(self, "_monkey_running", False))
        self._set_action_enabled(
            "start_monkey_btn",
            has_device and has_package and not monkey_running,
            "Select a device and enter a package name first",
        )
        self._set_action_enabled(
            "kill_monkey_btn",
            monkey_running
            and bool(getattr(self, "_monkey_active_devices", ()))
            and not bool(getattr(self, "_monkey_stopping", False)),
            (
                "Stopping Monkey"
                if getattr(self, "_monkey_stopping", False)
                else "Monkey is not running"
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
        self.program_edit.setCurrentText(pkg)

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
