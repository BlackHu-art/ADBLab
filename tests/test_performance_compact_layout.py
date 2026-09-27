"""验证性能页紧凑工具行的真实几何、重排及配置锁定契约。"""

import pytest
from PySide6.QtTest import QSignalSpy
from qfluentwidgets import TogglePushButton

from gui.i18n import tr
from gui.styles import BaseStyles
from gui.widgets.content_section import ContentSection
from tests.test_dialog_languages import dialog_language as dialog_language
from tests.test_performance_library import _Library
from tests.test_performance_responsive import (
    _build_performance_page,
    _editor,
    isolated_performance_settings,  # noqa: F401  复用隔离配置，避免访问真实用户设置。
)
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    assert_scroll_target_reachable,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)

pytestmark = pytest.mark.ui


def _result_controls(page):
    """定位既有功能按钮，不要求实现新增特定容器或私有字段。"""
    toggles = {button.text(): button for button in page.findChildren(TogglePushButton)}
    return toggles[tr("日志")], toggles[tr("图表")], page.result_btn, page.perfetto_btn


def _preset_controls(page):
    bar = page.run_preset_bar
    return bar.combo, bar.load_button, bar.save_button, bar.delete_button


def _assert_same_row(widgets, ancestor):
    rectangles = tuple(mapped_rect(widget, ancestor) for widget in widgets)
    assert max(rect.top() for rect in rectangles) <= min(rect.bottom() for rect in rectangles), (
        f"expected one visual row, got {rectangles!r}"
    )
    assert_non_overlapping(widgets, ancestor)


def _show(page, app, width):
    library = _Library()
    parameters = page.capture_run_parameters()
    assert parameters is not None
    library.save_preset("布局回归方案", "performance", parameters)
    page.set_run_library(library)
    page.run_preset_bar.combo.setCurrentIndex(1)
    page.resize(width, 900)
    page.run_preset_bar.show()
    page.show()
    wait_until(app, lambda: page.isVisible() and page.run_preset_bar.isVisibleTo(page))
    wait_for_stable_geometry(app, (page, page._config_group, page.run_preset_bar))


@pytest.mark.parametrize("width,font_size", [(1000, 12), (1200, 22)])
def test_plan_title_and_preset_share_a_row_when_width_is_sufficient(
    qt_application, monkeypatch, width, font_size,
):
    """宽窗合并标题与方案操作，仍为包名等配置保留独立下一行。"""
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    page, _runner = _build_performance_page()
    try:
        _show(page, qt_application, width)
        plan = next(section for section in page.findChildren(ContentSection)
                    if section.headerLabel.text() == tr("采集计划"))
        controls = (plan.headerLabel, *_preset_controls(page))
        assert all(control.isVisibleTo(page) for control in controls)
        _assert_same_row(controls, page._config_group)
        for control in controls:
            assert_contained(control, page._config_group)
        assert max(mapped_rect(control, page._config_group).bottom() for control in controls) < (
            mapped_rect(page.package_edit, page._config_group).top()
        )
    finally:
        page.close()


@pytest.mark.parametrize("font_size", [12, 22])
def test_result_modes_and_actions_share_toolbar_above_current_view(
    qt_application, monkeypatch, font_size,
):
    """日志、图表和结果动作在宽窗同排，切换结果不会把动作留在视图下方。"""
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    page, _runner = _build_performance_page()
    try:
        _show(page, qt_application, 1200)
        controls = _result_controls(page)
        for button, view in ((controls[0], page.log_view), (controls[1], page.chart_view)):
            button.click()
            wait_until(qt_application, lambda: view.isVisibleTo(page))
            wait_for_stable_geometry(qt_application, (page._config_group, view, *controls))
            _assert_same_row(controls, page._config_group)
            assert max(mapped_rect(control, page._config_group).bottom()
                       for control in controls) < mapped_rect(view, page._config_group).top()
    finally:
        page.close()


