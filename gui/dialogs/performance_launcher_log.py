"""保留旧性能模块路径，与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.performance import log as _implementation

if TYPE_CHECKING:
    from gui.features.performance.log import AppSettings as AppSettings
    from gui.features.performance.log import PerformanceLauncherLog as PerformanceLauncherLog
    from gui.features.performance.log import QTextCursor as QTextCursor
    from gui.features.performance.log import datetime as datetime

sys.modules[__name__] = _implementation
