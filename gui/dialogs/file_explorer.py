"""保留旧文件浏览器模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.file_explorer import page as _implementation

if TYPE_CHECKING:
    from gui.features.file_explorer.page import ADBWorker as ADBWorker
    from gui.features.file_explorer.page import BaseStyles as BaseStyles
    from gui.features.file_explorer.page import BodyLabel as BodyLabel
    from gui.features.file_explorer.page import CaptionLabel as CaptionLabel
    from gui.features.file_explorer.page import CardWidget as CardWidget
    from gui.features.file_explorer.page import CheckBox as CheckBox
    from gui.features.file_explorer.page import CommandBar as CommandBar
    from gui.features.file_explorer.page import FileExplorerImagePreview as FileExplorerImagePreview
    from gui.features.file_explorer.page import FileExplorerItemDelegate as FileExplorerItemDelegate
    from gui.features.file_explorer.page import FileExplorerList as FileExplorerList
    from gui.features.file_explorer.page import FileExplorerOps as FileExplorerOps
    from gui.features.file_explorer.page import FileExplorerPage as FileExplorerPage
    from gui.features.file_explorer.page import FileExplorerView as FileExplorerView
    from gui.features.file_explorer.page import FileTransferCoordinator as FileTransferCoordinator
    from gui.features.file_explorer.page import FluentMessageBox as FluentMessageBox
    from gui.features.file_explorer.page import FontRole as FontRole
    from gui.features.file_explorer.page import InfoBadge as InfoBadge
    from gui.features.file_explorer.page import InfoLevel as InfoLevel
    from gui.features.file_explorer.page import LineEdit as LineEdit
    from gui.features.file_explorer.page import PlainTextEdit as PlainTextEdit
    from gui.features.file_explorer.page import PushButton as PushButton
    from gui.features.file_explorer.page import QAction as QAction
    from gui.features.file_explorer.page import QFrame as QFrame
    from gui.features.file_explorer.page import QGridLayout as QGridLayout
    from gui.features.file_explorer.page import QHBoxLayout as QHBoxLayout
    from gui.features.file_explorer.page import QHeaderView as QHeaderView
    from gui.features.file_explorer.page import QPainter as QPainter
    from gui.features.file_explorer.page import QSize as QSize
    from gui.features.file_explorer.page import QSizePolicy as QSizePolicy
    from gui.features.file_explorer.page import QSplitter as QSplitter
    from gui.features.file_explorer.page import QStackedWidget as QStackedWidget
    from gui.features.file_explorer.page import Qt as Qt
    from gui.features.file_explorer.page import QTimer as QTimer
    from gui.features.file_explorer.page import QVBoxLayout as QVBoxLayout
    from gui.features.file_explorer.page import QWidget as QWidget
    from gui.features.file_explorer.page import RoundMenu as RoundMenu
    from gui.features.file_explorer.page import SearchLineEdit as SearchLineEdit
    from gui.features.file_explorer.page import Signal as Signal
    from gui.features.file_explorer.page import TableWidget as TableWidget
    from gui.features.file_explorer.page import TransferWorker as TransferWorker
    from gui.features.file_explorer.page import TransparentToolButton as TransparentToolButton
    from gui.features.file_explorer.page import __all__ as __all__
    from gui.features.file_explorer.page import _FileExplorerStatusLabel as _FileExplorerStatusLabel
    from gui.features.file_explorer.page import add_menu_action as add_menu_action
    from gui.features.file_explorer.page import alive_callback as alive_callback
    from gui.features.file_explorer.page import apply_focus_indicator as apply_focus_indicator
    from gui.features.file_explorer.page import apply_font_role as apply_font_role
    from gui.features.file_explorer.page import apply_label_role as apply_label_role
    from gui.features.file_explorer.page import apply_reading_surface as apply_reading_surface
    from gui.features.file_explorer.page import create_transient_menu as create_transient_menu
    from gui.features.file_explorer.page import explorer_service as explorer_service
    from gui.features.file_explorer.page import file_explorer_icon as file_explorer_icon
    from gui.features.file_explorer.page import is_qobject_alive as is_qobject_alive
    from gui.features.file_explorer.page import safe_disconnect as safe_disconnect
    from gui.features.file_explorer.page import stop_reading_surface as stop_reading_surface
    from gui.features.file_explorer.page import tr as tr
    from gui.features.file_explorer.page import use_smooth_scroll as use_smooth_scroll
    from gui.features.file_explorer.page import weakref as weakref

sys.modules[__name__] = _implementation
