"""验证 Monkey 测试包准备不绕过取消、目标快照与异步边界。"""

import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QSignalSpy

from adblab.application.cancellation import CancellationToken
from controllers._app_monkey import ADBAppMonkeyMixin
from controllers.signals import ADBControllerSignals
from gui.panels.side_panel import SidePanel
from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from models.adb_app import ADBApp
from tests.ui_geometry_helpers import assert_non_overlapping, mapped_rect, wait_until


@pytest.fixture
def apps(qt_application):
    owner = SidePanel()
    owner._devices_tab.update_device_list(["demo-a", "demo-b"])
    owner._devices_tab.set_selected_devices(["demo-a", "demo-b"])
    panel = owner._ensure_tab_loaded(0)
    panel.program_edit.setText("com.example.demo")
    yield panel
    owner.shutdown()
    owner.deleteLater()


def test_start_waits_for_all_target_package_information(apps):
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    preparations = QSignalSpy(apps.monkey_preparation_requested)
    apps._on_start_monkey()
    assert preparations.count() == 1
    assert starts.count() == 0
    assert not apps.start_monkey_btn.isEnabled()
    assert apps.monkey_cancel_prepare_btn.isEnabled()
    apps._on_start_monkey()
    apps.monkey_get_package_btn.click()
    assert preparations.count() == 1


def test_recording_and_monkey_stop_keep_original_targets_after_selection_is_cleared(apps):
    """停止操作使用运行批次快照，清空当前选择不影响原任务的释放。"""
    recording_stops = QSignalSpy(apps.signals.stop_screen_record_batch_requested)
    monkey_stops = QSignalSpy(apps.signals.kill_monkey_batch_requested)
    legacy_stops = QSignalSpy(apps.signals.kill_monkey_requested)
    apps._on_record_start()
    record_batch = apps._recording_batch_id
    apps._on_start_monkey()
    pending = apps._monkey_preparation
    apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    monkey_batch = apps._monkey_batch_id
    apps.panel._devices_tab.set_selected_devices([])

    assert apps.btn_stop_record.isEnabled()
    assert apps.kill_monkey_btn.isEnabled()
    apps.btn_stop_record.click()
    apps.kill_monkey_btn.click()
    assert recording_stops.at(0) == [["demo-a", "demo-b"], record_batch]
    assert monkey_stops.at(0) == [["demo-a", "demo-b"], monkey_batch]
    apps.btn_stop_record.clicked.emit()
    apps.kill_monkey_btn.clicked.emit()
    assert recording_stops.count() == monkey_stops.count() == 1

    for device in ("demo-a", "demo-b"):
        apps.on_monkey_target_finished(monkey_batch, device)
    apps.panel._devices_tab.set_selected_devices(["demo-b"])
    apps._on_kill_monkey()
    assert legacy_stops.count() == 0


def _success(pending, package="com.example.demo"):
    return {
        "success": True, "devices": list(pending.devices), "package_name": package,
        "packages": [
            {"device_ip": device, "package_name": package, "version_name": f"{index}.0",
             "version_code": str(index), "target_sdk": "34"}
            for index, device in enumerate(pending.devices, 1)
        ],
    }


def test_all_prepared_targets_start_once_with_snapshot_and_version_differences(apps):
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    apps._on_start_monkey()
    pending = apps._monkey_preparation
    result = _success(pending)
    apps.on_monkey_preparation_finished(pending.request_id, result)
    apps.on_monkey_preparation_finished(pending.request_id, result)
    assert starts.count() == 1
    assert starts.at(0)[0] == ["demo-a", "demo-b"]
    assert starts.at(0)[1]["package_name"] == "com.example.demo"
    assert "1.0 (1)" in apps.monkey_package_info.text()
    assert "2.0 (2)" in apps.monkey_package_info.text()
    assert apps.kill_monkey_btn.isEnabled()
    assert not apps.monkey_get_package_btn.isEnabled()


@pytest.mark.parametrize("change", ["cancel", "package", "targets", "shutdown"])
def test_cancel_input_change_and_close_reject_late_success(apps, change):
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    apps._on_start_monkey()
    pending = apps._monkey_preparation
    if change == "cancel":
        apps.monkey_cancel_prepare_btn.click()
    elif change == "package":
        apps.program_edit.setText("com.example.other")
    elif change == "targets":
        apps.panel._devices_tab.set_selected_devices(["demo-b"])
    else:
        apps.shutdown()
    assert pending.cancellation.is_cancelled
    assert apps._monkey_preparation is None
    apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    assert starts.count() == 0
    assert apps.start_monkey_btn.isEnabled() == (change != "shutdown")


