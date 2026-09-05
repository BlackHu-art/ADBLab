import os
import sys
from builtins import ExceptionGroup
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from gui.styles import BaseStyles
from gui.styles.fonts import _font
from gui.styles.typography import typography_manager

_APPLICATION_REFERENCES = []


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """在整个测试进程中保留同一个 QApplication 包装对象。"""
    application = QApplication.instance() or QApplication([])
    if sys.platform == "win32" and not QFontDatabase.families():
        # Windows 离屏插件不枚举系统字体；显式加载系统现有字体，
        # 让文字尺寸与视觉测试使用真实字形，而不是方框占位。
        font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
            font_path = font_directory / filename
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
    _APPLICATION_REFERENCES.append(application)
    yield application


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

    cleanup_errors = []
    for window in set(qt_application.topLevelWidgets()) - initial_windows:
        if not isValid(window):
            continue
        try:
            initial_timers = window.findChildren(QTimer)
            timer_was_active = any(timer.isActive() for timer in initial_timers)
            for timer in initial_timers:
                if timer.isActive():
                    timer.stop()
            shutdown = getattr(window, "shutdown", None)
            if callable(shutdown):
                shutdown()
            if not isValid(window):
                continue
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
        except Exception as error:
            # 活对象的清理失败必须报告；先继续释放其它窗口，避免污染下个用例。
            cleanup_errors.append(error)
        finally:
            # close 不代表 QObject 已释放；失败及已关闭窗口也必须完成释放。
            if isValid(window):
                window.deleteLater()
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
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if cleanup_errors:
        raise ExceptionGroup("UI window cleanup failed", cleanup_errors)


# 测试分层 marker 映射（ADR-0003 Phase 0）：集中登记，避免在几十个文件里散落 pytestmark。
# 新增 UI 类或探针类测试文件时，在这里同步登记并更新 TESTING_GUIDE 的 marker 说明。
_UI_TEST_FILES = frozenset(
    {
        "test_file_app_device_admission.py",
        "test_session_device_admission.py",
        "test_shell_workflows.py",
        "test_live_logcat_visual.py",
    "test_file_explorer_visual.py",
        "test_monkey_preparation.py",
        "test_flat_feature_navigation.py",
        "test_device_hub_page.py",
        "test_global_device_context.py",
        "test_device_context_bar_presentation.py",
        "test_content_section.py",
        "test_category_scroll_range.py",
        "test_settings_typography.py",
        "test_system_input_widths.py",
        "test_app_manager_visual.py",
        "test_app_manager_icons.py",
        "test_workspace_consolidation.py",
        "test_accessibility_contract.py",
        "test_adaptive_category_stack.py",
        "test_adaptive_navigation.py",
        "test_app_panel_categories.py",
        "test_app_manager_selection.py",
        "test_button_tooltips.py",
        "test_feature_typography.py",
        "test_fluent_components.py",
        "test_fluent_dialog_contract.py",
        "test_main_window_layout.py",
        # test_model_execution.py 已按主题拆分为以下文件（ADR-0003 Phase 2）。
        # runner/parser/配置类按本地测试选择需求独立保留，不由此假定 CI 门禁。
        "test_model_apps.py",
        "test_model_media_adb.py",
        "test_model_meta.py",
        "test_model_mainframe.py",
        "test_model_panels.py",
        "test_model_performance_launcher.py",
        "test_navbar.py",
        "test_navigation_rendering.py",
        "test_panel_typography.py",
        "test_page_layout.py",
        "test_perf_chart_data.py",
        "test_performance_responsive.py",
        "test_responsive_layout_controller.py",
        "test_responsive_panels.py",
        "test_responsive_row_height.py",
        "test_screenshot_page.py",
        "test_system_panel_categories.py",
        "test_task_center.py",
        "test_typography_core.py",
        "test_ui_geometry_helpers.py",
        "test_window_lifecycle.py",
        "test_workspace_feature_host.py",
        "test_workspace_device_recovery.py",
        "test_workspace_route_payload.py",
        # 以下文件 import 并实例化 GUI（2026-08-28 基线核实补登，避免漏出 ui 子集）。
        "test_logging_contract.py",
        "test_logging_routing_mobileperf.py",
        "test_model_processes.py",
        "test_phase0_remote_mobileperf.py",
        "test_phase2_live_logcat_gate.py",
        "test_phase2_mainframe_shutdown_gate.py",
        "test_remote_services.py",
    }
)

_INTEGRATION_TEST_FILES = frozenset(
    {
        "test_gui_bootstrap.py",
        "test_mobileperf_runner_concurrency.py",
        "test_ui_dpi_matrix.py",
        "test_test_collection.py",
    }
)

# 混合模块按真实 Qt 用例登记，保留同文件纯 Operation 契约的快速选择范围。
_UI_TEST_FUNCTIONS = {
    "test_app_icons_service.py": frozenset(
        {
            "test_icon_worker_dispatches_packages_and_relays_png",
            "test_icon_worker_aborted_before_start_has_no_device_work",
            "test_icon_worker_runs_in_background_and_abort_reaches_service",
        }
    ),
    "test_phase1_operations.py": frozenset(
        {
            "test_async_command_keeps_signal_signature_and_strips_reserved_operation_kwargs",
            "test_async_command_carries_manager_generation_without_forwarding_it_to_model_method",
            "test_async_command_carries_owner_token_without_forwarding_it_to_model_method",
            "test_async_command_reports_business_runtime_error_with_same_operation_metadata",
            "test_async_command_long_running_routes_to_long_pool",
            "test_command_task_runs_in_real_thread_pool_and_emits_finished",
        }
    )
}


def pytest_collection_modifyitems(config, items):
    """为本地选择标记 ui / integration；unit 尚未系统分配，其余保持默认。"""
    for item in items:
        function_name = getattr(item, "originalname", item.name)
        if item.path.name in _UI_TEST_FILES or function_name in _UI_TEST_FUNCTIONS.get(
            item.path.name, ()
        ):
            item.add_marker(pytest.mark.ui)
        elif item.path.name in _INTEGRATION_TEST_FILES:
            item.add_marker(pytest.mark.integration)
