"""单页任务中心：投影既有任务与归档，行内阅读，不接管执行资源。"""

from __future__ import annotations

import logging
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QHideEvent, QPalette, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    IconWidget,
    PlainTextEdit,
    PushButton,
    SearchLineEdit,
    SmoothScrollArea,
    StrongBodyLabel,
    getFont,
)

from gui.i18n import tr
from gui.run_library import RunLibraryController
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    apply_label_role,
    apply_reading_surface,
    configure_fluent_control,
    use_smooth_scroll,
)
from gui.widgets.action_result_view import ActionResultView
from gui.widgets.eliding_combo_box import ElidingComboBox
from gui.widgets.run_results import RunResultsWidget
from gui.widgets.task_table import TaskRowData, TaskTable
from services.run_library import RunRecord
from services.task_history import TaskHistoryEntry, TaskHistoryStore
from services.tasks.action_results import ActionResult, ActionResults
from services.tasks.operations import OperationManager, OperationSnapshot

POLL_INTERVAL_MS = 1000
DEFAULT_HISTORY_LIMIT = 50

_STATE_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "finalizing": "收尾中",
    "succeeded": "成功",
    "partial": "部分成功",
    "failed": "失败",
    "cancelled": "已取消",
    "recorded": "记录",
    "warning": "注意",
}
_STATE_TONES = {
    "running": "accent",
    "queued": "neutral",
    "finalizing": "accent",
    "succeeded": "success",
    "partial": "warning",
    "failed": "danger",
    "warning": "warning",
}

_OPERATION_LABELS = {
    "apk_info": "APK 信息",
    "batch_install": "批量安装",
    "install": "安装应用",
    "battery_reset": "重置电池状态",
    "battery_set": "设置电池状态",
    "bugreport": "错误报告",
    "cleanup_device_logs": "清理设备日志",
    "clear_data": "清除应用数据",
    "connect": "连接设备",
    "content_query": "查询内容提供者",
    "cpu_info": "CPU 信息",
    "current_activity": "当前 Activity",
    "deep_link": "打开链接",
    "device_uptime": "设备运行时间",
    "disable_app": "禁用应用",
    "disable_app_for_user": "对当前用户禁用应用",
    "disconnect": "断开设备",
    "dumpsys_battery": "电池信息",
    "dumpsys_cpuinfo": "CPU 使用情况",
    "dumpsys_meminfo": "内存信息",
    "dumpsys_service": "查询系统服务",
    "emu_call": "模拟来电",
    "emu_geo": "模拟位置",
    "emu_sms": "模拟短信",
    "enable_app": "启用应用",
    "file_list": "列出文件",
    "file_pull": "下载文件",
    "file_push": "上传文件",
    "force_stop": "强行停止应用",
    "forward_port": "添加端口转发",
    "get_info": "获取设备信息",
    "get_package": "获取前台应用",
    "gfxinfo": "图形渲染信息",
    "grant_permission": "授予权限",
    "ime_list": "列出输入法",
    "ime_set": "设置输入法",
    "input_keyevent": "发送按键事件",
    "input_swipe": "发送滑动手势",
    "input_tap": "发送点击",
    "input_text": "发送文本",
    "installed_packages": "已安装应用",
    "kernel_version": "内核版本",
    "kill_monkey": "停止 Monkey",
    "kill_process": "结束进程",
    "list_forwards": "列出端口转发",
    "list_processes": "进程列表",
    "list_reverse": "列出反向转发",
    "logcat_filtered": "筛选 Logcat",
    "monkey": "Monkey 测试",
    "netstats_detail": "网络统计",
    "pair_device": "配对设备",
    "pm_features": "设备功能",
    "pull_anr": "获取 ANR",
    "pull_recording": "下载录屏",
    "quick_setting": "快捷设置",
    "reboot_mode": "重启设备",
    "refresh": "刷新设备",
    "remove_forwards": "移除端口转发",
    "remove_reverse": "移除反向转发",
    "restart": "重启设备",
    "restart_adb": "重启 ADB",
    "restart_app": "重启应用",
    "retrieve_device_logs": "获取设备日志",
    "reverse_port": "添加反向转发",
    "revoke_permission": "撤销权限",
    "screen_record": "录制屏幕",
    "screenshot": "截图",
    "send_broadcast": "发送广播",
    "settings_get": "读取系统设置",
    "settings_list": "列出系统设置",
    "settings_put": "写入系统设置",
    "shell_command": "执行 Shell",
    "start_activity": "启动 Activity",
    "stop_recording": "停止录屏",
    "tcpip_mode": "开启 TCP/IP",
    "top_snapshot": "进程快照",
    "uninstall": "卸载应用",
    "wakelocks": "唤醒锁",
}