def test_old_result_does_not_replace_a_new_preparation(apps):
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    apps._on_start_monkey()
    old = apps._monkey_preparation
    apps.monkey_cancel_prepare_btn.click()
    apps._on_start_monkey()
    current = apps._monkey_preparation
    apps.on_monkey_preparation_finished(old.request_id, _success(old))
    assert apps._monkey_preparation is current
    assert starts.count() == 0
    apps.on_monkey_preparation_finished(current.request_id, _success(current))
    assert starts.count() == 1


@pytest.mark.parametrize("result", [
    {"success": False, "error": "第二台设备未安装目标应用"},
    {"success": True, "devices": ["demo-a"], "package_name": "com.example.demo", "packages": []},
    {"success": True, "devices": ["demo-a", "demo-b"], "packages": None},
])
def test_failed_or_incomplete_preparation_cannot_start_a_partial_batch(apps, result):
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    apps._on_start_monkey()
    pending = apps._monkey_preparation
    apps.on_monkey_preparation_finished(pending.request_id, result)
    assert starts.count() == 0
    assert apps.start_monkey_btn.isEnabled()
    assert not apps.kill_monkey_btn.isEnabled()


def test_manual_query_does_not_start_and_start_rechecks_installation(apps):
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    requests = QSignalSpy(apps.monkey_preparation_requested)
    apps.monkey_get_package_btn.click()
    pending = apps._monkey_preparation
    apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    assert starts.count() == 0
    apps._on_start_monkey()
    assert requests.count() == 2
    assert apps._monkey_preparation is not None


def test_empty_package_autofill_is_not_mistaken_for_a_new_user_request(apps):
    apps.program_edit.setText("")
    requests = QSignalSpy(apps.monkey_preparation_requested)
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    apps._on_start_monkey()
    pending = apps._monkey_preparation
    assert pending.package_name == ""
    apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    assert requests.count() == 1
    assert starts.count() == 1
    assert apps.package_text == "com.example.demo"
    assert not pending.cancellation.is_cancelled


def test_parameter_edits_during_query_require_a_new_start(apps):
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    apps._on_start_monkey()
    pending = apps._monkey_preparation
    apps.monkey_events.setText("12345")
    apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    assert starts.count() == 0
    assert "参数已改变" in apps.monkey_package_info.text()


def test_model_requires_package_to_be_installed_on_every_target(qt_application):
    model = ADBApp()
    model._run = Mock(return_value={"success": True, "output": ""})
    result = ADBApp.prepare_monkey_targets_async.__wrapped__(
        model, ["demo-a", "demo-b"], "com.example.demo", "request-a", CancellationToken()
    )
    assert result["success"] is False
    assert result["request_id"] == "request-a"
    assert "未安装" in result["error"]
    assert model._run.call_count == 1
    model.deleteLater()


def _installed_details(version="1.0"):
    return [
        {"success": True, "output": "package:/data/app/demo/base.apk"},
        {"success": True, "output": (
            "Package [com.example.demo] (123):\n"
            f"  versionCode=5 minSdk=21 targetSdk=34\n  versionName={version}\n"
        )},
    ]


def test_model_collects_each_device_version_and_limits_every_command(qt_application):
    model = ADBApp()
    model._run = Mock(side_effect=_installed_details() + _installed_details("2.0"))
    result = ADBApp.prepare_monkey_targets_async.__wrapped__(
        model, ["demo-a", "demo-b"], "com.example.demo", "request-a", CancellationToken()
    )
    assert result["success"]
    assert [item["version_name"] for item in result["packages"]] == ["1.0", "2.0"]
    assert all(call.kwargs["timeout"] == 5 for call in model._run.call_args_list)
    assert all(call.args[0][4] in {"pm", "dumpsys"} for call in model._run.call_args_list)
    model.deleteLater()


@pytest.mark.parametrize("reason", ["cancel", "shutdown"])
def test_model_checks_cancel_between_commands(qt_application, reason):
    model = ADBApp()
    cancellation = CancellationToken()

    def installed(*_args, **_kwargs):
        cancellation.request() if reason == "cancel" else model.begin_shutdown()
        return _installed_details()[0]

    model._run = Mock(side_effect=installed)
    result = ADBApp.prepare_monkey_targets_async.__wrapped__(
        model, ["demo-a"], "com.example.demo", "request-a", cancellation
    )
    assert result["cancelled"]
    assert model._run.call_count == 1
    assert result["request_id"] == "request-a"
    model.deleteLater()


