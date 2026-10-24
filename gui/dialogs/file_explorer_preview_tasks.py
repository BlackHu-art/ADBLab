"""保留旧文件浏览器模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.file_explorer import preview_tasks as _implementation

if TYPE_CHECKING:
    from gui.features.file_explorer.preview_tasks import (
        MAX_IMAGE_PREVIEW_DIMENSION as MAX_IMAGE_PREVIEW_DIMENSION,
    )
    from gui.features.file_explorer.preview_tasks import OrderedDict as OrderedDict
    from gui.features.file_explorer.preview_tasks import PreviewIdentity as PreviewIdentity
    from gui.features.file_explorer.preview_tasks import PreviewImageCache as PreviewImageCache
    from gui.features.file_explorer.preview_tasks import PreviewReadWorker as PreviewReadWorker
    from gui.features.file_explorer.preview_tasks import PreviewVersion as PreviewVersion
    from gui.features.file_explorer.preview_tasks import QImage as QImage
    from gui.features.file_explorer.preview_tasks import QImageReader as QImageReader
    from gui.features.file_explorer.preview_tasks import QSize as QSize
    from gui.features.file_explorer.preview_tasks import QThread as QThread
    from gui.features.file_explorer.preview_tasks import raster_image_reader as raster_image_reader
    from gui.features.file_explorer.preview_tasks import threading as threading

sys.modules[__name__] = _implementation
