"""保留旧性能模块路径，与功能包共享实现及替换点。"""

import sys
from typing import TYPE_CHECKING

from gui.features.performance import page as _implementation

if TYPE_CHECKING:
    from gui.features.performance.page import CONFIG_HINTS as CONFIG_HINTS
    from gui.features.performance.page import MONKEY_PERCENT_FIELDS as MONKEY_PERCENT_FIELDS
    from gui.features.performance.page import AppSettings as AppSettings
    from gui.features.performance.page import BaseStyles as BaseStyles
    from gui.features.performance.page import BodyLabel as BodyLabel
    from gui.features.performance.page import ContentSection as ContentSection
    from gui.features.performance.page import CurrentPackageWorker as CurrentPackageWorker
    from gui.features.performance.page import FluentMessageBox as FluentMessageBox
    from gui.features.performance.page import FontRole as FontRole
    from gui.features.performance.page import HeaderCardWidget as HeaderCardWidget
    from gui.features.performance.page import InfoBadge as InfoBadge
    from gui.features.performance.page import InfoLevel as InfoLevel
    from gui.features.performance.page import MobilePerfRunConfig as MobilePerfRunConfig
    from gui.features.performance.page import MobilePerfRunner as MobilePerfRunner
    from gui.features.performance.page import PerformanceLauncherForm as PerformanceLauncherForm
    from gui.features.performance.page import PerformanceLauncherLog as PerformanceLauncherLog
    from gui.features.performance.page import PerformanceLauncherRun as PerformanceLauncherRun
    from gui.features.performance.page import PerformanceLibrary as PerformanceLibrary
    from gui.features.performance.page import PerformancePage as PerformancePage
    from gui.features.performance.page import PerformanceProgress as PerformanceProgress
    from gui.features.performance.page import PerformanceSnapshot as PerformanceSnapshot
    from gui.features.performance.page import ProgressBar as ProgressBar
    from gui.features.performance.page import PushButton as PushButton
    from gui.features.performance.page import QAction as QAction
    from gui.features.performance.page import QCheckBox as QCheckBox
    from gui.features.performance.page import QDesktopServices as QDesktopServices
    from gui.features.performance.page import QFileDialog as QFileDialog
    from gui.features.performance.page import QFontMetrics as QFontMetrics
    from gui.features.performance.page import QLineEdit as QLineEdit
    from gui.features.performance.page import QPlainTextEdit as QPlainTextEdit
    from gui.features.performance.page import QPushButton as QPushButton
    from gui.features.performance.page import QStackedWidget as QStackedWidget
    from gui.features.performance.page import Qt as Qt
    from gui.features.performance.page import QThread as QThread
    from gui.features.performance.page import QThreadGroupShutdownTask as QThreadGroupShutdownTask
    from gui.features.performance.page import QTimer as QTimer
    from gui.features.performance.page import QUrl as QUrl
    from gui.features.performance.page import QWidget as QWidget
    from gui.features.performance.page import RunPresetBar as RunPresetBar
    from gui.features.performance.page import Signal as Signal
    from gui.features.performance.page import StrictIntComboBox as StrictIntComboBox
    from gui.features.performance.page import StrictIntLineEdit as StrictIntLineEdit
    from gui.features.performance.page import ThreadedShutdownTask as ThreadedShutdownTask
    from gui.features.performance.page import alive_callback as alive_callback
    from gui.features.performance.page import detect_current_package as detect_current_package
    from gui.features.performance.page import get_fluent_icon as get_fluent_icon
    from gui.features.performance.page import get_themed_icon as get_themed_icon
    from gui.features.performance.page import is_qobject_alive as is_qobject_alive
    from gui.features.performance.page import os as os
    from gui.features.performance.page import re as re
    from gui.features.performance.page import safe_disconnect as safe_disconnect
    from gui.features.performance.page import stop_reading_surface as stop_reading_surface
    from gui.features.performance.page import threading as threading
    from gui.features.performance.page import time as time
    from gui.features.performance.page import tr as tr

sys.modules[__name__] = _implementation
