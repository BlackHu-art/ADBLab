"""验证媒体职责归位后的旧入口、注册和完整协议链。"""

from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adblab.application.envelope import OperationMetadata
from adblab.application.operations import OperationManager, OperationState
from adblab.application.screen_record import ScreenRecordUseCase
from controllers import ADBController
from controllers._base import _ADBControllerBase
from controllers._media import ADBMediaMixin

MEDIA_HANDLERS = {
    "start_screen_record": "_process_start_screen_record_result",
    "stop_screen_record": "_process_stop_screen_record_result",
    "pull_recorded_video": "_process_pull_recorded_video_result",
    "dumpsys_meminfo": "_process_dumpsys_meminfo_result",
    "dumpsys_cpuinfo": "_process_dumpsys_cpuinfo_result",
    "dumpsys_battery": "_process_dumpsys_battery_result",
    "top_snapshot": "_process_top_snapshot_result",
    "gfxinfo": "_process_gfxinfo_result",
    "wakelocks": "_process_wakelocks_result",
    "netstats_detail": "_process_netstats_detail_result",
    "battery_set_level": "_process_battery_set_level_result",
    "battery_set_status": "_process_battery_set_status_result",
    "battery_reset": "_process_battery_reset_result",
    "logcat_filtered": "_process_logcat_filtered_result",
    "list_processes": "_process_list_processes_result",
    "kill_process": "_process_kill_process_result",
    "get_device_uptime": "_process_get_device_uptime_result",
}


def _uninitialized(klass):
    controller = klass.__new__(klass)
    controller.log_service = Mock()
    return controller


def test_media_facade_routes_each_registered_result_once():
    controller = _uninitialized(ADBMediaMixin)
    for name in (*MEDIA_HANDLERS.values(), "_process_screenshot_operation_result"):
        setattr(controller, name, Mock())
    controller._build_handler_map()
    assert set(controller._handler_map) == set(MEDIA_HANDLERS)
    assert set(controller._operation_handler_map) == {"take_screenshot"}
    payload, metadata = object(), object()
    for key, name in MEDIA_HANDLERS.items():
        controller._handler_map[key](payload)
        getattr(controller, name).assert_called_once_with(payload)
    controller._operation_handler_map["take_screenshot"](payload, metadata)
    controller._process_screenshot_operation_result.assert_called_once_with(payload, metadata)
    controller.log_service.log.assert_not_called()


def test_full_controller_keeps_media_and_install_registration_without_collisions():
    from controllers.media.diagnostics import ADBDiagnosticsMixin
    from controllers.media.recording import ADBRecordingMixin
    from controllers.media.screenshot import ADBScreenshotMixin

    controller = _uninitialized(ADBController)
    controller._build_handler_map()
    for key, name in MEDIA_HANDLERS.items():
        handler = controller._handler_map[key]
        assert handler.__self__ is controller
        assert handler.__func__ is getattr(ADBMediaMixin, name)
    assert set(controller._operation_handler_map) == {"take_screenshot", "install_apk"}
    for key, name in {
        "take_screenshot": "_process_screenshot_operation_result",
        "install_apk": "_process_install_operation_result",
    }.items():
        assert controller._operation_handler_map[key] == getattr(controller, name)
    for table in ("_handlers", "_operation_handlers"):
        counts = Counter(
            key for klass in ADBController.__mro__ for key in klass.__dict__.get(table, {})
        )
        assert set(counts.values()) == {1}
        assert table not in ADBMediaMixin.__dict__
    mro = ADBController.__mro__
    offset = mro.index(ADBMediaMixin)
    assert mro[offset + 1:offset + 4] == (
        ADBScreenshotMixin, ADBRecordingMixin, ADBDiagnosticsMixin,
    )
    assert mro.count(_ADBControllerBase) == 1
    for klass in (ADBMediaMixin, ADBScreenshotMixin, ADBRecordingMixin, ADBDiagnosticsMixin):
        assert "__init__" not in klass.__dict__
    controller.log_service.log.assert_not_called()


