"""任务中心页：在途任务轮询视图 + 有界历史视图（P1-B 填充实现）。

在途数据源为 ``OperationManager.active_snapshot()``（仅 QUEUED/RUNNING/FINALIZING，
终态即删除、无历史）；历史由 :class:`services.task_history.TaskHistoryStore` 自持有界
存储消费终态事件。页面可见时以 1000ms ``QTimer`` 轮询并做不可变快照 diff，无变化
不重建控件；隐藏时停表。取消按钮走双路径：``OperationManager.request_cancel`` +
注入的资源停止回调 ``stop_hook``（本阶段允许为空实现，接口保留）。

构造契约（兼容 P1-A 占位接口）：``panel`` 预留为 SidePanel 兼容入口；在途视图
需要注入 ``operation_manager`` 才能读取活动快照，未注入时在途视图退化为空态。
``refresh()`` 是本页对组合根的稳定契约：同步重读在途快照与历史并按 diff 决定重建。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget
from qfluentwidgets import InfoBadge, InfoLevel

from adblab.application.operations import OperationManager, OperationSnapshot, OperationState
from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent import Card, DangerPushButton, EmptyState, FluentProgressBar
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
    ) -> None:
        super().__init__(parent)
        self.setObjectName("taskCenterPage")
        # panel 预留为 SidePanel 兼容接口（P1-A 契约）；本阶段未使用统一信号层。
        self._panel = panel
        self._operation_manager = operation_manager
        self._history_store = (
            history_store if history_store is not None else TaskHistoryStore()
        )
        self._stop_hook = stop_hook
        self._history_limit = history_limit

        # diff 缓存：首次为 None，保证首帧必渲染；此后仅快照变化才重建。
        self._active_cache: tuple[OperationSnapshot, ...] | None = None
        self._history_cache: tuple[TaskHistoryEntry, ...] | None = None

        self._active_card = Card(title="在途任务")
        self._history_card = Card(title="历史记录")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._active_card)
        layout.addWidget(self._history_card, 1)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(max(0, int(poll_interval_ms)))
        self._poll_timer.timeout.connect(self.refresh)

        self._sync_theme_state()

    # ── 数据刷新契约 ────────────────────────────────────────────────────

    def refresh(self) -> None:
        """重读在途快照与历史，并按 diff 决定是否重建控件。"""

        active = (
            self._operation_manager.active_snapshot()
            if self._operation_manager is not None
            else ()
        )
        self._apply_active(active)
        history = self._history_store.recent(self._history_limit)
        self._apply_history(history)

    def _apply_active(self, active: tuple[OperationSnapshot, ...]) -> None:
        if active == self._active_cache:
            return
        self._active_cache = active
        self._render_active_rows(active)

    def _apply_history(self, history: tuple[TaskHistoryEntry, ...]) -> None:
        if history == self._history_cache:
            return
        self._history_cache = history
        self._render_history_rows(history)

    # ── 在途视图 ────────────────────────────────────────────────────────

    def _render_active_rows(self, active: tuple[OperationSnapshot, ...]) -> None:
        self._clear_layout(self._active_card.body_layout())
        if not active:
            self._active_card.body_layout().addWidget(
                EmptyState(
                    title="暂无在途任务",
                    description="安装批次、录屏、Monkey 与 MobilePerf 任务会显示在这里。",
                    parent=self,
                )
            )
            return
        for snapshot in active:
            self._active_card.body_layout().addWidget(self._make_active_row(snapshot))
        self._active_card.body_layout().addStretch(1)

    def _make_active_row(self, snapshot: OperationSnapshot) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        summary = QLabel(f"{snapshot.kind} · {self._short_id(snapshot.operation_id)}")
        summary.setProperty("fontRole", FontRole.UI.value)
        summary.setFont(BaseStyles.font_for_role(FontRole.UI))
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setToolTip(snapshot.operation_id)
        layout.addWidget(summary, 1)

        badge = _StatusBadge(
            _STATE_LABELS.get(snapshot.state, snapshot.state.value),
            tone=_STATE_TONES.get(snapshot.state, "neutral"),
        )
        layout.addWidget(badge)

        progress = FluentProgressBar(maximum=100, value=int(snapshot.progress))
        progress.setFixedWidth(120)
        layout.addWidget(progress)

        cancel = DangerPushButton("取消")
        cancel.setToolTip(f"取消任务 {snapshot.operation_id}")
        cancel.setAccessibleName("取消")
        cancel.setAccessibleDescription(f"取消任务 {snapshot.operation_id}")
        cancel.setProperty("functionalToolTip", f"取消任务 {snapshot.operation_id}")
        cancel.clicked.connect(
            lambda _checked=False, oid=snapshot.operation_id: self._cancel(oid)
        )
        layout.addWidget(cancel)
        return row

    # ── 历史视图 ────────────────────────────────────────────────────────

    def _render_history_rows(self, history: tuple[TaskHistoryEntry, ...]) -> None:
        self._clear_layout(self._history_card.body_layout())
        if not history:
            self._history_card.body_layout().addWidget(
                EmptyState(
                    title="暂无历史记录",
                    description="已完成的任务会显示在这里。",
                    parent=self,
                )
            )
            return
        for entry in history:
            self._history_card.body_layout().addWidget(self._make_history_row(entry))
        self._history_card.body_layout().addStretch(1)

    def _make_history_row(self, entry: TaskHistoryEntry) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        time_label = QLabel(self._format_time(entry.finished_at))
        time_label.setProperty("fontRole", FontRole.UI_SMALL.value)
        time_label.setFont(BaseStyles.font_for_role(FontRole.UI_SMALL))
        layout.addWidget(time_label)

        summary = QLabel(f"{entry.kind} · {self._short_id(entry.task_id)}")
        summary.setProperty("fontRole", FontRole.UI.value)
        summary.setFont(BaseStyles.font_for_role(FontRole.UI))
        summary.setToolTip(entry.detail or entry.task_id)
        layout.addWidget(summary, 1)

        state = _resolve_state(entry.state, entry.success)
        badge = _StatusBadge(
            _STATE_LABELS.get(state, state.value),
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

    def _sync_theme_state(self) -> None:
        """按当前主题重建页面内全部主题化控件样式（P2 接入广播前由组合根触发）。"""

        for widget in self.findChildren(QWidget):
            sync = getattr(widget, "_sync_theme_state", None)
            if callable(sync):
                sync()

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
