from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock, patch

from adblab.application.envelope import OperationMetadata
from adblab.application.operations import OperationManager, OperationState
from controllers._media import ADBMediaMixin

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _controller(tmp_path):
    controller = ADBMediaMixin.__new__(ADBMediaMixin)
    controller.operation_manager = OperationManager()
    controller.testing_model = Mock()
    controller.signals = Mock()
    controller.log_service = Mock()
    controller._get_screenshot_dir = Mock(return_value=str(tmp_path))
    return controller


def _tasks(controller, operation_id):
    return [
        call
        for call in controller.testing_model.take_screenshot_async.call_args_list
        if call.kwargs["_operation_id"] == operation_id
    ]


def _metadata(call):
    return OperationMetadata(
        version=1,
        operation_id=call.kwargs["_operation_id"],
        operation_kind=call.kwargs["_operation_kind"],
        method_name="take_screenshot",
        task_id=call.kwargs["_operation_task_id"],
        unit_id=call.kwargs["_operation_unit_id"],
        target_id=call.kwargs["_operation_target_id"],
        expected_artifact_path=call.kwargs["_operation_expected_artifact_path"],
        generation_token=call.kwargs["_operation_generation_token"],
    )


def _success(call, *, path=None, device=None):
    return {
        "success": True,
        "device_ip": device or call.args[0],
        "screenshot_path": path or call.args[1],
    }


def _write_png(call):
    path = Path(call.args[1])
    path.write_bytes(PNG_HEADER + b"gate-a")
    return path


def test_screenshot_filename_starts_with_device_and_uses_short_collision_suffix(tmp_path):
    controller = _controller(tmp_path)
    with patch("controllers._media.datetime") as datetime_mock:
        datetime_mock.now.return_value.strftime.return_value = "20260728_143205"

        first = controller._screenshot_path(str(tmp_path), "192.168.1.20:5555")
        second = controller._screenshot_path(str(tmp_path), "192.168.1.20:5555")

    assert Path(first).name == "192_168_1_20_5555_20260728_143205.png"
    assert Path(second).name == "192_168_1_20_5555_20260728_143205_2.png"


def test_two_overlapping_screenshot_batches_are_isolated_when_callbacks_interleave(tmp_path):
    controller = _controller(tmp_path)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda *args: args[-1](),
    ):
        operation_a = controller.take_screenshot(["target-a", "target-b"])
        operation_b = controller.take_screenshot(["target-a", "target-c"])
        tasks_a = _tasks(controller, operation_a)
        tasks_b = _tasks(controller, operation_b)

        assert operation_a != operation_b
        assert {call.kwargs["_operation_id"] for call in tasks_a} == {operation_a}
        assert {call.kwargs["_operation_id"] for call in tasks_b} == {operation_b}
        assert {call.kwargs["_operation_task_id"] for call in tasks_a}.isdisjoint(
            {call.kwargs["_operation_task_id"] for call in tasks_b}
        )
        assert {call.args[1] for call in tasks_a}.isdisjoint({call.args[1] for call in tasks_b})

        for call in (*tasks_a, *tasks_b):
            _write_png(call)

        order = (tasks_a[1], tasks_b[0], tasks_a[0], tasks_b[1])
        terminals = []
        for call in order:
            terminal = controller._process_screenshot_operation_result(
                _success(call),
                _metadata(call),
            )
            if terminal is not None:
                terminals.append(terminal)

    assert {terminal.operation_id for terminal in terminals} == {operation_a, operation_b}
    assert all(terminal.state is OperationState.SUCCEEDED for terminal in terminals)
    assert controller.operation_manager.active_count == 0
    assert controller.signals.screenshot_batch_ready.emit.call_count == 2
    batch_sets = {
        frozenset(call.args[0])
        for call in controller.signals.screenshot_batch_ready.emit.call_args_list
    }
    assert batch_sets == {
        frozenset(call.args[1] for call in tasks_a),
        frozenset(call.args[1] for call in tasks_b),
    }
    assert controller.signals.operation_completed.emit.call_count == 2
    assert all(
        call.args[0] == "screenshot" and call.args[1] is True
        for call in controller.signals.operation_completed.emit.call_args_list
    )


