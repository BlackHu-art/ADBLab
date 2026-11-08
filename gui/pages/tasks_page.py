"""单页任务中心：投影既有任务与归档，共享阅读器，不接管执行资源。"""

from __future__ import annotations

import logging
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from PySide6.QtCore import QEvent, QPoint, QSignalBlocker, QSize, Qt, QTimer, Signal
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
from gui.session_tasks import SessionTaskSnapshot
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import (
    apply_label_role,
    apply_reading_surface,
    configure_fluent_control,
    use_smooth_scroll,
)
from gui.widgets.action_result_view import STATE_LABELS as ITEM_STATE_LABELS
from gui.widgets.action_result_view import ActionResultView, result_target_caption
from gui.widgets.eliding_combo_box import ElidingComboBox
from gui.widgets.reader_interaction import ReaderInteraction
from gui.widgets.run_results import RunResultsWidget
from gui.widgets.task_navigation import TaskNavigationSnapshot
from gui.widgets.task_table import TaskRowData, TaskTable
from services.run_library import RunRecord
from services.task_history import TaskHistoryEntry, TaskHistoryStore
from services.tasks.action_results import ActionResult, ActionResults
from services.tasks.operations import OperationManager, OperationSnapshot

POLL_INTERVAL_MS = 1000
DEFAULT_HISTORY_LIMIT = 50