def _operation_label(kind: str) -> str:
    source = _OPERATION_LABELS.get(kind)
    return tr(source) if source is not None else kind


@dataclass(frozen=True)
class _Entry:
    """来源身份与展示字段分离，单调时钟只在原 Operation 内部使用。"""

    row: TaskRowData
    payload: ActionResult | OperationSnapshot | RunRecord | TaskHistoryEntry
    state: str
    kind: str
    active: bool
    operation_ids: tuple[str, ...] = ()
    search_text: str = ""


class TaskCenterPage(QWidget):
    """统一列表、条件筛选和共享行内阅读器；隐藏与退出停止轮询。"""

    def __init__(
        self,
        operation_manager: OperationManager | None = None,
        *,
        panel=None,
        history_store: TaskHistoryStore | None = None,
        stop_hook: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        history_limit: int | None = DEFAULT_HISTORY_LIMIT,
        run_library: RunLibraryController | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("taskCenterPage")
        self.setAccessibleName(tr("任务中心"))
        self._panel = panel
        self._operation_manager = operation_manager
        self._history_store = history_store if history_store is not None else TaskHistoryStore()
        self._history_limit = history_limit
        self._stop_hook = stop_hook
        self._library = run_library
        self._entries: dict[str, _Entry] = {}
        self._ordered_keys: tuple[str, ...] = ()
        self._frozen_order: tuple[str, ...] = ()
        self._detail_signature: object = None
        self._cancel_pending: set[str] = set()
        self._read_versions: dict[str, tuple] = {}
        self._closed = False
        self._rendering = False
        self._layout_mode: tuple[bool, bool] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # 任务页不显示设备栏，自有页头沿用设备任务标题的字体与阅读边界。
        self.page_header = QWidget(self)
        header_layout = QVBoxLayout(self.page_header)
        header_layout.setContentsMargins(32, 12, 32, 0)
        self.title_label = StrongBodyLabel(tr("任务中心"), self.page_header)
        header_layout.addWidget(self.title_label)
        layout.addWidget(self.page_header)
        self._scroll = use_smooth_scroll(SmoothScrollArea(self))
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 8, 32, 24)
        content_layout.setSpacing(6)
        self.filters = QWidget(content)
        self.filters.installEventFilter(self)
        self.filters.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._filter_layout = QGridLayout(self.filters)
        self._filter_layout.setContentsMargins(0, 0, 0, 0)
        self._filter_layout.setSpacing(8)
        self.search_edit = SearchLineEdit(self.filters)
        self.search_edit.setMinimumWidth(0)
        self.search_edit.setPlaceholderText(tr("搜索任务、设备、应用或日期"))
        self.search_edit.setAccessibleName(tr("搜索任务"))
        self.state_combo = ElidingComboBox(self.filters)
        self.state_combo.setAccessibleName(tr("任务状态"))
        for label, value in (
            ("全部状态", ""),
            ("进行中", "active"),
            ("成功", "succeeded"),
            ("部分完成", "partial"),
            ("失败", "failed"),
            ("已取消", "cancelled"),
            ("注意", "warning"),
            ("记录", "recorded"),
        ):
            self.state_combo.addItem(tr(label), userData=value)
        self.kind_combo = ElidingComboBox(self.filters)
        self.kind_combo.setAccessibleName(tr("任务类型"))
        for label, value in (
            ("全部类型", ""),
            ("设备", "device"),
            ("应用", "app"),
            ("Shell", "shell"),
            ("文件", "file"),
            ("系统", "system"),
            ("Monkey", "monkey"),
            ("性能", "performance"),
            ("其他", "other"),
        ):
            self.kind_combo.addItem(tr(label), userData=value)
        content_layout.addWidget(self.filters)
        self.count_label = apply_label_role(
            BodyLabel(content), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self.count_label.setWordWrap(True)
        content_layout.addWidget(self.count_label)
        self.table = TaskTable(content)
        content_layout.addWidget(self.table, 1)
        self.empty_state = QWidget(content)
        self.empty_state.setMinimumWidth(0)
        self.empty_state.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(10)
        empty_layout.addStretch(1)
        # 文字组通过横向布局居中；标签铺满组宽，换行高度按实际宽度计算。
        # 直接给标签加水平居中对齐会让布局按更宽的预算估高，裁掉窄窗的后续行。
        empty_center = QHBoxLayout()
        empty_center.setContentsMargins(0, 0, 0, 0)
        empty_center.addStretch()
        self.empty_content = QWidget(self.empty_state)
        self.empty_content.setMaximumWidth(560)
        self.empty_content.setMinimumWidth(0)
        text_layout = QVBoxLayout(self.empty_content)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(10)
        empty_center.addWidget(self.empty_content, 1)
        empty_center.addStretch()
        empty_layout.addLayout(empty_center)
        self.empty_icon = IconWidget(FluentIcon.HISTORY, self.empty_content)
        self.empty_icon.setFixedSize(24, 24)
        text_layout.addWidget(self.empty_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_title = StrongBodyLabel(self.empty_content)
        self.empty_label = BodyLabel(self.empty_content)
        for label in (self.empty_title, self.empty_label):
            label.setMinimumWidth(0)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setTextFormat(Qt.TextFormat.PlainText)
            text_layout.addWidget(label)
        self.clear_filters_button = PushButton(tr("清除筛选"), self.empty_content)
        self.clear_filters_button.clicked.connect(self._clear_filters)
        text_layout.addWidget(self.clear_filters_button, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        content_layout.addWidget(self.empty_state, 1)
        self._scroll.setWidget(content)
        content.setAutoFillBackground(False)
        layout.addWidget(self._scroll)
        self.detail = QWidget(self.table)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)
        self.detail_meta = apply_label_role(
            BodyLabel(self.detail), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        self.detail_meta.setWordWrap(True)
        self.detail_meta.setTextFormat(Qt.TextFormat.PlainText)
        detail_layout.addWidget(self.detail_meta)
        self.device_summary = apply_label_role(BodyLabel(self.detail), FontRole.UI_SMALL)
        self.device_summary.setWordWrap(True)
        self.device_summary.setTextFormat(Qt.TextFormat.PlainText)
        detail_layout.addWidget(self.device_summary)
        self.action_results = ActionResultView(self.detail, inline=True)
        detail_layout.addWidget(self.action_results)
        self.run_results = (
            RunResultsWidget(run_library, self.detail, detail_only=True)
            if run_library is not None
            else None
        )
        if self.run_results is not None:
            detail_layout.addWidget(self.run_results)
            assert run_library is not None
            run_library.changed.connect(self.refresh)
        self.operation_output = PlainTextEdit(self.detail)
        self.operation_output.setReadOnly(True)
        self.operation_output.setMinimumHeight(120)
        self.operation_output.setMaximumHeight(200)
        apply_reading_surface(self.operation_output)
        detail_layout.addWidget(self.operation_output)
        self.detail.hide()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(max(0, int(poll_interval_ms)))
        self._poll_timer.timeout.connect(self.refresh)
        self.search_edit.textChanged.connect(self._render)
        for control in (self.state_combo, self.kind_combo):
            control.currentIndexChanged.connect(self._render)
        self.table.expanded_changed.connect(self._expanded)
        self.table.cancel_requested.connect(self._cancel_entry)
        self.action_results.selection_changed.connect(self._select_reader_request)
        BaseStyles.ui_font_changed.connect(self._refresh_typography)
        BaseStyles.theme_changed.connect(self._sync_theme_state)
        self._sync_theme_state()
        self._refresh_typography()
        self.refresh()

    def present_action_result(self, result: ActionResult) -> None:
        """后台推送只更新原记录，不主动展开、切换阅读项或滚动页面。"""
        if self._closed:
            return
        self.action_results.present(
            result,
            preserve_selection=self.table.expanded_key.startswith("action:"),
        )
        self.refresh()
        if not self.table.expanded_key.startswith("action:"):
            self.action_results.hide()

    def select_request(self, request_id: str) -> bool:
        """通知精确定位请求；撤销阻挡目标的条件，不提交设备动作。"""
        key = f"action:{request_id}"
        if self._closed or key not in self._entries:
            return False
        with (
            QSignalBlocker(self.search_edit),
            QSignalBlocker(self.kind_combo),
            QSignalBlocker(self.state_combo),
        ):
            self.search_edit.clear()
            self.kind_combo.setCurrentIndex(0)
            self.state_combo.setCurrentIndex(0)
        self._render()
        self.table.set_expanded(key)
        self._show_detail(key)
        self._scroll.ensureWidgetVisible(self.table.rows[key].header, 0, 12)
        return True

    def _select_reader_request(self, request_id: str) -> None:
        key = f"action:{request_id}"
        if self.table.expanded_key != key:
            self.select_request(request_id)

    def refresh(self, *_args) -> None:
        """读取不可变快照并合并明确关联，普通操作正文与列表共用同一有界缓存。"""
        if self._closed:
            return
        active = self._operation_manager.active_snapshot() if self._operation_manager else ()
        operations = {op.operation_id: op for op in active}
        results = self.action_results.records_snapshot()
        pending_ids = {
            oid for result in results if result.state == "running" for oid in result.operation_ids
        }
        # Operation 可先移入终态缓存；底层 worker 的结果回调到达前仍保留取消意图。
        self._cancel_pending.intersection_update(set(operations) | pending_ids)
        entries = []
        linked = set()
        for result in reversed(results):
            operation_ids = tuple(oid for oid in result.operation_ids if oid in operations)
            linked.update(operation_ids)
            snapshots = [operations[oid] for oid in operation_ids]
            cancelling = (
                any(
                    op.cancel_requested or op.operation_id in self._cancel_pending
                    for op in snapshots
                )
                or result.state == "running"
                and any(oid in self._cancel_pending for oid in result.operation_ids)
            )
            state = result.state
            if state == "recorded":
                states = {item.state for item in result.items}
                state = (
                    "failed"
                    if "failed" in states
                    else "warning"
                    if "warning" in states
                    else "recorded"
                )
            active_result = result.state == "running" or bool(snapshots)
            state_text = tr("正在取消") if cancelling else tr(_STATE_LABELS.get(state, state))
            target = " · ".join(
                ActionResults.target_label(result, target) for target in result.targets
            ) or tr("本机")
            kind, kind_label = self._kind(result.spec.key, result.spec.section)
            row = TaskRowData(
                f"action:{result.request_id}",
                tr(result.spec.title),
                kind_label,
                target,
                state_text,
                _STATE_TONES.get(state, "neutral"),
                self._date(result.finished_at or result.started_at),
                tr("本次"),
                bool(operation_ids) or cancelling,
                cancelling,
                state in ("failed", "partial", "warning")
                and self._read_versions.get(result.request_id) != self._version(result),
                round(sum(op.progress for op in snapshots) / len(snapshots)) if snapshots else None,
            )
            entries.append(
                _Entry(
                    row,
                    result,
                    state,
                    kind,
                    active_result,
                    operation_ids,
                    f"{row.title} {target} {row.time_text} "
                    f"{self._date(result.started_at, full=True)}",
                )
            )
        for op in active:
            if op.operation_id in linked:
                continue
            state = op.state.value
            cancelling = op.cancel_requested or op.operation_id in self._cancel_pending
            kind, kind_label = self._kind(op.kind)
            row = TaskRowData(
                f"operation:{op.operation_id}",
                _operation_label(op.kind),
                kind_label,
                tr("任务提交时的目标"),
                tr("正在取消") if cancelling else tr(_STATE_LABELS[state]),
                _STATE_TONES.get(state, "neutral"),
                tr("进行中"),
                tr("本次"),
                True,
                cancelling,
                progress=round(op.progress),
            )
            entries.append(_Entry(row, op, state, kind, True, (op.operation_id,), row.title))
        if self._library is not None:
            for record in self._library.records_view:
                title = tr("性能采集") if record.kind == "performance" else tr("Monkey 测试")
                kind_label = tr("性能") if record.kind == "performance" else "Monkey"
                target = record.device_label or tr("未记录设备名称")
                row = TaskRowData(
                    f"run:{record.run_id}",
                    title,
                    kind_label,
                    target,
                    tr("结果不完整")
                    if record.state == "partial"
                    else tr(_STATE_LABELS.get(record.state, record.state)),
                    _STATE_TONES.get(record.state, "neutral"),
                    self._date(record.finished_at),
                    tr("已归档"),
                )
                entries.append(
                    _Entry(
                        row,
                        record,
                        record.state,
                        record.kind,
                        False,
                        search_text=f"{title} {target} {record.package_name} "
                        f"{self._date(record.finished_at, full=True)}",
                    )
                )
        else:
            for sequence, entry in self._history_store.recent_with_ids(self._history_limit):
                kind, kind_label = self._kind(entry.kind)
                state = entry.state or ("succeeded" if entry.success else "failed")
                row = TaskRowData(
                    f"history:{entry.task_id}:{sequence}",
                    _operation_label(entry.kind),
                    kind_label,
                    tr("任务提交时的目标"),
                    tr(_STATE_LABELS.get(state, state)),
                    _STATE_TONES.get(state, "neutral"),
                    self._date(entry.finished_at),
                    tr("本次"),
                )
                entries.append(
                    _Entry(
                        row, entry, state, kind, False, search_text=f"{row.title} {row.time_text}"
                    )
                )
        entries = self._order_entries(entries)
        self._entries = {entry.row.key: entry for entry in entries}
        retained = {item.request_id for item in self.action_results.records_snapshot()}
        self._read_versions = {
            key: version for key, version in self._read_versions.items() if key in retained
        }
        natural = tuple(self._entries)
        self._ordered_keys = (
            tuple(key for key in self._frozen_order if key in self._entries)
            + tuple(key for key in natural if key not in self._frozen_order)
            if self._frozen_order
            else natural
        )
        self._render()
        if self.table.expanded_key:
            self._show_detail(self.table.expanded_key)

    def _render(self, *_args) -> None:
        if self._rendering:
            return
        self._rendering = True
        try:
            query = self.search_edit.text().strip().casefold()
            kind, state = self.kind_combo.currentData(), self.state_combo.currentData()
            description = (
                tr("部分成功 / 结果不完整")
                if state == "partial"
                else self.state_combo.currentText()
            )
            self.state_combo.setToolTip(description)
            self.state_combo.setAccessibleDescription(description)
            rows = tuple(
                self._entries[key].row
                for key in self._ordered_keys
                if (not kind or self._entries[key].kind == kind)
                and (
                    not state
                    or (
                        self._entries[key].active
                        if state == "active"
                        else self._entries[key].state == state
                    )
                )
                and (not query or query in self._entries[key].search_text.casefold())
            )
            self.table.set_rows(rows)
            self.count_label.setText(
                tr("{visible} / {total} 条记录 · {active} 项进行中 · {unread} 项异常待查看").format(
                    visible=len(rows),
                    total=len(self._entries),
                    active=sum(entry.active for entry in self._entries.values()),
                    unread=sum(entry.row.unread for entry in self._entries.values()),
                )
            )
            self.table.setVisible(bool(rows))
            self.empty_state.setVisible(not rows)
            self.empty_title.setText(
                tr("没有匹配的任务") if self._entries else tr("暂无任务")
            )
            self.empty_label.setText(
                tr("请调整搜索或筛选条件。")
                if self._entries
                else tr("执行操作或完成测试后，任务进度与结果会显示在这里。")
            )
            self.clear_filters_button.setVisible(bool(self._entries) and not rows)
        finally:
            self._rendering = False

    def _clear_filters(self) -> None:
        """只撤销查看条件，不改变任务、设备选择或任务执行状态。"""

        with (
            QSignalBlocker(self.search_edit), QSignalBlocker(self.state_combo),
            QSignalBlocker(self.kind_combo),
        ):
            self.search_edit.clear()
            self.state_combo.setCurrentIndex(0)
            self.kind_combo.setCurrentIndex(0)
        self._render()
        self.search_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def _expanded(self, key: str) -> None:
        self._frozen_order = self._ordered_keys if key else ()
        self._detail_signature = None
        if key:
            self._show_detail(key)
        else:
            self.detail.hide()
            if not self._rendering:
                self.refresh()

    def _show_detail(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None or entry.payload == self._detail_signature:
            return
        self._detail_signature = entry.payload
        result = entry.payload
        self.action_results.setVisible(isinstance(result, ActionResult))
        self.operation_output.setVisible(isinstance(result, (OperationSnapshot, TaskHistoryEntry)))
        if self.run_results is not None:
            self.run_results.setVisible(isinstance(result, RunRecord))
        self.detail_meta.setText(
            tr("已归档 · 关闭应用后仍可查看")
            if isinstance(result, RunRecord)
            else tr("本次会话 · 需要保留的正文请导出")
        )
        self.device_summary.hide()
        if isinstance(result, ActionResult):
            self._read_versions[result.request_id] = self._version(result)
            if entry.row.unread:
                updated = replace(entry, row=replace(entry.row, unread=False))
                self._entries[key] = updated
                self.table.rows[key].update_data(updated.row)
                self._render()
            self.action_results.select_request(result.request_id)
            lines = []
            for target in result.targets:
                items = [item for item in result.items if item.target == target]
                states = Counter(item.state for item in items)
                status = (
                    " · ".join(
                        tr("{count} 项{state}").format(
                            count=count,
                            state=tr(_STATE_LABELS.get(state, state)),
                        )
                        for state, count in states.items()
                    )
                    if items
                    else tr(_STATE_LABELS.get(result.state, result.state))
                )
                lines.append(f"{ActionResults.target_label(result, target)}  ·  {status}")
            self.device_summary.setText("\n".join(lines))
            self.device_summary.setVisible(bool(lines))
        elif isinstance(result, RunRecord) and self.run_results is not None:
            self.run_results.present_record(result)
        elif isinstance(result, (OperationSnapshot, TaskHistoryEntry)):
            message = result.message if isinstance(result, OperationSnapshot) else result.detail
            text = (
                message or tr("正在执行，请等待结果。")
                if entry.active
                else message or tr("操作已结束，无文本输出。")
            )
            if self.operation_output.toPlainText() != text:
                self.operation_output.setPlainText(text[:64000])
        self.table.set_expanded(key, self.detail)

    def _cancel_entry(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is not None:
            for operation_id in entry.operation_ids:
                self._cancel(operation_id)

    def _cancel(self, task_id: str) -> None:
        """登记原任务取消意图并调用资源停止入口；受理不等同于资源已经退出。"""
        if self._closed or task_id in self._cancel_pending:
            return
        accepted = False
        if self._operation_manager is not None:
            accepted = self._operation_manager.request_cancel(task_id)
            snapshot = self._operation_manager.get(task_id)
            accepted = accepted or bool(snapshot and snapshot.cancel_requested)
        if self._stop_hook is not None:
            try:
                self._stop_hook(task_id)
                accepted = True
            except Exception:
                logging.getLogger(__name__).exception("任务取消资源请求失败")
        if accepted:
            self._cancel_pending.add(task_id)
        self.refresh()

    def record_history(self, entry: TaskHistoryEntry) -> None:
        """保留未注入测试库的兼容历史入口。"""
        self._history_store.record(entry)
        self.refresh()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._closed:
            self.refresh()
            self._poll_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        self._poll_timer.stop()
        super().hideEvent(event)

    def shutdown(self) -> None:
        """停止轮询并封闭晚到结果准入；共享测试库仍由主窗口负责释放。"""
        self._closed = True
        self._poll_timer.stop()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reflow_filters()

    def _refresh_typography(self, *_args) -> None:
        apply_label_role(self.title_label, FontRole.TITLE, bold=True)
        apply_label_role(self.empty_title, FontRole.UI, bold=True)
        for control in (
            self.search_edit, self.state_combo, self.kind_combo, self.clear_filters_button,
        ):
            configure_fluent_control(control)
        for label in (self.count_label, self.empty_label, self.detail_meta, self.device_summary):
            apply_label_role(label, FontRole.UI_SMALL, color_key="TEXT_SECONDARY")
        self.operation_output.setFont(BaseStyles.font_for_role(FontRole.LOG))
        self._layout_mode = None
        self._reflow_filters()

    def _sync_theme_state(self, *_args) -> None:
        """独立页面使用主题底色；嵌入主窗口时继续透出既有共享材质。"""
        if self.isWindow():
            palette = self.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor(BaseStyles.color("WINDOW_BG")))
            self.setPalette(palette)
            self.setAutoFillBackground(True)

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "filters", None) and event.type() == QEvent.Type.Resize:
            self._reflow_filters()
        return super().eventFilter(watched, event)

    def _reflow_filters(self) -> None:
        width = max(0, min(self.width() - 64, self.filters.width()))
        state_size = self._filter_preferred_size(self.state_combo)
        kind_size = self._filter_preferred_size(self.kind_combo)
        state_width, kind_width = state_size.width(), kind_size.width()
        height = max(state_size.height(), kind_size.height())
        combo_width = state_width + kind_width + 8
        inline = width >= combo_width + 240
        stacked = width < combo_width
        # 固定预算不随当前选项变化；同一排布模式下缩窗也必须更新封顶宽度。
        self.state_combo.setFixedSize(min(state_width, width), height)
        self.kind_combo.setFixedSize(min(kind_width, width), height)
        self.search_edit.setFixedHeight(height)
        if self._layout_mode == (inline, stacked):
            return
        self._layout_mode = (inline, stacked)
        while self._filter_layout.count():
            self._filter_layout.takeAt(0)
        for column in range(3):
            self._filter_layout.setColumnStretch(column, 0)
        if inline:
            self._filter_layout.addWidget(self.search_edit, 0, 0)
            self._filter_layout.addWidget(self.state_combo, 0, 1)
            self._filter_layout.addWidget(self.kind_combo, 0, 2)
            self._filter_layout.setColumnStretch(0, 1)
        else:
            self._filter_layout.addWidget(self.search_edit, 0, 0, 1, 3)
            self._filter_layout.addWidget(
                self.state_combo,
                1,
                0,
                1,
                3 if stacked else 1,
                Qt.AlignmentFlag.AlignLeft,
            )
            self._filter_layout.addWidget(
                self.kind_combo,
                2 if stacked else 1,
                0 if stacked else 1,
                1,
                3 if stacked else 1,
                Qt.AlignmentFlag.AlignLeft,
            )
            self._filter_layout.setColumnStretch(2, 1)

    @staticmethod
    def _filter_preferred_size(combo: ElidingComboBox) -> QSize:
        """按完整选项与实际按钮样式测量，不临时选择选项或触发业务信号。"""
        option = QStyleOptionButton()
        combo.initStyleOption(option)
        popup_metrics = QFontMetrics(getFont())
        sizes = []
        for index in range(combo.count()):
            text = combo.itemText(index)
            setattr(option, "text", text)
            text_size = combo.fontMetrics().size(Qt.TextFlag.TextShowMnemonic, text)
            styled = combo.style().sizeFromContents(
                QStyle.ContentsType.CT_PushButton,
                option,
                text_size,
                combo,
            )
            # 省略控件为箭头预留 48px，部分主题的原生边距更小，须同时满足两种预算。
            # 弹层沿用 Fluent 的 14px 字体和左右 40px 留白、2px 边框；低 DPI 下
            # 它可能比用户的按钮字体更大，不能只按按钮字体计算展开宽度。
            popup_width = popup_metrics.boundingRect(text).width() + 42
            sizes.append(
                QSize(
                    max(styled.width(), text_size.width() + 48, popup_width),
                    styled.height(),
                )
            )
        return QSize(
            max((size.width() for size in sizes), default=0),
            max((size.height() for size in sizes), default=0),
        )

    @staticmethod
    def _order_entries(entries: list[_Entry]) -> list[_Entry]:
        """在途优先；按墙钟插入归档，同时保留普通结果的实际完成/更新顺序。"""
        active = [entry for entry in entries if entry.active]
        actions = deque(
            entry
            for entry in entries
            if not entry.active and isinstance(entry.payload, ActionResult)
        )
        others = deque(
            sorted(
                (
                    entry
                    for entry in entries
                    if not entry.active and isinstance(entry.payload, (RunRecord, TaskHistoryEntry))
                ),
                key=lambda entry: entry.payload.finished_at or 0,
                reverse=True,
            )
        )
        while actions and others:
            action = actions[0].payload
            assert isinstance(action, ActionResult)
            other = others[0].payload
            assert isinstance(other, (RunRecord, TaskHistoryEntry))
            active.append(
                actions.popleft()
                if (action.finished_at or action.started_at) >= other.finished_at
                else others.popleft()
            )
        return [*active, *actions, *others]

    @staticmethod
    def _version(result: ActionResult) -> tuple:
        """已读仅按事件身份与终态保存，不延长大段正文的保留周期。"""
        return (
            result.state,
            result.finished_at,
            tuple((item.job_id, item.state) for item in result.items),
        )

    @staticmethod
    def _kind(key: str, section: str = "") -> tuple[str, str]:
        if section == "apps.monkey" or key in ("monkey", "run_monkey_test", "kill_monkey"):
            return "monkey", "Monkey"
        if section == "system.shell" or key == "shell_command":
            return "shell", "Shell"
        if key.startswith("file_") or "file" in section:
            return "file", tr("文件")
        if section.startswith("devices") or key in ("connect", "disconnect", "get_info", "refresh"):
            return "device", tr("设备")
        if section.startswith("apps") or key in ("batch_install", "install", "uninstall"):
            return "app", tr("应用")
        if section.startswith("system"):
            return "system", tr("系统")
        return "other", tr("其他")

    @staticmethod
    def _date(timestamp: float, *, full: bool = False) -> str:
        try:
            return datetime.fromtimestamp(timestamp).strftime(
                "%Y-%m-%d %H:%M:%S" if full else "%m-%d %H:%M"
            )
        except (OSError, OverflowError, ValueError):
            return ""


__all__ = ["DEFAULT_HISTORY_LIMIT", "POLL_INTERVAL_MS", "TaskCenterPage"]
