"""保留旧文件浏览器模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.file_explorer import image as _implementation

if TYPE_CHECKING:
    from gui.features.file_explorer.image import BodyLabel as BodyLabel
    from gui.features.file_explorer.image import (
        FileExplorerImagePreview as FileExplorerImagePreview,
    )
    from gui.features.file_explorer.image import FontRole as FontRole
    from gui.features.file_explorer.image import ImageLabel as ImageLabel
    from gui.features.file_explorer.image import PushButton as PushButton
    from gui.features.file_explorer.image import QImage as QImage
    from gui.features.file_explorer.image import QPixmap as QPixmap
    from gui.features.file_explorer.image import QSize as QSize
    from gui.features.file_explorer.image import QSizePolicy as QSizePolicy
    from gui.features.file_explorer.image import Qt as Qt
    from gui.features.file_explorer.image import QTimer as QTimer
    from gui.features.file_explorer.image import QVBoxLayout as QVBoxLayout
    from gui.features.file_explorer.image import QWidget as QWidget
    from gui.features.file_explorer.image import Signal as Signal
    from gui.features.file_explorer.image import SmoothScrollArea as SmoothScrollArea
    from gui.features.file_explorer.image import __all__ as __all__
    from gui.features.file_explorer.image import apply_label_role as apply_label_role
    from gui.features.file_explorer.image import get_themed_icon as get_themed_icon
    from gui.features.file_explorer.image import tr as tr
    from gui.features.file_explorer.image import use_instant_scroll as use_instant_scroll

sys.modules[__name__] = _implementation
