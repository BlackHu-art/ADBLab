"""兼容旧截图模块入口，实际实现位于 media 功能包。"""

import sys
from typing import TYPE_CHECKING

from gui.features.media import actions as _implementation

if TYPE_CHECKING:
    from gui.features.media.actions import ProcessRunner as ProcessRunner
    from gui.features.media.actions import QApplication as QApplication
    from gui.features.media.actions import QFileDialog as QFileDialog
    from gui.features.media.actions import QImageReader as QImageReader
    from gui.features.media.actions import ScreenshotDeleteWorker as ScreenshotDeleteWorker
    from gui.features.media.actions import ScreenshotValidateWorker as ScreenshotValidateWorker
    from gui.features.media.actions import ScreenshotViewerActions as ScreenshotViewerActions
    from gui.features.media.actions import os as os
    from gui.features.media.actions import show_toast as show_toast
    from gui.features.media.actions import sys as sys

sys.modules[__name__] = _implementation