@pytest.mark.parametrize(
    "kind,op_type,method,metadata_kind,generation,claimed,expected",
    [
        ("screenshot", "take_screenshot", "take_screenshot", "screenshot", "none", False, False),
        ("screenshot", "take_screenshot", "take_screenshot", "screenshot", "same", False, True),
        ("screenshot", "take_screenshot", "take_screenshot", "screenshot", "same", True, False),
        ("install", "install_apk", "install_apk", "install", "same", True, True),
        ("install", "install_apk", "install_apk", "install", "other", True, False),
        ("screenshot", "take_screenshot", "wrong", "screenshot", "same", False, False),
        ("screenshot", "take_screenshot", "take_screenshot", "generic", "same", False, False),
        ("screenshot", "take_screenshot", "take_screenshot", "screenshot", "other", False, False),
        ("generic", "generic", "generic", "generic", "none", False, True),
    ],
)
def test_screenshot_protocol_still_reaches_install_and_base(
    kind, op_type, method, metadata_kind, generation, claimed, expected,
):
    controller = _uninitialized(ADBController)
    controller.operation_manager = OperationManager()
    snapshot = controller.operation_manager.begin(kind)
    tokens = {"none": None, "same": snapshot.generation_token, "other": object()}
    metadata = OperationMetadata(
        1, snapshot.operation_id, metadata_kind, method, "task-1",
        generation_token=tokens[generation],
    )
    assert controller._operation_metadata_matches(
        op_type, metadata, snapshot, object() if claimed else None,
    ) is expected


@pytest.mark.parametrize("kind", ["screenshot", "install", "batch_install", "generic"])
def test_protocol_failure_reaches_correct_terminal_owner(kind):
    controller = _uninitialized(ADBController)
    controller.operation_manager = OperationManager()
    snapshot = controller.operation_manager.begin(kind)
    screenshot_terminal, owner, install_terminal = object(), object(), object()
    controller._fail_screenshot_operation = Mock(return_value=screenshot_terminal)
    controller.install_batch_use_case = SimpleNamespace(
        fail_snapshot=Mock(return_value=(True, owner, install_terminal)),
    )
    controller._publish_install_terminal = Mock()
    terminal = controller._fail_operation_protocol(snapshot, "invalid protocol")
    if kind == "screenshot":
        assert terminal is screenshot_terminal
        controller._fail_screenshot_operation.assert_called_once_with(
            snapshot.operation_id, "invalid protocol",
            expected_generation=snapshot.generation_token,
        )
    else:
        controller._fail_screenshot_operation.assert_not_called()
    if kind in {"install", "batch_install"}:
        assert terminal is install_terminal
        controller.install_batch_use_case.fail_snapshot.assert_called_once_with(
            snapshot, "invalid protocol",
        )
        controller._publish_install_terminal.assert_called_once_with(install_terminal, owner)
    else:
        controller.install_batch_use_case.fail_snapshot.assert_not_called()
        controller._publish_install_terminal.assert_not_called()
    if kind == "generic":
        assert terminal.state is OperationState.FAILED
        assert terminal.operation_id == snapshot.operation_id
        assert terminal.generation_token is snapshot.generation_token
        assert terminal.message == "invalid protocol"
        assert controller.operation_manager.get(snapshot.operation_id) is None
    else:
        assert controller.operation_manager.get(snapshot.operation_id) == snapshot


@pytest.mark.parametrize("entry", ["old", "new"])
def test_new_screenshot_owner_preserves_old_entry_delivery(entry):
    if entry == "new":
        from controllers.media.screenshot import ADBScreenshotMixin
        klass = ADBScreenshotMixin
    else:
        klass = ADBMediaMixin
    controller = _uninitialized(klass)
    controller.signals = Mock()
    controller._emit_screenshot_batch(["", "image.png"])
    controller.signals.screenshot_batch_ready.emit.assert_called_once_with(["image.png"])
    controller._shutting_down = True
    controller._emit_screenshot_batch(["late.png"])
    controller.signals.screenshot_batch_ready.emit.assert_called_once_with(["image.png"])