def test_screenshot_partial_failure_is_not_reported_as_success(tmp_path):
    controller = _controller(tmp_path)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda *args: args[-1](),
    ):
        operation_id = controller.take_screenshot(["target-a", "target-b", "target-c"])
        success_task, failed_task, missing_task = _tasks(controller, operation_id)
        _write_png(success_task)

        controller._process_screenshot_operation_result(
            _success(success_task),
            _metadata(success_task),
        )
        controller._process_screenshot_operation_result(
            {"success": False, "device_ip": failed_task.args[0], "error": "offline"},
            _metadata(failed_task),
        )
        terminal = controller._process_screenshot_operation_result(
            _success(missing_task),
            _metadata(missing_task),
        )

    assert terminal.state is OperationState.PARTIAL
    assert len(terminal.artifacts) == 1
    controller.signals.screenshot_captured.emit.assert_called_once_with(
        success_task.args[0],
        success_task.args[1],
    )
    controller.signals.operation_completed.emit.assert_called_once()
    completed = controller.signals.operation_completed.emit.call_args.args
    assert completed[0] == "screenshot"
    assert completed[1] is False
    assert "1/3 succeeded" in completed[2]
    controller.signals.screenshot_batch_ready.emit.assert_called_once_with(
        [success_task.args[1]]
    )
    assert controller.operation_manager.active_count == 0


def test_screenshot_all_failure_creates_no_artifact_or_batch_signal(tmp_path):
    controller = _controller(tmp_path)
    operation_id = controller.take_screenshot(["target-a", "target-b"])
    first, second = _tasks(controller, operation_id)

    controller._process_screenshot_operation_result(
        {"success": False, "device_ip": first.args[0], "error": "offline"},
        _metadata(first),
    )
    terminal = controller._process_screenshot_operation_result(
        _success(second),
        _metadata(second),
    )

    assert terminal.state is OperationState.FAILED
    assert terminal.artifacts == ()
    controller.signals.screenshot_captured.emit.assert_not_called()
    controller.signals.screenshot_batch_ready.emit.assert_not_called()
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller.signals.operation_completed.emit.call_args.args[1] is False
    assert controller.operation_manager.active_count == 0


def test_screenshot_duplicate_and_late_callbacks_have_no_duplicate_side_effects(tmp_path):
    controller = _controller(tmp_path)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda *args: args[-1](),
    ):
        operation_id = controller.take_screenshot(["target-a", "target-b"])
        first, second = _tasks(controller, operation_id)
        _write_png(first)
        _write_png(second)
        first_result = _success(first)
        first_meta = _metadata(first)

        assert controller._process_screenshot_operation_result(first_result, first_meta) is None
        assert controller._process_screenshot_operation_result(first_result, first_meta) is None
        terminal = controller._process_screenshot_operation_result(
            _success(second),
            _metadata(second),
        )
        counts = (
            controller.signals.screenshot_captured.emit.call_count,
            controller.signals.operation_completed.emit.call_count,
            controller.signals.screenshot_batch_ready.emit.call_count,
        )

        assert controller._process_screenshot_operation_result(first_result, first_meta) is None

    assert terminal.state is OperationState.SUCCEEDED
    assert counts == (2, 1, 1)
    assert (
        controller.signals.screenshot_captured.emit.call_count,
        controller.signals.operation_completed.emit.call_count,
        controller.signals.screenshot_batch_ready.emit.call_count,
    ) == counts


