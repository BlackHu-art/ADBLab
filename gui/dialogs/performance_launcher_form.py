"""保留旧性能模块路径，与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.performance import form as _implementation

if TYPE_CHECKING:
    from gui.features.performance.form import CONFIG_HINTS as CONFIG_HINTS
    from gui.features.performance.form import MONKEY_PERCENT_FIELDS as MONKEY_PERCENT_FIELDS
    from gui.features.performance.form import BodyLabel as BodyLabel
    from gui.features.performance.form import CheckBox as CheckBox
    from gui.features.performance.form import ContentSection as ContentSection
    from gui.features.performance.form import FluentMessageBox as FluentMessageBox
    from gui.features.performance.form import FontRole as FontRole
    from gui.features.performance.form import HeaderCardWidget as HeaderCardWidget
    from gui.features.performance.form import InfoBadge as InfoBadge
    from gui.features.performance.form import LineEdit as LineEdit
    from gui.features.performance.form import MobilePerfMonkeyConfig as MobilePerfMonkeyConfig
    from gui.features.performance.form import PerformanceLauncherForm as PerformanceLauncherForm
    from gui.features.performance.form import PerformanceProgress as PerformanceProgress
    from gui.features.performance.form import PlainTextEdit as PlainTextEdit
    from gui.features.performance.form import PrimaryPushButton as PrimaryPushButton
    from gui.features.performance.form import PushButton as PushButton
    from gui.features.performance.form import QAbstractButton as QAbstractButton
    from gui.features.performance.form import QAbstractScrollArea as QAbstractScrollArea
    from gui.features.performance.form import QAction as QAction
    from gui.features.performance.form import QBoxLayout as QBoxLayout
    from gui.features.performance.form import QButtonGroup as QButtonGroup
    from gui.features.performance.form import QEvent as QEvent
    from gui.features.performance.form import QFrame as QFrame
    from gui.features.performance.form import QGridLayout as QGridLayout
    from gui.features.performance.form import QHBoxLayout as QHBoxLayout
    from gui.features.performance.form import QLayout as QLayout
    from gui.features.performance.form import QLineEdit as QLineEdit
    from gui.features.performance.form import QScrollArea as QScrollArea
    from gui.features.performance.form import QSize as QSize
    from gui.features.performance.form import QSizePolicy as QSizePolicy
    from gui.features.performance.form import QStackedWidget as QStackedWidget
    from gui.features.performance.form import Qt as Qt
    from gui.features.performance.form import QTimer as QTimer
    from gui.features.performance.form import QVBoxLayout as QVBoxLayout
    from gui.features.performance.form import QWidget as QWidget
    from gui.features.performance.form import Sequence as Sequence
    from gui.features.performance.form import Signal as Signal
    from gui.features.performance.form import SmoothScrollArea as SmoothScrollArea
    from gui.features.performance.form import StrictIntComboBox as StrictIntComboBox
    from gui.features.performance.form import StrictIntLineEdit as StrictIntLineEdit
    from gui.features.performance.form import TogglePushButton as TogglePushButton
    from gui.features.performance.form import _PerformanceActionCard as _PerformanceActionCard
    from gui.features.performance.form import _PerformanceField as _PerformanceField
    from gui.features.performance.form import _PerformanceGrid as _PerformanceGrid
    from gui.features.performance.form import _PerformanceResultStack as _PerformanceResultStack
    from gui.features.performance.form import _PerformanceRow as _PerformanceRow
    from gui.features.performance.form import _PerformanceViewToggle as _PerformanceViewToggle
    from gui.features.performance.form import apply_label_role as apply_label_role
    from gui.features.performance.form import configure_button as configure_button
    from gui.features.performance.form import get_fluent_icon as get_fluent_icon
    from gui.features.performance.form import get_themed_icon as get_themed_icon
    from gui.features.performance.form import tr as tr
    from gui.features.performance.form import use_smooth_scroll as use_smooth_scroll

sys.modules[__name__] = _implementation
