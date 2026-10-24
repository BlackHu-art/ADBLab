"""保留旧应用管理模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.app_manager import icons as _implementation

if TYPE_CHECKING:
    from gui.features.app_manager.icons import AppManagerIcons as AppManagerIcons
    from gui.features.app_manager.icons import OrderedDict as OrderedDict
    from gui.features.app_manager.icons import QEvent as QEvent
    from gui.features.app_manager.icons import QIcon as QIcon
    from gui.features.app_manager.icons import QImage as QImage
    from gui.features.app_manager.icons import QObject as QObject
    from gui.features.app_manager.icons import QPixmap as QPixmap
    from gui.features.app_manager.icons import Qt as Qt
    from gui.features.app_manager.icons import QTimer as QTimer
    from gui.features.app_manager.icons import Slot as Slot
    from gui.features.app_manager.icons import _safe_failure_reason as _safe_failure_reason
    from gui.features.app_manager.icons import _visible_row_indexes as _visible_row_indexes
    from gui.features.app_manager.icons import re as re
    from gui.features.app_manager.icons import refresh_row_description as refresh_row_description
    from gui.features.app_manager.icons import tr as tr

sys.modules[__name__] = _implementation
