"""保留旧应用管理模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.app_manager import views as _implementation

if TYPE_CHECKING:
    from gui.features.app_manager.views import STATUS_ROLE as STATUS_ROLE
    from gui.features.app_manager.views import VERSION_ROLE as VERSION_ROLE
    from gui.features.app_manager.views import AppManagerViews as AppManagerViews
    from gui.features.app_manager.views import BaseStyles as BaseStyles
    from gui.features.app_manager.views import FontRole as FontRole
    from gui.features.app_manager.views import Generator as Generator
    from gui.features.app_manager.views import Iterator as Iterator
    from gui.features.app_manager.views import QColor as QColor
    from gui.features.app_manager.views import QFont as QFont
    from gui.features.app_manager.views import QIcon as QIcon
    from gui.features.app_manager.views import QModelIndex as QModelIndex
    from gui.features.app_manager.views import QObject as QObject
    from gui.features.app_manager.views import QPainter as QPainter
    from gui.features.app_manager.views import QPixmap as QPixmap
    from gui.features.app_manager.views import QPoint as QPoint
    from gui.features.app_manager.views import QStandardItem as QStandardItem
    from gui.features.app_manager.views import Qt as Qt
    from gui.features.app_manager.views import QTimer as QTimer
    from gui.features.app_manager.views import QTreeView as QTreeView
    from gui.features.app_manager.views import QTreeWidgetItem as QTreeWidgetItem
    from gui.features.app_manager.views import _icon_font as _icon_font
    from gui.features.app_manager.views import _painted_icon as _painted_icon
    from gui.features.app_manager.views import _visible_row_indexes as _visible_row_indexes
    from gui.features.app_manager.views import add_menu_action as add_menu_action
    from gui.features.app_manager.views import alive_callback as alive_callback
    from gui.features.app_manager.views import (
        alive_forwarding_callback as alive_forwarding_callback,
    )
    from gui.features.app_manager.views import get_fluent_icon as get_fluent_icon
    from gui.features.app_manager.views import is_qobject_alive as is_qobject_alive
    from gui.features.app_manager.views import lru_cache as lru_cache
    from gui.features.app_manager.views import perf_counter as perf_counter
    from gui.features.app_manager.views import refresh_row_description as refresh_row_description
    from gui.features.app_manager.views import tr as tr
    from gui.features.app_manager.views import weakref as weakref

sys.modules[__name__] = _implementation
