"""在功能分区显示操作快照；按需阅读正文和打开附件，不订阅全局日志。"""

from __future__ import annotations

import re
from collections import Counter, OrderedDict
from collections.abc import Callable
from datetime import datetime
from math import ceil

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QResizeEvent, QTextCursor, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FlowLayout,
    FluentIcon,
    PlainTextEdit,
    PushButton,
    SearchLineEdit,
)

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.cached_icon import cached_fluent_icon
from gui.styles.fluent import (
    apply_focus_indicator,
    apply_font_role,
    apply_label_role,
    apply_reading_surface,
    configure_fluent_control,
    set_function_tooltip,
)
from gui.styles.reading_surface import ensure_reading_surface
from gui.widgets.collapsible_tools import CollapsibleTools, ContentReveal
from gui.widgets.eliding_combo_box import ElidingComboBox
from gui.widgets.reader_interaction import ReaderInteraction
from services.tasks.action_results import (
    ActionResult,
    ActionResults,
    artifact_name,
    expired_action_results,
)

STATE_LABELS = {
    "running": "执行中",
    "succeeded": "已完成",
    "partial": "部分成功",
    "failed": "失败",
    "cancelled": "已取消",
    "recorded": "记录",
    "warning": "注意",
}


def result_target_caption(result: ActionResult, target: str) -> str:
    """按该目标自己的快照补齐旧名称，未知条目只显示安全占位。"""
    if not target:
        return tr("本机")
    if target not in result.targets:
        return tr("设备")
    label = ActionResults.target_label(result, target)
    index = result.targets.index(target)
    if (index >= len(result.target_labels) or not result.target_labels[index]) and (
        index < len(result.target_names) and result.target_names[index]
    ):
        return f"{label} · {result.target_names[index]}"
    return label


class _ResultButton(PushButton):
    """复用原文字按钮；检查器的纯图标形态按实际按钮中央绘制。"""

    def _drawIcon(self, icon, painter, rect, state=QIcon.State.Off):  # noqa: N802
        if not self.text():
            rect.moveLeft((self.width() - rect.width()) / 2)
        super()._drawIcon(icon, painter, rect, state)


