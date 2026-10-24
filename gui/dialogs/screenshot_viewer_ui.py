"""兼容旧截图模块入口，实际实现位于 media 功能包。"""

import sys
from typing import TYPE_CHECKING

from gui.features.media import ui as _implementation

if TYPE_CHECKING:
    from gui.features.media.ui import ScreenshotViewerUI as ScreenshotViewerUI

sys.modules[__name__] = _implementation
