"""保留旧文件浏览器模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.file_explorer import view as _implementation

if TYPE_CHECKING:
    from gui.features.file_explorer.view import (
        MAX_IMAGE_PREVIEW_DIMENSION as MAX_IMAGE_PREVIEW_DIMENSION,
    )
    from gui.features.file_explorer.view import MAX_TEXT_VIEW_BYTES as MAX_TEXT_VIEW_BYTES
    from gui.features.file_explorer.view import FileExplorerView as FileExplorerView
    from gui.features.file_explorer.view import LogService as LogService
    from gui.features.file_explorer.view import PreviewIdentity as PreviewIdentity
    from gui.features.file_explorer.view import PreviewImageCache as PreviewImageCache
    from gui.features.file_explorer.view import PreviewReadWorker as PreviewReadWorker
    from gui.features.file_explorer.view import QImageReader as QImageReader
    from gui.features.file_explorer.view import QPixmap as QPixmap
    from gui.features.file_explorer.view import QPixmapCache as QPixmapCache
    from gui.features.file_explorer.view import QSize as QSize
    from gui.features.file_explorer.view import Qt as Qt
    from gui.features.file_explorer.view import TextReadWorker as TextReadWorker
    from gui.features.file_explorer.view import _ImageRequest as _ImageRequest
    from gui.features.file_explorer.view import _load_image_preview as _load_image_preview
    from gui.features.file_explorer.view import add_menu_action as add_menu_action
    from gui.features.file_explorer.view import dataclass as dataclass
    from gui.features.file_explorer.view import explorer_service as explorer_service
    from gui.features.file_explorer.view import os as os
    from gui.features.file_explorer.view import raster_image_reader as raster_image_reader
    from gui.features.file_explorer.view import tempfile as tempfile
    from gui.features.file_explorer.view import tr as tr
    from gui.features.file_explorer.view import uuid as uuid

sys.modules[__name__] = _implementation