def test_screenshot_result_must_match_target_expected_path_and_png_signature(tmp_path):
    controller = _controller(tmp_path)
    operation_id = controller.take_screenshot(["target-a", "target-b", "target-c"])
    wrong_target, wrong_path, invalid_png = _tasks(controller, operation_id)
    Path(invalid_png.args[1]).write_bytes(b"not-a-png")
    other_path = tmp_path / "other.png"
    other_path.write_bytes(PNG_HEADER)

    controller._process_screenshot_operation_result(
        _success(wrong_target, device="another-target"),
        _metadata(wrong_target),
    )
    controller._process_screenshot_operation_result(
        _success(wrong_path, path=str(other_path)),
        _metadata(wrong_path),
    )
    terminal = controller._process_screenshot_operation_result(
        _success(invalid_png),
        _metadata(invalid_png),
    )

    assert terminal.state is OperationState.FAILED
    assert terminal.artifacts == ()
    controller.signals.screenshot_captured.emit.assert_not_called()
    assert controller.operation_manager.active_count == 0


def test_screenshot_submission_failures_are_terminal_without_waiting_for_callbacks(tmp_path):
    controller = _controller(tmp_path)
    controller.testing_model.take_screenshot_async.side_effect = RuntimeError("pool stopped")

    operation_id = controller.take_screenshot(["target-a", "target-b"])

    assert operation_id
    assert controller.operation_manager.get(operation_id) is None
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller.signals.operation_completed.emit.call_args.args[1] is False
    controller.signals.screenshot_captured.emit.assert_not_called()
    controller.signals.screenshot_batch_ready.emit.assert_not_called()


def test_screenshot_cancel_midflight_is_partial_and_late_results_are_ignored(tmp_path):
    controller = _controller(tmp_path)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda *args: args[-1](),
    ):
        operation_id = controller.take_screenshot(["target-a", "target-b"])
        first, second = _tasks(controller, operation_id)
        _write_png(first)
        _write_png(second)
        controller._process_screenshot_operation_result(
            _success(first),
            _metadata(first),
        )

        assert controller.cancel_screenshot(operation_id) is True
        counts = (
            controller.signals.screenshot_captured.emit.call_count,
            controller.signals.operation_completed.emit.call_count,
            controller.signals.screenshot_batch_ready.emit.call_count,
        )
        assert controller.cancel_screenshot(operation_id) is False
        assert (
            controller._process_screenshot_operation_result(
                _success(second),
                _metadata(second),
            )
            is None
        )

    assert counts == (1, 1, 1)
    assert controller.signals.operation_completed.emit.call_args.args[1] is False
    assert "1/2 succeeded" in controller.signals.operation_completed.emit.call_args.args[2]
    assert (
        controller.signals.screenshot_captured.emit.call_count,
        controller.signals.operation_completed.emit.call_count,
        controller.signals.screenshot_batch_ready.emit.call_count,
    ) == counts
    assert controller.operation_manager.active_count == 0


def test_screenshot_cancel_uses_results_written_after_its_initial_snapshot(tmp_path):
    controller = _controller(tmp_path)
    operation_id = controller.take_screenshot(["target-a", "target-b"])
    first, _second = _tasks(controller, operation_id)
    _write_png(first)
    initial_snapshot_read = Event()
    release_cancel = Event()
    real_get = controller.operation_manager.get
    cancel_results = []
    cancel_errors = []

    def block_after_initial_cancel_snapshot(candidate_id, **kwargs):
        snapshot = real_get(candidate_id, **kwargs)
        if (
            candidate_id == operation_id
            and kwargs.get("expected_kind") == "screenshot"
            and kwargs.get("expected_generation") is None
        ):
            initial_snapshot_read.set()
            assert release_cancel.wait(timeout=2)
        return snapshot

    def cancel():
        try:
            cancel_results.append(controller.cancel_screenshot(operation_id))
        except BaseException as exc:  # pragma: no cover - asserted through cancel_errors
            cancel_errors.append(exc)

    controller.operation_manager.get = Mock(side_effect=block_after_initial_cancel_snapshot)
    cancel_thread = Thread(target=cancel)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda *args: args[-1](),
    ):
        cancel_thread.start()
        assert initial_snapshot_read.wait(timeout=2)
        assert (
            controller._process_screenshot_operation_result(
                _success(first),
                _metadata(first),
            )
            is None
        )
        release_cancel.set()
        cancel_thread.join(timeout=2)

    assert cancel_thread.is_alive() is False
    assert cancel_errors == []
    assert cancel_results == [True]
    assert controller.operation_manager.active_count == 0
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller.signals.operation_completed.emit.call_args.args[1] is False
    assert "1/2 succeeded" in controller.signals.operation_completed.emit.call_args.args[2]


