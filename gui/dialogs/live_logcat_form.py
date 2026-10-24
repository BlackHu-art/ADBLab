"""保留旧 Logcat 模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.logcat import form as _implementation

if TYPE_CHECKING:
    from gui.features.logcat.form import LEVEL_LABELS as LEVEL_LABELS
    from gui.features.logcat.form import LiveLogcatForm as LiveLogcatForm
    from gui.features.logcat.form import LogcatCommandBar as LogcatCommandBar
    from gui.features.logcat.form import LogcatHighlighter as LogcatHighlighter
    from gui.features.logcat.form import LogcatMaterial as LogcatMaterial
    from gui.features.logcat.form import _LogcatOutput as _LogcatOutput
    from gui.features.logcat.form import _LogcatStatusLabel as _LogcatStatusLabel

sys.modules[__name__] = _implementation