def test_model_rejects_ambiguous_foreground_packages(qt_application, monkeypatch):
    model = ADBApp()
    model._run = Mock()
    monkeypatch.setattr("models.adb_app.detect_current_package", Mock(side_effect=[
        {"success": True, "package_name": "com.example.one"},
        {"success": True, "package_name": "com.example.two"},
    ]))
    result = ADBApp.prepare_monkey_targets_async.__wrapped__(
        model, ["demo-a", "demo-b"], "", "request-a", CancellationToken()
    )
    assert not result["success"]
    assert "不一致" in result["error"]
    model._run.assert_not_called()
    model.deleteLater()


def test_model_preserves_request_identity_when_query_raises(qt_application):
    model = ADBApp()
    model._run = Mock(side_effect=RuntimeError("query failed"))
    result = ADBApp.prepare_monkey_targets_async.__wrapped__(
        model, ["demo-a"], "com.example.demo", "request-a", CancellationToken()
    )
    assert not result["success"]
    assert result["request_id"] == "request-a"
    assert result["error_detail"] == "query failed"
    model.deleteLater()


def test_invalid_package_is_rejected_before_any_device_command(qt_application):
    model = ADBApp()
    model._run = Mock()
    result = ADBApp.prepare_monkey_targets_async.__wrapped__(
        model, ["demo-a"], "com.example.app;reboot", "request-a", CancellationToken()
    )
    assert not result["success"]
    assert "包名格式无效" in result["error"]
    model._run.assert_not_called()
    model.deleteLater()


@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("width", [292, 960])
def test_package_information_and_prepare_actions_reflow_without_overlap(
    qt_application, monkeypatch, font_size, width,
):
    from tests.test_responsive_panels import (
        _close_feature_panel,
        _resize_feature_viewport,
        _show_feature_panel,
    )

    config = replace(BaseStyles.current_font_config(), ui_family="Segoe UI", ui_size=font_size)
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    owner, panel, scroll, content = _show_feature_panel(
        "apps", width, font_size, qt_application, monkeypatch, patch_font_factory=False,
    )
    try:
        owner._devices_tab.update_device_list(["demo-a", "demo-b"])
        owner._devices_tab.set_selected_devices(["demo-a", "demo-b"])
        panel.program_edit.setText("com.example.demo")
        panel._begin_monkey_preparation()
        pending = panel._monkey_preparation
        panel.on_monkey_preparation_finished(pending.request_id, _success(pending))
        _resize_feature_viewport(qt_application, owner, panel, scroll, width)
        info = panel.monkey_package_info
        controls = (info, panel.monkey_get_package_btn, panel.monkey_cancel_prepare_btn)
        assert info.font().pointSize() == font_size
        assert info.height() >= info.heightForWidth(info.width())
        assert_non_overlapping(controls, content)
        for button in controls[1:]:
            assert button.width() >= button.minimumSizeHint().width()
            assert button.height() >= button.minimumSizeHint().height()
            assert mapped_rect(button, content).bottom() < content.height()
            assert button.toolTip()
    finally:
        _close_feature_panel(owner)


def test_prepare_uses_worker_thread_and_delivers_one_result(qt_application):
    model = ADBApp()
    main_thread = threading.get_ident()
    worker_threads = []
    responses = iter(_installed_details())

    def query(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        return next(responses)

    model._run = Mock(side_effect=query)
    finished = QSignalSpy(model.command_finished)
    model.prepare_monkey_targets_async(
        ["demo-a"], "com.example.demo", "request-a", CancellationToken()
    )
    wait_until(qt_application, lambda: finished.count() == 1)
    assert worker_threads and all(thread_id != main_thread for thread_id in worker_threads)
    assert finished.at(0)[1]["request_id"] == "request-a"
    model.deleteLater()


def test_controller_reports_submission_failure_without_starting_any_test(qt_application):
    controller = SimpleNamespace(
        _shutting_down=False, app_model=Mock(), testing_model=Mock(),
        signals=ADBControllerSignals(), log_service=Mock(),
    )
    controller._process_monkey_preparation_result = lambda result: (
        ADBAppMonkeyMixin._process_monkey_preparation_result(controller, result)
    )
    controller.app_model.prepare_monkey_targets_async.side_effect = RuntimeError("closed pool")
    results = QSignalSpy(controller.signals.monkey_preparation_finished)
    ADBAppMonkeyMixin.prepare_monkey_targets(
        controller, ["demo-a"], "com.example.demo", "request-a", CancellationToken()
    )
    assert results.count() == 1
    assert results.at(0)[0] == "request-a"
    assert not results.at(0)[1]["success"]
    controller.testing_model.run_monkey_test_async.assert_not_called()
    controller._shutting_down = True
    controller._process_monkey_preparation_result({"request_id": "late"})
    assert results.count() == 1
