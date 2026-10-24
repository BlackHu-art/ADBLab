"""保留旧 Logcat 模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.logcat import page as _implementation

if TYPE_CHECKING:
    from gui.features.logcat.page import CurrentPackageWorker as CurrentPackageWorker
    from gui.features.logcat.page import LiveLogcatForm as LiveLogcatForm
    from gui.features.logcat.page import LiveLogcatLifecycle as LiveLogcatLifecycle
    from gui.features.logcat.page import LiveLogcatPage as LiveLogcatPage
    from gui.features.logcat.page import LiveLogcatStream as LiveLogcatStream
    from gui.features.logcat.page import LogcatBatch as LogcatBatch
    from gui.features.logcat.page import LogcatTermination as LogcatTermination
    from gui.features.logcat.page import LogcatWorker as LogcatWorker
    from gui.features.logcat.page import _LogcatStatusLabel as _LogcatStatusLabel

sys.modules[__name__] = _implementation