def test_cancel_between_artifact_and_result_does_not_publish_cancelled_artifact(tmp_path):
    controller = _controller(tmp_path)
    operation_id = controller.take_screenshot(["target-a"])
    task = _tasks(controller, operation_id)[0]
    _write_png(task)
    artifact_recorded = Event()
    release_result = Event()
    real_record = controller.operation_manager.record_unit_result
    callback_errors = []

    def block_before_result(*args, **kwargs):
        artifact_recorded.set()
        assert release_result.wait(timeout=2)
        return real_record(*args, **kwargs)

    def handle_result():
        try:
            controller._process_screenshot_operation_result(
                _success(task),
                _metadata(task),
            )
        except BaseException as exc:  # pragma: no cover - asserted through callback_errors
            callback_errors.append(exc)

    controller.operation_manager.record_unit_result = Mock(side_effect=block_before_result)
    callback_thread = Thread(target=handle_result)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda *args: args[-1](),
    ):
        callback_thread.start()
        assert artifact_recorded.wait(timeout=2)
        assert controller.cancel_screenshot(operation_id) is True
        release_result.set()
        callback_thread.join(timeout=2)

    assert callback_thread.is_alive() is False
    assert callback_errors == []
    assert controller.operation_manager.active_count == 0
    controller.signals.screenshot_captured.emit.assert_not_called()
    controller.signals.screenshot_batch_ready.emit.assert_not_called()
    controller.signals.operation_completed.emit.assert_called_once()
    assert "0/1 succeeded" in controller.signals.operation_completed.emit.call_args.args[2]
    assert "1 cancelled" in controller.signals.operation_completed.emit.call_args.args[2]


def test_screenshot_filters_empty_and_duplicate_targets(tmp_path):
    controller = _controller(tmp_path)

    operation_id = controller.take_screenshot(["", "target-a", "target-a", None])

    assert len(_tasks(controller, operation_id)) == 1


def test_screenshot_metadata_mismatch_fails_closed_and_emits_compat_terminal(tmp_path):
    controller = _controller(tmp_path)
    controller._operation_handler_map = {
        "take_screenshot": controller._process_screenshot_operation_result
    }
    operation_id = controller.take_screenshot(["target-a"])
    task = _tasks(controller, operation_id)[0]
    metadata = _metadata(task)

    controller._route_operation_response(
        "unexpected_method",
        _success(task),
        metadata,
    )

    assert controller.operation_manager.get(operation_id) is None
    controller.signals.screenshot_captured.emit.assert_not_called()
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller.signals.operation_completed.emit.call_args.args[1] is False


