"""报告区只提供已生成文件入口，执行过程和失败明细由任务中心呈现。"""

from collections import OrderedDict

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, PushButton

from adblab.application.action_results import ActionResult, ActionResults, artifact_name
from gui.i18n import tr


class ReportArtifactsView(QWidget):
    """保留最近生成的文件；同一快照更新不会重复添加，也不访问设备或本地文件。"""

    artifact_requested = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: OrderedDict[str, str] = OrderedDict()
        self._latest_started = 0.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        self.heading = BodyLabel(tr("已生成文件"), self)
        layout.addWidget(self.heading)
        self.files = ComboBox(self)
        self.files.setMinimumWidth(0)
        self.files.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.files.setAccessibleName(tr("已生成的报告和日志"))
        layout.addWidget(self.files)
        actions = QHBoxLayout()
        self.open_button = PushButton(tr("打开文件"), self)
        self.folder_button = PushButton(tr("打开文件夹"), self)
        self.open_button.clicked.connect(lambda: self._open(False))
        self.folder_button.clicked.connect(lambda: self._open(True))
        actions.addWidget(self.open_button)
        actions.addWidget(self.folder_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.hide()

    def present(self, result: ActionResult) -> None:
        previous = self.files.currentData()
        newer = result.started_at > self._latest_started
        changed = False
        for item in result.items:
            for path in item.artifacts:
                if path in self._files:
                    continue
                label = ActionResults.safe_text(result, artifact_name(path))
                self._files[path] = f"{tr(result.spec.title)} · {tr(item.label)} · {label}"
                changed = True
        if not changed:
            return
        while len(self._files) > 20:
            self._files.popitem(last=False)
        blocker = QSignalBlocker(self.files)
        self.files.clear()
        for path, label in reversed(self._files.items()):
            self.files.addItem(label, userData=path)
        index = self.files.findData(previous)
        if index >= 0 and not newer:
            self.files.setCurrentIndex(index)
        self._latest_started = max(self._latest_started, result.started_at)
        del blocker
        self.show()

    def _open(self, folder: bool) -> None:
        path = self.files.currentData()
        if isinstance(path, str) and path:
            self.artifact_requested.emit(path, folder)
