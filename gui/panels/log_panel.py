"""提供支持主题切换、自动滚动和批量渲染的用户日志面板。

结构说明（ADR-0005 日志优化）：
- 记录为 ``(时间戳, 级别, 消息)`` 三元组，时间戳由 LogService 在产生时生成，
  面板数据层保留但不渲染（界面只显示级别与消息）；
- 每条日志渲染为独立 ``<p>`` 块，使裁剪可按块从文档头部删除（O(裁剪行)）；
- 每行采用块级悬挂缩进：`margin-left` 为当前级别标签的实际像素宽（按日志字体
  度量，字号变化自动适配），`text-indent` 负等值——自动折行与显式换行都对齐到
  消息列起点，级别与消息间只保留一个空格；
- ERROR/CRITICAL 加粗；条目内容 HTML 按 (级别, 消息) 缓存，主题切换时重建；
- 正文外包卡片视觉容器（``logViewCard``，Fluent CardWidget 圆角卡片）：纯外围包壳，
  ``text_output`` 的属性与渲染契约保持不变，主题切换经 ``_apply_style``
  重建卡片样式；
- ``logViewCard`` 上方为卡片化工具条（``logToolbarCard``）：级别过滤下拉
  （``logLevelFilter``）、当前过滤级别徽标（``logLevelBadge``，InfoBadge 按
  语义级别着色）与清空图标按钮（``logClearButton``）。objectName 为公开
  契约，供测试与 QSS 稳定引用；
- 级别过滤只作用于新到达的批次（默认 ``All Levels`` 与历史行为完全一致），
  已渲染的历史行不回溯隐藏——正文渲染、裁剪、防抖与背压管线保持一字不动。
"""

from collections import OrderedDict
from html import escape

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CardWidget, ComboBox, InfoBadge, InfoLevel, TextEdit

from core.log_service import LogService
from gui.styles import BaseStyles, FontRole
from gui.widgets.fluent import IconButton

_HTML_CACHE_LIMIT = 2048

# 过滤级别徽标按语义映射 InfoLevel；qfluentwidgets InfoBadge 只有五个级别色，
# 因此按严重程度对应（DEBUG/INFO→INFOAMTION、SUCCESS→SUCCESS、WARNING→WARNING、
# ERROR/CRITICAL→ERROR），接受与旧 LOG_* 色值的细微色差（向 qfluentwidgets 靠拢）。
_LOG_LEVEL_INFO_LEVEL = {
    "": InfoLevel.INFOAMTION,
    "DEBUG": InfoLevel.INFOAMTION,
    "INFO": InfoLevel.INFOAMTION,
    "SUCCESS": InfoLevel.SUCCESS,
    "WARNING": InfoLevel.WARNING,
    "ERROR": InfoLevel.ERROR,
    "CRITICAL": InfoLevel.ERROR,
}


