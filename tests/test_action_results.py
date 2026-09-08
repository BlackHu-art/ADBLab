"""验证用户操作结果脱离日志后的身份、终态与完整正文。"""

from adblab.application.action_results import (
    ActionEnvelope,
    ActionResults,
    ActionSpec,
    capture_action_job,
    report_action_message,
)


def test_device_labels_are_frozen_and_duplicate_targets_keep_aligned_names():
    store = ActionResults(lambda _result: None)
    store.set_target_labels({"demo-c": "设备 3 · Phone", "demo-a": "设备 1"})
    jobs = []
    store.run(
        ActionSpec("query", "system.shell", "查询"), ("demo-c", "demo-c", "demo-a"),
        lambda: jobs.append(capture_action_job("query_async", "demo-c")),
        target_names=("Phone", "Phone", "Tablet"),
    )
    store.set_target_labels({"demo-c": "设备 3 · New name"})
    store.complete(jobs[0], {"success": True, "output": "demo-c result"})
    result = store.recent()[0]
    assert result.targets == ("demo-c", "demo-a")
    assert result.target_names == ("Phone", "Tablet")
    assert result.items[0].label == "设备 3 · Phone"
    assert result.items[0].detail == "设备 3 · Phone result"


def test_device_counts_group_chained_commands_and_preserve_mixed_outcomes():
    store = ActionResults(lambda _result: None)
    jobs = []
    targets = ("demo-a", "demo-b", "demo-c")
    store.run(
        ActionSpec("query", "system.shell", "查询"), targets,
        lambda: jobs.extend(capture_action_job("query_async", target)
                            for target in ("demo-a", "demo-a", "demo-b", "demo-c")),
    )
    for job, payload in zip(jobs, (
        {"success": True}, {"success": True}, {"success": False}, {"cancelled": True},
    )):
        store.complete(job, payload)
    assert store.recent()[0].state == "partial"
    assert ActionResults.target_outcomes(store.recent()[0]) == {
        "succeeded": 1, "failed": 1, "cancelled": 1,
    }


def test_progress_is_not_success_and_multiple_targets_finish_once():
    events = []
    store = ActionResults(events.append)
    jobs = []

    def submit():
        report_action_message(True, "开始执行")
        jobs.extend(capture_action_job("query_async", target) for target in ("demo-a", "demo-b"))

    store.run(ActionSpec("query", "apps.diagnostics", "内存", "text"), ("demo-a", "demo-b"), submit)
    assert all(event.state == "running" for event in events)
    store.complete(jobs[1], {"success": False, "error": "demo-b offline"})
    assert events[-1].state == "running"
    store.complete(jobs[0], {"success": True, "output": "x" * 100000 + "END"})
    assert events[-1].state == "partial"
    assert events[-1].items[1].detail.endswith("END")
    assert events[-1].items[0].detail == "设备 2 offline"
    assert len([event for event in events if event.state != "running"]) == 1
    count = len(events)
    store.complete(jobs[0], {"success": False})
    assert len(events) == count


def test_callback_semantic_failure_overrides_transport_success():
    events = []
    store = ActionResults(events.append)
    jobs = []
    store.run(
        ActionSpec("connect", "devices", "连接"),
        ("demo-a",),
        lambda: jobs.append(capture_action_job("connect_async", "demo-a")),
    )
    with store.scope(jobs[0].request_id, jobs[0]):
        report_action_message(False, "连接失败")
    store.complete(jobs[0], {"success": True, "output": "unable to connect"})
    assert events[-1].state == "failed"
    assert "连接失败" in events[-1].items[0].detail


def test_chained_submission_keeps_request_running_until_child_finishes():
    events, jobs = [], []
    store = ActionResults(events.append)
    store.run(
        ActionSpec("install", "apps.packages", "安装"),
        ("demo",),
        lambda: jobs.append(capture_action_job("install_async", "demo")),
    )
    with store.scope(jobs[0].request_id, jobs[0]):
        jobs.append(capture_action_job("install_async", "demo"))
    store.complete(jobs[0], {"success": True})
    assert events[-1].state == "running"
    store.complete(jobs[1], {"success": True})
    assert events[-1].state == "succeeded"


