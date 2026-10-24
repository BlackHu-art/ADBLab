"""保留旧应用管理模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.app_manager import details as _implementation

if TYPE_CHECKING:
    from gui.features.app_manager.details import AppDetailsPage as AppDetailsPage
    from gui.features.app_manager.details import AppManagerWorker as AppManagerWorker
    from gui.features.app_manager.details import BaseStyles as BaseStyles
    from gui.features.app_manager.details import BodyLabel as BodyLabel
    from gui.features.app_manager.details import CaptionLabel as CaptionLabel
    from gui.features.app_manager.details import FluentMessageBox as FluentMessageBox
    from gui.features.app_manager.details import FontRole as FontRole
    from gui.features.app_manager.details import ListItemDelegate as ListItemDelegate
    from gui.features.app_manager.details import ListWidget as ListWidget
    from gui.features.app_manager.details import PushButton as PushButton
    from gui.features.app_manager.details import QFontMetrics as QFontMetrics
    from gui.features.app_manager.details import QHBoxLayout as QHBoxLayout
    from gui.features.app_manager.details import QLayout as QLayout
    from gui.features.app_manager.details import QListWidgetItem as QListWidgetItem
    from gui.features.app_manager.details import QSize as QSize
    from gui.features.app_manager.details import QSizePolicy as QSizePolicy
    from gui.features.app_manager.details import Qt as Qt
    from gui.features.app_manager.details import (
        QThreadGroupShutdownTask as QThreadGroupShutdownTask,
    )
    from gui.features.app_manager.details import QTimer as QTimer
    from gui.features.app_manager.details import QVBoxLayout as QVBoxLayout
    from gui.features.app_manager.details import QWidget as QWidget
    from gui.features.app_manager.details import Signal as Signal
    from gui.features.app_manager.details import TabWidget as TabWidget
    from gui.features.app_manager.details import TextEdit as TextEdit
    from gui.features.app_manager.details import ToastLevel as ToastLevel
    from gui.features.app_manager.details import (
        _apply_adaptive_text_heights as _apply_adaptive_text_heights,
    )
    from gui.features.app_manager.details import _PermissionItemDelegate as _PermissionItemDelegate
    from gui.features.app_manager.details import alive_callback as alive_callback
    from gui.features.app_manager.details import apply_label_role as apply_label_role
    from gui.features.app_manager.details import apply_reading_surface as apply_reading_surface
    from gui.features.app_manager.details import cast as cast
    from gui.features.app_manager.details import deque as deque
    from gui.features.app_manager.details import get_fluent_icon as get_fluent_icon
    from gui.features.app_manager.details import html as html
    from gui.features.app_manager.details import is_qobject_alive as is_qobject_alive
    from gui.features.app_manager.details import report_feedback as report_feedback
    from gui.features.app_manager.details import safe_disconnect as safe_disconnect
    from gui.features.app_manager.details import stop_reading_surface as stop_reading_surface
    from gui.features.app_manager.details import tr as tr
    from gui.features.app_manager.details import use_smooth_scroll as use_smooth_scroll

sys.modules[__name__] = _implementation
