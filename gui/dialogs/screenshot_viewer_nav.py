"""兼容旧截图模块入口，实际实现位于 media 功能包。"""

import sys
from typing import TYPE_CHECKING

from gui.features.media import nav as _implementation

if TYPE_CHECKING:
    from gui.features.media.nav import MAX_ZOOM as MAX_ZOOM
    from gui.features.media.nav import MIN_ZOOM as MIN_ZOOM
    from gui.features.media.nav import ZOOM_STEP as ZOOM_STEP
    from gui.features.media.nav import ImageKey as ImageKey
    from gui.features.media.nav import QImageReader as QImageReader
    from gui.features.media.nav import ScreenshotImageCache as ScreenshotImageCache
    from gui.features.media.nav import ScreenshotReadWorker as ScreenshotReadWorker
    from gui.features.media.nav import ScreenshotViewerNav as ScreenshotViewerNav
    from gui.features.media.nav import os as os

sys.modules[__name__] = _implementation
