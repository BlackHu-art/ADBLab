"""保留旧性能模块路径，与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.performance import library as _implementation

if TYPE_CHECKING:
    from gui.features.performance.library import FluentMessageBox as FluentMessageBox
    from gui.features.performance.library import MobilePerfRunConfig as MobilePerfRunConfig
    from gui.features.performance.library import PerformanceLibrary as PerformanceLibrary
    from gui.features.performance.library import _ActivePerformanceRun as _ActivePerformanceRun
    from gui.features.performance.library import asdict as asdict
    from gui.features.performance.library import dataclass as dataclass
    from gui.features.performance.library import deepcopy as deepcopy
    from gui.features.performance.library import os as os
    from gui.features.performance.library import time as time
    from gui.features.performance.library import tr as tr
    from gui.features.performance.library import uuid4 as uuid4

sys.modules[__name__] = _implementation
