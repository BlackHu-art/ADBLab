"""保留旧性能模块路径，与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.performance import run as _implementation

if TYPE_CHECKING:
    from gui.features.performance.run import BaseStyles as BaseStyles
    from gui.features.performance.run import CancelledError as CancelledError
    from gui.features.performance.run import FluentMessageBox as FluentMessageBox
    from gui.features.performance.run import PerformanceArtifacts as PerformanceArtifacts
    from gui.features.performance.run import PerformanceLauncherRun as PerformanceLauncherRun
    from gui.features.performance.run import PerformanceStartWorker as PerformanceStartWorker
    from gui.features.performance.run import QObject as QObject
    from gui.features.performance.run import Qt as Qt
    from gui.features.performance.run import QThread as QThread
    from gui.features.performance.run import QTimer as QTimer
    from gui.features.performance.run import Signal as Signal
    from gui.features.performance.run import Slot as Slot
    from gui.features.performance.run import ThreadedShutdownTask as ThreadedShutdownTask
    from gui.features.performance.run import alive_signal_emitter as alive_signal_emitter
    from gui.features.performance.run import threading as threading
    from gui.features.performance.run import time as time
    from gui.features.performance.run import tr as tr

sys.modules[__name__] = _implementation
