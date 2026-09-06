"""验证独立 Monkey 方案、真实 seed 和终态记录保持同一次运行的身份。"""

import copy
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QSignalSpy

from controllers._app_monkey import ADBAppMonkeyMixin
from controllers.signals import ADBControllerSignals
from gui.panels.side_panel import SidePanel
from gui.run_library import RunLibraryController
from gui.styles import BaseStyles
from gui.styles.typography import typography_manager
from models.adb_testing import ADBTesting
from services.run_library import RunLibrary
from tests.test_monkey_preparation import _success
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _show_feature_panel,
)
from tests.ui_geometry_helpers import assert_contained, assert_non_overlapping, wait_until


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


@pytest.fixture
def model(qt_application, monkeypatch):
    instance = ADBTesting()
    instance._procs = Mock()
    instance._procs.stop.return_value = None
    instance._procs.start.return_value.poll.return_value = 0
    monkeypatch.setattr(instance, "_run", Mock(return_value={"success": True, "output": ""}))
    yield instance
    instance.shutdown()
    assert instance.long_pool.waitForDone(3000)
    instance.deleteLater()


@pytest.fixture
def controller(qt_application, tmp_path):
    instance = ADBAppMonkeyMixin.__new__(ADBAppMonkeyMixin)
    instance.testing_model = Mock()
    instance.testing_model.prepare_monkey_batch.return_value = True
    instance.signals = ADBControllerSignals()
    instance.log_service = Mock()
    instance._emit_operation = Mock()
    instance._get_screenshot_dir = Mock(return_value=str(tmp_path))
    instance._monkey_running = set()
    instance._monkey_lock = threading.RLock()
    yield instance
    instance.signals.deleteLater()


def _parameters(**overrides):
    return {
        "package_name": "com.example.demo", "events": 100, "throttle": 300,
        "touch": 30, "motion": 15, "trackball": 0, "nav": 20, "majornav": 10,
        "syskeys": 5, "appswitch": 8, "anyevent": 10, "pinch": 2,
        "ignore_crashes": True, "ignore_timeouts": True, "ignore_security": False,
        "seed_mode": "fixed", "seed": 42, **overrides,
    }


def test_loading_scheme_restores_fields_without_targets_queries_or_start(apps):
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    queries = QSignalSpy(apps.monkey_preparation_requested)
    targets = tuple(apps.selected_devices)
    parameters = _parameters(seed=2147483647, events=1000000, throttle=60000)

    apps.apply_run_parameters(parameters)
    assert apps.capture_run_parameters() == parameters
    assert tuple(apps.selected_devices) == targets
    assert starts.count() == queries.count() == 0
    parameters["events"] = 1
    assert apps.capture_run_parameters()["events"] == 1000000


@pytest.mark.parametrize("changed", [
    {"events": 0}, {"touch": 101}, {"touch": 29}, {"seed": True},
    {"seed": 2147483648}, {"seed_mode": "unknown"}, {"ignore_security": "false"},
])
def test_invalid_scheme_cannot_partially_change_form(apps, changed):
    before = apps.capture_run_parameters()
    with pytest.raises(ValueError):
        apps.apply_run_parameters(_parameters(**changed))
    assert apps.capture_run_parameters() == before


@pytest.mark.parametrize("state", ["preparing", "running", "closed"])
def test_scheme_actions_are_blocked_while_preparing_running_or_closed(apps, state):
    if state == "preparing":
        apps._begin_monkey_preparation()
    elif state == "running":
        apps._set_monkey_running(True)
    else:
        apps.shutdown()
    assert not apps.monkey_parameters_card.isEnabled()
    assert apps.capture_run_parameters() is None
    with pytest.raises(ValueError):
        apps.apply_run_parameters(_parameters())


