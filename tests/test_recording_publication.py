"""录屏保存的发布、取消和原批次重试契约；设备边界由替身隔离。"""

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from adblab.application.screen_record import ScreenRecordUseCase
from controllers._media import ADBMediaMixin
from models.adb_advanced import ADBAdvanced


def _recording(tmp_path):
    model = ADBAdvanced()
    process = SimpleNamespace(pid=123, poll=lambda: 0)
    with patch.object(model._rec_procs, "start", return_value=process):
        started = ADBAdvanced.start_screen_record_async.__wrapped__(
            model, "mock-device", str(tmp_path), batch_id="batch-1",
        )
    assert started["success"]
    return model, started


def _save(model, started, tmp_path):
    return ADBAdvanced.pull_recorded_video_async.__wrapped__(
        model, "mock-device", started["remote_path"], str(tmp_path),
        started["filename"], batch_id=started["batch_id"],
    )


@pytest.mark.parametrize("failure", ["transfer", "cancelled", "shutdown", "publish"])
@pytest.mark.parametrize("previous_exists", [True, False])
def test_recording_failed_save_preserves_previous_file_and_cleans_partial(
    tmp_path, failure, previous_exists,
):
    model, started = _recording(tmp_path)
    target = tmp_path / started["filename"]
    if previous_exists:
        target.write_bytes(b"previous video")
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        assert command[3] == "pull"
        Path(command[-1]).write_bytes(b"partial video")
        if failure == "shutdown":
            model.begin_shutdown()
        return {"success": failure in {"shutdown", "publish"},
                "cancelled": failure == "cancelled", "error": "connection lost"}

    with patch.object(model, "_run", side_effect=run), patch.object(model._rec_procs, "stop"):
        if failure == "publish":
            with patch("models.adb_advanced.os.replace", side_effect=OSError("busy target")):
                result = _save(model, started, tmp_path)
        else:
            result = _save(model, started, tmp_path)

    if previous_exists:
        assert target.read_bytes() == b"previous video"
    assert list(tmp_path.iterdir()) == ([target] if previous_exists else [])
    assert not result["success"]
    assert result.get("retryable", False) is (failure != "shutdown")
    assert len(commands) == 1
    if failure in {"cancelled", "shutdown"}:
        assert result["cancelled"]
    if failure == "shutdown":
        assert "mock-device" not in model._record_sessions


@pytest.mark.parametrize("cleanup_failure", ["result", "exception"])
def test_recording_success_publishes_only_complete_file_before_remote_cleanup(
    tmp_path, cleanup_failure,
):
    model, started = _recording(tmp_path)
    target = tmp_path / started["filename"]
    target.write_bytes(b"previous video")

    def run(command, **_kwargs):
        if command[3] == "pull":
            assert target.read_bytes() == b"previous video"
            staging = Path(command[-1])
            assert staging.parent == target.parent and staging != target
            staging.write_bytes(b"complete video")
            return {"success": True}
        assert target.read_bytes() == b"complete video"
        if cleanup_failure == "exception":
            raise OSError("cleanup unavailable")
        return {"success": False, "error": "cleanup unavailable"}

    with patch.object(model, "_run", side_effect=run), patch.object(model._rec_procs, "stop"):
        result = _save(model, started, tmp_path)

    assert result["success"]
    assert result["cleanup_error"] == "cleanup unavailable"
    assert target.read_bytes() == b"complete video"
    assert list(tmp_path.iterdir()) == [target]
    assert "mock-device" not in model._record_sessions


@pytest.mark.parametrize("changed_identity", ["batch_id", "remote_path"])
def test_recording_failed_save_can_retry_same_artifact_and_reject_wrong_identity(
    tmp_path, changed_identity,
):
    model, started = _recording(tmp_path)
    with patch.object(model, "_run", return_value={"success": False, "error": "offline"}):
        failed = _save(model, started, tmp_path)
    assert failed.get("retryable")

    def run(command, **_kwargs):
        if command[3] == "pull":
            assert command[4] == started["remote_path"]
            Path(command[-1]).write_bytes(b"retried video")
        return {"success": True}

    with patch.object(model, "_run", side_effect=run) as execute:
        wrong = _save(model, {**started, changed_identity: "unrelated"}, tmp_path)
        assert not wrong["success"]
        execute.assert_not_called()
        retried = _save(model, started, tmp_path)

    assert retried["success"]
    assert (tmp_path / started["filename"]).read_bytes() == b"retried video"


