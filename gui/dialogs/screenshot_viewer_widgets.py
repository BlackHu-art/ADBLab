"""兼容旧截图模块入口，实际实现位于 media 功能包。"""

import sys
from typing import TYPE_CHECKING

from gui.features.media import widgets as _implementation

if TYPE_CHECKING:
    from gui.features.media.widgets import ScreenshotDetailsBar as ScreenshotDetailsBar
    from gui.features.media.widgets import ScreenshotFlipView as ScreenshotFlipView
    from gui.features.media.widgets import ScreenshotImageDelegate as ScreenshotImageDelegate
    from gui.features.media.widgets import ScreenshotPipsPager as ScreenshotPipsPager
    from gui.features.media.widgets import _navigation_target as _navigation_target

sys.modules[__name__] = _implementation
