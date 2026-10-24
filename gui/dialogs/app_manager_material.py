"""保留旧应用管理模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.app_manager import material as _implementation

if TYPE_CHECKING:
    from gui.features.app_manager.material import AppManagerMaterial as AppManagerMaterial
    from gui.features.app_manager.material import BaseStyles as BaseStyles
    from gui.features.app_manager.material import Iterable as Iterable
    from gui.features.app_manager.material import QAbstractItemView as QAbstractItemView
    from gui.features.app_manager.material import QColor as QColor
    from gui.features.app_manager.material import QEvent as QEvent
    from gui.features.app_manager.material import QObject as QObject
    from gui.features.app_manager.material import QPalette as QPalette
    from gui.features.app_manager.material import QTreeView as QTreeView
    from gui.features.app_manager.material import QWidget as QWidget
    from gui.features.app_manager.material import annotations as annotations
    from gui.features.app_manager.material import isValid as isValid
    from gui.features.app_manager.material import safe_disconnect as safe_disconnect
    from gui.features.app_manager.material import setCustomStyleSheet as setCustomStyleSheet
    from gui.features.app_manager.material import weakref as weakref

sys.modules[__name__] = _implementation
