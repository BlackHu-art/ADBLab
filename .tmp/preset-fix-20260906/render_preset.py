"""仅渲染内存方案与真实输入框，不加载用户方案或调用设备。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

import gui.widgets.run_preset_bar as preset_module
from gui.dialogs.fluent_dialog import FluentInputDialog
from gui.run_library import RunLibraryController
from gui.widgets.run_preset_bar import RunPresetBar
from services.run_library import RunLibrary

application = QApplication([])
owner = QWidget()
owner.resize(860, 600)
layout = QVBoxLayout(owner)
bar = RunPresetBar("performance", lambda: {"frequency_seconds": 2}, lambda _p: None, owner)
layout.addWidget(bar)
layout.addStretch()
controller = RunLibraryController(RunLibrary())
bar.set_library(controller)
owner.show()
application.processEvents()


class CapturedInput(FluentInputDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        QTimer.singleShot(350, self.capture)

    def capture(self):
        self.lineEdit.setText("日常性能采集")
        owner.grab().save(str(Path(__file__).with_name("preset-dialog-after.png")))
        QTest.mouseClick(self.yesButton, Qt.MouseButton.LeftButton)


preset_module.FluentInputDialog = CapturedInput
QTest.mouseClick(bar.save_button, Qt.MouseButton.LeftButton)
assert controller.shutdown()
application.processEvents()
assert len(controller.presets) == 1
assert bar.combo.currentText() == "日常性能采集"
owner.grab().save(str(Path(__file__).with_name("preset-saved-after.png")))
owner.close()
owner.deleteLater()