def test_busy_action_is_not_resubmitted_and_shutdown_ignores_late_result():
    events, calls, jobs = [], [], []
    store = ActionResults(events.append)
    spec = ActionSpec("query", "system.shell", "查询")
    store.run(spec, ("demo",), lambda: jobs.append(capture_action_job("query_async", "demo")))
    store.run(spec, ("changed",), lambda: calls.append(True))
    assert calls == []
    assert len(store.recent()) == 1
    store.close()
    count = len(events)
    store.complete(jobs[0], {"success": True})
    assert len(events) == count


def test_cancelled_picker_has_no_success_history_and_scope_does_not_leak():
    events = []
    store = ActionResults(events.append)
    store.run(ActionSpec("apk", "apps.packages", "APK"), (), lambda: None)
    assert events[-1].state == "cancelled"
    assert capture_action_job("background_async", "demo") is None


def test_text_result_uses_output_and_omits_unrelated_device_metadata():
    events, jobs = [], []
    store = ActionResults(events.append)
    store.run(
        ActionSpec("query", "system.shell", "查询", "text"),
        ("demo",),
        lambda: jobs.append(capture_action_job("query_async", "demo")),
    )
    store.complete(
        jobs[0],
        {
            "success": True,
            "output": "Query result",
            "Model": "Test model",
            "device_ip": "demo",
            "Serial Number": "private",
            "Mac": "private-network",
        },
    )
    assert events[-1].state == "succeeded"
    assert events[-1].items[0].detail == "Query result"


def test_async_model_preserves_action_identity_and_original_operation_protocol(qt_application):
    from core.perf_trace import split_perf
    from models.adb_model import ADBModelCore, async_command

    class Model(ADBModelCore):
        @async_command
        def query_async(self, target):
            return {"success": True, "device_ip": target, "output": "answer"}

    class Pool:
        def start(self, task):
            task.run()

    model = Model()
    model.thread_pool = Pool()
    responses = []
    model.command_finished.connect(lambda name, result: responses.append((name, result)))
    store = ActionResults(lambda result: None)
    store.run(
        ActionSpec("query", "system.shell", "查询"), ("demo",), lambda: model.query_async("demo")
    )
    assert isinstance(responses[0][1], ActionEnvelope)
    envelope = responses[0][1]
    assert envelope.job.target == "demo"
    payload, perf = split_perf(envelope.payload)
    assert payload["output"] == "answer"
    assert perf is not None


