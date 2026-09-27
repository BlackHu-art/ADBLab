"""验证 Monkey 与应用管理的共享边界及重排中的输入和查询状态。"""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QSignalSpy

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.test_dialog_languages import dialog_language as dialog_language
from tests.test_monkey_preparation import _success
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _show_feature_panel,
)
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    assert_scroll_target_reachable,
    mapped_rect,
    wait_until,
)

pytestmark = pytest.mark.ui


@pytest.fixture
def monkey_page(qt_application, monkeypatch):
    """沿用真实滚动页，所有配置读写和设备列表均由现有 helper 隔离。"""
    settings = Mock()
    settings.get.side_effect = lambda _key, default=None: default
    settings.save_directory = "."
    monkeypatch.setattr("core.settings_manager.AppSettings.instance", lambda: settings)
    owners = []

    def show(width=900, font_size=12, font_family="Segoe UI"):
        config = replace(
            BaseStyles.current_font_config(), ui_family=font_family, ui_size=font_size,
        )
        BaseStyles._sync_legacy_values(config)
        typography_manager.apply(config)
        result = _show_feature_panel(
            "apps", width, font_size, qt_application, monkeypatch, patch_font_factory=False,
        )
        owner, apps, scroll, _content = result
        owners.append(owner)
        owner._devices_tab.update_device_list(["demo-a", "demo-b"])
        owner._devices_tab.set_selected_devices(["demo-a", "demo-b"])
        apps.program_edit.setText("com.example.demo")
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        return result

    yield show
    for owner in reversed(owners):
        _close_feature_panel(owner)


@pytest.mark.parametrize("width,font_size", [(900, 12), (900, 22), (420, 22)])
def test_monkey_content_shares_app_management_horizontal_edges(
    monkey_page, width, font_size,
):
    """内部信息与参数不叠加缩进，方案及动作均遵守相同的可用右边界。"""
    _owner, apps, scroll, content = monkey_page(width, font_size)
    app_bounds = mapped_rect(apps.package_action_binding._container_ref(), content)
    for widget in (
        apps.monkey_section.headerLabel, apps.monkey_target_summary,
        apps.monkey_package_info, apps.monkey_parameters_heading,
        apps.monkey_events_label, apps.monkey_run_status,
    ):
        assert mapped_rect(widget, content).left() == app_bounds.left(), (
            widget.objectName(), mapped_rect(widget, content), app_bounds,
        )
    label_rect = mapped_rect(apps.monkey_events_label, content)
    field_rect = mapped_rect(apps.monkey_events, content)
    plan = apps.monkey_parameter_binding.applied_plan
    assert plan is not None
    if plan.mode.paired:
        assert label_rect.right() < field_rect.left()
        assert abs(label_rect.center().y() - field_rect.center().y()) <= 2
    else:
        assert field_rect.left() == app_bounds.left()
        assert label_rect.bottom() < field_rect.top()
    fields = apps.monkey_parameter_binding.widgets()[1::2]
    assert max(mapped_rect(field, content).right() for field in fields) == app_bounds.right()
    preset = apps.monkey_preset_bar
    for control in (preset.combo, preset.load_button, preset.save_button, preset.delete_button):
        assert_contained(control, apps.monkey_parameters_card)
        assert mapped_rect(control, content).right() <= app_bounds.right()
    assert mapped_rect(apps.start_monkey_btn, content).right() == app_bounds.right()
    assert_non_overlapping(
        (apps.monkey_package_card, apps.monkey_parameters_card, apps.monkey_run_actions),
        apps.monkey_section,
    )
    for control in (apps.start_monkey_btn, apps.kill_monkey_btn):
        assert_scroll_target_reachable(scroll, control)


@pytest.mark.parametrize("width", [420, 900])
def test_monkey_footer_keeps_stop_and_start_together_when_they_fit(monkey_page, width):
    """中等宽度先给状态独立一行，两按钮仍相邻靠右，主要操作在最右。"""
    _owner, apps, _scroll, content = monkey_page(width)
    stop = mapped_rect(apps.kill_monkey_btn, content)
    start = mapped_rect(apps.start_monkey_btn, content)
    app_bounds = mapped_rect(apps.package_action_binding._container_ref(), content)
    assert max(stop.top(), start.top()) <= min(stop.bottom(), start.bottom())
    assert stop.right() < start.left()
    assert start.left() - stop.right() <= 17
    assert start.right() == app_bounds.right()
    assert_non_overlapping(
        (apps.monkey_run_status, apps.kill_monkey_btn, apps.start_monkey_btn), content,
    )