def test_old_screenshot_generation_cannot_mutate_reused_operation_id(tmp_path):
    controller = _controller(tmp_path)
    controller._operation_handler_map = {
        "take_screenshot": controller._process_screenshot_operation_result
    }
    controller._generate_operation_id = Mock(side_effect=("shared-id", "old-task"))
    old_id = controller.take_screenshot(["target-a"])
    old_call = _tasks(controller, old_id)[0]
    old_snapshot = controller.operation_manager.get(old_id)
    controller.operation_manager.finish(
        old_id,
        OperationState.FAILED,
        expected_kind="screenshot",
        expected_generation=old_snapshot.generation_token,
    )
    new_generation = object()
    new_snapshot = controller.operation_manager.begin(
        "screenshot",
        operation_id=old_id,
        unit_ids=("new-task",),
        generation_token=new_generation,
    )
    current = controller.operation_manager.mark_running(
        old_id,
        expected_kind="screenshot",
        expected_generation=new_generation,
    )

    assert (
        controller._route_operation_response(
            "take_screenshot",
            _success(old_call),
            _metadata(old_call),
        )
        is None
    )
    assert current is not None
    assert current.generation_token is new_snapshot.generation_token
    assert controller.operation_manager.get(old_id) == current
    assert controller.operation_manager.get(old_id).unit_results == ()
    controller.signals.operation_completed.emit.assert_not_called()


def test_screenshot_result_without_generation_fails_closed(tmp_path):
    controller = _controller(tmp_path)
    controller._operation_handler_map = {
        "take_screenshot": controller._process_screenshot_operation_result
    }
    operation_id = controller.take_screenshot(["target-a"])
    task = _tasks(controller, operation_id)[0]
    metadata = _metadata(task)
    metadata = OperationMetadata(
        version=metadata.version,
        operation_id=metadata.operation_id,
        operation_kind=metadata.operation_kind,
        method_name=metadata.method_name,
        task_id=metadata.task_id,
        unit_id=metadata.unit_id,
        target_id=metadata.target_id,
        expected_artifact_path=metadata.expected_artifact_path,
        generation_token=None,
    )

    terminal = controller._route_operation_response(
        "take_screenshot",
        _success(task),
        metadata,
    )

    assert terminal.state is OperationState.FAILED
    assert controller.operation_manager.active_count == 0
    controller.signals.screenshot_captured.emit.assert_not_called()
    controller.signals.operation_completed.emit.assert_called_once()


def test_screenshot_cas_loss_before_artifact_record_emits_no_success(tmp_path):
    controller = _controller(tmp_path)
    operation_id = controller.take_screenshot(["target-a"])
    task = _tasks(controller, operation_id)[0]
    _write_png(task)
    snapshot = controller.operation_manager.get(operation_id)
    real_add_artifact = controller.operation_manager.add_artifact

    def finish_before_add(*args, **kwargs):
        controller.operation_manager.finish(
            operation_id,
            OperationState.FAILED,
            expected_kind=snapshot.kind,
            expected_generation=snapshot.generation_token,
        )
        return real_add_artifact(*args, **kwargs)

    controller.operation_manager.add_artifact = Mock(side_effect=finish_before_add)

    assert (
        controller._process_screenshot_operation_result(
            _success(task),
            _metadata(task),
        )
        is None
    )
    controller.signals.screenshot_captured.emit.assert_not_called()
    controller.signals.operation_completed.emit.assert_not_called()


def test_screenshot_batch_is_published_without_creating_or_owning_gui():
    controller = ADBMediaMixin.__new__(ADBMediaMixin)
    controller.signals = Mock()

    controller._emit_screenshot_batch(["shot.png", "", "second.png"])

    controller.signals.screenshot_batch_ready.emit.assert_called_once_with(
        ["shot.png", "second.png"]
    )


def test_screenshot_batch_is_skipped_while_shutting_down():
    controller = ADBMediaMixin.__new__(ADBMediaMixin)
    controller._shutting_down = True
    controller.signals = Mock()

    controller._emit_screenshot_batch(["shot.png"])

    controller.signals.screenshot_batch_ready.emit.assert_not_called()


def test_auto_pull_is_skipped_while_shutting_down():
    controller = ADBMediaMixin.__new__(ADBMediaMixin)
    controller._shutting_down = True
    controller.screen_records = Mock()
    controller.advanced_model = Mock()

    controller._auto_pull("device-1", "batch-1")

    controller.screen_records.active.assert_not_called()
    controller.advanced_model.pull_recorded_video_async.assert_not_called()
