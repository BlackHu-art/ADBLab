"""兼容旧截图模块入口，实际实现位于 media 功能包。"""

import sys
from typing import TYPE_CHECKING

from gui.features.media import tasks as _implementation

if TYPE_CHECKING:
    from gui.features.media.tasks import ImageKey as ImageKey
    from gui.features.media.tasks import QImage as QImage
    from gui.features.media.tasks import QThread as QThread
    from gui.features.media.tasks import ScreenshotDeleteWorker as ScreenshotDeleteWorker
    from gui.features.media.tasks import ScreenshotImageCache as ScreenshotImageCache
    from gui.features.media.tasks import ScreenshotIOShutdownTask as ScreenshotIOShutdownTask
    from gui.features.media.tasks import ScreenshotReadWorker as ScreenshotReadWorker
    from gui.features.media.tasks import ScreenshotValidateWorker as ScreenshotValidateWorker
    from gui.features.media.tasks import os as os
    from gui.features.media.tasks import raster_image_reader as raster_image_reader

sys.modules[__name__] = _implementation
