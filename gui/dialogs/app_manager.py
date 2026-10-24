"""保留旧应用管理模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.app_manager import page as _implementation

if TYPE_CHECKING:
    from gui.features.app_manager.page import AppDetailsPage as AppDetailsPage
    from gui.features.app_manager.page import AppManagerBatch as AppManagerBatch
    from gui.features.app_manager.page import AppManagerForm as AppManagerForm
    from gui.features.app_manager.page import AppManagerIcons as AppManagerIcons
    from gui.features.app_manager.page import AppManagerPage as AppManagerPage
    from gui.features.app_manager.page import AppManagerViews as AppManagerViews
    from gui.features.app_manager.page import AppManagerWorker as AppManagerWorker
    from gui.features.app_manager.page import AppSortProxy as AppSortProxy
    from gui.features.app_manager.page import BaseStyles as BaseStyles
    from gui.features.app_manager.page import CaptionLabel as CaptionLabel
    from gui.features.app_manager.page import QSize as QSize
    from gui.features.app_manager.page import QSizePolicy as QSizePolicy
    from gui.features.app_manager.page import QSortFilterProxyModel as QSortFilterProxyModel
    from gui.features.app_manager.page import QSplitter as QSplitter
    from gui.features.app_manager.page import Qt as Qt
    from gui.features.app_manager.page import QThreadGroupShutdownTask as QThreadGroupShutdownTask
    from gui.features.app_manager.page import QTimer as QTimer
    from gui.features.app_manager.page import QVBoxLayout as QVBoxLayout
    from gui.features.app_manager.page import QWidget as QWidget
    from gui.features.app_manager.page import Signal as Signal
    from gui.features.app_manager.page import ToastLevel as ToastLevel
    from gui.features.app_manager.page import cast as cast
    from gui.features.app_manager.page import is_qobject_alive as is_qobject_alive
    from gui.features.app_manager.page import report_feedback as report_feedback
    from gui.features.app_manager.page import safe_disconnect as safe_disconnect
    from gui.features.app_manager.page import tr as tr

sys.modules[__name__] = _implementation