def test_named_scheme_round_trip_through_actual_bar_and_shared_library(
    apps, qt_application, monkeypatch,
):
    library = RunLibraryController(RunLibrary())
    try:
        apps.set_run_library(library)
        parameters = _parameters(seed_mode="random", seed=None)
        apps.apply_run_parameters(parameters)
        monkeypatch.setattr(
            "gui.widgets.run_preset_bar.FluentInputDialog.getText",
            lambda *_args, **_kwargs: ("Daily smoke", True),
        )
        apps.monkey_preset_bar.save_button.click()
        wait_until(qt_application, lambda: len(library.presets) == 1)
        apps.monkey_events.setText("999")
        apps.monkey_seed_mode.setCurrentIndex(1)
        apps.monkey_seed.setText("2026")
        starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
        queries = QSignalSpy(apps.monkey_preparation_requested)
        apps.monkey_preset_bar.load_button.click()
        assert apps.capture_run_parameters() == parameters
        assert starts.count() == queries.count() == 0
    finally:
        assert library.shutdown()
        library.deleteLater()


def test_prepared_metadata_uses_versions_and_seed_does_not_enter_global_settings(apps, monkeypatch):
    from core.settings_manager import AppSettings

    settings = AppSettings.instance()
    writes = []
    monkeypatch.setattr(settings, "set", lambda key, value: writes.append((key, value)))
    starts = QSignalSpy(apps.signals.start_monkey_batch_requested)
    apps.apply_run_parameters(_parameters())
    apps._on_start_monkey()
    pending = apps._monkey_preparation
    apps.on_monkey_preparation_finished(pending.request_id, _success(pending))
    parameters = starts.at(0)[1]
    assert parameters["seed"] == 42 and parameters["seed_mode"] == "fixed"
    assert parameters["_target_metadata"]["demo-a"]["app_version"] == "1.0 (1)"
    saved = next(value for key, value in writes if key == "monkey_params")
    assert not {"seed", "seed_mode", "_target_metadata"} & saved.keys()