@pytest.mark.parametrize("width", [420, 900])
def test_package_query_and_cancel_share_a_stable_slot_and_reject_late_results(
    qt_application, monkey_page, width,
):
    """按钮显隐不会改变摘要行布局，取消后晚到结果也不能启动测试或覆盖新请求。"""
    owner, apps, scroll, _content = monkey_page(width)
    requests = QSignalSpy(apps.monkey_preparation_requested)
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    slot = apps.monkey_prepare_actions
    before = mapped_rect(slot, apps.monkey_package_card)
    summary_before = mapped_rect(apps.monkey_target_summary, apps.monkey_package_card)
    get_button, cancel_button = apps.monkey_get_package_btn, apps.monkey_cancel_prepare_btn

    def assert_stable_slot():
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        assert apps.monkey_get_package_btn is get_button
        assert apps.monkey_cancel_prepare_btn is cancel_button
        assert mapped_rect(slot, apps.monkey_package_card) == before
        assert mapped_rect(apps.monkey_target_summary, apps.monkey_package_card) == summary_before
        visible = cancel_button if apps._monkey_preparation is not None else get_button
        assert visible.isVisibleTo(apps.monkey_package_card)
        assert_contained(visible, slot)

    get_button.click()
    first = apps._monkey_preparation
    get_button.click()
    assert requests.count() == 1 and first is not None
    assert not apps.monkey_events.isEnabled()
    assert_stable_slot()
    cancel_button.click()
    assert first.cancellation.is_cancelled
    assert_stable_slot()
    assert apps.monkey_events.isEnabled()

    get_button.click()
    second = apps._monkey_preparation
    assert requests.count() == 2 and second is not None
    apps.on_monkey_preparation_finished(first.request_id, _success(first))
    assert apps._monkey_preparation is second and starts.count() == 0
    assert_stable_slot()
    apps.on_monkey_preparation_finished(second.request_id, _success(second))
    assert apps._monkey_preparation is None and starts.count() == 0
    assert_stable_slot()
    assert apps.monkey_events.isEnabled()


@pytest.mark.parametrize("language", ["zh_CN", "en_US"])
def test_monkey_reflow_preserves_editor_focus_and_uncommitted_values(
    qt_application, monkey_page, dialog_language, language,
):
    """翻译和宽窄重排保持控件身份及未提交原文，不额外发起包查询。"""
    dialog_language(language)
    owner, apps, scroll, content = monkey_page()
    field = apps.monkey_events
    seed = apps.monkey_seed
    requests = QSignalSpy(apps.monkey_preparation_requested)
    editor_window = field.window()
    editor_window.activateWindow()
    wait_until(qt_application, lambda: qt_application.activeWindow() is editor_window)
    field.setFocus()
    field.setText("123")
    seed.setText("bad")
    wait_until(qt_application, field.hasFocus)
    for width in (420, 292, 900):
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        assert apps.monkey_events is field and apps.monkey_seed is seed
        assert field.hasFocus() and field.text() == "123"
        assert seed.text() == "bad"
        assert requests.count() == 0
        controls = (field, apps.monkey_throttle, apps.start_monkey_btn, apps.kill_monkey_btn)
        assert_non_overlapping(controls, content)
        for control in controls:
            assert_contained(control, content)
        for control in (apps.start_monkey_btn, apps.kill_monkey_btn):
            assert_scroll_target_reachable(scroll, control)


def test_large_font_preset_height_grows_and_recovers_without_overlapping_fields(
    qt_application, monkey_page,
):
    """超宽种子撑开内容时方案仍按视口换行，返回宽窗必须释放新增行高。"""
    owner, apps, scroll, _content = monkey_page(900, 22, "Microsoft YaHei UI")
    apps.monkey_seed_mode.setCurrentIndex(1)
    apps.monkey_seed.setText("2147483647")
    apps.monkey_events.setText("321")
    preset = apps.monkey_preset_bar
    seed = apps.monkey_seed
    field_row = apps.monkey_parameter_binding._container_ref()
    heights = []
    row_heights = []
    for width in (900, 292, 900):
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        assert apps.monkey_preset_bar is preset and apps.monkey_seed is seed
        assert seed.currentText() == "2147483647"
        assert apps.monkey_events.currentText() == "321"
        assert_non_overlapping(
            (apps.monkey_parameters_heading, preset, field_row),
            apps.monkey_parameters_card,
        )
        assert_contained(preset, preset.parentWidget())
        assert preset.height() >= preset.heightForWidth(preset.width())
        for control in (preset.combo, preset.load_button, preset.save_button, preset.delete_button):
            assert_contained(control, preset)
        heights.append(preset.height())
        row_heights.append(preset.parentWidget().height())
    assert heights[1] > heights[0]
    assert heights[2] == heights[0]
    assert row_heights[1] > row_heights[0]
    assert row_heights[2] == row_heights[0]