def test_recording_new_capture_replaces_failed_save_without_reusing_old_remote(tmp_path):
    model, old = _recording(tmp_path)
    with patch.object(model, "_run", return_value={"success": False, "error": "offline"}):
        _save(model, old, tmp_path)
    with patch.object(
        model._rec_procs, "start", return_value=SimpleNamespace(pid=456, poll=lambda: 0),
    ):
        new = ADBAdvanced.start_screen_record_async.__wrapped__(
            model, "mock-device", str(tmp_path), batch_id="new-batch",
        )
    assert new["success"]
    assert new["remote_path"] != old["remote_path"]
    with patch.object(model, "_run") as execute:
        assert not _save(model, old, tmp_path)["success"]
    execute.assert_not_called()
    assert len(model._record_sessions) == 1


def _controller(tmp_path):
    records = ScreenRecordUseCase()
    records.start("mock-device", "batch-1", str(tmp_path), 30)
    records.mark_started("mock-device", "batch-1", "/sdcard/owned.mp4", "owned.mp4")
    records.mark_pull_submitted("mock-device", "batch-1")
    controller = SimpleNamespace(
        screen_records=records, advanced_model=Mock(), _require_devices=lambda *_args: True,
        _emit_operation=Mock(), signals=SimpleNamespace(
            record_target_finished=Mock(), record_finished=Mock(), record_target_retryable=Mock(),
        ),
    )
    return controller


def test_recording_controller_preserves_identity_and_existing_stop_retries_once(tmp_path):
    controller = _controller(tmp_path)
    failed = {"device_ip": "mock-device", "batch_id": "batch-1",
              "success": False, "retryable": True, "error": "offline"}
    ADBMediaMixin._process_pull_recorded_video_result(controller, failed)

    controller.signals.record_target_finished.emit.assert_not_called()
    controller.signals.record_target_retryable.emit.assert_called_once_with(
        "batch-1", "mock-device",
    )
    ADBMediaMixin.stop_screen_record(controller, ["mock-device"], "batch-1")
    ADBMediaMixin.stop_screen_record(controller, ["mock-device"], "batch-1")

    controller.advanced_model.stop_screen_record_async.assert_not_called()
    controller.advanced_model.pull_recorded_video_async.assert_called_once_with(
        "mock-device", "/sdcard/owned.mp4", str(tmp_path), "owned.mp4", batch_id="batch-1",
    )
    ADBMediaMixin._process_pull_recorded_video_result(controller, {
        **failed, "success": True, "local_path": str(tmp_path / "owned.mp4"),
    })
    assert controller.screen_records.active("mock-device") is None
    controller.signals.record_target_finished.emit.assert_called_once_with("batch-1", "mock-device")


def test_recording_controller_ignores_old_retry_failure_after_new_capture(tmp_path):
    controller = _controller(tmp_path)
    failed = {"device_ip": "mock-device", "batch_id": "batch-1",
              "success": False, "retryable": True, "error": "offline"}
    ADBMediaMixin._process_pull_recorded_video_result(controller, failed)
    assert controller.screen_records.start("mock-device", "new-batch", str(tmp_path), 30)
    controller.signals.record_target_retryable.emit.reset_mock()

    ADBMediaMixin._process_pull_recorded_video_result(controller, failed)
    ADBMediaMixin.stop_screen_record(controller, ["mock-device"], "batch-1")

    assert controller.screen_records.active("mock-device")["batch_id"] == "new-batch"
    controller.signals.record_target_retryable.emit.assert_not_called()
    controller.advanced_model.stop_screen_record_async.assert_not_called()
    controller.advanced_model.pull_recorded_video_async.assert_not_called()