_STATE_LABELS = {
    "starting": "启动中",
    "stopping": "停止中",
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
    payload: ActionResult | OperationSnapshot | RunRecord | TaskHistoryEntry | SessionTaskSnapshot
    state: str
    kind: str
    active: bool
    operation_ids: tuple[str, ...] = ()
    search_text: str = ""


class TaskCenterPage(QWidget):
    """统一列表与共享阅读器；外部宿主固定挂载详情，独立使用时保留行内入口。"""

    session_stop_requested = Signal(str, str)
    detail_requested = Signal(str)
    detail_changed = Signal(str)
    detail_closed = Signal()
    navigation_snapshot_changed = Signal(object)

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
        external_details: bool = False,
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
        self._external_details = external_details
        self._reader_hosted = False
        self._reader_interaction_guard: Callable[[], bool] | None = None
        self._operation_action_key = ""
        self._selected_key = ""
        self._selecting_entry = False
        self._navigation = TaskNavigationSnapshot()
        self._success_sequence = 0
        self._entries: dict[str, _Entry] = {}
        self._recent_ranks: dict[str, int] = {}
        self._ordered_keys: tuple[str, ...] = ()
        self._frozen_order: tuple[str, ...] = ()
        self._detail_signature: object = None
        self._cancel_pending: set[str] = set()
        self._read_versions: dict[str, tuple] = {}
        self._session_snapshots: tuple[SessionTaskSnapshot, ...] = ()
        self._session_read_versions: dict[str, tuple] = {}
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
        self.table = TaskTable(content, external_details=external_details)
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
        self._operation_interaction = ReaderInteraction(
            self.operation_output,
            lambda: self._reader_interaction_guard is None or self._reader_interaction_guard(),
            lambda: self.selected_key,
        )
        self._operation_interaction.watch_editor(self.operation_output)
        self.operation_output.setMinimumHeight(120)
        self.operation_output.setMaximumHeight(200)
        apply_reading_surface(self.operation_output)
        detail_layout.addWidget(self.operation_output)
        self.detail.hide()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(max(0, int(poll_interval_ms)))
        self._poll_timer.timeout.connect(self.refresh)
        self.search_edit.textChanged.connect(self._render)
        self.kind_combo.currentIndexChanged.connect(self._render)
        self.table.expanded_changed.connect(self._expanded)
        self.table.detail_requested.connect(self.select_entry)
        self.table.cancel_requested.connect(self._cancel_entry)
        self.table.stop_requested.connect(self.request_session_stop)
        self.action_results.selection_changed.connect(self._select_reader_request)
        BaseStyles.ui_font_changed.connect(self._refresh_typography)
        BaseStyles.theme_changed.connect(self._sync_theme_state)
        self._sync_theme_state()
        self._refresh_typography()
        self.refresh()

    @property
    def selected_key(self) -> str:
        """返回阅读身份；外部详情不依赖筛选后是否仍有对应记录行。"""
        return self._selected_key if self._external_details else self.table.expanded_key

    def detail_row(self, key: str) -> TaskRowData | None:
        """读取未筛选记录的已脱敏元数据，不改变选择与阅读状态。"""
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._reader_hosted and isinstance(entry.payload, ActionResult):
            # 列表仍需本机占位；详情只显式列出实际提交的设备，即使其显示名恰为“本机”。
            result = entry.payload
            targets = [result_target_caption(result, t) for t in result.targets if t]
            caption = " · ".join(targets)
            if len(targets) > 1:
                caption += tr(" · {count} 台目标设备").format(count=len(targets))
            return replace(entry.row, target=caption)
        return entry.row

    def allows_automatic_details(self, key: str) -> bool:
        """只允许机器状态可证明的失败自动呈现，不改变选择、筛选或异常已读。

        notes 只判断最新事件，避免历史失败让后续成功重新弹出。普通 partial 的
        非空条目全成功时，依据 ActionResults._settle 的完整归并规则可确认请求级失败。
        """
        entry = self._entries.get(key)
        if self._closed or entry is None:
            return False
        result = entry.payload
        if isinstance(result, ActionResult):
            if result.spec.presentation == "notes":
                return (result.state == "recorded" and bool(result.items)
                        and result.items[-1].state == "failed")
            if result.state == "failed":
                return True
            if result.state != "partial":
                return False
            states = {item.state for item in result.items}
            return "failed" in states or states == {"succeeded"}
        return entry.state == "failed"

    def reader_for_drawer(self, *, interaction_guard: Callable[[], bool] | None = None) -> QWidget:
        """固定挂载单例正文；宿主可约束用户动作，页面继续拥有身份与后台内容。"""
        self._reader_hosted = True
        self._reader_interaction_guard = interaction_guard
        self.action_results.set_hosted_full_results(True)
        self.action_results.set_interaction_guard(
            (lambda: interaction_guard() and self.action_results.isVisible())
            if interaction_guard is not None else None
        )
        if self.run_results is not None:
            reader = self.run_results
            reader.set_hosted_full_results(True)
            reader.set_interaction_guard(
                (lambda: interaction_guard() and reader.isVisible())
                if interaction_guard is not None else None
            )
        return self.detail

    def revoke_reader_interactions(self) -> None:
        """关闭或宿主撤销呈现时停止未完用户动作，正文仍由既有末帧协议持有。"""
        self.action_results.revoke_interactions()
        if self.run_results is not None:
            self.run_results.revoke_interactions()
        self._operation_interaction.revoke()

    def detail_source(self, key: str) -> str:
        """仅返回已有稳定来源；不依据当前目标猜测执行入口。"""
        entry = self._entries.get(key)
        if entry is not None:
            if isinstance(entry.payload, ActionResult):
                return entry.payload.spec.section
            if isinstance(entry.payload, SessionTaskSnapshot):
                return {"performance": "system.performance", "logcat": "system.logcat",
                        "remote": "devices.remote"}.get(entry.payload.kind, "")
            if isinstance(entry.payload, RunRecord):
                return (
                    "system.performance" if entry.payload.kind == "performance" else "apps.monkey"
                )
        return ""

    def recent_rows(self) -> tuple[TaskRowData, ...]:
        """返回全部保留记录的自然新近顺序，不沿用阅读时冻结的可视列表位置。"""
        return tuple(entry.row for entry in self._entries.values())

    def navigation_snapshot(self) -> TaskNavigationSnapshot:
        """提供未筛选的逻辑任务统计，成功身份只来自观察到的实时终态转换。"""
        return self._navigation

    def select_entry(
        self, key: str, *, clear_filters: bool = False, mark_read: bool = True,
    ) -> bool:
        """显式选择稳定身份；自动呈现不消费异常版本，重复显式请求仍可打开宿主。"""
        if self._closed or key not in self._entries:
            return False
        if clear_filters:
            self._reset_filters()
        if not self._external_details and key not in self.table.rows:
            return False
        if self._external_details:
            self._selected_key = key
            self._frozen_order = self._ordered_keys
        else:
            # 行点击默认消费已读；公共选择入口单独按 mark_read 提交，避免同步信号抢先确认。
            self._selecting_entry = True
            try:
                self.table.set_expanded(key)
            finally:
                self._selecting_entry = False
        self._show_detail(key)
        if mark_read:
            self._mark_read(key)
        self.detail_requested.emit(key)
        if not self._external_details and key in self.table.rows:
            header = self.table.rows[key].header
            # 两层视口依次定位，在行头下方留出一行阅读空间。
            for area in (self.table.view, self._scroll):
                anchor = header.mapTo(area.widget(), QPoint(0, header.height()))
                area.ensureVisible(anchor.x(), anchor.y(), 0, header.height())
        return True

    def close_detail(self) -> None:
        """立即释放失效或收起的身份；已挂载的正文随抽屉末帧一起隐藏。"""
        if not self.selected_key:
            return
        if not self._external_details:
            self.table.set_expanded("")
            return
        self._selected_key = ""
        self._frozen_order = ()
        self._detail_signature = None
        if not self._reader_hosted:
            self.detail.hide()
        self.detail_closed.emit()
        if not self._closed:
            self.refresh()

    def cancel_entry(self, key: str) -> None:
        """按原提交身份请求取消，不将请求受理视作执行资源已释放。"""
        if not self._closed:
            self._cancel_entry(key)

    def request_session_stop(self, key: str, expected_revision: str) -> None:
        """仅转发手势按下时仍匹配的原会话；版本换代后不能重新解释成停止新运行。"""
        entry = self._entries.get(key)
        if self._closed or entry is None or not isinstance(entry.payload, SessionTaskSnapshot):
            return
        session = entry.payload
        if (session.revision == expected_revision and session.resource_owned
                and session.stop_enabled):
            self.session_stop_requested.emit(session.key, expected_revision)

    def present_action_result(self, result: ActionResult) -> None:
        """后台推送只更新原记录，不主动展开、切换阅读项或滚动页面。"""
        if self._closed:
            return
        self.action_results.present(
            result,
            preserve_selection=self.selected_key.startswith("action:"),
        )
        self.refresh()
        if not self.selected_key.startswith("action:"):
            self.action_results.hide()

    def select_request(self, request_id: str) -> bool:
        """通知精确定位请求；撤销阻挡目标的条件，不提交设备动作。"""
        return self.select_entry(f"action:{request_id}", clear_filters=True)

    def _select_reader_request(self, request_id: str) -> None:
        key = f"action:{request_id}"
        if self.selected_key != key:
            self.select_request(request_id)

    def set_session_snapshots(self, snapshots: tuple[SessionTaskSnapshot, ...]) -> None:
        """接收原 owner 的内存投影；停止受理或来源消失不能推断资源已成功释放。"""
        if self._closed or snapshots == self._session_snapshots:
            return
        self._session_snapshots = snapshots
        retained = {snapshot.key for snapshot in snapshots}
        self._session_read_versions = {
            key: version for key, version in self._session_read_versions.items() if key in retained
        }
        self.refresh()

    @staticmethod
    def _session_version(snapshot: SessionTaskSnapshot) -> tuple:
        """稳定异常版本不含轮询时钟；同 owner 的下一次运行仍需要重新确认。"""
        return snapshot.revision, snapshot.state, snapshot.detail

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
        for session in self._session_snapshots:
            title = tr({"performance": "性能采集", "logcat": "实时 Logcat",
                        "remote": "远程控制"}.get(session.kind, "持续会话"))
            target = " · ".join(session.target_labels) or tr("任务提交时的目标")
            row = TaskRowData(
                f"session:{session.key}", title,
                tr("性能") if session.kind == "performance" else tr("系统"),
                target, tr("已停止") if session.state == "cancelled"
                else tr(_STATE_LABELS.get(session.state, session.state)),
                _STATE_TONES.get(session.state, "accent" if session.resource_owned else "neutral"),
                tr("进行中") if session.resource_owned else tr("已结束"), tr("持续会话"),
                cancellable=session.resource_owned
                and (session.stop_enabled or session.state == "stopping"),
                cancelling=session.resource_owned and session.state == "stopping"
                and not session.stop_enabled,
                unread=session.state in ("failed", "partial", "warning")
                and self._session_read_versions.get(session.key) != self._session_version(session),
                stop_action=True,
                stop_revision=session.revision,
            )
            entries.append(_Entry(
                row, session, session.state,
                "performance" if session.kind == "performance" else "system",
                session.resource_owned, search_text=f"{title} {target}",
            ))
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
        previous = self._entries
        self._entries = {entry.row.key: entry for entry in entries}
        # 消失、旧归档和说明更新不代表成功；只消费明确观察到的业务终态。
        if any(
            key in previous and previous[key].active and not entry.active
            and entry.state == "succeeded" and (
                isinstance(entry.payload, ActionResult)
                and entry.payload.spec.presentation != "notes"
                or isinstance(entry.payload, SessionTaskSnapshot)
                and isinstance(previous[key].payload, SessionTaskSnapshot)
                and cast(SessionTaskSnapshot, previous[key].payload).revision
                == entry.payload.revision
            )
            for key, entry in self._entries.items()
        ):
            self._success_sequence += 1
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
        if self.selected_key:
            if self.selected_key not in self._entries:
                self.close_detail()
            else:
                self._show_detail(self.selected_key)
                if self._external_details:
                    self.detail_changed.emit(self.selected_key)
        # 同线程订阅者会立即查询页面；排序、行数据和失效选择必须先完成本代提交。
        self._publish_navigation()

    def _publish_navigation(self) -> None:
        """筛选与阅读状态只影响展示；全局统计始终使用合并后的逻辑任务。"""
        snapshot = TaskNavigationSnapshot(
            active_count=sum(entry.active for entry in self._entries.values()),
            busy_count=sum(
                entry.active and (
                    not isinstance(entry.payload, SessionTaskSnapshot)
                    or entry.payload.busy
                    or entry.payload.state in {"starting", "stopping", "finalizing"}
                )
                for entry in self._entries.values()
            ),
            unread_count=sum(entry.row.unread for entry in self._entries.values()),
            success_event_id=(
                f"task-success:{self._success_sequence}" if self._success_sequence else None
            ),
        )
        if snapshot != self._navigation:
            self._navigation = snapshot
            self.navigation_snapshot_changed.emit(snapshot)

    def _render(self, *_args) -> None:
        if self._rendering:
            return
        self._rendering = True
        try:
            query = self.search_edit.text().strip().casefold()
            kind = self.kind_combo.currentData()
            rows = tuple(
                self._entries[key].row
                for key in self._ordered_keys
                if (not kind or self._entries[key].kind == kind)
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

        self._reset_filters()
        self.search_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def _reset_filters(self) -> None:
        with (
            QSignalBlocker(self.search_edit), QSignalBlocker(self.kind_combo),
        ):
            self.search_edit.clear()
            self.kind_combo.setCurrentIndex(0)
        self._render()

    def _expanded(self, key: str) -> None:
        self._frozen_order = self._ordered_keys if key else ()
        self._detail_signature = None
        if key:
            self._show_detail(key)
            if not self._selecting_entry:
                self._mark_read(key)
                self.detail_requested.emit(key)
        else:
            self.detail.hide()
            self.detail_closed.emit()
            if not self._rendering:
                self.refresh()

    def _show_detail(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None or entry.payload == self._detail_signature:
            return
        self._detail_signature = entry.payload
        result = entry.payload
        if key != self._operation_action_key:
            self._operation_interaction.revoke()
            self._operation_action_key = key
        # 抽屉状态提示统一承载保留说明；持续会话的来源提示仍是正文契约，不能一并隐藏。
        self.detail_meta.setVisible(
            not self._reader_hosted or isinstance(result, SessionTaskSnapshot),
        )
        self.action_results.setVisible(isinstance(result, ActionResult))
        self.operation_output.setVisible(
            isinstance(result, (OperationSnapshot, TaskHistoryEntry, SessionTaskSnapshot))
        )
        if self.run_results is not None:
            self.run_results.setVisible(isinstance(result, RunRecord))
        self.detail_meta.setText(
            tr("已归档 · 关闭应用后仍可查看")
            if isinstance(result, RunRecord)
            else tr("本次会话 · 需要保留的正文请导出")
        )
        self.device_summary.hide()
        if isinstance(result, ActionResult):
            self.action_results.select_request(result.request_id)
            lines = []
            if (
                result.targets and result.state in ("succeeded", "partial", "failed", "cancelled")
                and result.spec.presentation != "notes"
            ):
                counts = ActionResults.target_outcomes(result)
                if result.state == "partial" and not counts["failed"] and not counts["cancelled"]:
                    # 请求级收尾失败没有逐台归属，不能把子命令成功冒充设备最终成功。
                    lines.append(
                        tr("部分操作失败")
                        + tr(" · {count} 台目标设备").format(count=len(result.targets))
                    )
                elif not self._reader_hosted or len(result.targets) > 1:
                    labels = {
                        "succeeded": tr("成功 {count} 台"),
                        "failed": tr("失败 {count} 台"),
                        "cancelled": tr("未完成 {count} 台"),
                    }
                    lines.append(" · ".join(
                        label.format(count=counts[state])
                        for state, label in labels.items() if counts[state]
                    ))
            if (self._reader_hosted and result.spec.presentation != "notes"
                    and len(result.items) == 1):
                item = result.items[0]
                # 单条没有可切换项；仅补充与请求标题不一致的归属和子命令状态。
                same_target = (not item.target and not result.targets
                               or result.targets == (item.target,))
                if not same_target or item.state != result.state:
                    item_state = tr(ITEM_STATE_LABELS.get(item.state, item.state))
                    lines.append(item_state if same_target else (
                        f"{result_target_caption(result, item.target)} · {item_state}"
                    ))
            for target in result.targets:
                items = [item for item in result.items if item.target == target]
                if self._reader_hosted and (len(result.targets) < 2 or items):
                    continue
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
                if self._reader_hosted:
                    # 未返回设备不能借用请求的部分成功或子项完成状态。
                    status = tr("运行中") if result.state == "running" else tr("结果不完整")
                name = (result_target_caption(result, target) if self._reader_hosted
                        else ActionResults.target_label(result, target))
                lines.append(f"{name}  ·  {status}")
            self.device_summary.setText("\n".join(lines))
            self.device_summary.setVisible(bool(lines))
        elif isinstance(result, RunRecord) and self.run_results is not None:
            self.run_results.present_record(result)
        elif isinstance(result, SessionTaskSnapshot):
            source_hint = tr("完整会话内容请返回来源页面查看。")
            text = result.detail or source_hint
            if self.operation_output.toPlainText() != text[:64000]:
                self.operation_output.setPlainText(text[:64000])
            self.device_summary.setText("\n".join(result.target_labels))
            self.device_summary.setVisible(bool(result.target_labels) and not self._reader_hosted)
            self.detail_meta.setText(source_hint)
            self.operation_output.setVisible(not self._reader_hosted or text != source_hint)
        elif isinstance(result, (OperationSnapshot, TaskHistoryEntry)):
            message = result.message if isinstance(result, OperationSnapshot) else result.detail
            text = (
                message or tr("正在执行，请等待结果。")
                if entry.active
                else message or tr("操作已结束，无文本输出。")
            )
            if self.operation_output.toPlainText() != text:
                self.operation_output.setPlainText(text[:64000])
        if self._external_details:
            self.detail.show()
        else:
            self.table.set_expanded(key, self.detail)

    def _mark_read(self, key: str) -> None:
        """只消费用户明确查看时的版本；相同请求的新异常仍需再次确认。"""
        entry = self._entries.get(key)
        if entry is None:
            return
        if isinstance(entry.payload, ActionResult):
            self._read_versions[entry.payload.request_id] = self._version(entry.payload)
        elif isinstance(entry.payload, SessionTaskSnapshot):
            self._session_read_versions[entry.payload.key] = self._session_version(entry.payload)
        else:
            return
        if entry.row.unread:
            updated = replace(entry, row=replace(entry.row, unread=False))
            self._entries[key] = updated
            self._render()
            self._publish_navigation()

    def _cancel_entry(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is not None:
            if isinstance(entry.payload, SessionTaskSnapshot):
                session = entry.payload
                if session.resource_owned and session.stop_enabled:
                    self.session_stop_requested.emit(session.key, session.revision)
                return
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
            self.search_edit, self.kind_combo, self.clear_filters_button,
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
        """类型按钮按全部选项统一预算，窄窗只把搜索与类型分成两行。"""
        width = max(0, min(self.width() - 64, self.filters.width()))
        kind_size = self._filter_preferred_size(self.kind_combo)
        inline = width >= kind_size.width() + 248
        self.kind_combo.setFixedSize(min(kind_size.width(), width), kind_size.height())
        self.search_edit.setFixedHeight(kind_size.height())
        if self._layout_mode == (inline, False):
            return
        self._layout_mode = (inline, False)
        while self._filter_layout.count():
            self._filter_layout.takeAt(0)
        self._filter_layout.setColumnStretch(0, 1)
        self._filter_layout.setColumnStretch(1, 0)
        self._filter_layout.addWidget(self.search_edit, 0, 0, 1, 1 if inline else 2)
        self._filter_layout.addWidget(
            self.kind_combo, 0 if inline else 1, 1 if inline else 0,
            Qt.AlignmentFlag.AlignLeft,
        )

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

    def _order_entries(self, entries: list[_Entry]) -> list[_Entry]:
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
                key=lambda entry: (
                    cast(RunRecord | TaskHistoryEntry, entry.payload).finished_at or 0
                ),
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
        sessions = [entry for entry in entries
                    if not entry.active and isinstance(entry.payload, SessionTaskSnapshot)]
        ordered = [*active, *actions, *others]
        # 会话没有完成时间。仅记本页观察到的收尾次序，与普通结果的原排序归并。
        # 首次出现的终态会话排在已知结果之后，不把载入、改名或阅读当成刚完成。
        sequence = max(self._recent_ranks.values(), default=0) + 1
        ranks = {}
        for entry in entries:
            if entry.active:
                continue
            key = entry.row.key
            old = self._entries.get(key)
            previous = self._recent_ranks.get(key, 0)
            if isinstance(entry.payload, SessionTaskSnapshot):
                if (old is None or not isinstance(old.payload, SessionTaskSnapshot)
                        or old.payload.revision != entry.payload.revision):
                    ranks[key] = 0
                else:
                    ranks[key] = sequence if old.active else previous
            else:
                ranks[key] = sequence if old is None or old.payload != entry.payload else previous
        self._recent_ranks = ranks
        if not sessions:
            return ordered
        pending = deque(sorted(sessions, key=lambda entry: ranks[entry.row.key], reverse=True))
        merged = []
        for entry in ordered:
            while not entry.active and pending and ranks[pending[0].row.key] > ranks[entry.row.key]:
                merged.append(pending.popleft())
            merged.append(entry)
        return [*merged, *pending]

    @staticmethod
    def _version(result: ActionResult) -> tuple:
        """已读仅按事件身份与终态保存，不延长大段正文的保留周期。"""
        if result.spec.presentation == "notes":
            # 容量轮转移除较旧异常不代表新事件；最近异常身份足以识别后续新增异常。
            return next((
                (item.job_id, item.state)
                for item in reversed(result.items)
                if item.state in ("failed", "partial", "warning")
            ), ())
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
