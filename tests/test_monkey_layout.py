"""验证 Monkey 分区的信息层级、任务状态与宽窄布局。"""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QSignalSpy, QTest
from qfluentwidgets import PrimaryPushButton

from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from tests.test_monkey_preparation import _success
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _show_feature_panel,
)
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    mapped_rect,
)


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_monkey_inner_sections_share_page_surface_in_hover_and_disabled_states(
    qt_application, monkeypatch, theme,
):
    """嵌套分区在悬停和禁用时也不能重新绘制底板，输入仍保留交互底色。"""

    BaseStyles.switch_theme(theme)
    owner, apps, _scroll, _content = _show_feature_panel(
        "apps", 960, 12, qt_application, monkeypatch,
    )
    section = apps.monkey_section
    blocks = (apps.monkey_package_card, apps.monkey_parameters_card)
    try:
        for enabled in (True, False, True):
            for block in blocks:
                block.setEnabled(enabled)
                QTest.mouseMove(block, QPoint(8, 8))
                qt_application.processEvents()
                rendered = section.grab().toImage()
                background = rendered.pixelColor(
                    section.width() - 4, section.headerView.height() // 2,
                )
                for point in (QPoint(8, 8), QPoint(1, block.height() // 2)):
                    assert rendered.pixelColor(block.mapTo(section, point)) == background
        field = apps.monkey_events
        rendered = section.grab().toImage()
        assert rendered.pixelColor(
            field.mapTo(section, QPoint(field.width() // 2, field.height() // 2)),
        ) != background
    finally:
        _close_feature_panel(owner)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("font_size,width", [(12, 292), (12, 960), (22, 292), (22, 960)])
def test_monkey_sections_and_visible_query_actions_fit(
    qt_application, monkeypatch, theme, font_size, width,
):
    """真实结果与查询动作在浅深主题、大字号和窄视口中保持可读。"""

    BaseStyles.switch_theme(theme)
    config = replace(BaseStyles.current_font_config(), ui_family="Segoe UI", ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    owner, apps, scroll, content = _show_feature_panel(
        "apps", width, font_size, qt_application, monkeypatch, patch_font_factory=False,
    )
    try:
        owner._devices_tab.update_device_list(["demo-a", "demo-b"])
        owner._devices_tab.set_selected_devices(["demo-a", "demo-b"])
        package = "com.example.diagnostic.application.longpackagename"
        apps.program_edit.setText(package)
        assert apps.monkey_cancel_prepare_btn.isHidden()
        apps.monkey_get_package_btn.click()
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        assert apps.monkey_cancel_prepare_btn.isVisibleTo(content)
        assert apps.monkey_get_package_btn.isHidden()
        assert_non_overlapping(
            (apps.monkey_package_info, apps.monkey_cancel_prepare_btn),
            apps.monkey_package_card,
        )
        cancel = apps.monkey_cancel_prepare_btn
        assert_contained(cancel, apps.monkey_package_card)
        assert cancel.width() >= cancel.minimumSizeHint().width()
        assert cancel.height() >= cancel.minimumSizeHint().height()

        pending = apps._monkey_preparation
        apps.on_monkey_preparation_finished(pending.request_id, _success(pending, package))
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        assert apps.monkey_cancel_prepare_btn.isHidden()
        get_button = apps.monkey_get_package_btn
        assert get_button.width() == max(get_button.sizeHint().width(), get_button.minimumWidth())
        assert "1.0 (1)" in apps.monkey_package_info.text()
        assert "2.0 (2)" in apps.monkey_package_info.text()
        assert apps.monkey_target_summary.text().count(package) == 1
        assert package not in apps.monkey_package_info.text()
        assert apps.monkey_package_info.isHidden()
        assert "2" in apps.monkey_package_overview.text()
        overview_controls = (apps.monkey_package_overview, apps.monkey_package_details_btn)
        assert_non_overlapping(overview_controls, apps.monkey_package_card)
        for control in overview_controls:
            assert_contained(control, apps.monkey_package_card)
        apps.monkey_package_details_btn.click()
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        assert apps.monkey_package_info.isVisibleTo(content)
        for label in (apps.monkey_package_info, apps.monkey_target_summary):
            assert label.height() >= label.heightForWidth(label.width())
            assert label.font().pointSize() == font_size

        blocks = (apps.monkey_package_card, apps.monkey_parameters_card, apps.monkey_run_actions)
        assert_non_overlapping(blocks, apps.monkey_section)
        positions = [mapped_rect(block, apps.monkey_section) for block in blocks]
        assert all(first.bottom() < second.top() for first, second in zip(positions, positions[1:]))
        assert apps.monkey_exceptions_hint.isHidden()
        parameter_blocks = (
            apps.monkey_parameters_heading,
            apps.monkey_parameter_binding._container_ref(),
            apps.monkey_distribution_header_binding._container_ref(),
            apps.monkey_percentage_binding._container_ref(),
            apps.monkey_exceptions_heading,
        )
        assert_non_overlapping(parameter_blocks, apps.monkey_parameters_card)
        for block in parameter_blocks:
            assert mapped_rect(block, apps.monkey_parameters_card).left() == 16
        assert_non_overlapping(
            (apps.monkey_run_status, apps.start_monkey_btn, apps.kill_monkey_btn),
            apps.monkey_run_actions,
        )
        for binding in (apps.monkey_parameter_binding, apps.monkey_percentage_binding):
            widgets = binding.widgets()
            for label, field in zip(widgets[::2], widgets[1::2]):
                label_rect = mapped_rect(label, apps.monkey_parameters_card)
                field_rect = mapped_rect(field, apps.monkey_parameters_card)
                assert label_rect.left() == field_rect.left()
                assert label_rect.bottom() < field_rect.top()
            assert max(field.width() for field in widgets[1::2]) - min(
                field.width() for field in widgets[1::2]
            ) <= 1
        assert apps.monkey_parameter_binding._container_ref().isAncestorOf(apps.monkey_events)
        distribution_header = apps.monkey_distribution_header_binding._container_ref()
        assert distribution_header.isAncestorOf(apps._pct_total_lbl)
        assert apps._pct_total_lbl.text() == "合计：100%"
        assert isinstance(apps.start_monkey_btn, PrimaryPushButton)
    finally:
        _close_feature_panel(owner)


def test_monkey_presentation_tracks_cancel_failure_start_stop_and_close(
    qt_application, monkeypatch,
):
    """状态说明和取消显隐跟随原请求与批次；展示刷新不会额外提交操作。"""

    owner, apps, scroll, content = _show_feature_panel(
        "apps", 640, 12, qt_application, monkeypatch,
    )
    monkeypatch.setattr("core.settings_manager.AppSettings.instance", lambda: Mock())
    try:
        assert apps.monkey_run_status.text() == "请先选择设备"
        assert apps.monkey_cancel_prepare_btn.isHidden()
        owner._devices_tab.update_device_list(["demo-a", "demo-b"])
        owner._devices_tab.set_selected_devices(["demo-a", "demo-b"])
        apps.program_edit.setText("com.example.demo")
        requests = QSignalSpy(apps.monkey_preparation_requested)
        starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
        stops = QSignalSpy(apps.signals.kill_monkey_batch_requested)

        apps.monkey_get_package_btn.click()
        first = apps._monkey_preparation
        assert apps.monkey_cancel_prepare_btn.isVisibleTo(content)
        assert "正在核对" in apps.monkey_run_status.text()
        apps.monkey_get_package_btn.click()
        assert requests.count() == 1
        apps.monkey_cancel_prepare_btn.click()
        assert first.cancellation.is_cancelled
        assert apps.monkey_cancel_prepare_btn.isHidden()
        apps.on_monkey_preparation_finished(first.request_id, _success(first))
        assert starts.count() == 0
        assert "已取消" in apps.monkey_package_info.text()

        apps.monkey_get_package_btn.click()
        pending = apps._monkey_preparation
        apps.on_monkey_preparation_finished(
            pending.request_id, {"success": False, "error": "查询失败"}
        )
        assert apps.monkey_cancel_prepare_btn.isHidden()
        assert apps.monkey_package_info.text() == "查询失败"
        assert apps.monkey_get_package_btn.isEnabled()

        apps.start_monkey_btn.click()
        pending = apps._monkey_preparation
        apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
        assert starts.count() == 1
        assert apps.monkey_cancel_prepare_btn.isHidden()
        assert apps.monkey_run_status.text() == "正在运行 · 2 台设备"
        assert not apps.start_monkey_btn.isEnabled()
        batch = apps._monkey_batch_id
        apps.kill_monkey_btn.click()
        apps.kill_monkey_btn.click()
        assert stops.count() == 1
        assert apps.monkey_run_status.text() == "正在停止 Monkey"
        for device in ("demo-a", "demo-b"):
            apps.on_monkey_target_finished(batch, device)
        assert apps.start_monkey_btn.isEnabled()
        assert "开始时自动核对" in apps.monkey_run_status.text()
        apps.monkey_get_package_btn.click()
        pending = apps._monkey_preparation
        apps.shutdown()
        apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
        assert apps.monkey_cancel_prepare_btn.isHidden()
        assert apps.monkey_run_status.text() == "页面正在关闭"
        assert starts.count() == 1
    finally:
        _close_feature_panel(owner)


def test_single_monkey_target_uses_compact_inline_summary(qt_application, monkeypatch):
    """常用单设备状态保留两行信息，不再为独立小标题和内边距预留大块空间。"""
    owner, apps, scroll, content = _show_feature_panel(
        "apps", 900, 12, qt_application, monkeypatch,
    )
    try:
        owner._devices_tab.update_device_list(["demo-a"])
        owner._devices_tab.set_selected_devices(["demo-a"])
        apps.program_edit.setText("com.google.android.apps.nexuslauncher")
        apps.monkey_get_package_btn.click()
        pending = apps._monkey_preparation
        apps.on_monkey_preparation_finished(
            pending.request_id, _success(pending, pending.package_name),
        )
        _resize_feature_viewport(qt_application, owner, apps, scroll, 900)
        assert apps.monkey_package_overview_row.isHidden()
        assert apps.monkey_package_info.isVisibleTo(content)
        assert apps.monkey_package_card.height() <= 96
        summary = mapped_rect(apps.monkey_target_summary, apps.monkey_package_card)
        button = mapped_rect(apps.monkey_get_package_btn, apps.monkey_package_card)
        assert abs(summary.center().y() - button.center().y()) <= 2
        assert_non_overlapping(
            (apps.monkey_target_summary, apps.monkey_get_package_btn, apps.monkey_package_info),
            apps.monkey_package_card,
        )
    finally:
        _close_feature_panel(owner)


def test_multi_monkey_details_expand_without_query_and_errors_remain_visible(
    qt_application, monkeypatch,
):
    """大量设备不会推开参数区；展开仅阅读已有结果，过期与失败信息不能被折叠。"""
    owner, apps, scroll, content = _show_feature_panel(
        "apps", 900, 12, qt_application, monkeypatch,
    )
    try:
        devices = [f"demo-{index}" for index in range(12)]
        owner._devices_tab.update_device_list(devices)
        owner._devices_tab.set_selected_devices(devices)
        apps.program_edit.setText("com.example.demo")
        queries = QSignalSpy(apps.monkey_preparation_requested)
        starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
        apps.monkey_get_package_btn.click()
        pending = apps._monkey_preparation
        apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
        _resize_feature_viewport(qt_application, owner, apps, scroll, 900)
        collapsed_height = apps.monkey_package_card.height()
        assert collapsed_height <= 96
        assert apps.monkey_package_info.isHidden()
        assert "12" in apps.monkey_package_overview.text()
        assert "差异" in apps.monkey_package_overview.text()
        apps.monkey_package_details_btn.click()
        _resize_feature_viewport(qt_application, owner, apps, scroll, 900)
        assert apps.monkey_package_info.isVisibleTo(content)
        assert "设备 12" in apps.monkey_package_info.text()
        assert apps.monkey_package_card.height() > collapsed_height
        apps.monkey_package_details_btn.click()
        _resize_feature_viewport(qt_application, owner, apps, scroll, 900)
        assert apps.monkey_package_card.height() == collapsed_height
        assert queries.count() == 1 and starts.count() == 0
        apps.program_edit.setText("com.example.other")
        assert apps.monkey_package_overview_row.isHidden()
        assert not apps.monkey_package_info.isHidden()
        assert "已改变" in apps.monkey_package_info.text()
        apps.monkey_get_package_btn.click()
        pending = apps._monkey_preparation
        apps.on_monkey_preparation_finished(
            pending.request_id, {"success": False, "error": "连接已断开，请重试"},
        )
        assert not apps.monkey_package_info.isHidden()
        assert apps.monkey_package_info.text() == "连接已断开，请重试"
        assert starts.count() == 0
    finally:
        _close_feature_panel(owner)
