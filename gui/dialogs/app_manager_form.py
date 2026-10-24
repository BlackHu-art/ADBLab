"""保留旧应用管理模块路径，并与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.app_manager import form as _implementation

if TYPE_CHECKING:
    from gui.features.app_manager.form import STATUS_ROLE as STATUS_ROLE
    from gui.features.app_manager.form import AppManagerForm as AppManagerForm
    from gui.features.app_manager.form import AppManagerIconView as AppManagerIconView
    from gui.features.app_manager.form import AppManagerItemDelegate as AppManagerItemDelegate
    from gui.features.app_manager.form import AppManagerMaterial as AppManagerMaterial
    from gui.features.app_manager.form import AppManagerRowDelegate as AppManagerRowDelegate
    from gui.features.app_manager.form import AppManagerStatusLabel as AppManagerStatusLabel
    from gui.features.app_manager.form import AppManagerTableHeader as AppManagerTableHeader
    from gui.features.app_manager.form import BaseStyles as BaseStyles
    from gui.features.app_manager.form import BodyLabel as BodyLabel
    from gui.features.app_manager.form import CaptionLabel as CaptionLabel
    from gui.features.app_manager.form import CardWidget as CardWidget
    from gui.features.app_manager.form import ComboBox as ComboBox
    from gui.features.app_manager.form import CommandBar as CommandBar
    from gui.features.app_manager.form import FontRole as FontRole
    from gui.features.app_manager.form import InfoBadge as InfoBadge
    from gui.features.app_manager.form import InfoLevel as InfoLevel
    from gui.features.app_manager.form import PushButton as PushButton
    from gui.features.app_manager.form import QAbstractScrollArea as QAbstractScrollArea
    from gui.features.app_manager.form import QAction as QAction
    from gui.features.app_manager.form import QFontMetrics as QFontMetrics
    from gui.features.app_manager.form import QFrame as QFrame
    from gui.features.app_manager.form import QGridLayout as QGridLayout
    from gui.features.app_manager.form import QHBoxLayout as QHBoxLayout
    from gui.features.app_manager.form import QHeaderView as QHeaderView
    from gui.features.app_manager.form import QLayout as QLayout
    from gui.features.app_manager.form import QPainter as QPainter
    from gui.features.app_manager.form import QPushButton as QPushButton
    from gui.features.app_manager.form import QSize as QSize
    from gui.features.app_manager.form import QSizePolicy as QSizePolicy
    from gui.features.app_manager.form import QStackedWidget as QStackedWidget
    from gui.features.app_manager.form import QStandardItemModel as QStandardItemModel
    from gui.features.app_manager.form import Qt as Qt
    from gui.features.app_manager.form import QTreeView as QTreeView
    from gui.features.app_manager.form import QVBoxLayout as QVBoxLayout
    from gui.features.app_manager.form import QWidget as QWidget
    from gui.features.app_manager.form import RoundMenu as RoundMenu
    from gui.features.app_manager.form import SearchLineEdit as SearchLineEdit
    from gui.features.app_manager.form import TransparentToolButton as TransparentToolButton
    from gui.features.app_manager.form import TreeItemDelegate as TreeItemDelegate
    from gui.features.app_manager.form import TreeView as TreeView
    from gui.features.app_manager.form import (
        _apply_adaptive_text_heights as _apply_adaptive_text_heights,
    )
    from gui.features.app_manager.form import apply_focus_indicator as apply_focus_indicator
    from gui.features.app_manager.form import apply_label_role as apply_label_role
    from gui.features.app_manager.form import cast as cast
    from gui.features.app_manager.form import configure_combo_menu as configure_combo_menu
    from gui.features.app_manager.form import create_transient_menu as create_transient_menu
    from gui.features.app_manager.form import get_fluent_icon as get_fluent_icon
    from gui.features.app_manager.form import tr as tr
    from gui.features.app_manager.form import use_smooth_scroll as use_smooth_scroll

sys.modules[__name__] = _implementation