def test_recording_model_deduplicates_download_and_blocks_new_capture_until_done(tmp_path):
    model, started = _recording(tmp_path)
    entered, release = threading.Event(), threading.Event()
    outputs = []

    def run(command, **_kwargs):
        if command[3] == "pull":
            entered.set()
            assert release.wait(2)
            Path(command[-1]).write_bytes(b"video")
        return {"success": True}

    with patch.object(model, "_run", side_effect=run) as execute:
        thread = threading.Thread(target=lambda: outputs.append(_save(model, started, tmp_path)))
        thread.start()
        try:
            assert entered.wait(1)
            duplicate = _save(model, started, tmp_path)
            assert not duplicate["success"]
            assert execute.call_count == 1
            with patch.object(model._rec_procs, "start") as start:
                new = ADBAdvanced.start_screen_record_async.__wrapped__(
                    model, "mock-device", str(tmp_path), batch_id="new-batch",
                )
            assert not new["success"]
            start.assert_not_called()
        finally:
            release.set()
            thread.join(2)
    assert not thread.is_alive()
    assert outputs[0]["success"]


def test_recording_retry_submission_error_preserves_retry_entry(tmp_path):
    controller = _controller(tmp_path)
    ADBMediaMixin._process_pull_recorded_video_result(controller, {
        "device_ip": "mock-device", "batch_id": "batch-1",
        "success": False, "retryable": True, "error": "offline",
    })
    controller.advanced_model.pull_recorded_video_async.side_effect = RuntimeError("queue closed")

    ADBMediaMixin.stop_screen_record(controller, ["mock-device"], "batch-1")

    assert controller.screen_records.active("mock-device") is not None
    controller.signals.record_target_finished.emit.assert_not_called()
    assert controller.signals.record_target_retryable.emit.call_count == 2


def test_recording_shutdown_never_resubmits_retry_or_retains_save_state(tmp_path):
    controller = _controller(tmp_path)
    controller._shutting_down = True
    ADBMediaMixin._process_pull_recorded_video_result(controller, {
        "device_ip": "mock-device", "batch_id": "batch-1",
        "success": False, "retryable": True, "error": "offline",
    })
    ADBMediaMixin.stop_screen_record(controller, ["mock-device"], "batch-1")
    controller.advanced_model.pull_recorded_video_async.assert_not_called()
    controller.advanced_model.stop_screen_record_async.assert_not_called()
    controller.signals.record_target_retryable.emit.assert_not_called()


def test_recording_failed_save_history_is_bounded_without_device_cleanup(tmp_path):
    model = ADBAdvanced()
    process = SimpleNamespace(pid=123, poll=lambda: 0)
    with (
        patch.object(model._rec_procs, "start", return_value=process),
        patch.object(model, "_run", return_value={"success": False, "error": "offline"}) as run,
    ):
        for index in range(65):
            device = f"mock-{index}"
            started = ADBAdvanced.start_screen_record_async.__wrapped__(
                model, device, str(tmp_path), batch_id="same-batch",
            )
            failed = ADBAdvanced.pull_recorded_video_async.__wrapped__(
                model, device, started["remote_path"], str(tmp_path),
                started["filename"], batch_id="same-batch",
            )
            assert failed["retryable"]

    assert len(model._record_sessions) == 64
    assert "mock-0" not in model._record_sessions
    assert "mock-64" in model._record_sessions
    assert all(call.args[0][3] == "pull" for call in run.call_args_list)
    assert list(tmp_path.iterdir()) == []


def test_recording_retry_capacity_eviction_finishes_original_ui_target(tmp_path):
    controller = _controller(tmp_path)
    controller.screen_records.finish("mock-device", "batch-1")
    for index in range(65):
        device = f"mock-{index}"
        controller.screen_records.start(device, "batch-1", str(tmp_path), 30)
        controller.screen_records.mark_started(device, "batch-1", f"/{index}.mp4", f"{index}.mp4")
        ADBMediaMixin._process_pull_recorded_video_result(controller, {
            "device_ip": device, "batch_id": "batch-1", "success": False,
            "retryable": True, "error": "offline",
        })

    controller.signals.record_target_finished.emit.assert_called_once_with("batch-1", "mock-0")


def test_recording_shutdown_releases_retained_retry_after_owned_pools_drain(tmp_path):
    model, started = _recording(tmp_path)
    with patch.object(model, "_run", return_value={"success": False, "error": "offline"}):
        assert _save(model, started, tmp_path)["retryable"]
    with patch.object(model._rec_procs, "stop_all"), patch.object(model, "_run") as command:
        model.shutdown()
        model.wait_for_commands()
    assert not model._record_sessions
    command.assert_not_called()
