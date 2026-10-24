"""保留旧性能模块路径，与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.performance import result_tasks as _implementation

if TYPE_CHECKING:
    from gui.features.performance.result_tasks import PerformanceArtifacts as PerformanceArtifacts
    from gui.features.performance.result_tasks import (
        PerformanceResultLoader as PerformanceResultLoader,
    )
    from gui.features.performance.result_tasks import (
        PerformanceResultWorker as PerformanceResultWorker,
    )
    from gui.features.performance.result_tasks import QObject as QObject
    from gui.features.performance.result_tasks import Qt as Qt
    from gui.features.performance.result_tasks import QThread as QThread
    from gui.features.performance.result_tasks import QTimer as QTimer
    from gui.features.performance.result_tasks import Signal as Signal
    from gui.features.performance.result_tasks import Slot as Slot
    from gui.features.performance.result_tasks import load_result_metrics as load_result_metrics
    from gui.features.performance.result_tasks import threading as threading
    from gui.features.performance.result_tasks import time as time
    from gui.features.performance.result_tasks import tr as tr

sys.modules[__name__] = _implementation