def test_every_controller_signal_map_has_a_result_destination():
    import ast
    from pathlib import Path

    from controllers.action_catalog import ACTION_SIGNALS

    tree = ast.parse(Path("gui/main_frame.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "_device_signal_map",
            "_app_signal_map",
            "_testing_signal_map",
            "_system_signal_map",
        }:
            names.update(
                item.attr
                for item in ast.walk(node)
                if isinstance(item, ast.Attribute)
                and isinstance(item.value, ast.Name)
                and item.value.id == "LP"
            )
    assert names == set(ACTION_SIGNALS)


def test_native_screenshot_partial_batch_keeps_last_successful_unit_successful(
    qt_application, tmp_path
):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from adblab.application.envelope import attach_operation_metadata
    from controllers.action_catalog import ACTION_SIGNALS
    from models.adb_model import ADBModelCore, async_command
    from tests.test_phase2_screenshot_gate import _controller, _write_png

    class Model(ADBModelCore):
        @async_command
        def take_screenshot_async(self, target, path, **kwargs):
            return {"success": True}

    tasks, events = [], []
    model = Model()
    model.thread_pool = SimpleNamespace(start=tasks.append)
    controller = _controller(tmp_path)
    from controllers.signals import ADBControllerSignals

    controller.signals = ADBControllerSignals()
    controller.testing_model = model
    controller._settings = Mock()
    controller._settings.get.return_value = 100
    controller._build_handler_map()
    controller.action_results = ActionResults(events.append)
    controller.action_results.run(
        ACTION_SIGNALS["screenshot_requested"],
        ("demo-a", "demo-b"),
        lambda: controller.take_screenshot(["demo-a", "demo-b"]),
    )
    assert len(tasks) == 2
    assert all(task.action_job is not None for task in tasks)
    for index, task in enumerate(tasks):
        if index:
            _write_png(SimpleNamespace(args=task.args))
        payload = {
            "success": bool(index),
            "device_ip": task.args[0],
            "screenshot_path": task.args[1],
            "error": "" if index else "capture failed",
        }
        response = ActionEnvelope(
            attach_operation_metadata(payload, task.metadata), task.action_job
        )
        controller._handle_async_response("take_screenshot_async", response)
    assert events[-1].state == "partial"
    assert [item.state for item in events[-1].items] == ["failed", "succeeded"]
    assert events[-1].items[1].artifacts == (tasks[1].args[1],)
    assert controller.operation_manager.active_count == 0


def test_model_submission_error_ends_action_without_leaving_a_running_job(qt_application):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from models.adb_model import ADBModelCore, async_command

    class Model(ADBModelCore):
        @async_command
        def query_async(self, target):
            return {"success": True}

    model = Model()
    model.thread_pool = SimpleNamespace(start=Mock(side_effect=RuntimeError("queue unavailable")))
    events = []
    store = ActionResults(events.append)
    model.command_finished.connect(lambda _name, result: store.complete(result.job, result.payload))
    import pytest

    with pytest.raises(RuntimeError):
        store.run(
            ActionSpec("query", "system.shell", "查询"),
            ("demo",),
            lambda: model.query_async("demo"),
        )
    assert events[-1].state == "failed"
    assert len(events[-1].items) == 1


def test_shutdown_during_modal_submission_does_not_access_cleared_request():
    store = ActionResults(lambda _result: None)
    store.run(ActionSpec("picker", "apps.packages", "APK"), (), store.close)
    assert store.recent() == ()


def test_automatic_recording_pull_creates_one_media_result_per_device(qt_application, tmp_path):
    from types import SimpleNamespace

    from adblab.application.screen_record import ScreenRecordUseCase
    from controllers._media import ADBMediaMixin
    from models.adb_model import ADBModelCore, async_command

    class Model(ADBModelCore):
        @async_command
        def pull_recorded_video_async(self, device, remote_path, save_dir, filename, **kwargs):
            return {"success": True}

    tasks, events = [], []
    model = Model()
    model.thread_pool = SimpleNamespace(start=tasks.append)
    controller = SimpleNamespace(
        screen_records=ScreenRecordUseCase(),
        advanced_model=model,
        action_results=ActionResults(events.append),
    )
    for device in ("demo-a", "demo-b"):
        controller.screen_records.start(device, "batch", str(tmp_path), 30)
        controller.screen_records.mark_started(device, "batch", "/remote.mp4", f"{device}.mp4")
        info = controller.screen_records.active(device)
        assert ADBMediaMixin._submit_recording_pull(controller, device, info)
        assert not ADBMediaMixin._submit_recording_pull(controller, device, info)
    assert len(tasks) == 2
    assert tasks[0].action_job.request_id != tasks[1].action_job.request_id
    for task in reversed(tasks):
        path = str(tmp_path / task.args[3])
        controller.action_results.complete(task.action_job, {"success": True, "local_path": path})
        result = events[-1]
        assert result.spec.section == "apps.media"
        assert result.targets == (task.args[0],)
        assert result.state == "succeeded"
        assert result.items[0].artifacts == (path,)


def test_notes_are_bounded_by_source_and_rejected_after_close():
    events = []
    store = ActionResults(events.append, capacity=2)
    spec = ActionSpec("notes:manager", "apps.manager", "应用管理", "notes")
    for index in range(220):
        store.record_note(spec, ("demo-a",), f"demo-a: {index}", "info")
    result = store.recent()[0]
    assert result.state == "recorded"
    assert len(result.items) == 200
    assert result.items[0].detail.endswith(": 20")
    assert all("demo-a" not in item.detail for item in result.items)
    store.record_note(spec, ("demo-b",), "Second device", "error")
    assert len(store.recent()) == 2
    store.close()
    count = len(events)
    assert store.record_note(spec, (), "late event", "error") is None
    assert len(events) == count
