import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from gui.styles import BaseStyles
from gui.styles.fonts import _font
from gui.styles.typography import typography_manager

_APPLICATION_REFERENCES = []


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """在整个测试进程中保留同一个 QApplication 包装对象。"""
    application = QApplication.instance() or QApplication([])
    _APPLICATION_REFERENCES.append(application)
    yield application


@pytest.fixture(autouse=True)
def drain_qt_deferred_deletes(qt_application):
    """保留兼容夹具名称；窗口清理由 isolated_ui_state 按安全边界处理。"""
    yield


@pytest.fixture
def isolated_ui_state_probe():
    """为隔离夹具提供可重复的 teardown 断言入口。"""

    probe = {"assertions": [], "cleanup": {}}
    yield probe
    for assertion in probe["assertions"]:
        assertion(probe)


@pytest.fixture(autouse=True)
def isolated_ui_state(qt_application, isolated_ui_state_probe):
    """恢复每个用例改动过的全局 UI 状态并清理其顶层窗口。"""

    initial_theme = BaseStyles.current_theme()
    initial_font = QFont(qt_application.font())
    initial_font_config = BaseStyles.current_font_config()
    initial_windows = set(qt_application.topLevelWidgets())
    initial_font_state = {
        name: getattr(BaseStyles, name)
        for name in (
            "DEFAULT_FONT_FAMILY",
            "DEFAULT_FONT_SIZE",
            "LOG_FONT",
            "LOG_FONT_SIZE",
            "LOG_FONT_SIZE_VAR",
        )
    }
    initial_font_projection = dict(_font)
    yield

    for window in set(qt_application.topLevelWidgets()) - initial_windows:
        try:
            initial_timers = window.findChildren(QTimer)
            timer_was_active = any(timer.isActive() for timer in initial_timers)
            for timer in initial_timers:
                if timer.isActive():
                    timer.stop()
            shutdown = getattr(window, "shutdown", None)
            if callable(shutdown):
                shutdown()
            post_shutdown_timers = window.findChildren(QTimer)
            post_shutdown_timer_was_active = any(
                timer.isActive() for timer in post_shutdown_timers
            )
            for timer in post_shutdown_timers:
                if timer.isActive():
                    timer.stop()
            isolated_ui_state_probe["cleanup"][id(window)] = {
                "post_shutdown_timer_was_active": post_shutdown_timer_was_active,
                "timer_stopped": all(not timer.isActive() for timer in post_shutdown_timers),
                "timer_was_active": timer_was_active,
            }
            if window.isVisible():
                window.close()
                window.deleteLater()
        except RuntimeError:
            continue
    if BaseStyles.current_font_config() != initial_font_config:
        BaseStyles._sync_legacy_values(initial_font_config)
        typography_manager.apply(initial_font_config)
    for name, value in initial_font_state.items():
        setattr(BaseStyles, name, value)
    _font.clear()
    _font.update(initial_font_projection)
    if BaseStyles.current_theme() != initial_theme:
        BaseStyles.switch_theme(initial_theme)
    if qt_application.font() != initial_font:
        qt_application.setFont(initial_font)


# 测试分层 marker 映射（ADR-0003 Phase 0）：集中登记，避免在几十个文件里散落 pytestmark。
# 新增 UI 类或探针类测试文件时，在这里同步登记并更新 TESTING_GUIDE 的 marker 说明。
_UI_TEST_FILES = frozenset(
    {
        "test_accessibility_contract.py",
        "test_app_manager_selection.py",
        "test_button_tooltips.py",
        "test_dialog_typography.py",
        "test_main_window_layout.py",
        # test_model_execution.py 为混合大文件；Phase 2 拆分后按主题重新归类。
        "test_model_execution.py",
        "test_panel_typography.py",
        "test_performance_responsive.py",
        "test_preset_spin_box.py",
        "test_responsive_layout_controller.py",
        "test_responsive_panels.py",
        "test_settings_typography.py",
        "test_settings_window_layout.py",
        "test_typography_core.py",
        "test_ui_geometry_helpers.py",
        "test_window_lifecycle.py",
    }
)

_INTEGRATION_TEST_FILES = frozenset(
    {
        "test_mobileperf_runner_concurrency.py",
        "test_ui_dpi_matrix.py",
    }
)


def pytest_collection_modifyitems(config, items):
    """按文件把测试标记为 ui / integration，其余保持默认（计入快速子集）。"""
    for item in items:
        if item.path.name in _UI_TEST_FILES:
            item.add_marker(pytest.mark.ui)
        elif item.path.name in _INTEGRATION_TEST_FILES:
            item.add_marker(pytest.mark.integration)
