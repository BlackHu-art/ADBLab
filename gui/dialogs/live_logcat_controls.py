"""保留旧 Logcat 模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.logcat import controls as _implementation

if TYPE_CHECKING:
    from gui.features.logcat.controls import LogcatCommandBar as LogcatCommandBar
    from gui.features.logcat.controls import LogcatReadingButton as LogcatReadingButton
    from gui.features.logcat.controls import _ReadingButtonStyleOption as _ReadingButtonStyleOption

sys.modules[__name__] = _implementation