class LogPanel(QWidget):
    """用户日志面板：批量渲染核心 + 卡片容器与卡片化工具条外围。

    公开契约：
    - 渲染/裁剪/防抖/背压行为由 ADR-0005 测试固定，本类只在其外围换肤；
    - 正文 ``text_output`` 外包 ``logViewCard`` 卡片容器（objectName 稳定，
      供测试与 QSS 引用）；
    - 工具条控件 objectName 稳定：``logToolbarCard`` / ``logLevelFilter`` /
      ``logLevelBadge`` / ``logClearButton``；
    - 级别过滤默认 ``All Levels``（空 UserRole 数据），只过滤新到达批次，
      已渲染历史行不回溯隐藏。
    """

    RENDER_DEBOUNCE_MS = 16
    FRAME_BATCH_SIZE = 100
    IMMEDIATE_BATCH_SIZE = FRAME_BATCH_SIZE

    # 级别过滤下拉项：(显示文本, UserRole 数据)；空数据代表 All Levels。
    _LEVEL_FILTER_OPTIONS: tuple[tuple[str, str], ...] = (
        ("All Levels", ""),
        ("DEBUG", "DEBUG"),
        ("INFO", "INFO"),
        ("SUCCESS", "SUCCESS"),
        ("WARNING", "WARNING"),
        ("ERROR", "ERROR"),
        ("CRITICAL", "CRITICAL"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.settings_manager import AppSettings

        self._max_lines = AppSettings.instance().get("log_max_lines", 2000)
        self._entries: list[tuple[str, str, str]] = []
        self._pending_dropped_total = 0
        self._pending_drop_notice_count = 0
        self._pending_rows: list[tuple[str, str, str]] = []
        self._pending_scroll_to_bottom = False
        self._html_cache: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._render_pending_timer = QTimer(self)
        self._render_pending_timer.setSingleShot(True)
        self._render_pending_timer.timeout.connect(self._flush_pending_rows)
        self._init_ui()
        self._connect_services()
        BaseStyles.theme_changed.connect(self._on_theme_changed)
        BaseStyles.log_font_changed.connect(self._on_log_font_changed)
        BaseStyles.ui_font_changed.connect(self._on_ui_font_changed)

    # ------------------------------------------------------------------
    # 样式与主题
    # ------------------------------------------------------------------

    def _apply_style(self):
        # 正文已收敛为 qfluentwidgets TextEdit，背景/边框/滚动条自维护（随主题切换），
        # 无需在此套 QSS。
        # 卡片容器与工具条包壳已由 CardWidget 自绘制并随主题切换，无需再套 QSS。
        self._refresh_level_badge()
        self.logClearButton._sync_theme_state()

    def _on_theme_changed(self, _name: str):
        from core.settings_manager import AppSettings

        self._max_lines = AppSettings.instance().get("log_max_lines", 2000)
        self._apply_style()
        self._consume_pending_without_render()
        # 颜色系变化后重建条目缓存，再整份重绘。
        self._html_cache.clear()
        self._rerender_all()

    def _on_log_font_changed(self, _config):
        """更新日志字体并按新字号重绘（悬挂缩进按字体度量计算）。"""

        self.text_output.setFont(BaseStyles.font_for_role(FontRole.LOG))
        self._consume_pending_without_render()
        self._rerender_all()

    def _on_ui_font_changed(self, _config):
        """界面字体变化时刷新工具条控件字体（正文走独立 LOG 字体角色）。"""

        ui_font = BaseStyles.font_for_role(FontRole.UI)
        for widget in (self.logLevelBadge, self.logLevelFilter, self.logClearButton):
            widget.setFont(ui_font)

    def _init_ui(self):
        self.text_output = TextEdit(self)
        self.text_output.setReadOnly(True)
        self.text_output.setAccessibleName("Operation log")
        self.text_output.setPlaceholderText("Operation logs will appear here.")
        self.text_output.setUndoRedoEnabled(False)

        self.text_output.setFont(BaseStyles.font_for_role(FontRole.LOG))

        self._build_toolbar()

        # 正文外包卡片视觉容器：只换肤，正文属性与渲染契约不变。
        self.logViewCard = CardWidget(self)
        self.logViewCard.setObjectName("logViewCard")
        self.logViewCard.setBorderRadius(BaseStyles.RADIUS_LG)
        card_layout = QVBoxLayout(self.logViewCard)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.addWidget(self.text_output)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.logToolbarCard)
        layout.addWidget(self.logViewCard)
        self._apply_style()

    def _connect_services(self):
        LogService().logs_received.connect(self._append_logs, Qt.ConnectionType.AutoConnection)

    # ------------------------------------------------------------------
    # 卡片化工具条与级别过滤
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        """构建卡片化工具条：级别徽标、过滤下拉与清空图标按钮。"""

        self.logToolbarCard = CardWidget(self)
        self.logToolbarCard.setObjectName("logToolbarCard")
        self.logToolbarCard.setBorderRadius(BaseStyles.RADIUS_LG)

        self.logLevelBadge = InfoBadge("ALL", self.logToolbarCard)
        self.logLevelBadge.setObjectName("logLevelBadge")
        self.logLevelBadge.setProperty("fontRole", FontRole.UI.value)
        self.logLevelBadge.setFont(BaseStyles.font_for_role(FontRole.UI))
        self.logLevelBadge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.logLevelFilter = ComboBox(parent=self.logToolbarCard)
        self.logLevelFilter.setObjectName("logLevelFilter")
        self.logLevelFilter.setAccessibleName("Log level filter")
        for label, data in self._LEVEL_FILTER_OPTIONS:
            self.logLevelFilter.addItem(label, userData=data)
        self.logLevelFilter.setMinimumWidth(110)
        # 先填项再连接：避免 set_items 清空动作触发未初始化的槽。
        self.logLevelFilter.currentIndexChanged.connect(self._on_level_filter_changed)

        self.logClearButton = IconButton("broom.svg", "Clear Log", parent=self.logToolbarCard)
        self.logClearButton.setObjectName("logClearButton")
        self.logClearButton.clicked.connect(self.clear)

        row = QHBoxLayout(self.logToolbarCard)
        row.setContentsMargins(8, 4, 4, 4)
        row.setSpacing(8)
        row.addWidget(self.logLevelBadge)
        row.addWidget(self.logLevelFilter)
        row.addStretch(1)
        row.addWidget(self.logClearButton)

    def _current_filter_level(self) -> str:
        """返回当前过滤级别；``All Levels`` 返回空字符串（不过滤）。"""

        data = self.logLevelFilter.currentData()
        return str(data or "").upper()

    def _passes_filter(self, level: str) -> bool:
        wanted = self._current_filter_level()
        return not wanted or level == wanted

    def _on_level_filter_changed(self, _index: int):
        """级别过滤变化时刷新徽标；历史已渲染行不回溯隐藏。"""

        self._refresh_level_badge()

    def _refresh_level_badge(self):
        """按当前过滤级别刷新徽标（InfoBadge 按语义级别着色）。"""

        level = self._current_filter_level()
        self.logLevelBadge.setText(level or "ALL")
        self.logLevelBadge.setLevel(_LOG_LEVEL_INFO_LEVEL.get(level, InfoLevel.INFOAMTION))

    # ------------------------------------------------------------------
    # 缓冲与防抖
    # ------------------------------------------------------------------

    def _append_log(self, level: str, message: str):
        self._append_logs([("", level, message)])

    def _append_logs(self, records: list[tuple[str, str, str]]):
        """接收三元组批次；DEBUG 已由 LogService 在源头过滤，此处不再重复。

        级别过滤（工具条）只作用于新到达批次：默认 All Levels 时与历史行为
        完全一致；已渲染的历史行不回溯隐藏，正文渲染管线保持不变。
        """

        rows = [
            (str(timestamp), str(level).upper(), str(message))
            for timestamp, level, message in records
        ]
        rows = [row for row in rows if self._passes_filter(row[1])]
        if not rows:
            return
        sb = self.text_output.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 20

        self._pending_rows.extend(rows)
        self._bound_pending_backlog()
        self._pending_scroll_to_bottom = self._pending_scroll_to_bottom or at_bottom
        if not self._render_pending_timer.isActive():
            self._render_pending_timer.start(self.RENDER_DEBOUNCE_MS)

    def _flush_pending_rows(self):
        if not self._pending_rows and not self._pending_drop_notice_count:
            return
        rows = []
        if self._pending_drop_notice_count:
            rows.append(self._pending_drop_notice_row())
            self._pending_drop_notice_count = 0
        row_budget = max(0, self.FRAME_BATCH_SIZE - len(rows))
        rows.extend(self._pending_rows[:row_budget])
        del self._pending_rows[:row_budget]
        scroll_bar = self.text_output.verticalScrollBar()
        still_at_bottom = scroll_bar.value() >= scroll_bar.maximum() - 20
        at_bottom = self._pending_scroll_to_bottom and still_at_bottom
        added_count = len(rows)
        self._render_rows(rows, at_bottom, added_count)
        if self._pending_rows:
            self._render_pending_timer.start(self.RENDER_DEBOUNCE_MS)
        else:
            self._pending_scroll_to_bottom = False

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def _render_rows(self, rows: list[tuple[str, str, str]], at_bottom: bool, added_count: int):
        scroll_bar = self.text_output.verticalScrollBar()
        scroll_value = scroll_bar.value()
        self._entries.extend(rows)
        self._render_entries(rows)
        if at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())
        else:
            scroll_bar.setValue(min(scroll_value, scroll_bar.maximum()))
        self._trim_excess()

    def _render_entries(self, rows: list[tuple[str, str, str]]):
        if not rows:
            return
        cursor = self.text_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        try:
            fm = QFontMetrics(self.text_output.font())
            for _ts, level, msg in rows:
                # insertHtml 会把片段第一个块合并进光标所在块；当前块非空时先换行。
                if cursor.block().text():
                    cursor.insertBlock()
                cursor.insertHtml(self._message_body_html(level, msg))
                indent = fm.horizontalAdvance(f"[{level}] ")
                fmt = QTextBlockFormat()
                fmt.setTopMargin(0)
                fmt.setBottomMargin(0)
                fmt.setLeftMargin(indent)
                fmt.setTextIndent(-indent)
                cursor.setBlockFormat(fmt)
        finally:
            cursor.endEditBlock()

    def _rerender_all(
        self,
        *,
        scroll_to_bottom: bool | None = None,
        scroll_value: int | None = None,
    ):
        """批量重绘，并恢复用户在历史记录中的滚动锚点。"""

        sb = self.text_output.verticalScrollBar()
        if scroll_to_bottom is None:
            scroll_to_bottom = sb.value() >= sb.maximum() - 20
        if scroll_value is None:
            scroll_value = sb.value()
        self.text_output.setHtml(
            "".join(self._row_html(ts, level, msg) for ts, level, msg in self._entries)
        )
        if scroll_to_bottom:
            sb.setValue(sb.maximum())
        else:
            sb.setValue(min(max(0, int(scroll_value)), sb.maximum()))

    def _row_html(self, timestamp: str, level: str, message: str) -> str:
        """组装单条日志的块级 HTML；时间戳不渲染，悬挂缩进按当前字体度量。"""

        del timestamp
        indent = QFontMetrics(self.text_output.font()).horizontalAdvance(f"[{level}] ")
        body = self._message_body_html(level, message)
        # margin 上下必须显式归零：Qt 富文本对 <p> 有默认 12px 上下外边距，
        # 否则每条日志之间以及首条日志上方会出现空白行。
        return (
            f'<p style="margin:0 0 0 {indent}px; text-indent:-{indent}px;">{body}</p>'
        )

    def _message_body_html(self, level: str, message: str) -> str:
        """返回级别标签与消息正文的 HTML；命中缓存时跳过转义与拼接。"""

        cache_key = (level, message)
        cached = self._html_cache.get(cache_key)
        if cached is not None:
            self._html_cache.move_to_end(cache_key)
            return cached
        c = BaseStyles.color
        lv_key = (
            f"LOG_{level}"
            if level in ("DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")
            else "LOG_INFO"
        )
        # 级别与消息之间只保留一个普通空格；ERROR/CRITICAL 加粗突出。
        bold_open, bold_close = ("<b>", "</b>") if level in ("ERROR", "CRITICAL") else ("", "")
        msg = escape(str(message).strip("\r\n")).replace("\n", "<br>")
        body = (
            f'{bold_open}<span style="color:{c(lv_key)}">[{escape(str(level))}]</span>'
            f'{bold_close} '
            f'<span style="color:{c("LOG_TEXT_COLOR")}">{msg}</span>'
        )
        if len(self._html_cache) >= _HTML_CACHE_LIMIT:
            self._html_cache.clear()
        self._html_cache[cache_key] = body
        return body

    # ------------------------------------------------------------------
    # 裁剪与清理
    # ------------------------------------------------------------------

    def _trim_excess(self):
        """超过上限时按块从文档头部删除，避免整份重绘（O(裁剪行)）。"""

        if len(self._entries) <= self._max_lines:
            return
        excess = len(self._entries) - self._max_lines
        self._entries = self._entries[excess:]
        self._remove_head_blocks(excess)

    def _remove_head_blocks(self, count: int):
        document = self.text_output.document()
        if count <= 0 or document.blockCount() <= 1:
            return
        scroll_bar = self.text_output.verticalScrollBar()
        at_bottom = scroll_bar.value() >= scroll_bar.maximum() - 20
        scroll_value = scroll_bar.value()
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.Down,
            QTextCursor.MoveMode.KeepAnchor,
            min(count, document.blockCount() - 1),
        )
        cursor.removeSelectedText()
        if at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())
        else:
            scroll_bar.setValue(min(scroll_value, scroll_bar.maximum()))

    @property
    def dropped_pending_count(self) -> int:
        """返回因界面渲染背压而丢弃的累计日志数。"""

        return self._pending_dropped_total

    def _pending_capacity(self) -> int:
        try:
            return max(self.FRAME_BATCH_SIZE, int(self._max_lines))
        except (TypeError, ValueError, OverflowError):
            return 2000

    def _bound_pending_backlog(self) -> None:
        """只保留界面最终可能展示的最新日志，防止队列无限增长。"""

        overflow = len(self._pending_rows) - self._pending_capacity()
        if overflow <= 0:
            return
        del self._pending_rows[:overflow]
        self._pending_dropped_total += overflow
        self._pending_drop_notice_count += overflow

    def _pending_drop_notice_row(self) -> tuple[str, str, str]:
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        message = (
            "Log display backlog overflow: dropped "
            f"{self._pending_drop_notice_count} records "
            f"({self._pending_dropped_total} total dropped)"
        )
        return timestamp, "WARNING", message

    def _consume_pending_without_render(self) -> None:
        """主题重绘前接纳等待行，避免取消定时器时丢失用户日志。"""

        if self._render_pending_timer.isActive():
            self._render_pending_timer.stop()
        if self._pending_drop_notice_count:
            self._entries.append(self._pending_drop_notice_row())
        if self._pending_rows:
            self._entries.extend(self._pending_rows)
        self._pending_rows = []
        self._pending_scroll_to_bottom = False
        self._pending_drop_notice_count = 0
        if len(self._entries) > self._max_lines:
            self._entries = self._entries[-self._max_lines :]

    def _cancel_pending_render(self):
        if self._render_pending_timer.isActive():
            self._render_pending_timer.stop()
        self._pending_rows = []
        self._pending_scroll_to_bottom = False
        self._pending_drop_notice_count = 0

    def closeEvent(self, event):
        """关闭时停止防抖定时器并断开类级信号，避免晚到事件触碰已销毁面板。"""

        self._cancel_pending_render()
        BaseStyles.theme_changed.disconnect(self._on_theme_changed)
        BaseStyles.log_font_changed.disconnect(self._on_log_font_changed)
        BaseStyles.ui_font_changed.disconnect(self._on_ui_font_changed)
        super().closeEvent(event)

    def clear(self):
        self._cancel_pending_render()
        self._entries.clear()
        self.text_output.clear()
        self._pending_dropped_total = 0
        self._html_cache.clear()

    def set_max_lines(self, max_lines: int):
        """立即应用日志保留上限，并裁剪已经显示的历史记录。"""

        try:
            normalized = int(max_lines)
        except (TypeError, ValueError, OverflowError):
            return
        self._max_lines = max(normalized, 100)
        self._bound_pending_backlog()
        self._flush_pending_rows()
        self._trim_excess()
