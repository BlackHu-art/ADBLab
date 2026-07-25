from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt

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
    controller._active_viewers = []
    controller._get_screenshot_dir = Mock(return_value=str(tmp_path))
    controller._show_screenshot_viewer = Mock()
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


def test_two_overlapping_screenshot_batches_are_isolated_when_callbacks_interleave(tmp_path):
    controller = _controller(tmp_path)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda _delay, callback: callback(),
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
        assert {call.args[1] for call in tasks_a}.isdisjoint(
            {call.args[1] for call in tasks_b}
        )

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
    assert controller._show_screenshot_viewer.call_count == 2
    viewer_sets = {
        frozenset(call.args[0])
        for call in controller._show_screenshot_viewer.call_args_list
    }
    assert viewer_sets == {
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
        side_effect=lambda _delay, callback: callback(),
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
    controller._show_screenshot_viewer.assert_called_once_with([success_task.args[1]])
    assert controller.operation_manager.active_count == 0


def test_screenshot_all_failure_creates_no_artifact_signal_or_viewer(tmp_path):
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
    controller._show_screenshot_viewer.assert_not_called()
    controller.signals.operation_completed.emit.assert_called_once()
    assert controller.signals.operation_completed.emit.call_args.args[1] is False
    assert controller.operation_manager.active_count == 0


def test_screenshot_duplicate_and_late_callbacks_have_no_duplicate_side_effects(tmp_path):
    controller = _controller(tmp_path)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda _delay, callback: callback(),
    ):
        operation_id = controller.take_screenshot(["target-a", "target-b"])
        first, second = _tasks(controller, operation_id)
        _write_png(first)
        _write_png(second)
        first_result = _success(first)
        first_meta = _metadata(first)

        assert (
            controller._process_screenshot_operation_result(first_result, first_meta)
            is None
        )
        assert (
            controller._process_screenshot_operation_result(first_result, first_meta)
            is None
        )
        terminal = controller._process_screenshot_operation_result(
            _success(second),
            _metadata(second),
        )
        counts = (
            controller.signals.screenshot_captured.emit.call_count,
            controller.signals.operation_completed.emit.call_count,
            controller._show_screenshot_viewer.call_count,
        )

        assert (
            controller._process_screenshot_operation_result(first_result, first_meta)
            is None
        )

    assert terminal.state is OperationState.SUCCEEDED
    assert counts == (2, 1, 1)
    assert (
        controller.signals.screenshot_captured.emit.call_count,
        controller.signals.operation_completed.emit.call_count,
        controller._show_screenshot_viewer.call_count,
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
    controller._show_screenshot_viewer.assert_not_called()


def test_screenshot_cancel_midflight_is_partial_and_late_results_are_ignored(tmp_path):
    controller = _controller(tmp_path)
    with patch(
        "controllers._media.QTimer.singleShot",
        side_effect=lambda _delay, callback: callback(),
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
            controller._show_screenshot_viewer.call_count,
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
        controller._show_screenshot_viewer.call_count,
    ) == counts
    assert controller.operation_manager.active_count == 0


def test_screenshot_filters_empty_and_duplicate_targets_and_uses_no_legacy_shared_state(tmp_path):
    controller = _controller(tmp_path)

    operation_id = controller.take_screenshot(["", "target-a", "target-a", None])

    assert len(_tasks(controller, operation_id)) == 1
    assert not hasattr(controller, "_screenshot_paths")
    assert not hasattr(controller, "_screenshot_remaining")
    assert not hasattr(controller, "_screenshot_devices")
    assert not hasattr(controller, "_pending_ops")


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


def test_screenshot_viewer_is_owned_by_injected_main_window():
    controller = ADBMediaMixin.__new__(ADBMediaMixin)
    controller.window_parent = Mock()
    controller.log_service = Mock()
    controller._active_viewers = []
    viewer = Mock()

    with patch("controllers._media.ScreenshotViewer", return_value=viewer) as viewer_cls:
        controller._show_screenshot_viewer(["shot.png"])

    viewer_cls.assert_called_once_with(["shot.png"], parent=controller.window_parent)
    viewer.setAttribute.assert_called_once_with(Qt.WA_DeleteOnClose)
    viewer.installEventFilter.assert_called_once_with(controller.window_parent)
    viewer.show.assert_called_once_with()
    created_message = controller.log_service.log.call_args.args[1]
    assert "dialog=ScreenshotViewer" in created_message
    assert "phase=created" in created_message
    assert "shot.png" not in created_message

    destroyed_handler = viewer.destroyed.connect.call_args.args[0]
    destroyed_handler()

    assert controller._active_viewers == []
    closed_message = controller.log_service.log.call_args.args[1]
    assert "phase=closed" in closed_message