class ActionResultView(QWidget):
    """保留本分区最近结果，更新旧请求不抢占新结果和用户主动选择的历史。"""

    artifact_requested = Signal(str, bool)
    export_requested = Signal(str, str)
    reveal_requested = Signal(object)
    selection_changed = Signal(str)
    _output_fit_requested = Signal()
    TEXT_BUDGET = 16 * 1024 * 1024

    def __init__(self, parent=None, *, diagnostic: bool = False, inline: bool = False):
        super().__init__(parent)
        self.setObjectName("actionResultView")
        self._records: OrderedDict[str, ActionResult] = OrderedDict()
        self._selected = ""
        self._detail = ""
        self._last_detail = ""
        self._search_query = ""
        self._search_offset = 0
        self._diagnostic = diagnostic
        self._inline = inline
        self._hosted_compact = False
        self._hosted_full_results = False
        self._fitting_output = False
        self._interaction_guard: Callable[[], bool] | None = None
        self._action_context: tuple[str, object] = ("", None)
        self._interaction = ReaderInteraction(
            self, self._allows_user_action, lambda: self._selected,
        )
        self._latest_started = 0.0
        self._history_signature: tuple[tuple[str, str], ...] = ()
        self._target_signature: tuple[tuple[str, str], ...] = ()
        self._artifact_signature: tuple[str, ...] = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0 if inline else 12, 0, 0 if inline else 4)
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
        self.history = ElidingComboBox()
        self.history.setAccessibleName(tr("本分区最近操作"))
        self.targets = ElidingComboBox()
        self.targets.setAccessibleName(tr("本次操作的设备结果"))
        for control in (self.history, self.targets):
            control.setMinimumWidth(0)
            control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            row.addWidget(control, 1)
        layout.addLayout(row)
        self.detail_toggle = PushButton(tr("查看详情"))
        set_function_tooltip(self.detail_toggle, "展开或收起本次操作的完整结果")
        self.detail_toggle.setCheckable(True)
        layout.addWidget(self.detail_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail_host = QWidget()
        detail_layout = QVBoxLayout(self.detail_host)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.search = SearchLineEdit()
        self._default_search_margins = self.search.textMargins()
        self.search.setPlaceholderText(tr("查找结果，按 Enter 查找下一处"))
        self.search.setAccessibleName(tr("查找结果"))
        self._search_row = QHBoxLayout()
        self._search_row.setContentsMargins(0, 0, 0, 0)
        self._search_row.setSpacing(4)
        self._search_row.addWidget(self.search, 1)
        detail_layout.addLayout(self._search_row)
        self.output = PlainTextEdit()
        self.output.setReadOnly(True)
        self._interaction.watch_editor(self.output)
        self.output.setProperty("fontRole", FontRole.LOG.value)
        apply_reading_surface(self.output)
        self.output.setAccessibleName(tr("操作结果正文"))
        self.output.setMinimumHeight(160)
        self.output.setMaximumHeight(320)
        self.output.viewport().installEventFilter(self)
        # 等文本视口先完成自身重排，再按实际换行回算外层高度；连接随阅读器释放。
        self.output.document().documentLayout().documentSizeChanged.connect(
            self._fit_hosted_output, Qt.ConnectionType.QueuedConnection,
        )
        self._output_fit_requested.connect(
            self._fit_hosted_output, Qt.ConnectionType.QueuedConnection,
        )
        detail_layout.addWidget(self.output)
        self.preview_notice = apply_label_role(BodyLabel(), FontRole.UI_SMALL)
        self.preview_notice.setWordWrap(True)
        detail_layout.addWidget(self.preview_notice)
        self._commands = FlowLayout()
        self._commands.setContentsMargins(0, 0, 0, 0)
        self._commands.setHorizontalSpacing(8)
        self._commands.setVerticalSpacing(8)
        self.copy_button = _ResultButton(tr("复制完整结果"))
        self.export_button = _ResultButton(tr("导出结果"))
        self._result_focus: dict[_ResultButton, Qt.FocusPolicy] = {}
        set_function_tooltip(self.copy_button, "将当前设备的完整结果复制到剪贴板")
        set_function_tooltip(self.export_button, "将当前设备的完整结果保存到本地文件")
        self._commands.addWidget(self.copy_button)
        self._commands.addWidget(self.export_button)
        detail_layout.addLayout(self._commands)
        self.detail_reveal = ContentReveal(self.detail_host, self.detail_toggle)
        layout.addWidget(self.detail_reveal)
        self.artifacts = ElidingComboBox()
        self.artifacts.setMinimumWidth(0)
        self.artifacts.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.artifacts.setAccessibleName(tr("本次操作产物"))
        layout.addWidget(self.artifacts)
        self.artifact_actions = QWidget()
        artifact_layout = FlowLayout(self.artifact_actions)
        artifact_layout.setContentsMargins(0, 0, 0, 0)
        artifact_layout.setHorizontalSpacing(8)
        artifact_layout.setVerticalSpacing(8)
        self.open_button = PushButton(tr("打开结果"))
        self.folder_button = PushButton(tr("打开文件夹"))
        set_function_tooltip(self.open_button, "打开所选的操作结果文件")
        set_function_tooltip(self.folder_button, "打开所选操作结果所在的文件夹")
        artifact_layout.addWidget(self.open_button)
        artifact_layout.addWidget(self.folder_button)
        layout.addWidget(self.artifact_actions)
        self.artifact_section: CollapsibleTools | None = None
        self.artifact_heading = apply_label_role(
            BodyLabel(tr("生成文件"), self), FontRole.UI_SMALL, color_key="TEXT_SECONDARY",
        )
        self.artifact_heading.hide()
        if inline:
            files = QWidget(self)
            files_layout = QVBoxLayout(files)
            files_layout.setContentsMargins(0, 0, 0, 0)
            files_layout.setSpacing(8)
            files_layout.addWidget(self.artifact_heading)
            for widget in (self.artifacts, self.artifact_actions):
                layout.removeWidget(widget)
                files_layout.addWidget(widget)
            self.artifact_section = CollapsibleTools(
                "生成文件", files, self, tooltip="查看本次操作生成的文件",
            )
            self.artifact_section.toggle_button.toggled.connect(self._keep_hosted_files_open)
            layout.addWidget(self.artifact_section)
        self.history.currentIndexChanged.connect(self._choose_history)
        self.targets.currentIndexChanged.connect(self._render_detail)
        self.detail_toggle.toggled.connect(self._toggle_detail)
        # 正文按原文查找，保留纯空格查询；原生 search() 会先 strip，不适用于此处。
        self.search.searchButton.clicked.connect(self._find)
        self.search.returnPressed.connect(self._find)
        self.search.textChanged.connect(self._fit_search_margins)
        self._interaction.bind_button(self.copy_button, self._copy_detail)
        self._interaction.bind_button(self.export_button, self._export_detail)
        self._interaction.bind_button(self.open_button, lambda: self._open(False))
        self._interaction.bind_button(self.folder_button, lambda: self._open(True))
        BaseStyles.fonts_changed.connect(self._refresh_font)
        BaseStyles.theme_changed.connect(self._refresh_font)
        BaseStyles.accent_color_changed.connect(self._refresh_font)
        self._refresh_font()
        if diagnostic:
            self.history.hide()
            self.detail_toggle.hide()
            self.detail_toggle.setChecked(True)
        if inline:
            self.summary.hide()
            self.history.hide()
            self._toggle_detail(False)
        self.hide()

    def set_interaction_guard(self, guard: Callable[[], bool] | None) -> None:
        """仅约束新用户动作；独立使用默认允许，后台快照、选择和渲染不经过此门禁。"""
        self.revoke_interactions()
        self._interaction_guard = guard

    def set_hosted_compact(self, enabled: bool) -> None:
        """宿主已有标题、状态和目标时，只收敛严格单条成功的重复信息。"""
        self._hosted_compact = enabled
        self._render()

    def set_hosted_full_results(self, enabled: bool) -> None:
        """仅显式抽屉宿主直接呈现原正文和附件；默认行内及诊断契约保持不变。"""
        if self._hosted_full_results == enabled:
            return
        self._hosted_full_results = enabled
        ensure_reading_surface(self.output).set_document_mode(enabled)
        search_hint = tr("查找结果，按 Enter 查找下一处")
        self.search.setPlaceholderText(tr("搜索") if enabled else search_hint)
        self.search.setToolTip(search_hint if enabled else "")
        for button, icon, caption in ((self.copy_button, FluentIcon.COPY, "复制完整结果"),
                                      (self.export_button, FluentIcon.SAVE_AS, "导出结果")):
            button.setText("" if enabled else tr(caption))
            button.setAccessibleName(tr(caption))
            button.setIcon(cached_fluent_icon(icon) if enabled else QIcon())
            if enabled:
                # Cocoa 的键盘导航会跳过只有 TabFocus 的普通按钮。
                self._result_focus[button] = button.focusPolicy()
                button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                self._commands.removeWidget(button)
                self._search_row.addWidget(button)
            else:
                self._search_row.removeWidget(button)
                button.setFocusPolicy(self._result_focus.pop(button))
                button.setMinimumSize(0, 0)
                button.setMaximumSize(16777215, 16777215)
                apply_focus_indicator(button, content_qss="")
                self._commands.addWidget(button)
        if enabled:
            QWidget.setTabOrder(self.search, self.copy_button)
            QWidget.setTabOrder(self.copy_button, self.export_button)
            QWidget.setTabOrder(self.export_button, self.output)
            self._fit_search_margins()
        else:
            QWidget.setTabOrder(self.search, self.output)
            QWidget.setTabOrder(self.output, self.copy_button)
            QWidget.setTabOrder(self.copy_button, self.export_button)
            self.search.setTextMargins(self._default_search_margins)
        self._refresh_font()
        self.detail_toggle.setVisible(not enabled and not self._diagnostic)
        if enabled:
            self._toggle_detail(True)
        self._fit_hosted_output()
        self.artifact_heading.setVisible(enabled and self._inline)
        if self.artifact_section is not None:
            section = self.artifact_section
            section.toggle_button.setVisible(not enabled)
            if enabled:
                self._keep_hosted_files_open()
        self._render()

    def _fit_search_margins(self, *_args) -> None:
        """空查询只为放大镜留位；输入后再预留清空按钮，窄窗仍可读提示。"""
        if self._hosted_full_results:
            margins = self._default_search_margins
            right = margins.right()
            if not self.search.text():
                right -= self.search.clearButton.width()
            self.search.setTextMargins(margins.left(), margins.top(), right, margins.bottom())

    def _keep_hosted_files_open(self, *_args) -> None:
        """撤销旧展开入口的晚到切换，完整模式始终保留同一附件区域。"""
        section = self.artifact_section
        if self._hosted_full_results and section is not None:
            with QSignalBlocker(section.toggle_button):
                section.toggle_button.setChecked(True)
            section.reveal.set_expanded(True, animated=False)
            section.reveal.finish()

    def compact_success(self, result: ActionResult) -> bool:
        """请求与唯一条目均成功且目标精确对应时，才允许省略不可切换的目标行。"""
        return (self._hosted_compact and result.state == "succeeded"
                and len(result.items) == 1 and result.items[0].state == "succeeded"
                and len(result.targets) <= 1
                # 兼容目标名只在 selector 中补充时，头部占位名不能替代这份可见信息。
                and (not result.targets or any(result.target_labels)
                     or not result.target_names or not result.target_names[0])
                and result.items[0].target == (result.targets[0] if result.targets else None))

    def revoke_interactions(self) -> None:
        """宿主撤销一次呈现时清除未完成激活和旧正文菜单，保留完整数据。"""
        self._interaction.revoke()

    def _allows_user_action(self) -> bool:
        return self._interaction_guard is None or self._interaction_guard()

    def _copy_detail(self) -> None:
        if self._allows_user_action():
            QApplication.clipboard().setText(self._detail)

    def _export_detail(self) -> None:
        if self._allows_user_action():
            self.export_requested.emit(self._selected, self._detail)

    def _refresh_font(self, *_args) -> None:
        """原位同步界面和日志字号，保留历史选择、查找位置与全文。"""
        apply_font_role(self.summary, FontRole.UI)
        for label in (self.message_label, self.preview_notice, self.artifact_heading):
            apply_font_role(label, FontRole.UI_SMALL)
        for control in (
            self.history, self.targets, self.detail_toggle, self.search,
            self.copy_button, self.export_button, self.artifacts,
            self.open_button, self.folder_button,
        ):
            configure_fluent_control(control)
        if self._hosted_full_results:
            for button in (self.copy_button, self.export_button):
                button.setFixedSize(32, self.search.minimumHeight())
                apply_focus_indicator(button, keyboard_only=True, content_qss=(
                    "_ResultButton { background: transparent; padding: 0; }"
                    f"_ResultButton:hover {{ background: {BaseStyles.color('BUTTON_HOVER')}; }}"
                    f"_ResultButton:pressed {{ background: {BaseStyles.color('BUTTON_PRESSED')}; }}"
                ))
        self._refresh_message()
        self.output.setFont(BaseStyles.font_for_role(FontRole.LOG))
        self._fit_hosted_output()

    def _refresh_message(self) -> None:
        """同正文重复的说明只展示一次，过宽命令可换行，原文仍用于提示。"""
        result = self._records.get(self._selected)
        if result is None:
            return
        message = result.message
        hosted = self._hosted_full_results
        redundant = hosted and message in (self._detail, tr(result.spec.title))
        self.message_label.setVisible(bool(message) and not self._diagnostic and not redundant)
        self.message_label.setToolTip(message if hosted else "")
        self.message_label.setAccessibleDescription(message if hosted else "")
        if not hosted:
            self.message_label.setText(" ".join(message.splitlines())[:200])
            return
        display = self._shell_command_if_duplicate(result) or message
        preview = " ".join(display[:200].splitlines()) + ("…" if len(display) > 200 else "")
        width = max(1, self.contentsRect().width())
        font = self.message_label.font()

        def wrap_token(match: re.Match[str]) -> str:
            token = match.group()
            if self.message_label.fontMetrics().horizontalAdvance(token) <= width:
                return token
            # Qt 以 UTF-16 定位换行；按段解码可保留 emoji 和组合字形。
            layout = QTextLayout(token, font, self.message_label)
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAnywhere)
            layout.setTextOption(option)
            data = token.encode("utf-16-le")
            parts = []
            layout.beginLayout()
            while (line := layout.createLine()).isValid():
                line.setLineWidth(width)
                start = line.textStart() * 2
                parts.append(data[start:start + line.textLength() * 2].decode("utf-16-le"))
            layout.endLayout()
            return "\u200b".join(parts)

        self.message_label.setText(re.sub(r"\S+", wrap_token, preview))

    def _shell_command_if_duplicate(self, result: ActionResult) -> str:
        """仅收紧控制器已知的成功格式；完整输出及唯一目标必须对应当前子命令。"""
        if result.spec.key != "run_shell_command" or result.state != "succeeded":
            return ""
        message = result.message
        end = message.find("\n")
        if (end < 0 or len(message) - end - 1 != len(self._detail)
                or not message.endswith(self._detail)):
            return ""
        item = next((i for i in result.items if i.job_id == self.targets.currentData()), None)
        if item is None or item.state != "succeeded" or item.target not in result.targets:
            return ""
        label = ActionResults.target_label(result, item.target)
        if (sum(i.target == item.target for i in result.items) != 1 or
                sum(ActionResults.target_label(result, t) == label for t in result.targets) != 1):
            return ""
        header = message[:end]
        prefix = f"Shell [{label}] `"
        if not header.startswith(prefix) or not header.endswith("`:"):
            return ""
        command = header[len(prefix):-2]
        return command if "`" not in command and command.splitlines() == [command] else ""

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._hosted_full_results and event.size().width() != event.oldSize().width():
            self._refresh_message()

    @Slot()
    def _fit_hosted_output(self, *_args) -> None:
        """抽屉短正文按自然行数收紧，长正文仍使用有界视口及独立文本滚动。"""
        if not self._hosted_full_results:
            self.output.setMinimumHeight(160)
            self.output.setMaximumHeight(320)
            return
        if self._fitting_output:
            return
        self._fitting_output = True
        try:
            document = self.output.document()
            text_layout = document.documentLayout()
            block = document.begin()
            height = 0.0
            # Qt 段落布局包含实际换行及回退字形度量；达到视口上限后无需布局后续段落。
            while block.isValid() and height < 320:
                height += text_layout.blockBoundingRect(block).height()
                block = block.next()
            self.output.setFixedHeight(ceil(min(
                320, max(self.output.fontMetrics().lineSpacing(), height) + 8,
            )))
        finally:
            self._fitting_output = False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (watched is self.output.viewport() and event.type() == QEvent.Type.Resize
                and isinstance(event, QResizeEvent)
                and event.size().width() != event.oldSize().width()
                and self._hosted_full_results):
            # 过滤器先于文本视口处理 Resize；排队到其真实换行布局完成后再量高。
            self._output_fit_requested.emit()
        return super().eventFilter(watched, event)

    def _toggle_detail(self, expanded: bool) -> None:
        if self._hosted_full_results:
            # 不启动旧展开动画；若已有旧动画，finish 明确提交最终状态。
            with QSignalBlocker(self.detail_toggle):
                self.detail_toggle.setChecked(True)
            self.detail_reveal.set_expanded(True, animated=False)
            self.detail_reveal.finish()
            return
        self.detail_reveal.set_expanded(expanded)
        if self._inline:
            self.detail_toggle.setText(
                tr("收起 · 完整输出") if expanded else tr("展开 · 完整输出")
            )
        else:
            self.detail_toggle.setText(tr("收起详情") if expanded else tr("查看详情"))

    def present(self, result: ActionResult, *, preserve_selection: bool = True) -> None:
        """保存完整快照；更新相同正文保留选区，行内宿主可释放已收起的选择保护。"""
        self._latest_started = max(self._latest_started, result.started_at)
        ignored_diagnostic = self._diagnostic and (
            not result.items or result.started_at < self._latest_started
        )
        if ignored_diagnostic and result.request_id not in self._records:
            return
        previous = self._records.get(result.request_id)
        fresh = previous is None
        if not fresh and result.state != "running" and result != previous:
            # 仅新终态或说明更新推进顺序；从通知重新打开旧快照不改变其保留优先级。
            self._records.pop(result.request_id)
        self._records[result.request_id] = result
        if (fresh and (not self._inline or not self._selected)) or not preserve_selection:
            self._selected = result.request_id
        for request_id in expired_action_results(
            self._records.values(), capacity=20, text_budget=self.TEXT_BUDGET,
            protected=(self._selected, result.request_id) if self._inline else (self._selected,),
        ):
            del self._records[request_id]
        if ignored_diagnostic:
            # 旧请求终态必须解除在途保护，但晚到正文不能抢占较新诊断的阅读位置。
            return
        entries = tuple(
            (
                item.request_id,
                f"{datetime.fromtimestamp(item.started_at).strftime('%H:%M:%S')} · "
                f"{tr(item.spec.title)}",
            )
            for item in reversed(self._records.values())
        )
        blocker = QSignalBlocker(self.history)
        if entries != self._history_signature:
            self.history.clear()
            for request_id, label in entries:
                self.history.addItem(label, userData=request_id)
            self._history_signature = entries
        index = self.history.findData(self._selected)
        if index >= 0 and self.history.currentIndex() != index:
            self.history.setCurrentIndex(index)
        del blocker
        if fresh and not self._diagnostic and not self._inline:
            self.detail_toggle.setChecked(result.spec.presentation in ("text", "notes"))
        if self._selected == result.request_id:
            self._render()
        self.show()
        if fresh and not self._inline:
            self.reveal_requested.emit(self)

    def _choose_history(self, *_args) -> None:
        self._selected = str(self.history.currentData() or "")
        self._render()

    def select_request(self, request_id: str) -> bool:
        """显式打开通知所指的结果，不能借用当前下拉框中的较新请求。"""
        index = self.history.findData(request_id)
        if index < 0:
            return False
        previous = self._selected
        self.history.setCurrentIndex(index)
        if self._selected != previous:
            self.selection_changed.emit(self._selected)
        return True

    def records_snapshot(self) -> tuple[ActionResult, ...]:
        """返回保留顺序的不可变快照，供任务表投影；不改变阅读目标或结果归属。"""
        return tuple(self._records.values())

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
        previous = self.targets.currentData()
        target_entries = []
        for item in result.items:
            label = ActionResults.target_label(result, item.target)
            if self._hosted_full_results:
                label = result_target_caption(result, item.target)
            elif not any(result.target_labels) and item.target in result.targets:
                index = result.targets.index(item.target)
                if index < len(result.target_names) and result.target_names[index]:
                    label += " · " + result.target_names[index]
            target_entries.append((item.job_id, f"{label} · {tr(STATE_LABELS[item.state])}"))
        if self._hosted_full_results and len(target_entries) > 1:
            counts = Counter(label for _, label in target_entries)
            seen: Counter[str] = Counter()
            for i, (job_id, label) in enumerate(target_entries):
                if counts[label] > 1:
                    seen[label] += 1
                    target_entries[i] = (job_id, f"{label} · {seen[label]}")
        blocker = QSignalBlocker(self.targets)
        if tuple(target_entries) != self._target_signature:
            self.targets.clear()
            for job_id, label in target_entries:
                self.targets.addItem(label, userData=job_id)
            self._target_signature = tuple(target_entries)
        index = self.targets.findData(previous)
        if index >= 0 and self.targets.currentIndex() != index:
            self.targets.setCurrentIndex(index)
        del blocker
        self.targets.setEnabled(bool(result.items))
        selectable = (len(result.items) > 1 if self._hosted_full_results
                      else not self.compact_success(result))
        self.targets.setVisible(result.spec.presentation != "notes" and selectable)
        self._render_detail()

    def _render_detail(self, *_args) -> None:
        context = self._selected, self.targets.currentData()
        if context != self._action_context:
            self.revoke_interactions()
            self._action_context = context
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
        self._refresh_message()
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
        self._fit_hosted_output()
        paths = tuple(item.artifacts if item else ())
        if paths != self._artifact_signature:
            self.artifacts.clear()
            for path in paths:
                self.artifacts.addItem(artifact_name(path), userData=path)
            self._artifact_signature = paths
        self.artifacts.setVisible(bool(paths) and not self._diagnostic)
        self.artifact_actions.setVisible(bool(paths) and not self._diagnostic)
        if self.artifact_section is not None:
            self.artifact_section.setVisible(bool(paths))
        if not self._inline and (
            result.state in ("failed", "partial") or (item and item.state == "failed")
        ):
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
        self._fit_hosted_output()
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
        if not self._allows_user_action():
            return
        path = self.artifacts.currentData()
        if isinstance(path, str) and path:
            self.artifact_requested.emit(path, folder)
