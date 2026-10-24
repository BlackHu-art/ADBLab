"""保留旧 Logcat 模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.logcat import stream as _implementation

if TYPE_CHECKING:
    from gui.features.logcat.stream import LEVEL_ORDER as LEVEL_ORDER
    from gui.features.logcat.stream import CurrentPackageWorker as CurrentPackageWorker
    from gui.features.logcat.stream import LiveLogcatStream as LiveLogcatStream
    from gui.features.logcat.stream import LogcatBatch as LogcatBatch
    from gui.features.logcat.stream import LogcatExportWorker as LogcatExportWorker
    from gui.features.logcat.stream import LogcatTermination as LogcatTermination
    from gui.features.logcat.stream import LogcatTerminationKind as LogcatTerminationKind
    from gui.features.logcat.stream import LogcatWorker as LogcatWorker

sys.modules[__name__] = _implementation
