"""验证 Monkey 分区的信息层级、任务状态与宽窄布局。"""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QSignalSpy
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
        assert_non_overlapping(
            (apps.monkey_package_info, apps.monkey_get_package_btn, apps.monkey_cancel_prepare_btn),
            apps.monkey_package_card,
        )
        for button in (apps.monkey_get_package_btn, apps.monkey_cancel_prepare_btn):
            assert_contained(button, apps.monkey_package_card)
            assert button.width() >= button.minimumSizeHint().width()
            assert button.height() >= button.minimumSizeHint().height()

        pending = apps._monkey_preparation
        apps.on_monkey_preparation_finished(pending.request_id, _success(pending, package))
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        assert apps.monkey_cancel_prepare_btn.isHidden()
        assert apps.monkey_get_package_btn.width() == apps.monkey_get_package_btn.sizeHint().width()
        assert "1.0 (1)" in apps.monkey_package_info.text()
        assert "2.0 (2)" in apps.monkey_package_info.text()
        for label in (apps.monkey_package_info, apps.monkey_target_summary):
            assert label.height() >= label.heightForWidth(label.width())
            assert label.font().pointSize() == font_size

        blocks = (
            apps.monkey_target_heading,
            apps.monkey_target_summary,
            apps.monkey_package_card,
            apps.monkey_parameters_heading,
            apps.monkey_parameter_binding._container_ref(),
            apps.monkey_distribution_header_binding._container_ref(),
            apps.monkey_percentage_binding._container_ref(),
            apps.monkey_exceptions_heading,
            apps.monkey_exceptions_hint,
            apps.monkey_run_actions,
            apps.monkey_run_status,
        )
        assert_non_overlapping(blocks, apps.monkey_section)
        positions = [mapped_rect(block, apps.monkey_section) for block in blocks]
        assert all(first.bottom() < second.top() for first, second in zip(positions, positions[1:]))
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
