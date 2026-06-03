from __future__ import annotations

import os
import time

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs.lifecycle import (
    WorkerSignalBinding,
    alive_callback,
    is_qobject_alive,
    safe_disconnect,
    wait_for_thread_later,
)
from gui.dialogs.performance_timeline import PerfDogTimelineChart
from gui.styles import BaseStyles
from gui.styles.icon_loader import get_themed_icon
from gui.styles.theme import apply_dark_title_bar
from models.performance.dashboard import (
    axis_policy,
    build_metric_lanes,
    chart_points,
    frame_chart_values,
    marker_payload,
    metric_details,
    metric_summaries,
    monitor_control_state,
    refresh_metric_lane_colors,
    snapshot_chart_values,
    web_dashboard_context,
)
from models.performance.presentation import build_report_summary, render_report_text
from models.performance.sampling import PerformanceSamplingSchedule
from models.performance.service import PerformanceService
from models.performance.session import PerformanceSession
from models.performance.workers import (
    PerformanceAnalyzeWorker,
    PerformanceFrameWorker,
    PerformanceQuickCheckWorker,
    PerformanceSnapshotWorker,
)


PERFETTO_RECORD_URL = "https://ui.perfetto.dev/#!/record/target"


class PerformanceMonitorDialog(QDialog):
    """Per-device live performance monitor."""

    REFRESH_INTERVAL_MS = 1000
    FRAME_REFRESH_INTERVAL_MS = REFRESH_INTERVAL_MS
    DEVICE_INFO_REFRESH_DELAY_MS = 1800
    DEVICE_INFO_RETRY_DELAY_MS = 500
    TIMELINE_MAX_ENTRIES = 3600

    def __init__(self, parent=None, device_ip: str = ""):
        super().__init__(parent, Qt.Window)
        self.device_ip = device_ip
        self._service = PerformanceService(
            device_ip,
            process_key_prefix=f"performance_{device_ip}_{id(self)}",
        )
        self._closing = False
        self._snapshot_worker = None
        self._frame_worker = None
        self._quick_worker = None
        self._analyze_worker = None
        self._worker_bindings: dict[str, WorkerSignalBinding] = {}
        self._monitoring = False
        self._monitor_started_at = 0.0
        self._sampling = PerformanceSamplingSchedule(self.FRAME_REFRESH_INTERVAL_MS)
        self._latest_frame_values: dict[str, float | int | None] = {}
        self._monitor_samples = []
        self._monitor_cpu_samples = []
        self._timeline_entries = []
        self._last_report_dir = ""
        self._last_report_summary = {}
        self._device_info_rows = []
        self._session = PerformanceSession(device_id=device_ip)
        self._preview_session = PerformanceSession(device_id=device_ip, status="Preview")
        self._use_web_dashboard = _is_web_dashboard_available()
        self._metric_lanes = build_metric_lanes(BaseStyles.color)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._refresh_snapshot)
        self._device_info_timer = QTimer(self)
        self._device_info_timer.setSingleShot(True)
        self._device_info_timer.timeout.connect(self._refresh_device_info)

        self.setWindowTitle(f"Performance Monitor - {device_ip}")
        self.setWindowIcon(get_themed_icon("speedometer.svg"))
        self.setMinimumSize(1180, 720)
        self.resize(1280, 800)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._apply_theme()
        BaseStyles.theme_changed.connect(self._apply_theme)
        self._refresh_timer.start()
        self._refresh_snapshot()
        if self._use_web_dashboard:
            self._device_info_timer.start(self.DEVICE_INFO_REFRESH_DELAY_MS)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.target_group = QGroupBox("Target", self)
        self.target_group.setVisible(not self._use_web_dashboard)
        target_layout = QHBoxLayout(self.target_group)
        target_layout.setContentsMargins(2, 2, 2, 2)
        target_layout.setSpacing(2)
        self.package_input = QLineEdit()
        self.package_input.setPlaceholderText("com.example.app")
        target_layout.addWidget(self.package_input, 3)
        self.current_pkg_btn = QPushButton("Current")
        self.current_pkg_btn.setIcon(get_themed_icon("target.svg"))
        self.current_pkg_btn.setIconSize(QSize(14, 14))
        self.current_pkg_btn.setFixedHeight(30)
        self.current_pkg_btn.setFixedWidth(92)
        self.current_pkg_btn.clicked.connect(self._use_current_package)
        target_layout.addWidget(self.current_pkg_btn)
        self.activity_input = QLineEdit()
        self.activity_input.setPlaceholderText("optional: com.example/.MainActivity")
        target_layout.addWidget(self.activity_input, 2)
        if not self._use_web_dashboard:
            layout.addWidget(self.target_group)

        self.controls_frame = QFrame(self)
        self.controls_frame.setVisible(not self._use_web_dashboard)
        controls = QHBoxLayout(self.controls_frame)
        controls.setContentsMargins(2, 2, 2, 2)
        controls.setSpacing(2)
        self.quick_btn = self._button("Quick", "play-circle.svg")
        self.start_btn = self._button("Start", "record.svg")
        self.stop_btn = self._button("Stop", "stop-circle.svg")
        self.mark_btn = self._button("Mark", "push-pin.svg")
        self.open_report_btn = self._button("Open", "folder-open.svg")
        self.export_btn = self._button("Export", "file-arrow-down.svg")
        self.quick_btn.clicked.connect(self._quick_check)
        self.start_btn.clicked.connect(self._start_monitor)
        self.stop_btn.clicked.connect(self._stop_monitor)
        self.mark_btn.clicked.connect(self._add_marker)
        self.open_report_btn.clicked.connect(self._open_report)
        self.export_btn.clicked.connect(self._export_report)
        for button in (
            self.quick_btn,
            self.start_btn,
            self.stop_btn,
            self.mark_btn,
            self.open_report_btn,
            self.export_btn,
        ):
            controls.addWidget(button)
        controls.addStretch()
        self.device_state_value = self._state_label("Idle")
        self.current_pkg_value = self._state_label("--")
        controls.addWidget(QLabel("State"))
        controls.addWidget(self.device_state_value)
        controls.addWidget(QLabel("Current"))
        controls.addWidget(self.current_pkg_value, 1)
        if not self._use_web_dashboard:
            layout.addWidget(self.controls_frame)

        dashboard = QHBoxLayout()
        dashboard.setContentsMargins(0, 0, 0, 0)
        dashboard.setSpacing(2)
        self.metric_panel = None
        self.summary_panel = None
        if not self._use_web_dashboard:
            self.metric_panel = self._create_metric_panel()
            dashboard.addWidget(self.metric_panel)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(2)
        self.timeline_chart = self._create_timeline_chart()
        center.addWidget(self.timeline_chart, 3)
        self.timeline = QTextEdit()
        self.timeline.setReadOnly(True)
        self.timeline.setFont(BaseStyles.get_log_font())
        self.timeline.setPlaceholderText("Timeline...")
        self.timeline.document().setMaximumBlockCount(self.TIMELINE_MAX_ENTRIES)
        self.timeline.setVisible(not self._use_web_dashboard)
        if not self._use_web_dashboard:
            center.addWidget(self.timeline, 1)
        dashboard.addLayout(center, 1)

        layout.addLayout(dashboard, 1)

        self.report_output = QTextEdit()
        self.report_output.setReadOnly(True)
        self.report_output.setFont(BaseStyles.get_log_font())
        self.report_output.setPlaceholderText("Report summary...")
        self.report_output.setMaximumHeight(132)
        self.report_output.setVisible(not self._use_web_dashboard)
        if not self._use_web_dashboard:
            layout.addWidget(self.report_output)
        self._sync_controls()

    def _state_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setMinimumHeight(24)
        label.setMinimumWidth(96)
        return label

    def _create_metric_panel(self) -> QGroupBox:
        group = QGroupBox("监控指标")
        group.setFixedWidth(148)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.metric_checks = {}
        for lane in self._metric_lanes:
            checkbox = QCheckBox(lane["label"])
            checkbox.setChecked(lane.get("enabled", True))
            checkbox.stateChanged.connect(
                lambda state, metric=lane["metric"]: self._on_metric_toggled(metric, state == Qt.Checked)
            )
            self.metric_checks[lane["metric"]] = checkbox
            layout.addWidget(checkbox)
        layout.addStretch()
        return group

    def _button(self, text: str, icon_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setIcon(get_themed_icon(icon_name))
        button.setIconSize(QSize(14, 14))
        button.setFixedHeight(30)
        button.setFixedWidth(82)
        button.setToolTip(text)
        return button

    def _on_metric_toggled(self, metric: str, enabled: bool):
        self.timeline_chart.set_lane_enabled(metric, enabled)

    def _create_timeline_chart(self):
        if self._use_web_dashboard:
            chart = _create_web_timeline_chart(self._metric_lanes)
            bridge = getattr(chart, "bridge", None)
            action_signal = getattr(bridge, "action_requested", None)
            if action_signal is not None:
                action_signal.connect(self._on_web_action)
            return chart
        return PerfDogTimelineChart(self._metric_lanes)

    def _on_web_action(self, action: str, payload: dict):
        if action == "setPackage":
            self.package_input.setText(payload.get("value", ""))
            self._refresh_web_context()
        elif action == "setActivity":
            self.activity_input.setText(payload.get("value", ""))
            self._refresh_web_context()
        elif action == "currentPackage":
            self._use_current_package()
        elif action == "quickCheck":
            self._quick_check()
        elif action == "startMonitor":
            self._start_monitor()
        elif action == "stopMonitor":
            self._stop_monitor()
        elif action == "mark":
            self._add_marker()
        elif action == "openReport":
            self._open_report()
        elif action == "exportReport":
            self._export_report()
        elif action == "openPerfetto":
            self._open_perfetto()
        elif action == "refreshDeviceInfo":
            self._refresh_device_info(force=True)

    def _control_state(self) -> dict[str, bool]:
        return monitor_control_state(
            monitoring=bool(getattr(self, "_monitoring", False)),
            quick_running=_worker_active(getattr(self, "_quick_worker", None)),
            analyzing=_worker_active(getattr(self, "_analyze_worker", None)),
            has_report=bool(getattr(self, "_last_report_dir", "")),
        )

    def _sync_controls(self):
        controls = self._control_state()
        button_map = {
            "current": "current_pkg_btn",
            "quick": "quick_btn",
            "start": "start_btn",
            "stop": "stop_btn",
            "mark": "mark_btn",
            "openReport": "open_report_btn",
            "export": "export_btn",
        }
        for key, attr_name in button_map.items():
            button = getattr(self, attr_name, None)
            if button is not None and hasattr(button, "setEnabled"):
                button.setEnabled(bool(controls.get(key, True)))
        self._refresh_web_context()

    def _apply_theme(self, _name: str = ""):
        apply_dark_title_bar(self)
        self.timeline.setFont(BaseStyles.get_log_font())
        self.report_output.setFont(BaseStyles.get_log_font())
        self.setStyleSheet(BaseStyles.PANEL_BASE_STYLE() + BaseStyles.GROUP_BOX_STYLE())
        border = BaseStyles.color("BORDER_COLOR")
        self._refresh_chart_colors()
        self.timeline.setStyleSheet(
            f"background-color:{BaseStyles.color('LOG_BACKGROUND')}; "
            f"color:{BaseStyles.color('LOG_TEXT_COLOR')}; "
            f"border:1px solid {border}; border-radius:{BaseStyles.RADIUS_MD}px;"
        )
        self.report_output.setStyleSheet(self.timeline.styleSheet())
        self._refresh_web_context()

    def _refresh_snapshot(self):
        if self._closing or _worker_running(self._snapshot_worker):
            return
        worker = PerformanceSnapshotWorker(
            self._service,
            self.package_input.text().strip(),
            include_device_info=False,
        )
        self._start_snapshot_worker(worker)

    def _refresh_device_info(self, force: bool = False):
        if self._closing:
            return
        if _worker_running(self._snapshot_worker):
            timer = getattr(self, "_device_info_timer", None)
            if is_qobject_alive(timer):
                timer.start(self.DEVICE_INFO_RETRY_DELAY_MS)
            return
        worker = PerformanceSnapshotWorker(
            self._service,
            self.package_input.text().strip(),
            include_device_info=True,
            refresh_device_info=force,
        )
        self._start_snapshot_worker(worker)

    def _start_snapshot_worker(self, worker):
        self._start_worker(
            "_snapshot_worker",
            worker,
            "snapshot",
            (
                (worker.snapshot_ready, self._on_snapshot),
                (worker.device_info_ready, self._on_device_info),
                (worker.status_changed, self._on_status),
            ),
        )

    def _on_snapshot(self, snapshot):
        if self._closing:
            return
        self.current_pkg_value.setText(snapshot.current_package or "--")
        if snapshot.current_package and not self.package_input.text().strip():
            self.package_input.setText(snapshot.current_package)
        values = snapshot_chart_values(
            snapshot,
            collecting=self._monitoring,
            latest_frame_values=getattr(self, "_latest_frame_values", {}),
        )
        if snapshot.memory:
            if self._monitoring:
                self._monitor_samples.append(snapshot.memory)
        if snapshot.cpu and self._monitoring:
            self._monitor_cpu_samples.append(snapshot.cpu)
        if self._monitoring:
            self.device_state_value.setText(f"Collecting {_elapsed_text(self._monitor_started_at)}")
            self._maybe_refresh_frame_metrics()
        else:
            self.device_state_value.setText(snapshot.status)
        if self._monitoring:
            self._append_session_values(values)
        else:
            package_name = _snapshot_package_name(snapshot)
            self._replace_preview_values(values, package_name=package_name)

    def _on_device_info(self, rows):
        if self._closing:
            return
        self._device_info_rows = list(rows or [])
        self._refresh_web_context()

    def _on_snapshot_finished(self, worker):
        self._finish_worker("_snapshot_worker", worker)

    def _use_current_package(self):
        package_name = self.current_pkg_value.text().strip()
        if package_name and package_name != "--":
            self.package_input.setText(package_name)
            self._append_timeline(f"Target package set to {package_name}")

    def _quick_check(self):
        package_name = self.package_input.text().strip()
        if not package_name:
            QMessageBox.warning(self, "Package Required", "No package name provided.")
            return
        if _worker_running(self._quick_worker):
            return
        worker = PerformanceQuickCheckWorker(
            self._service,
            package_name,
            self.activity_input.text().strip(),
        )
        self._start_worker(
            "_quick_worker",
            worker,
            "quick",
            (
                (worker.status_changed, self._on_status),
                (worker.result_ready, self._on_quick_check_result),
            ),
            sync_controls=True,
        )
        self._append_timeline("Quick Check started")

    def _on_quick_check_result(self, result):
        if self._closing:
            return
        self._last_report_dir = result.get("report_dir", "")
        self._render_result(result, "Quick Check")
        self._append_timeline(f"Quick Check finished: {self._last_report_dir}")
        self._sync_controls()
        frames = result.get("frames")
        if frames:
            self._append_frame_sample(frames, append_when_idle=False)

    def _on_quick_worker_finished(self, worker):
        self._finish_worker("_quick_worker", worker, sync_controls=True)

    def _start_monitor(self):
        if _worker_running(self._quick_worker):
            return
        package_name = self.package_input.text().strip()
        if not package_name:
            QMessageBox.warning(self, "Package Required", "No package name provided.")
            return
        self._monitoring = True
        self._monitor_started_at = time.monotonic()
        self._session = PerformanceSession(
            device_id=self.device_ip,
            package_name=package_name,
            activity=self.activity_input.text().strip(),
            started_at_ms=_now_ms(),
            status="Collecting",
        )
        self._sampling_schedule().reset()
        self._latest_frame_values = {}
        self._monitor_samples = []
        self._monitor_cpu_samples = []
        self.device_state_value.setText("Collecting 00:00")
        self._sync_controls()
        self._append_timeline("Monitor started")
        self._service.reset_frame_stats(package_name)
        self._maybe_refresh_frame_metrics(force=True)

    def _stop_monitor(self):
        if not self._monitoring:
            return
        self._monitoring = False
        self._session.status = "Analyzing"
        self.device_state_value.setText("Analyzing")
        package_name = self.package_input.text().strip()
        worker = PerformanceAnalyzeWorker(
            self._service,
            package_name,
            list(self._monitor_samples),
            list(self._monitor_cpu_samples),
            self._monitor_started_at,
        )
        self._start_worker(
            "_analyze_worker",
            worker,
            "analyze",
            (
                (worker.status_changed, self._on_status),
                (worker.result_ready, self._on_monitor_result),
            ),
            sync_controls=True,
        )
        self._append_timeline("Monitor stopped, analyzing")

    def _on_monitor_result(self, result):
        if self._closing:
            return
        self._last_report_dir = result.get("report_dir", "")
        self._render_result(result, "Monitor")
        self._append_timeline(f"Monitor report ready: {self._last_report_dir}")
        self._sync_controls()
        frames = result.get("frames")
        if frames:
            self._append_frame_sample(frames)
        self._session.status = "Ready"
        self.device_state_value.setText("Ready")

    def _on_analyze_worker_finished(self, worker):
        self._finish_worker("_analyze_worker", worker, sync_controls=True)

    def _maybe_refresh_frame_metrics(self, force: bool = False):
        if self._closing or not self._monitoring:
            return
        package_name = self.package_input.text().strip()
        if not package_name:
            return
        if _worker_running(self._frame_worker):
            return
        now = time.monotonic()
        schedule = self._sampling_schedule()
        if not schedule.should_refresh_frame(now, force=force):
            return
        worker = PerformanceFrameWorker(self._service, package_name)
        self._start_worker(
            "_frame_worker",
            worker,
            "frame",
            (
                (worker.result_ready, self._on_frame_metrics_result),
                (worker.status_changed, self._on_status),
            ),
            auto_start=False,
        )
        schedule.mark_frame_refresh(now)
        worker.start()

    def _on_frame_metrics_result(self, frames):
        if self._closing or not frames:
            return
        self._append_frame_sample(frames)

    def _on_frame_worker_finished(self, worker):
        self._finish_worker("_frame_worker", worker)

    def _render_result(self, result: dict, title: str):
        self.report_output.setPlainText(render_report_text(result, title))
        self._last_report_summary = build_report_summary(result, title)
        self._refresh_web_context()

    def _append_frame_sample(self, frames, *, append_when_idle: bool = True):
        values = frame_chart_values(frames)
        self._latest_frame_values = values
        if self._monitoring:
            if self._session.update_latest_point(values):
                self._refresh_dashboard()
            else:
                self._append_session_values(values)
            return
        if append_when_idle and (self._session.points or self._session.markers):
            if self._session.update_latest_point(values):
                self._refresh_dashboard()
            else:
                self._append_session_values(values)
            return
        preview = getattr(self, "_preview_session", None)
        if preview is not None and preview.update_latest_point(values):
            self._refresh_dashboard()
        else:
            self._replace_preview_values(values)

    def _append_session_values(self, values: dict[str, float | int | None]):
        self._session.add_point(_now_ms(), values)
        self._refresh_dashboard()

    def _replace_preview_values(self, values: dict[str, float | int | None], *, package_name: str = ""):
        preview = PerformanceSession(
            device_id=getattr(self, "device_ip", ""),
            package_name=package_name,
            activity=_widget_text(getattr(self, "activity_input", None)),
            started_at_ms=_now_ms(),
            status="Preview",
        )
        preview.add_point(_now_ms(), values)
        self._preview_session = preview
        self._refresh_dashboard()

    def _active_chart_session(self) -> PerformanceSession:
        session = getattr(self, "_session", PerformanceSession(device_id=getattr(self, "device_ip", "")))
        if getattr(self, "_monitoring", False) or session.points or session.markers:
            return session
        return getattr(self, "_preview_session", session)

    def _refresh_dashboard(self):
        session = self._active_chart_session()
        points = chart_points(session, self.timeline_chart.max_points)
        self.timeline_chart.set_points(points, marker_payload(session))
        self._refresh_web_context()

    def _refresh_web_context(self):
        if not getattr(self, "_use_web_dashboard", False) or not hasattr(self.timeline_chart, "set_context"):
            return

        def _text_from(attr_name: str) -> str:
            widget = getattr(self, attr_name, None)
            if widget is None or not hasattr(widget, "text"):
                return ""
            return str(widget.text()).strip()

        session = self._active_chart_session()
        palette, font = _web_dashboard_style()
        context = web_dashboard_context(
            events=list(self._timeline_entries),
            report=self.report_output.toPlainText(),
            report_summary=dict(self._last_report_summary),
            state=self.device_state_value.text(),
            current_package=self.current_pkg_value.text(),
            package_name=_text_from("package_input"),
            activity=_text_from("activity_input"),
            controls=self._control_state(),
            theme=BaseStyles.current_theme(),
            palette=palette,
            font=font,
            device_info=list(getattr(self, "_device_info_rows", [])),
            metric_summaries=metric_summaries(session, BaseStyles.color),
            metric_details=metric_details(session),
            axis_policy=axis_policy(),
        )
        self.timeline_chart.set_context(**context)

    def _marker_positions(self) -> list[dict]:
        return marker_payload(self._session)

    def _add_marker(self):
        label = f"Mark {len(self._session.markers) + 1}"
        self._session.add_marker(_now_ms(), label)
        self._append_timeline(label)
        self._refresh_dashboard()

    def _refresh_chart_colors(self):
        refresh_metric_lane_colors(self._metric_lanes, BaseStyles.color)
        self.timeline_chart.update()

    def _open_report(self):
        if not self._last_report_dir or not os.path.isdir(self._last_report_dir):
            return
        os.startfile(self._last_report_dir)

    def _open_perfetto(self):
        QDesktopServices.openUrl(QUrl(PERFETTO_RECORD_URL))

    def _export_report(self):
        if not self._last_report_dir:
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Export report summary",
            os.path.join(self._last_report_dir, "report.md"),
            "Markdown (*.md);;All Files (*)",
        )
        if not target:
            return
        source = os.path.join(self._last_report_dir, "report.md")
        try:
            with open(source, encoding="utf-8") as src, open(target, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            self._append_timeline(f"Exported report to {target}")
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _append_timeline(self, message: str):
        entry = f"{time.strftime('%H:%M:%S')} {message}"
        self._timeline_entries.append(entry)
        if len(self._timeline_entries) > self.TIMELINE_MAX_ENTRIES:
            self._timeline_entries = self._timeline_entries[-self.TIMELINE_MAX_ENTRIES:]
        self.timeline.append(entry)
        self._refresh_web_context()

    def _on_status(self, message: str):
        if not self._closing:
            self.device_state_value.setText(message)
            self._append_timeline(message)

    def _start_worker(
        self,
        attr_name: str,
        worker,
        worker_key: str,
        signal_handlers: tuple,
        *,
        sync_controls: bool = False,
        auto_start: bool = True,
    ):
        finished_handler = alive_callback(
            self,
            "_on_worker_finished",
            attr_name,
            worker_key,
            worker,
            sync_controls,
        )
        binding = WorkerSignalBinding(
            worker=worker,
            handlers=tuple(signal_handlers),
            finished_handler=finished_handler,
        )
        self._worker_bindings = getattr(self, "_worker_bindings", {})
        self._worker_bindings[worker_key] = binding
        binding.connect()
        setattr(self, attr_name, worker)
        if sync_controls:
            self._sync_controls()
        if auto_start:
            worker.start()

    def _on_worker_finished(self, attr_name: str, worker_key: str, worker, sync_controls: bool = False):
        self._finish_worker(attr_name, worker, worker_key=worker_key, sync_controls=sync_controls)

    def _finish_worker(self, attr_name: str, worker, *, worker_key: str | None = None, sync_controls: bool = False):
        if not is_qobject_alive(worker):
            return
        self._disconnect_worker(worker_key or _worker_key_from_attr(attr_name), worker)
        if getattr(self, attr_name, None) is worker:
            setattr(self, attr_name, None)
        worker.deleteLater()
        if sync_controls and not self._closing:
            self._sync_controls()

    def _sampling_schedule(self) -> PerformanceSamplingSchedule:
        schedule = getattr(self, "_sampling", None)
        if schedule is None:
            schedule = PerformanceSamplingSchedule(self.FRAME_REFRESH_INTERVAL_MS)
            self._sampling = schedule
        return schedule

    def _disconnect_worker(self, worker_key: str, worker):
        if not is_qobject_alive(worker):
            return
        bindings = getattr(self, "_worker_bindings", {})
        binding = bindings.pop(worker_key, None)
        if binding is not None:
            binding.disconnect()

    def closeEvent(self, event):
        self._closing = True
        if is_qobject_alive(self._refresh_timer):
            self._refresh_timer.stop()
            safe_disconnect(self._refresh_timer.timeout, self._refresh_snapshot)
        device_info_timer = getattr(self, "_device_info_timer", None)
        if is_qobject_alive(device_info_timer):
            device_info_timer.stop()
            safe_disconnect(device_info_timer.timeout, self._refresh_device_info)
        safe_disconnect(BaseStyles.theme_changed, self._apply_theme)
        for attr, key in (
            ("_snapshot_worker", "snapshot"),
            ("_frame_worker", "frame"),
            ("_quick_worker", "quick"),
            ("_analyze_worker", "analyze"),
        ):
            worker = getattr(self, attr)
            if not worker:
                continue
            setattr(self, attr, None)
            self._disconnect_worker(key, worker)
            if _worker_running(worker):
                worker.requestInterruption()
                worker.setParent(None)
                worker.finished.connect(worker.deleteLater)
                wait_for_thread_later(worker, 5000)
            else:
                worker.deleteLater()
        self._service.stop()
        super().closeEvent(event)


def _is_web_dashboard_available() -> bool:
    try:
        from gui.performance_web.dashboard import is_web_timeline_available
    except Exception:
        return False
    return is_web_timeline_available()


def _create_web_timeline_chart(metric_lanes):
    from gui.performance_web.dashboard import WebPerformanceTimelineChart

    return WebPerformanceTimelineChart(metric_lanes)


def _web_dashboard_style() -> tuple[dict, dict]:
    from gui.performance_web.dashboard import build_web_font, build_web_palette

    return build_web_palette(), build_web_font()


def _snapshot_package_name(snapshot) -> str:
    target = getattr(snapshot, "target_package", "")
    if isinstance(target, str) and target:
        return target
    current = getattr(snapshot, "current_package", "")
    return current if isinstance(current, str) else ""


def _widget_text(widget) -> str:
    if widget is None or not hasattr(widget, "text"):
        return ""
    return str(widget.text()).strip()


def _elapsed_text(started_at: float) -> str:
    if not started_at:
        return "--"
    elapsed = max(0, int(time.monotonic() - started_at))
    minutes, seconds = divmod(elapsed, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _worker_active(worker) -> bool:
    return bool(worker and is_qobject_alive(worker))


def _worker_running(worker) -> bool:
    return bool(worker and is_qobject_alive(worker) and worker.isRunning())


def _worker_key_from_attr(attr_name: str) -> str:
    return attr_name.strip("_").removesuffix("_worker")
