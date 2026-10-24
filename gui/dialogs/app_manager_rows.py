"""保留旧应用管理模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.app_manager import rows as _implementation

if TYPE_CHECKING:
    from gui.features.app_manager.rows import STATUS_ROLE as STATUS_ROLE
    from gui.features.app_manager.rows import VERSION_ROLE as VERSION_ROLE
    from gui.features.app_manager.rows import Any as Any
    from gui.features.app_manager.rows import AppManagerIconView as AppManagerIconView
    from gui.features.app_manager.rows import AppManagerRowDelegate as AppManagerRowDelegate
    from gui.features.app_manager.rows import BaseStyles as BaseStyles
    from gui.features.app_manager.rows import QEvent as QEvent
    from gui.features.app_manager.rows import QFont as QFont
    from gui.features.app_manager.rows import QFontMetrics as QFontMetrics
    from gui.features.app_manager.rows import QIcon as QIcon
    from gui.features.app_manager.rows import QItemSelectionModel as QItemSelectionModel
    from gui.features.app_manager.rows import QPalette as QPalette
    from gui.features.app_manager.rows import QRect as QRect
    from gui.features.app_manager.rows import QSize as QSize
    from gui.features.app_manager.rows import QStyleOptionViewItem as QStyleOptionViewItem
    from gui.features.app_manager.rows import Qt as Qt
    from gui.features.app_manager.rows import QTimer as QTimer
    from gui.features.app_manager.rows import QTreeWidgetItem as QTreeWidgetItem
    from gui.features.app_manager.rows import QWidget as QWidget
    from gui.features.app_manager.rows import TreeItemDelegate as TreeItemDelegate
    from gui.features.app_manager.rows import TreeWidget as TreeWidget
    from gui.features.app_manager.rows import cast as cast
    from gui.features.app_manager.rows import refresh_row_description as refresh_row_description
    from gui.features.app_manager.rows import row_metadata as row_metadata
    from gui.features.app_manager.rows import row_status as row_status
    from gui.features.app_manager.rows import tr as tr

sys.modules[__name__] = _implementation
