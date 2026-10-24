"""保留旧应用管理模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.app_manager import batch as _implementation

if TYPE_CHECKING:
    from gui.features.app_manager.batch import AppManagerBatch as AppManagerBatch
    from gui.features.app_manager.batch import AppSettings as AppSettings
    from gui.features.app_manager.batch import BaseStyles as BaseStyles
    from gui.features.app_manager.batch import BodyLabel as BodyLabel
    from gui.features.app_manager.batch import FluentDialog as FluentDialog
    from gui.features.app_manager.batch import FluentMessageBox as FluentMessageBox
    from gui.features.app_manager.batch import FontRole as FontRole
    from gui.features.app_manager.batch import LineEdit as LineEdit
    from gui.features.app_manager.batch import PrimaryPushButton as PrimaryPushButton
    from gui.features.app_manager.batch import PushButton as PushButton
    from gui.features.app_manager.batch import QFileDialog as QFileDialog
    from gui.features.app_manager.batch import QHBoxLayout as QHBoxLayout
    from gui.features.app_manager.batch import Qt as Qt
    from gui.features.app_manager.batch import QVBoxLayout as QVBoxLayout
    from gui.features.app_manager.batch import TextEdit as TextEdit
    from gui.features.app_manager.batch import add_menu_action as add_menu_action
    from gui.features.app_manager.batch import alive_callback as alive_callback
    from gui.features.app_manager.batch import (
        alive_forwarding_callback as alive_forwarding_callback,
    )
    from gui.features.app_manager.batch import apply_label_role as apply_label_role
    from gui.features.app_manager.batch import atomic_write_text as atomic_write_text
    from gui.features.app_manager.batch import configure_button as configure_button
    from gui.features.app_manager.batch import (
        fit_secondary_window_to_owner_screen as fit_secondary_window_to_owner_screen,
    )
    from gui.features.app_manager.batch import is_qobject_alive as is_qobject_alive
    from gui.features.app_manager.batch import json as json
    from gui.features.app_manager.batch import tr as tr
    from gui.features.app_manager.batch import use_smooth_scroll as use_smooth_scroll

sys.modules[__name__] = _implementation
