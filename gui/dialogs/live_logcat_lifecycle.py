"""保留旧 Logcat 模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.logcat import lifecycle as _implementation

if TYPE_CHECKING:
    from gui.features.logcat.lifecycle import CurrentPackageWorker as CurrentPackageWorker
    from gui.features.logcat.lifecycle import LiveLogcatLifecycle as LiveLogcatLifecycle
    from gui.features.logcat.lifecycle import LogcatWorker as LogcatWorker

sys.modules[__name__] = _implementation