@pytest.mark.parametrize("width,font_size,language", [
    (420, 12, "zh_CN"), (420, 22, "zh_CN"), (640, 22, "zh_CN"), (1200, 22, "zh_CN"),
    (420, 12, "en_US"), (640, 22, "en_US"), (1200, 22, "en_US"),
])
def test_compact_controls_wrap_without_overlap_or_losing_configuration_lock(
    qt_application, monkeypatch, dialog_language, width, font_size, language,
):
    """窄窗、大字体和长翻译可换行，Monkey 展开与运行锁不破坏控件可达性。"""
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    dialog_language(language)
    page, _runner = _build_performance_page()
    try:
        _show(page, qt_application, width)
        page.monkey_check.setChecked(True)
        controls = (
            *_preset_controls(page), page.package_edit, page.get_package_btn,
            page.frequency_input, page.timeout_input, page.save_path_edit, page.pick_save_btn,
            page.dumpheap_input, page.exception_edit, page.phone_log_edit, page.monkey_check,
            page.monkey_throttle_input, page.monkey_seed_input, *page.monkey_pct_inputs.values(),
            *_result_controls(page), page.start_btn, page.stop_btn,
        )
        wait_for_stable_geometry(qt_application, (page, page._config_group, *controls))
        assert all(control.isEnabled() for control in _preset_controls(page))
        assert page.width() == width
        assert page._config_scroll.horizontalScrollBar().maximum() == 0
        assert_non_overlapping(controls, page._config_group)
        for control in controls:
            assert control.isVisibleTo(page)
            assert_contained(control, page._config_group)
        for control in (page.monkey_seed_input, page.phone_log_edit, *_result_controls(page)):
            assert_scroll_target_reachable(page._config_scroll, control)
        assert max(mapped_rect(control, page._config_group).bottom()
                   for control in _result_controls(page)) < (
            mapped_rect(page.log_view, page._config_group).top()
        )

        page._set_running(True)
        assert all(not control.isEnabled() for control in (
            *_preset_controls(page), page.package_edit, page.frequency_input,
            page.dumpheap_input, page.monkey_check, page.monkey_seed_input,
        ))
        assert not page.start_btn.isEnabled() and page.stop_btn.isEnabled()
        assert page.log_view.isEnabled() and page.perfetto_btn.isEnabled()
        assert all(button.isEnabled() for button in _result_controls(page)[:2])
        page._set_running(False)
        assert all(control.isEnabled() for control in _preset_controls(page))
        assert page.frequency_input.isEnabled() and page.monkey_seed_input.isEnabled()
    finally:
        page._set_running(False)
        page.close()


def test_compact_reflow_preserves_editor_focus_uncommitted_values_and_signal_count(
    qt_application,
):
    """往返窄宽布局不重建输入、不提交原文，运行锁恢复后仍保留非法高级参数。"""
    page, _runner = _build_performance_page()
    field = page.frequency_input
    editor = _editor(field)
    committed = QSignalSpy(field.valueChanged)
    seed = page.monkey_seed_input
    try:
        _show(page, qt_application, 1200)
        page.monkey_check.setChecked(True)
        seed.setText("bad")
        page.activateWindow()
        field.focus_editor()
        editor.setText("7")
        wait_until(qt_application, editor.hasFocus)
        for width in (420, 1200, 640, 1200):
            page.resize(width, 900)
            wait_for_stable_geometry(qt_application, (page, page._config_group, field))
            assert page.frequency_input is field and _editor(field) is editor
            assert editor.hasFocus() and editor.text() == "7"
            assert page.monkey_seed_input is seed and seed.text() == "bad"
            assert committed.count() == 0
        assert field.commit_value()
        assert field.value() == 7 and committed.count() == 1
        page._set_running(True)
        page.resize(420, 900)
        wait_for_stable_geometry(qt_application, (page, page._config_group))
        assert not seed.isEnabled() and page.stop_btn.isEnabled()
        page._set_running(False)
        assert seed.isEnabled() and seed.text() == "bad"
    finally:
        page._set_running(False)
        page.close()