@pytest.mark.parametrize("font_size,width", [(12, 960), (12, 292), (22, 960), (22, 292)])
def test_scheme_bar_and_maximum_seed_fit_supported_viewports(
    qt_application, monkeypatch, font_size, width,
):
    config = replace(
        BaseStyles.current_font_config(), ui_family="Microsoft YaHei UI", ui_size=font_size,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    owner, apps, scroll, content = _show_feature_panel(
        "apps", width, font_size, qt_application, monkeypatch, patch_font_factory=False,
    )
    try:
        apps.monkey_seed_mode.setCurrentIndex(1)
        apps.monkey_seed.setText("2147483647")
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        widgets = (
            apps.monkey_preset_bar.combo, apps.monkey_preset_bar.load_button,
            apps.monkey_preset_bar.save_button, apps.monkey_preset_bar.delete_button,
        )
        assert_non_overlapping(widgets, apps.monkey_preset_bar)
        for widget in widgets:
            assert_contained(widget, apps.monkey_preset_bar)
            assert_contained(widget, apps.monkey_parameters_card)
            assert widget.width() >= widget.minimumSizeHint().width()
            assert widget.font().pointSize() == font_size
        assert_contained(apps.monkey_preset_bar, apps.monkey_parameters_card)
        assert_non_overlapping((
            apps.monkey_parameters_heading, apps.monkey_preset_bar,
            apps.monkey_parameter_binding._container_ref(),
        ), apps.monkey_parameters_card)
        assert_contained(apps.monkey_seed, apps.monkey_parameters_card)
        assert apps.monkey_seed.currentText() == "2147483647"
        assert apps.monkey_seed.width() >= apps.monkey_seed.minimumWidth()
    finally:
        _close_feature_panel(owner)


@pytest.mark.parametrize("seed", [0, 42, 2147483647, None])
def test_model_records_actual_seed_and_times_from_started_process(
    model, tmp_path, monkeypatch, seed,
):
    monkeypatch.setattr("models.adb_testing.random.randint", lambda *_args: 12345)
    result = ADBTesting.run_monkey_test_async.__wrapped__(
        model, "demo-a", "com.example.demo", {"events": 10, "seed": seed},
        "device_1", str(tmp_path), 1, batch_id="batch-a",
    )
    expected = 12345 if seed is None else seed
    command = model._procs.start.call_args_list[-1].args[1]
    assert command[command.index("-s", 4) + 1] == str(expected)
    assert result["seed"] == expected
    assert result["success"] and not result["cancelled"]
    assert 0 < result["started_at"] <= result["finished_at"]
    assert Path(result["monkey_log"]).is_file() and Path(result["logcat_log"]).is_file()


def test_cancelled_queued_model_run_has_seed_and_terminal_time_without_artifacts(model, tmp_path):
    assert model.prepare_monkey_batch("demo-a", "batch-a")
    ADBTesting.kill_monkey_async.__wrapped__(model, "demo-a", 1, batch_id="batch-a")
    result = ADBTesting.run_monkey_test_async.__wrapped__(
        model, "demo-a", "com.example.demo", {"events": 10, "seed": 71},
        "device_1", str(tmp_path), 1, batch_id="batch-a",
    )
    assert result["cancelled"] and not result["success"]
    assert result["seed"] == 71 and result["finished_at"] >= result["started_at"]
    assert result["monkey_log"] == result["logcat_log"] == ""
    model._procs.start.assert_not_called()


def test_each_target_gets_actual_random_seed_and_one_stable_record(
    controller, tmp_path, monkeypatch,
):
    seeds = iter((111, 222))
    monkeypatch.setattr("controllers._app_monkey.random.randint", lambda *_args: next(seeds))
    records = QSignalSpy(controller.signals.run_record_ready)
    parameters = _parameters(seed_mode="random", seed=None)
    parameters["_target_metadata"] = {
        "demo-a": {"device_label": "Device 1", "app_version": "1.0 (10)"},
    }
    original = copy.deepcopy(parameters)
    controller.run_monkey_test(["demo-a", "demo-b"], parameters, "batch-a")
    assert parameters == original
    dispatched = controller.testing_model.run_monkey_test_async.call_args_list
    assert [call.args[2]["seed"] for call in dispatched] == [111, 222]
    parameters["events"] = 999
    log = tmp_path / "monkey.txt"
    log.write_text("synthetic", encoding="utf-8")
    for index, device in enumerate(("demo-a", "demo-b")):
        result = {
            "device_ip": device, "batch_id": "batch-a", "success": index == 0,
            "seed": (111, 222)[index], "monkey_log": str(log),
            "logcat_log": str(tmp_path / "not-created.txt"),
            "started_at": 100.0, "finished_at": 120.0,
            "error": "" if index == 0 else "demo-b disconnected",
        }
        controller._process_run_monkey_test_result(result)
        controller._process_run_monkey_test_result(result)
    assert records.count() == 2
    first, second = (records.at(index)[0] for index in range(2))
    assert (first.run_id, second.run_id) == ("batch-a-1", "batch-a-2")
    assert (first.state, second.state) == ("succeeded", "failed")
    assert first.parameters["seed"] == 111 and second.parameters["seed"] == 222
    assert first.parameters["seed_mode"] == "fixed" and first.parameters["seed_source"] == "random"
    assert first.parameters["events"] == 100 and "_target_metadata" not in first.parameters
    assert len(first.artifacts) == 1 and first.app_version == "1.0 (10)"
    assert "demo-b" not in second.message and "demo-a" not in first.device_label
    assert first.started_at == 100.0 and first.finished_at == 120.0
    assert not controller._monkey_run_snapshots and not controller._monkey_run_results


@pytest.mark.parametrize("ack_first", [True, False])
def test_cancel_record_waits_for_both_run_terminal_and_stop_ack(controller, ack_first):
    records = QSignalSpy(controller.signals.run_record_ready)
    controller.run_monkey_test(["demo-a"], _parameters(), "batch-a")
    controller.kill_monkey(["demo-a"], "batch-a")
    result = {"device_ip": "demo-a", "batch_id": "batch-a", "success": False,
              "cancelled": True, "error": "Aborted by user", "seed": 42}
    ack = {"device_ip": "demo-a", "batch_id": "batch-a", "success": True, "index": 1}
    if ack_first:
        controller._process_kill_monkey_result(ack)
        assert records.count() == 0
        controller._process_run_monkey_test_result(result)
    else:
        controller._process_run_monkey_test_result(result)
        assert records.count() == 0
        controller._process_kill_monkey_result(ack)
    assert records.count() == 1 and records.at(0)[0].state == "cancelled"
    controller._process_kill_monkey_result(ack)
    controller._process_run_monkey_test_result(result)
    assert records.count() == 1


@pytest.mark.parametrize("failure", ["directory", "dispatch"])
def test_start_failure_archives_per_target_and_releases_slots(controller, failure):
    records = QSignalSpy(controller.signals.run_record_ready)
    if failure == "directory":
        controller._get_screenshot_dir.side_effect = OSError("output unavailable")
    else:
        controller.testing_model.run_monkey_test_async.side_effect = RuntimeError("queue rejected")
    controller.run_monkey_test(["demo-a", "demo-b"], _parameters(), "batch-a")
    assert records.count() == 2
    assert all(records.at(index)[0].state == "failed" for index in range(2))
    assert not controller._monkey_running and not controller._monkey_run_snapshots


def test_old_batch_result_cannot_replace_new_snapshot(controller):
    records = QSignalSpy(controller.signals.run_record_ready)
    controller.run_monkey_test(["demo-a"], _parameters(seed=71), "batch-new")
    controller._process_run_monkey_test_result({
        "device_ip": "demo-a", "batch_id": "batch-old", "success": True, "seed": 9,
    })
    assert records.count() == 0
    controller._process_run_monkey_test_result({
        "device_ip": "demo-a", "batch_id": "batch-new", "success": True, "seed": 71,
    })
    assert records.count() == 1 and records.at(0)[0].parameters["seed"] == 71


def test_shutdown_archives_model_terminal_even_when_regular_callback_was_rejected(
    controller, model, tmp_path,
):
    records = QSignalSpy(controller.signals.run_record_ready)
    controller.run_monkey_test(["demo-a"], _parameters(), "batch-a")
    result = ADBTesting.run_monkey_test_async.__wrapped__(
        model, "demo-a", "com.example.demo", _parameters(), "device_1",
        str(tmp_path), 1, batch_id="batch-a",
    )
    assert result["success"] and result["terminal"]
    controller.testing_model = model
    controller._shutting_down = True
    controller.archive_finished_monkey_runs(resources_stopped=True)
    assert records.count() == 1
    record = records.at(0)[0]
    assert record.state == "succeeded" and len(record.artifacts) == 2
    assert record.finished_at == result["finished_at"]
    assert model.monkey_run_archive_snapshot("demo-a", "batch-a") is None
    controller.archive_finished_monkey_runs(resources_stopped=True)
    assert records.count() == 1


@pytest.mark.parametrize("resources_stopped,state", [(True, "cancelled"), (False, "partial")])
def test_shutdown_without_terminal_distinguishes_confirmed_stop_and_residual_resources(
    controller, tmp_path, resources_stopped, state,
):
    records = QSignalSpy(controller.signals.run_record_ready)
    controller.run_monkey_test(["demo-a"], _parameters(), "batch-a")
    artifact = tmp_path / "partial-monkey.txt"
    artifact.write_text("synthetic pending output", encoding="utf-8")
    controller.testing_model.monkey_run_archive_snapshot.return_value = {
        "monkey_log": str(artifact), "seed": 42, "started_at": 100,
    }
    controller._shutting_down = True
    controller.archive_finished_monkey_runs(resources_stopped=resources_stopped)
    assert records.count() == 1
    record = records.at(0)[0]
    assert record.state == state and len(record.artifacts) == 1
    assert record.parameters["seed"] == 42 and record.finished_at >= 100
    assert not controller._monkey_run_snapshots
