"""保留旧 Logcat 模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.logcat import worker as _implementation

if TYPE_CHECKING:
    from gui.features.logcat.worker import FALLBACK_RE as FALLBACK_RE
    from gui.features.logcat.worker import LEVEL_LABELS as LEVEL_LABELS
    from gui.features.logcat.worker import LEVEL_ORDER as LEVEL_ORDER
    from gui.features.logcat.worker import THREADTIME_RE as THREADTIME_RE
    from gui.features.logcat.worker import CurrentPackageWorker as CurrentPackageWorker
    from gui.features.logcat.worker import LogcatBatch as LogcatBatch
    from gui.features.logcat.worker import LogcatTermination as LogcatTermination
    from gui.features.logcat.worker import LogcatTerminationKind as LogcatTerminationKind
    from gui.features.logcat.worker import LogcatWorker as LogcatWorker
    from gui.features.logcat.worker import (
        _InterruptiblePackageRunner as _InterruptiblePackageRunner,
    )

sys.modules[__name__] = _implementation
