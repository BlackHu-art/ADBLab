"""保留旧文件浏览器模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.file_explorer import ops as _implementation

if TYPE_CHECKING:
    from gui.features.file_explorer.ops import BodyLabel as BodyLabel
    from gui.features.file_explorer.ops import CheckBox as CheckBox
    from gui.features.file_explorer.ops import FileExplorerOps as FileExplorerOps
    from gui.features.file_explorer.ops import FluentDialog as FluentDialog
    from gui.features.file_explorer.ops import FluentInputDialog as FluentInputDialog
    from gui.features.file_explorer.ops import FluentMessageBox as FluentMessageBox
    from gui.features.file_explorer.ops import FontRole as FontRole
    from gui.features.file_explorer.ops import LocalTextSaveWorker as LocalTextSaveWorker
    from gui.features.file_explorer.ops import LogService as LogService
    from gui.features.file_explorer.ops import PushButton as PushButton
    from gui.features.file_explorer.ops import QFileDialog as QFileDialog
    from gui.features.file_explorer.ops import QGridLayout as QGridLayout
    from gui.features.file_explorer.ops import QHBoxLayout as QHBoxLayout
    from gui.features.file_explorer.ops import QSize as QSize
    from gui.features.file_explorer.ops import Qt as Qt
    from gui.features.file_explorer.ops import QVBoxLayout as QVBoxLayout
    from gui.features.file_explorer.ops import TextSaveWorker as TextSaveWorker
    from gui.features.file_explorer.ops import apply_label_role as apply_label_role
    from gui.features.file_explorer.ops import default_save_path as default_save_path
    from gui.features.file_explorer.ops import explorer_service as explorer_service
    from gui.features.file_explorer.ops import (
        fit_secondary_window_to_owner_screen as fit_secondary_window_to_owner_screen,
    )
    from gui.features.file_explorer.ops import get_themed_icon as get_themed_icon
    from gui.features.file_explorer.ops import local_child_path as local_child_path
    from gui.features.file_explorer.ops import os as os
    from gui.features.file_explorer.ops import report_feedback as report_feedback
    from gui.features.file_explorer.ops import safe_disconnect as safe_disconnect
    from gui.features.file_explorer.ops import tr as tr
    from gui.features.file_explorer.ops import uuid as uuid

sys.modules[__name__] = _implementation
