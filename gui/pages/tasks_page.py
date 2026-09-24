"""任务中心页：在途任务、可持久化测试结果与本次操作记录。

可取消任务读取 ``OperationManager.active_snapshot()``；通用命令由组合根推送
ActionResult 快照，包含普通长命令的在途入口与本次操作历史。Monkey/性能的跨会话
结果由共享测试库异步更新；未注入测试库时保留 TaskHistoryStore 兼容入口。页面可见时
以 1000ms ``QTimer`` 轮询并做不可变快照 diff，无变化
不更新控件；活动行按任务身份复用，隐藏时停表。取消按钮走双路径：
``OperationManager.request_cancel`` + 注入的资源停止回调 ``stop_hook``。

构造契约：``panel`` 预留为 SidePanel 兼容入口；在途视图
需要注入 ``operation_manager`` 才能读取可取消任务，普通命令快照不依赖此注入。
``refresh()`` 是本页对组合根的稳定契约：同步重读在途快照与历史并按 diff 更新。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QHideEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    HeaderCardWidget,
    InfoBadge,
    InfoLevel,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SmoothScrollArea,
)

from adblab.application.action_results import ActionResult
from adblab.application.operations import OperationManager, OperationSnapshot, OperationState
from gui.i18n import tr
from gui.run_library import RunLibraryController
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_font_role, apply_label_role, configure_button
from gui.widgets.category_stack import AdaptiveCategoryStack
from gui.widgets.content_section import ContentSection
from gui.widgets.run_results import RunResultsWidget
from services.task_history import TaskHistoryEntry, TaskHistoryStore

# 在途视图轮询间隔（毫秒）。
POLL_INTERVAL_MS = 1000

# 历史视图默认展示条数。
DEFAULT_HISTORY_LIMIT = 50

# 状态 → 中文标签。
_STATE_LABELS = {
    OperationState.QUEUED: "排队中",
    OperationState.RUNNING: "运行中",
    OperationState.FINALIZING: "收尾中",
    OperationState.SUCCEEDED: "成功",
    OperationState.PARTIAL: "部分成功",
    OperationState.FAILED: "失败",
    OperationState.CANCELLED: "已取消",
}

# 状态 → 徽标语义配色。
_STATE_TONES = {
    OperationState.QUEUED: "neutral",
    OperationState.RUNNING: "accent",
    OperationState.FINALIZING: "accent",
    OperationState.SUCCEEDED: "success",
    OperationState.PARTIAL: "warning",
    OperationState.FAILED: "danger",
    OperationState.CANCELLED: "danger",
}


# 操作类型只在展示边界映射，历史记录、取消路由和未知扩展类型保留原始标识。
_OPERATION_LABELS = {
    "apk_info": "APK 信息", "batch_install": "批量安装", "install": "安装应用",
    "battery_reset": "重置电池状态", "battery_set": "设置电池状态", "bugreport": "错误报告",
    "cleanup_device_logs": "清理设备日志", "clear_data": "清除应用数据", "connect": "连接设备",
    "content_query": "查询内容提供者", "cpu_info": "CPU 信息", "current_activity": "当前 Activity",
    "deep_link": "打开链接", "device_uptime": "设备运行时间", "disable_app": "禁用应用",
    "disable_app_for_user": "对当前用户禁用应用", "disconnect": "断开设备",
    "dumpsys_battery": "电池信息", "dumpsys_cpuinfo": "CPU 使用情况",
    "dumpsys_meminfo": "内存信息", "dumpsys_service": "查询系统服务", "emu_call": "模拟来电",
    "emu_geo": "模拟位置", "emu_sms": "模拟短信", "enable_app": "启用应用",
    "file_list": "列出文件", "file_pull": "下载文件", "file_push": "上传文件",
    "force_stop": "强行停止应用", "forward_port": "添加端口转发", "get_info": "获取设备信息",
    "get_package": "获取前台应用", "gfxinfo": "图形渲染信息", "grant_permission": "授予权限",
    "ime_list": "列出输入法", "ime_set": "设置输入法", "input_keyevent": "发送按键事件",
    "input_swipe": "发送滑动手势", "input_tap": "发送点击", "input_text": "发送文本",
    "installed_packages": "已安装应用", "kernel_version": "内核版本",
    "kill_monkey": "停止 Monkey", "kill_process": "结束进程", "list_forwards": "列出端口转发",
    "list_processes": "进程列表", "list_reverse": "列出反向转发", "logcat_filtered": "筛选 Logcat",
    "monkey": "Monkey 测试", "netstats_detail": "网络统计", "pair_device": "配对设备",
    "pm_features": "设备功能", "pull_anr": "获取 ANR", "pull_recording": "下载录屏",
    "quick_setting": "快捷设置", "reboot_mode": "重启设备", "refresh": "刷新设备",
    "remove_forwards": "移除端口转发", "remove_reverse": "移除反向转发", "restart": "重启设备",
    "restart_adb": "重启 ADB", "restart_app": "重启应用", "retrieve_device_logs": "获取设备日志",
    "reverse_port": "添加反向转发", "revoke_permission": "撤销权限", "screen_record": "录制屏幕",
    "screenshot": "截图", "send_broadcast": "发送广播", "settings_get": "读取系统设置",
    "settings_list": "列出系统设置", "settings_put": "写入系统设置", "shell_command": "执行 Shell",
    "start_activity": "启动 Activity", "stop_recording": "停止录屏", "tcpip_mode": "开启 TCP/IP",
    "top_snapshot": "进程快照", "uninstall": "卸载应用", "wakelocks": "唤醒锁",
}


def _operation_label(kind: str) -> str:
    source = _OPERATION_LABELS.get(kind)
    return tr(source) if source is not None else kind


def _resolve_state(state: str, success: bool) -> OperationState:
    """把历史条目的状态值还原为 :class:`OperationState`；空或非法值按 success 回退。"""

    if state:
        try:
            return OperationState(state)
        except ValueError:
            pass
    return OperationState.SUCCEEDED if success else OperationState.FAILED


class _StatusBadge(InfoBadge):
    """带语义配色的状态徽标，用于在途状态与历史结果展示。"""

    # 语义色调 → InfoBadge 级别（InfoLevel 五级与业务五色一一对应）。
    _TONE_LEVELS = {
        "neutral": InfoLevel.INFOAMTION,
        "accent": InfoLevel.ATTENTION,
        "success": InfoLevel.SUCCESS,
        "warning": InfoLevel.WARNING,
        "danger": InfoLevel.ERROR,
    }

    def __init__(
        self,
        text: str = "",
        *,
        tone: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        # InfoBadge 的 singledispatchmethod 会按 text 分发到 str 重载，该重载又回调
        # self.__init__，与子类重载冲突；这里走 parent 默认重载后再 setText。
        super().__init__(parent)
        self.setText(text)
        self.setObjectName("statusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("fontRole", FontRole.UI_SMALL.value)
        self.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        self._tone = "neutral"
        self.set_status(text, tone)

    def set_status(self, text: str, tone: str = "neutral") -> None:
        """更新徽标文字与语义级别。"""

        self._tone = tone if tone in self._TONE_LEVELS else "neutral"
        self.setText(text)
        self.setAccessibleName(text)
        self._sync_theme_state()

    def _sync_theme_state(self) -> None:
        """按当前语义级别同步 InfoBadge 配色（主题色由 qfluentwidgets 自管理）。"""

        self.setLevel(self._TONE_LEVELS.get(self._tone, InfoLevel.INFOAMTION))


class _RunningActionsButton(PushButton):
    """窄页省略在途入口文字，完整动作和计数仍可悬停或辅助读取。"""

    def __init__(self, parent=None) -> None:
        self._full_text = ""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.refresh_text()

    def refresh_text(self) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        contents = self.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, self,
        )
        super().setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(0, contents.width()),
        ))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.refresh_text()


class _ActiveTaskRow(QWidget):
    """窄宽度下把任务信息和取消控件分行，保留原控件及任务身份。"""

    def __init__(
        self, summary: BodyLabel, badge: _StatusBadge,
        progress: ProgressBar, cancel: PrimaryPushButton,
    ) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._summary = summary
        self._badge = badge
        self._progress = progress
        self._cancel = cancel
        self._snapshot: OperationSnapshot | None = None
        summary.setWordWrap(True)
        summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._controls = QWidget(self)
        controls_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self._controls)
        self._controls_layout = controls_layout
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)
        controls_layout.addStretch(1)
        for control in (badge, progress, cancel):
            controls_layout.addWidget(control)
        self._row_layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._row_layout.setContentsMargins(0, 2, 0, 2)
        self._row_layout.setSpacing(8)
        self._row_layout.addWidget(summary, 1)
        self._row_layout.addWidget(self._controls)

    def update_snapshot(self, snapshot: OperationSnapshot) -> None:
        """原位更新变化字段，避免轮询销毁正在按下或聚焦的取消按钮。"""
        previous = self._snapshot
        if previous is None or previous.state != snapshot.state:
            self._badge.set_status(
                tr(_STATE_LABELS.get(snapshot.state, snapshot.state.value)),
                _STATE_TONES.get(snapshot.state, "neutral"),
            )
        if previous is None or previous.progress != snapshot.progress:
            self._progress.setValue(int(snapshot.progress))
        self._snapshot = snapshot

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.refresh_layout()

    def refresh_layout(self) -> None:
        """字号改变后立即重新分行，保留原任务控件和正在选择的文本。"""
        controls_width = sum(
            control.sizeHint().width() for control in (self._badge, self._progress, self._cancel)
        ) + self._controls_layout.spacing() * 2
        self._controls_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if self.width() < controls_width
            else QBoxLayout.Direction.LeftToRight
        )
        required = (
            self._summary.fontMetrics().horizontalAdvance(self._summary.text())
            + self._controls.sizeHint().width() + self._row_layout.spacing()
        )
        direction = (
            QBoxLayout.Direction.LeftToRight if self.width() >= required
            else QBoxLayout.Direction.TopToBottom
        )
        if self._row_layout.direction() != direction:
            self._row_layout.setDirection(direction)
            self.updateGeometry()


class TaskCenterPage(QWidget):
    """任务中心：在途列表 + 历史列表 + 取消双路径。"""

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
        # 保留 SidePanel 调用入口，活动任务通过独立的 operation_manager 注入。
        self._panel = panel
        self._operation_manager = operation_manager
        self._history_store = history_store if history_store is not None else TaskHistoryStore()
        self._stop_hook = stop_hook
        self._history_limit = history_limit

        # diff 缓存：首次为 None，保证首帧必渲染；活动行仅随任务进入或退出创建/释放。
        self._active_cache: tuple[OperationSnapshot, ...] | None = None
        self._active_rows: dict[str, _ActiveTaskRow] = {}
        self._active_empty_state: QWidget | None = None
        self._history_cache: tuple[TaskHistoryEntry, ...] | None = None

        self._active_card = self._make_card(tr("在途任务"))
        self._history_card = self._make_card(tr("历史记录"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._scroll = SmoothScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 24, 32, 32)
        content_layout.setSpacing(20)
        content_layout.addWidget(self._active_card)
        from gui.widgets.action_result_view import ActionResultView

        self.action_results = ActionResultView(content)
        self.action_empty_label = apply_label_role(
            BodyLabel(tr("本次运行尚无操作结果，执行功能后会在此显示。"), content),
            FontRole.UI_SMALL, color_key="TEXT_SECONDARY",
        )
        self.action_empty_label.setWordWrap(True)
        self.running_actions_button = _RunningActionsButton(content)
        self.running_actions_button.hide()
        self.running_actions_button.clicked.connect(self._open_running_action)
        content_layout.insertWidget(0, self.running_actions_button)
        self._idle_label: BodyLabel | None = None
        self.run_results: RunResultsWidget | None = None
        if run_library is not None:
            self._history_card.setParent(self)
            self._history_card.hide()
            self._idle_label = apply_label_role(
                BodyLabel(tr("暂无在途任务"), content), FontRole.UI_SMALL,
                color_key="TEXT_SECONDARY",
            )
            content_layout.insertWidget(0, self._idle_label)
            self.run_results = RunResultsWidget(run_library, content)
            self._history_card.headerView.hide()
            self.history_views = AdaptiveCategoryStack("taskHistory", content)
            self.history_views.add_category("test_results", tr("测试结果"), (self.run_results,))
            self.history_views.add_category(
                "operations", tr("本次操作"), (self.action_empty_label, self.action_results),
            )
            content_layout.addWidget(self.history_views)
        else:
            content_layout.addWidget(self.action_results)
            content_layout.addWidget(self._history_card)
        content_layout.addStretch(1)
        self._scroll.setWidget(content)
        content.setAutoFillBackground(False)
        layout.addWidget(self._scroll)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(max(0, int(poll_interval_ms)))
        self._poll_timer.timeout.connect(self.refresh)

        self._sync_theme_state()
        BaseStyles.ui_font_changed.connect(self._refresh_typography)
        self._refresh_typography()
    # ── 数据刷新契约 ────────────────────────────────────────────────────

    def present_action_result(self, result: ActionResult) -> None:
        """普通命令也呈现在途入口，避免仅有 Operation 任务才能被观察。"""
        self.action_empty_label.hide()
        self.action_results.present(result)
        self._refresh_action_status()

    def _refresh_action_status(self) -> None:
        running = self.action_results.running_results()
        self.running_actions_button.setText(
            tr("查看执行中的操作（{count}）").format(count=len(running))
        )
        self.running_actions_button.setVisible(bool(running))
        if self._idle_label is not None:
            self._idle_label.setVisible(not self._active_cache and not running)

    def _open_running_action(self) -> None:
        running = self.action_results.running_results()
        if not running:
            return
        if self.run_results is not None:
            self.history_views.set_current("operations")
        self.action_results.select_request(running[-1].request_id)
        self._scroll.ensureWidgetVisible(self.action_results, 0, 12)

    def refresh(self) -> None:
        """重读在途快照与历史，原位更新活动行并按需重建历史。"""

        active = (
            self._operation_manager.active_snapshot() if self._operation_manager is not None else ()
        )
        self._apply_active(active)
        history = self._history_store.recent(self._history_limit)
        self._apply_history(history)

    def _apply_active(self, active: tuple[OperationSnapshot, ...]) -> None:
        if active == self._active_cache:
            return
        self._active_cache = active
        self._render_active_rows(active)
        self._refresh_action_status()

    def _apply_history(self, history: tuple[TaskHistoryEntry, ...]) -> None:
        if history == self._history_cache:
            return
        self._history_cache = history
        self._render_history_rows(history)

    # ── 在途视图 ────────────────────────────────────────────────────────

    def _render_active_rows(self, active: tuple[OperationSnapshot, ...]) -> None:
        layout = self._active_card.viewLayout
        current_ids = {snapshot.operation_id for snapshot in active}
        for operation_id in self._active_rows.keys() - current_ids:
            row = self._active_rows.pop(operation_id)
            layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        if active and self._active_empty_state is not None:
            layout.removeWidget(self._active_empty_state)
            self._active_empty_state.hide()
            self._active_empty_state.deleteLater()
            self._active_empty_state = None
        if self._idle_label is not None:
            # 测试结果是常驻内容；空在途状态只占一行，避免把结果操作推到首屏之外。
            self._active_card.setVisible(bool(active))
            self._idle_label.setVisible(not active)
            if not active:
                return
        if not active:
            if self._active_empty_state is None:
                self._active_empty_state = self._empty_state(
                    tr("暂无在途任务"),
                    tr("执行过程与完整结果在本次操作中回看，完成时通过右上角通知提示。"),
                )
                layout.addWidget(self._active_empty_state)
            return
        for index, snapshot in enumerate(active):
            row = self._active_rows.get(snapshot.operation_id)
            if row is None:
                row = self._make_active_row(snapshot)
                self._active_rows[snapshot.operation_id] = row
            row.update_snapshot(snapshot)
            if layout.indexOf(row) != index:
                layout.insertWidget(index, row)

    def _make_active_row(self, snapshot: OperationSnapshot) -> _ActiveTaskRow:
        summary = apply_label_role(
            BodyLabel(
                f"{_operation_label(snapshot.kind)} · {self._short_id(snapshot.operation_id)}"
            ),
            FontRole.UI,
        )
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setToolTip(snapshot.operation_id)

        badge = _StatusBadge(
            tr(_STATE_LABELS.get(snapshot.state, snapshot.state.value)),
            tone=_STATE_TONES.get(snapshot.state, "neutral"),
        )

        progress = ProgressBar()
        progress.setRange(0, 100)
        progress.setValue(int(snapshot.progress))
        progress.setFixedWidth(120)

        cancel = PrimaryPushButton()
        configure_button(
            cancel,
            text=tr("取消"),
            tooltip=tr("取消任务 {operation_id}").format(operation_id=snapshot.operation_id),
            danger=True,
        )
        cancel.clicked.connect(lambda _checked=False, oid=snapshot.operation_id: self._cancel(oid))
        return _ActiveTaskRow(summary, badge, progress, cancel)

    # ── 历史视图 ────────────────────────────────────────────────────────

    def _render_history_rows(self, history: tuple[TaskHistoryEntry, ...]) -> None:
        self._clear_layout(self._history_card.viewLayout)
        if not history:
            self._history_card.viewLayout.addWidget(
                self._empty_state(tr("暂无历史记录"), tr("已完成的任务会显示在这里。"))
            )
            return
        for entry in history:
            self._history_card.viewLayout.addWidget(self._make_history_row(entry))

    def _make_history_row(self, entry: TaskHistoryEntry) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        time_label = apply_label_role(
            BodyLabel(self._format_time(entry.finished_at)),
            FontRole.UI_SMALL,
            color_key="TEXT_SECONDARY",
        )
        layout.addWidget(time_label)

        summary = apply_label_role(
            BodyLabel(f"{_operation_label(entry.kind)} · {self._short_id(entry.task_id)}"),
            FontRole.UI,
        )
        summary.setToolTip(entry.detail or entry.task_id)
        layout.addWidget(summary, 1)

        state = _resolve_state(entry.state, entry.success)
        badge = _StatusBadge(
            tr(_STATE_LABELS.get(state, state.value)),
            tone=_STATE_TONES.get(state, "danger"),
        )
        layout.addWidget(badge)
        return row

    # ── 取消双路径 ──────────────────────────────────────────────────────

    def _cancel(self, task_id: str) -> None:
        """取消双路径：先登记协作式取消意图，再调用注入的资源停止入口。"""

        if self._operation_manager is not None:
            self._operation_manager.request_cancel(task_id)
        if self._stop_hook is not None:
            self._stop_hook(task_id)

    def record_history(self, entry: TaskHistoryEntry) -> None:
        """写入一条终态记录并立即刷新（供组合根订阅终态事件时调用）。"""

        self._history_store.record(entry)
        self.refresh()

    # ── 可见性与清理 ────────────────────────────────────────────────────

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()
        self._poll_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        self._poll_timer.stop()
        super().hideEvent(event)

    def shutdown(self) -> None:
        """停止轮询定时器，供窗口关闭清理调用。"""

        self._poll_timer.stop()

    # ── 主题与辅助 ──────────────────────────────────────────────────────

    def _refresh_typography(self, _config=None) -> None:
        """只刷新页面自有文字，嵌入的结果组件继续拥有各自的字体与选择状态。"""
        for card in (self._active_card, self._history_card):
            for widget in card.findChildren(QWidget):
                role = widget.property("fontRole")
                if role:
                    apply_font_role(
                        widget, role, ensure_height=isinstance(widget, QAbstractButton),
                    )
        for label in (self.action_empty_label, self._idle_label):
            if label is not None:
                apply_font_role(label, FontRole.UI_SMALL)
        apply_font_role(self.running_actions_button, FontRole.UI, ensure_height=True)
        self.running_actions_button.refresh_text()
        for row in self._active_rows.values():
            row.refresh_layout()
        self.updateGeometry()

    def _sync_theme_state(self) -> None:
        """按当前主题重建页面内全部主题化控件样式。"""

        for widget in self.findChildren(QWidget):
            sync = getattr(widget, "_sync_theme_state", None)
            if callable(sync):
                sync()

    @staticmethod
    def _make_card(title: str) -> HeaderCardWidget:
        """以标题和间距区分任务列表，复用原分区的布局与行生命周期。"""

        card = ContentSection(title)
        card.viewLayout.setDirection(QBoxLayout.Direction.TopToBottom)
        card.viewLayout.setContentsMargins(0, 8, 0, 8)
        card.viewLayout.setSpacing(6)
        apply_label_role(card.headerLabel, FontRole.TITLE, color_key="TITLE_COLOR")
        return card

    @staticmethod
    def _empty_state(title: str, description: str) -> QWidget:
        """用 qfluentwidgets 标签组合轻量空状态。"""

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)
        title_label = apply_label_role(BodyLabel(title), FontRole.TITLE, color_key="TITLE_COLOR")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_label = apply_label_role(
            BodyLabel(description), FontRole.UI_SMALL, color_key="TEXT_SECONDARY"
        )
        description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return host

    @staticmethod
    def _short_id(task_id: str) -> str:
        """把长标识截断为列表可读的摘要。"""

        if len(task_id) <= 12:
            return task_id
        return task_id[:12] + "…"

    @staticmethod
    def _format_time(timestamp: float) -> str:
        """把墙钟时间格式化为列表可读的时间。"""

        try:
            return datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            return ""

    @staticmethod
    def _clear_layout(layout: QLayout) -> None:
        """移除布局内全部控件与子布局，并通过 ``deleteLater`` 延迟释放。"""

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout is not None:
                TaskCenterPage._clear_layout(child_layout)


__all__ = ["DEFAULT_HISTORY_LIMIT", "POLL_INTERVAL_MS", "TaskCenterPage"]
