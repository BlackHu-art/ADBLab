"""在功能分区显示操作快照；按需阅读正文和打开附件，不订阅全局日志。"""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, LineEdit, PlainTextEdit, PushButton

from adblab.application.action_results import ActionResult, ActionResults, artifact_name
from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role, apply_reading_surface

STATE_LABELS = {
    "running": "执行中",
    "succeeded": "已完成",
    "partial": "部分成功",
    "failed": "失败",
    "cancelled": "已取消",
    "recorded": "记录",
    "warning": "注意",
}


class ActionResultView(QWidget):
    """保留本分区最近结果，更新旧请求不抢占新结果和用户主动选择的历史。"""

    artifact_requested = Signal(str, bool)
    export_requested = Signal(str, str)
    reveal_requested = Signal(object)

    def __init__(self, parent=None, *, diagnostic: bool = False):
        super().__init__(parent)
        self.setObjectName("actionResultView")
        self._records: OrderedDict[str, ActionResult] = OrderedDict()
        self._selected = ""
        self._detail = ""
        self._last_detail = ""
        self._search_query = ""
        self._search_offset = 0
        self._diagnostic = diagnostic
        self._latest_started = 0.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 4)
        layout.setSpacing(8)
        self.summary = apply_label_role(BodyLabel(), FontRole.UI)
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setAccessibleName(tr("操作结果"))
        layout.addWidget(self.summary)
        self.message_label = apply_label_role(BodyLabel(), FontRole.UI_SMALL)
        self.message_label.setWordWrap(True)
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.message_label)
        row = QHBoxLayout()
        self.history = ComboBox()
        self.history.setAccessibleName(tr("本分区最近操作"))
        self.targets = ComboBox()
        self.targets.setAccessibleName(tr("本次操作的设备结果"))
        for control in (self.history, self.targets):
            control.setMinimumWidth(0)
            control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            row.addWidget(control, 1)
        layout.addLayout(row)
        self.detail_toggle = PushButton(tr("查看详情"))
        self.detail_toggle.setCheckable(True)
        layout.addWidget(self.detail_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail_host = QWidget()
        detail_layout = QVBoxLayout(self.detail_host)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.search = LineEdit()
        self.search.setPlaceholderText(tr("查找结果，按 Enter 查找下一处"))
        self.search.setAccessibleName(tr("查找结果"))
        detail_layout.addWidget(self.search)
        self.output = PlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setProperty("fontRole", FontRole.LOG.value)
        apply_reading_surface(self.output)
        self.output.setAccessibleName(tr("操作结果正文"))
        self.output.setMinimumHeight(160)
        self.output.setMaximumHeight(320)
        detail_layout.addWidget(self.output)
        self.preview_notice = apply_label_role(BodyLabel(), FontRole.UI_SMALL)
        self.preview_notice.setWordWrap(True)
        detail_layout.addWidget(self.preview_notice)
        commands = QHBoxLayout()
        self.copy_button = PushButton(tr("复制完整结果"))
        self.export_button = PushButton(tr("导出结果"))
        commands.addWidget(self.copy_button)
        commands.addWidget(self.export_button)
        commands.addStretch(1)
        detail_layout.addLayout(commands)
        layout.addWidget(self.detail_host)
        self.artifacts = ComboBox()
        self.artifacts.setMinimumWidth(0)
        self.artifacts.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.artifacts.setAccessibleName(tr("本次操作产物"))
        layout.addWidget(self.artifacts)
        self.artifact_actions = QWidget()
        artifact_layout = QHBoxLayout(self.artifact_actions)
        artifact_layout.setContentsMargins(0, 0, 0, 0)
        self.open_button = PushButton(tr("打开结果"))
        self.folder_button = PushButton(tr("打开文件夹"))
        artifact_layout.addWidget(self.open_button)
        artifact_layout.addWidget(self.folder_button)
        artifact_layout.addStretch(1)
        layout.addWidget(self.artifact_actions)
        self.history.currentIndexChanged.connect(self._choose_history)
        self.targets.currentIndexChanged.connect(self._render_detail)
        self.detail_toggle.toggled.connect(self._toggle_detail)
        self.search.returnPressed.connect(self._find)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self._detail))
        self.export_button.clicked.connect(
            lambda: self.export_requested.emit(self._selected, self._detail)
        )
        self.open_button.clicked.connect(lambda: self._open(False))
        self.folder_button.clicked.connect(lambda: self._open(True))
        BaseStyles.fonts_changed.connect(self._refresh_font)
        self._refresh_font()
        self.detail_host.hide()
        if diagnostic:
            self.history.hide()
            self.detail_toggle.hide()
            self.detail_toggle.setChecked(True)
        self.hide()

    def _refresh_font(self, *_args) -> None:
        self.output.setFont(BaseStyles.font_for_role(FontRole.LOG))

    def _toggle_detail(self, expanded: bool) -> None:
        self.detail_host.setVisible(expanded)
        self.detail_toggle.setText(tr("收起详情") if expanded else tr("查看详情"))

    def present(self, result: ActionResult) -> None:
        """新请求显示在原分区；同一请求的后台更新保持用户的设备和阅读位置。"""
        self._latest_started = max(self._latest_started, result.started_at)
        if self._diagnostic and (
            not result.items or result.started_at < self._latest_started
        ):
            return
        fresh = result.request_id not in self._records
        self._records[result.request_id] = result
        if fresh:
            self._selected = result.request_id
        ended = sorted(
            (item for item in self._records.values() if item.state != "running"),
            key=lambda item: item.finished_at or item.started_at,
        )
        for item in ended[:-20]:
            if item.request_id != self._selected:
                del self._records[item.request_id]
        blocker = QSignalBlocker(self.history)
        self.history.clear()
        for item in reversed(self._records.values()):
            stamp = datetime.fromtimestamp(item.started_at).strftime("%H:%M:%S")
            self.history.addItem(f"{stamp} · {tr(item.spec.title)}", userData=item.request_id)
        self.history.setCurrentIndex(self.history.findData(self._selected))
        del blocker
        if fresh and not self._diagnostic:
            self.detail_toggle.setChecked(result.spec.presentation in ("text", "notes"))
        if self._selected == result.request_id:
            self._render()
        self.show()
        if fresh:
            self.reveal_requested.emit(self)

    def _choose_history(self, *_args) -> None:
        self._selected = str(self.history.currentData() or "")
        self._render()

    def select_request(self, request_id: str) -> bool:
        """显式打开通知所指的结果，不能借用当前下拉框中的较新请求。"""
        index = self.history.findData(request_id)
        if index < 0:
            return False
        self.history.setCurrentIndex(index)
        return True

    def running_results(self) -> tuple[ActionResult, ...]:
        """提供仍在执行的请求快照，供任务页定位；不改变选择或任务所有权。"""
        return tuple(item for item in self._records.values() if item.state == "running")

    def _render(self) -> None:
        result = self._records.get(self._selected)
        if result is None:
            return
        finished = len(result.items)
        failed = sum(item.state == "failed" for item in result.items)
        title = f"{tr(result.spec.title)} · {tr(STATE_LABELS[result.state])}"
        if result.targets:
            title += tr(" · {count} 台目标设备").format(count=len(result.targets))
            if len(result.targets) == 1:
                title += " · " + ActionResults.target_label(result, result.targets[0])
        if finished:
            title += tr(" · {count} 项返回，{failed} 项失败").format(count=finished, failed=failed)
        if self._diagnostic:
            stamp = datetime.fromtimestamp(result.started_at).strftime("%H:%M:%S")
            title = f"{tr(result.spec.title)} · {stamp}"
        self.summary.setText(title)
        self.summary.setToolTip(result.message)
        self.message_label.setText(" ".join(result.message.splitlines())[:200])
        self.message_label.setVisible(bool(result.message) and not self._diagnostic)
        previous = self.targets.currentData()
        blocker = QSignalBlocker(self.targets)
        self.targets.clear()
        for item in result.items:
            label = ActionResults.target_label(result, item.target)
            if not any(result.target_labels) and item.target in result.targets:
                index = result.targets.index(item.target)
                if index < len(result.target_names) and result.target_names[index]:
                    label += " · " + result.target_names[index]
            self.targets.addItem(f"{label} · {tr(STATE_LABELS[item.state])}", userData=item.job_id)
        if self.targets.findData(previous) >= 0:
            self.targets.setCurrentIndex(self.targets.findData(previous))
        del blocker
        self.targets.setEnabled(bool(result.items))
        self.targets.setVisible(result.spec.presentation != "notes")
        self._render_detail()

    def _render_detail(self, *_args) -> None:
        result = self._records.get(self._selected)
        if result is None:
            return
        item = next(
            (item for item in result.items if item.job_id == self.targets.currentData()), None
        )
        self._detail = item.detail if item else result.message
        if result.spec.presentation == "notes":
            self._detail = "\n\n".join(
                f"[{tr(STATE_LABELS[note.state])}] {note.detail}" for note in result.items
            )
        if not self._detail:
            self._detail = (
                tr("正在执行，请等待结果。")
                if result.state == "running"
                else tr("操作已结束，无文本输出。")
            )
        if self._detail != self._last_detail:
            self.output.setPlainText(self._detail[:64000])
            self._last_detail = self._detail
            self._search_offset = 0
        self.preview_notice.setText(
            tr("正文较长，当前为预览；复制或导出可获取完整结果。")
            if len(self._detail) > 64000
            else ""
        )
        self.preview_notice.setVisible(len(self._detail) > 64000)
        self.artifacts.clear()
        paths = item.artifacts if item else ()
        for path in paths:
            self.artifacts.addItem(artifact_name(path), userData=path)
        self.artifacts.setVisible(bool(paths) and not self._diagnostic)
        self.artifact_actions.setVisible(bool(paths) and not self._diagnostic)
        if result.state in ("failed", "partial") or (item and item.state == "failed"):
            self.detail_toggle.setChecked(True)

    def _find(self) -> None:
        """搜索完整正文并按命中位置加载有界片段，避免超长 Qt 文档阻塞界面。"""
        query = self.search.text()
        if not query:
            return
        if query != self._search_query:
            self._search_query = query
            self._search_offset = 0
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        match = pattern.search(self._detail, self._search_offset) or pattern.search(self._detail)
        if match is None:
            self.preview_notice.setText(tr("未找到匹配内容"))
            self.preview_notice.show()
            return
        self._search_offset = match.end()
        start = max(0, match.start() - 2048)
        preview = self._detail[start : start + 64000]
        self.output.setPlainText(preview)
        cursor = self.output.textCursor()
        # QTextCursor 使用 UTF-16 位置；Python 字符索引遇到 emoji 时不能直接传入。
        begin = len(self._detail[start : match.start()].encode("utf-16-le")) // 2
        end = begin + len(match.group().encode("utf-16-le")) // 2
        cursor.setPosition(begin)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()
        self.preview_notice.setText(tr("已搜索完整结果，当前显示匹配位置附近的内容。"))
        self.preview_notice.show()

    def _open(self, folder: bool) -> None:
        path = self.artifacts.currentData()
        if isinstance(path, str) and path:
            self.artifact_requested.emit(path, folder)