@pytest.mark.parametrize("entry", ["old", "new"])
@pytest.mark.parametrize("batch_id", ["", "batch-1"])
def test_recording_owner_submits_deduplicated_capture_with_batch_identity(
    entry, batch_id, tmp_path,
):
    if entry == "new":
        from controllers.media.recording import ADBRecordingMixin
        klass = ADBRecordingMixin
    else:
        klass = ADBMediaMixin
    controller = _uninitialized(klass)
    controller.screen_records = ScreenRecordUseCase()
    controller.advanced_model = Mock()
    controller.signals = Mock()
    controller._require_devices = lambda *_args: True
    controller._get_screenshot_dir = lambda: str(tmp_path)
    controller._emit_operation = Mock()
    controller.start_screen_record(["mock-device", "mock-device"], 30, batch_id)
    active = controller.screen_records.active("mock-device")
    assert active is not None
    if batch_id:
        assert active["batch_id"] == batch_id
    else:
        assert len(active["batch_id"]) == 32
        assert all(char in "0123456789abcdef" for char in active["batch_id"])
    controller.advanced_model.start_screen_record_async.assert_called_once_with(
        "mock-device", str(tmp_path), 30, batch_id=active["batch_id"],
    )
    controller._emit_operation.assert_not_called()


@pytest.mark.parametrize("entry", ["old", "new"])
def test_new_recording_owner_preserves_old_entry_retry(entry, tmp_path):
    if entry == "new":
        from controllers.media.recording import ADBRecordingMixin
        klass = ADBRecordingMixin
    else:
        klass = ADBMediaMixin
    records = ScreenRecordUseCase()
    assert records.start("mock-device", "batch-1", str(tmp_path), 30)
    records.mark_started("mock-device", "batch-1", "/sdcard/owned.mp4", "owned.mp4")
    assert records.mark_pull_submitted("mock-device", "batch-1")
    controller = SimpleNamespace(
        screen_records=records, advanced_model=Mock(), _require_devices=lambda *_args: True,
        _emit_operation=Mock(), signals=Mock(),
    )
    failed = {
        "device_ip": "mock-device", "batch_id": "batch-1", "success": False, "retryable": True,
    }
    klass._process_pull_recorded_video_result(controller, failed)
    controller.signals.record_target_retryable.emit.assert_called_once_with(
        "batch-1", "mock-device",
    )
    controller.signals.record_target_finished.emit.assert_not_called()
    controller.signals.record_finished.emit.assert_not_called()
    klass.stop_screen_record(controller, ["mock-device"], "batch-1")
    klass.stop_screen_record(controller, ["mock-device"], "batch-1")
    controller.advanced_model.stop_screen_record_async.assert_not_called()
    controller.advanced_model.pull_recorded_video_async.assert_called_once_with(
        "mock-device", "/sdcard/owned.mp4", str(tmp_path), "owned.mp4", batch_id="batch-1",
    )
    klass._process_pull_recorded_video_result(controller, {
        **failed, "success": True, "local_path": str(tmp_path / "owned.mp4"),
    })
    assert records.active("mock-device") is None
    controller.signals.record_target_finished.emit.assert_called_once_with("batch-1", "mock-device")
    controller.signals.record_finished.emit.assert_called_once_with()


@pytest.mark.parametrize("entry", ["old", "new"])
def test_new_diagnostics_owner_preserves_old_entry_admission(entry):
    if entry == "new":
        from controllers.media.diagnostics import ADBDiagnosticsMixin
        klass = ADBDiagnosticsMixin
    else:
        klass = ADBMediaMixin
    controller = SimpleNamespace(
        advanced_model=Mock(), _require_devices=lambda *_args: True, _emit_operation=Mock(),
    )
    klass.kill_process(controller, ["mock-device", "other-device"], "1234")
    klass.kill_process(controller, ["mock-device"], "²")
    controller.advanced_model.kill_process_async.assert_not_called()
    klass.kill_process(controller, ["mock-device"], "1234")
    controller.advanced_model.kill_process_async.assert_called_once_with("mock-device", "1234")
    klass.gfxinfo(controller, ["mock-device"], "invalid;package")
    controller.advanced_model.gfxinfo_async.assert_not_called()
    klass.battery_set(controller, ["mock-device"], "level", "101")
    controller.advanced_model.battery_set_level_async.assert_not_called()
    assert [call.args[:2] for call in controller._emit_operation.call_args_list] == [
        ("kill_process", False), ("kill_process", False),
        ("gfxinfo", False), ("battery_set", False),
    ]
