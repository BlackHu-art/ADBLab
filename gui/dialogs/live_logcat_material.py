"""保留旧 Logcat 模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.logcat import material as _implementation

if TYPE_CHECKING:
    from gui.features.logcat.material import LogcatMaterial as LogcatMaterial

sys.modules[__name__] = _implementation
