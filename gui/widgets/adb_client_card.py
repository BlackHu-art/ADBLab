
"""ADB 客户端设置卡：识别本地候选、单选生效、自定义路径。

参考 qfluentwidgets 强调色卡的展开结构（ExpandGroupSettingCard + 单选列表 +
自定义行 + 尾部动作），只把颜色换成 ADB 客户端。识别在后台线程执行，
只运行 adb version，不连接 5037 服务。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ExpandGroupSettingCard,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    RadioButton,
)

from gui.i18n import tr
from services.adb_clients import (
    ERROR_CANCELLED,
    ERROR_MISSING,
    ERROR_NOT_ADB,
    ERROR_TIMEOUT,
    ERROR_UNAVAILABLE,
    ClientProbe,
    detect_clients,
)
from utils.adb_resolver import (
    CLIENT_PREFERENCE_AUTO,
    CLIENT_SOURCE_TOKENS,
    list_adb_candidates,
)

DETECTION_TIMEOUT_MS = 15000

# 候选行按实际配置的来源动态生成：未配置的来源不占位（不出现"未设置"噪音行）；
# Android SDK 三处仍留在自动解析链里兜底，但不展示、不探测。

_SOURCE_LABELS = {
    "bundled": "应用自带",
    "runtime_cache": "应用工具缓存",
    "env": "环境变量 ADB_PATH",
    "sdk_home": "Android SDK（ANDROID_HOME）",
    "sdk_root": "Android SDK（ANDROID_SDK_ROOT）",
    "sdk_local": "Android SDK（%LOCALAPPDATA%）",
    "PATH": "系统 PATH",
    "custom": "自定义 adb",
}

_ERROR_LABELS = {
    ERROR_MISSING: "未设置或文件不存在",
    ERROR_UNAVAILABLE: "无法执行",
    ERROR_TIMEOUT: "执行超时",
    ERROR_NOT_ADB: "不是 ADB 程序",
    ERROR_CANCELLED: "识别已取消",
}

CUSTOM_KEY = "custom"


def source_label(source: str) -> str:
    """返回来源的中文标签；未知来源原样回退。"""

    return _SOURCE_LABELS.get(source, source)


def error_label(error: str) -> str:
    """返回失败原因的中文标签。"""

    return _ERROR_LABELS.get(error, error or tr("不可用"))


def shorten_path(path: str, limit: int = 48) -> str:
    """中间省略过长路径，保留盘符与文件名便于辨认。"""

    text = str(path or "")
    if len(text) <= limit:
        return text
    head = max(1, limit // 2 - 1)
    tail = max(1, limit - head - 1)
    return f"{text[:head]}…{text[-tail:]}"


class _WrappingRow(QWidget):
    """按当前宽度测量高度的行控件。

    换行标签在水平方向使用 Ignored 策略：sizeHint() 会按零宽度估算换行行数并得到
    虚高高度。这里改用 heightForWidth 在当前宽度下测量，供展开卡计算总高。
    """

    def sizeHint(self):  # noqa: N802 - Qt 风格命名
        width = max(1, self.width())
        layout = self.layout()
        if layout is None:
            return super().sizeHint()
        return QSize(width, max(layout.heightForWidth(width), layout.minimumSize().height()))


class _ProbeSignals(QObject):
    finished = Signal(int, list)
    failed = Signal(int, str)


class _ProbeTask(QRunnable):
    """后台识别候选客户端；结果带回代次，晚到结果由卡片丢弃。"""

    def __init__(self, generation: int, cancelled: Callable[[], bool]) -> None:
        super().__init__()
        self.signals = _ProbeSignals()
        self._generation = generation
        self._cancelled = cancelled

    def run(self) -> None:
        try:
            probes = detect_clients(cancelled=self._cancelled)
        except Exception as exc:  # 识别失败不能影响设置页交互
            self.signals.failed.emit(self._generation, type(exc).__name__)
        else:
            self.signals.finished.emit(self._generation, probes)


class AdbClientSettingCard(ExpandGroupSettingCard):
    """ADB 客户端选择卡：自动、命名来源候选与自定义路径。"""

    client_selected = Signal(str)
    custom_requested = Signal()
    rescan_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(FluentIcon.COMMAND_PROMPT, tr("ADB 客户端"), tr("自动选择"), parent)
        self._selection = CLIENT_PREFERENCE_AUTO
        self._custom_path = ""
        self._generation = 0
        self._busy = False
        self._probes: dict[str, ClientProbe] = {}
        self._rows: dict[str, tuple[QWidget, RadioButton, CaptionLabel]] = {}
        self._tasks: set[_ProbeTask] = set()
        self._detection_timer = QTimer(self)
        self._detection_timer.setSingleShot(True)
        self._detection_timer.timeout.connect(self._on_detection_timeout)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._custom_radio = RadioButton(self.view)
        self._custom_button = PushButton(tr("选择文件…"), self.view)
        self._action_button = PrimaryPushButton(tr("重新识别本地 ADB 环境"), self.view)

        self._custom_row = self._build_custom_row()
        self._action_row = self._build_action_row()
        self._auto_row: QWidget | None = None

        self._group.buttonClicked.connect(self._on_radio_clicked)
        self._custom_button.clicked.connect(self.custom_requested.emit)
        self._action_button.clicked.connect(self.rescan_requested.emit)
        self.set_candidates()
        self.set_selection(CLIENT_PREFERENCE_AUTO)

    # ── 行构建 ────────────────────────────────────────────────────────

    def _build_radio_row(
        self, key: str, title: str, detail: str, *, enabled: bool = True,
    ) -> tuple[QWidget, RadioButton, CaptionLabel]:
        row = _WrappingRow(self.view)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(48, 8, 48, 8)
        layout.setSpacing(12)
        radio = RadioButton(row)
        radio.setProperty("adbKey", key)
        radio.setEnabled(enabled)
        column = QVBoxLayout()
        column.setSpacing(1)
        title_label = BodyLabel(title, row)
        caption = CaptionLabel(detail, row)
        for label in (title_label, caption):
            # 长路径与长译文必须换行，否则行的最小宽度会撑破卡片并裁掉尾部按钮。
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        column.addWidget(title_label)
        column.addWidget(caption)
        layout.addWidget(radio)
        layout.addLayout(column, 1)
        row.setEnabled(enabled)
        self._group.addButton(radio)
        return row, radio, caption

    def _build_custom_row(self) -> QWidget:
        row = _WrappingRow(self.view)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(48, 8, 48, 8)
        layout.setSpacing(12)
        self._custom_radio.setProperty("adbKey", CUSTOM_KEY)
        self._group.addButton(self._custom_radio)
        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(BodyLabel(tr("自定义 adb"), row))
        self._custom_detail = CaptionLabel(tr("未选择：可直接指定任意 adb 可执行文件"), row)
        self._custom_detail.setWordWrap(True)
        self._custom_detail.setMinimumWidth(0)
        self._custom_detail.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        column.addWidget(self._custom_detail)
        layout.addWidget(self._custom_radio)
        layout.addLayout(column, 1)
        layout.addWidget(self._custom_button)
        return row

    def _build_action_row(self) -> QWidget:
        row = _WrappingRow(self.view)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(48, 6, 48, 14)
        layout.addStretch(1)
        layout.addWidget(self._action_button)
        return row

    def set_candidates(self, candidates=None) -> None:
        """按实际配置的来源重建候选行；未配置的来源不显示。"""

        items = list(candidates) if candidates is not None else list_adb_candidates()
        for widget in list(self.widgets):
            self.removeGroupWidget(widget)
        for button in list(self._group.buttons()):
            self._group.removeButton(button)
        self._rows = {}

        self._auto_row, self._auto_radio, _detail = self._build_radio_row(
            CLIENT_PREFERENCE_AUTO, tr("自动选择（推荐）"),
            tr("按 应用自带 → 环境变量 ADB_PATH → Android SDK → 系统 PATH 使用第一个可用项"),
        )
        self.addGroupWidget(self._auto_row)
        for candidate in items:
            row, radio, detail = self._build_radio_row(
                candidate.source, tr(source_label(candidate.source)), "",
            )
            self._rows[candidate.source] = (row, radio, detail)
            self.addGroupWidget(row)
        self.addGroupWidget(self._custom_row)
        self.addGroupWidget(self._action_row)
        self.set_selection(self._selection)
        self.apply_probes(list(self._probes.values()))

    # ── 对外接口 ──────────────────────────────────────────────────────

    def selection(self) -> str:
        return self._selection

    def rescan_button(self) -> PrimaryPushButton:
        """返回「重新识别」按钮，供无障碍描述与测试核对。"""

        return self._action_button

    def choose_button(self) -> PushButton:
        """返回「选择文件…」按钮，供无障碍描述与测试核对。"""

        return self._custom_button

    def detail_text(self, key: str) -> str:
        """返回候选行说明文字，供无障碍描述与测试核对。"""

        if key == CUSTOM_KEY:
            return self._custom_detail.text()
        row = self._rows.get(key)
        return row[2].text() if row is not None else ""

    def client_button(self, key: str) -> RadioButton | None:
        """返回指定来源的单选钮；未知来源返回 None。"""

        if key == CLIENT_PREFERENCE_AUTO:
            return self._auto_radio
        if key == CUSTOM_KEY:
            return self._custom_radio
        row = self._rows.get(key)
        return row[1] if row is not None else None

    def custom_path(self) -> str:
        return self._custom_path

    def set_custom_path(self, path: str) -> None:
        self._custom_path = str(path or "")
        self._custom_detail.setText(
            self._custom_path or tr("未选择：可直接指定任意 adb 可执行文件")
        )
        self._refresh_content()

    def set_selection(self, value: str) -> None:
        """设置当前选择；绝对路径归入自定义项。"""

        text = str(value or "").strip() or CLIENT_PREFERENCE_AUTO
        self._selection = text
        key = self._key_for(text)
        for button in self._group.buttons():
            button.setChecked(str(button.property("adbKey") or "") == key)
        self._refresh_content()

    def set_busy(self, busy: bool) -> None:
        """识别期间只锁「重新识别」按钮。

        识别只影响信息展示：候选选择与自定义文件必须始终可用，否则冷启动偏慢时
        用户会被整卡锁死。
        """

        self._busy = busy
        self._action_button.setEnabled(not busy)
        for button in self._group.buttons():
            button.setEnabled(self._radio_enabled(button))
        self._refresh_content()

    def _radio_enabled(self, button: QAbstractButton) -> bool:
        key = str(button.property("adbKey") or "")
        if key in (CLIENT_PREFERENCE_AUTO, CUSTOM_KEY):
            return True
        probe = self._probes.get(key)
        return bool(probe is not None and probe.executable)

    # ── 识别 ──────────────────────────────────────────────────────────

    def start_detection(self) -> None:
        """后台识别候选客户端；展开卡片或点击重新识别时调用。"""

        if self._busy:
            return
        self._generation += 1
        generation = self._generation
        self.set_busy(True)
        task = _ProbeTask(generation, lambda: generation != self._generation)
        task.signals.finished.connect(self._on_probes)
        task.signals.failed.connect(self._on_probe_failed)
        # 持有引用，避免 QRunnable 的 Python 包装在完成前被回收；结束时统一丢弃。
        self._tasks.add(task)
        task.signals.finished.connect(lambda *_args: self._tasks.discard(task))
        task.signals.failed.connect(lambda *_args: self._tasks.discard(task))
        self._detection_timer.start(DETECTION_TIMEOUT_MS)
        QThreadPool.globalInstance().start(task)

    def _cancel_detection_timeout(self) -> None:
        if self._detection_timer.isActive():
            self._detection_timer.stop()

    def _on_detection_timeout(self) -> None:
        """识别超时兜底：退出忙态并允许重试，晚到结果仍会正常回填。"""

        if not self._busy:
            return
        self.set_busy(False)
        self.card.contentLabel.setText(tr("识别超时，可重试"))

    def _on_probes(self, generation: int, probes: list) -> None:
        if generation != self._generation:
            return
        self.apply_probes(probes)

    def _on_probe_failed(self, generation: int, reason: str) -> None:
        if generation != self._generation:
            return
        self._cancel_detection_timeout()
        self.set_busy(False)
        self.card.contentLabel.setText(tr("识别失败：{reason}").format(reason=reason))

    def apply_probes(self, probes: list) -> None:
        """用识别结果回填候选行；不可用与未设置的项保留并标注原因。"""

        self._cancel_detection_timeout()
        self._probes = {probe.source: probe for probe in probes}
        for source, (_row, _radio, detail) in self._rows.items():
            probe = self._probes.get(source)
            if probe is None:
                detail.setText(tr("未检测到结果，可重新识别"))
                continue
            detail.setText(self._candidate_detail(probe))
        # 忙态只在这里收口：成功、失败、取消、关闭四条路径都必须经过 set_busy(False)，
        # 否则标题会永久停在「正在识别…」并把单选项与按钮全部锁死。
        self.set_busy(False)
        if self.isExpand:
            self._adjustViewSize()

    @staticmethod
    def _candidate_detail(probe: ClientProbe) -> str:
        path = shorten_path(probe.path)
        if probe.executable and probe.version:
            return tr("{version} · {path}").format(version=probe.version, path=path)
        return tr("{reason}：{path}").format(
            reason=tr(error_label(probe.error)), path=path or tr("（无路径）")
        )

    # ── 交互 ──────────────────────────────────────────────────────────

    def _on_radio_clicked(self, button) -> None:
        key = str(button.property("adbKey") or "")
        if key == CUSTOM_KEY and not self._custom_path:
            self.custom_requested.emit()
            return
        if key == CUSTOM_KEY:
            self.client_selected.emit(self._custom_path)
            return
        self.client_selected.emit(key)

    def _key_for(self, value: str) -> str:
        if value == CLIENT_PREFERENCE_AUTO:
            return CLIENT_PREFERENCE_AUTO
        if value in CLIENT_SOURCE_TOKENS:
            return value
        return CUSTOM_KEY

    def _refresh_content(self) -> None:
        if self._busy:
            self.card.contentLabel.setText(tr("正在识别本地 ADB 环境…可继续选择"))
            return
        if self._selection == CLIENT_PREFERENCE_AUTO:
            self.card.contentLabel.setText(tr("自动选择"))
            return
        if self._key_for(self._selection) == CUSTOM_KEY:
            self.card.contentLabel.setText(
                tr("自定义 · {path}").format(path=self._custom_path or tr("未选择"))
            )
            return
        probe = self._probes.get(self._selection)
        label = tr(source_label(self._selection))
        if probe is not None and probe.version:
            label = tr("{label} · {version}").format(label=label, version=probe.version)
        self.card.contentLabel.setText(label)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 风格命名
        """关闭时让在途识别在下一个检查点退出，避免回调落到已销毁的对象。"""

        self._generation += 1
        self._cancel_detection_timeout()
        super().closeEvent(event)

    def setExpand(self, isExpand: bool) -> None:  # noqa: N802 - Qt 风格命名
        """展开卡片时按需识别一次本地环境。"""

        first = isExpand and not self.isExpand
        super().setExpand(isExpand)
        if first and not self._probes:
            # 设置页可能已经预热过识别，命中缓存时不再重复探测。
            self.start_detection()

def _settings_row(
    parent: QWidget,
    group: QButtonGroup,
    key: str,
    title: str,
    detail: str,
    *,
    checked: bool = False,
    enabled: bool = True,
) -> QWidget:
    """构建一行单选设置项；标题与说明允许换行，避免长文案撑破卡片。"""

    row = _WrappingRow(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(48, 8, 48, 8)
    layout.setSpacing(12)
    radio = RadioButton(row)
    radio.setProperty("adbKey", key)
    radio.setChecked(checked)
    radio.setEnabled(enabled)
    column = QVBoxLayout()
    column.setSpacing(1)
    for label in (BodyLabel(title, row), CaptionLabel(detail, row)):
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        column.addWidget(label)
    layout.addWidget(radio)
    layout.addLayout(column, 1)
    row.setEnabled(enabled)
    group.addButton(radio)
    return row


class AdbEnvironmentSettingCard(ExpandGroupSettingCard):
    """执行环境卡：折叠态显示检测结果并可重新检测，展开态选择执行模式。"""

    mode_requested = Signal(str)
    recheck_requested = Signal()

    MODES = (
        ("auto", "自动选择（推荐）", "按服务能力与测速结果选择设备列表与 Shell 的执行方式"),
        ("fast", "手动快速", "跳过测速偏好、优先 5037 直连，但仍需通过能力验证"),
        ("native", "手动原生", "全部启动 adb.exe 客户端，不使用直连"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(FluentIcon.SYNC, tr("ADB 执行环境"), tr("正在检查执行环境"), parent)
        self._mode = "auto"
        self._radios: dict[str, RadioButton] = {}
        self._titles: dict[str, str] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._recheck_button = PushButton(tr("重新检测"), self)
        # 重新检测常驻折叠标题右侧：状态一目了然，也不用先展开才够得着。
        self.addWidget(self._recheck_button)
        for key, title, detail in self.MODES:
            self._titles[key] = title
            row = _settings_row(
                self.view, self._group, key, tr(title), tr(detail), checked=key == "auto",
            )
            stored = row.findChild(RadioButton)
            if stored is not None:
                self._radios[key] = stored
            self.addGroupWidget(row)
        self._group.buttonClicked.connect(self._on_clicked)
        self._recheck_button.clicked.connect(self.recheck_requested.emit)

    @property
    def titleLabel(self):  # noqa: N802 - 沿用 SettingCard 命名
        """折叠态标题标签；沿用 SettingCard 命名，便于通用排版逻辑复用。"""

        return self.card.titleLabel

    @property
    def contentLabel(self):  # noqa: N802 - 沿用 SettingCard 命名
        """折叠态状态标签，供无障碍描述与测试读取。"""

        return self.card.contentLabel

    @property
    def button(self) -> PushButton:
        """返回尾部「重新检测」按钮。"""

        return self._recheck_button

    def set_status(self, text: str) -> None:
        """更新折叠态状态行；不改变当前执行模式。"""

        self.card.contentLabel.setText(text)

    def set_recheck_enabled(self, enabled: bool) -> None:
        self._recheck_button.setEnabled(enabled)

    def mode(self) -> str:
        return self._mode

    def mode_button(self, mode: str) -> RadioButton | None:
        """返回指定模式的单选钮，供无障碍描述与测试定位。"""

        return self._radios.get(mode)

    def set_mode(self, mode: str) -> None:
        """同步当前模式；未知值回退自动，不覆盖状态行文案。"""

        text = mode if mode in self._radios else "auto"
        self._mode = text
        for key, radio in self._radios.items():
            radio.setChecked(key == text)

    def _on_clicked(self, button) -> None:
        key = str(button.property("adbKey") or "")
        if key and key != self._mode:
            self.mode_requested.emit(key)
