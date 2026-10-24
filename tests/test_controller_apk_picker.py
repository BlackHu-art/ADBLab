"""验证 APK 入口使用注入选择器，并保留请求终态及提交参数。"""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QFileDialog, QWidget

from controllers import ADBController
from gui.adapters.apk_file_picker import QtApkFilePicker
from gui.close_controller import CloseController
from services.apps.apk_selection import ApkFilePicker
from services.tasks.action_results import ActionResults, ActionSpec, capture_action_job

ENTRIES = ("install_apk", "batch_install_apk", "parse_apk_info")


@pytest.fixture(autouse=True)
def forbid_native_dialogs(monkeypatch):
    for method in ("getOpenFileName", "getOpenFileNames"):
        monkeypatch.setattr(
            QFileDialog, method, Mock(side_effect=AssertionError("unexpected dialog")),
        )


@pytest.fixture
def controller():
    instance = ADBController.__new__(ADBController)
    instance.apk_picker = Mock(spec=ApkFilePicker)
    instance.apk_picker.select_one.return_value = None
    instance.apk_picker.select_many.return_value = ()
    instance.signals = Mock()
    instance.log_service = Mock()
    instance.app_model = Mock()
    instance._shutting_down = False
    instance._start_install_batch = Mock(return_value="operation-test")
    instance.action_results = ActionResults(lambda _result: None)
    return instance


def run_entry(controller, entry, devices=None):
    targets = ["device-a"] if devices is None else devices
    return controller.action_results.run(
        ActionSpec(entry, "apps.packages", "APK"), tuple(targets),
        lambda: (getattr(controller, entry)() if entry == "parse_apk_info"
                 else getattr(controller, entry)(targets)),
    )


def shutdown_controller(controller):
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(controller.shutdown).result(timeout=5)


def closing_frame(controller, events):
    def observe(stage):
        events.append((stage, controller.action_results.recent()))

    return SimpleNamespace(
        adb_controller=controller,
        _unbind_window_screen=Mock(), _flush_pending_layout_state=Mock(),
        _close_ready=False, _close_started=False, _closing=False,
        SHUTDOWN_DEADLINE_SECONDS=0.5, SHUTDOWN_FINALIZER_RESERVE_SECONDS=0.05,
        log_service=Mock(), setWindowTitle=Mock(), setEnabled=Mock(),
        task_supervisor=SimpleNamespace(
            begin_application_shutdown=lambda: observe("begin"),
            stop_all_async=lambda **_kwargs: observe("stop"),
        ),
        _register_application_shutdown_tasks=lambda: observe("register"),
        _prepare_ui_for_shutdown=lambda: observe("prepare"),
    )


@pytest.mark.ui
def test_explicit_picker_is_kept_even_when_falsey(monkeypatch):
    class FalseyPicker:
        select_one = Mock(return_value=None)
        select_many = Mock(return_value=())

        def __bool__(self):
            return False

    monkeypatch.setattr("models.device_store.DeviceStore.load", Mock())
    picker = FalseyPicker()
    controller = ADBController(Mock(), apk_picker=picker)
    try:
        assert controller.apk_picker is picker
        picker.select_one.assert_not_called()
        controller.parse_apk_info()
        picker.select_one.assert_called_once_with()
        QFileDialog.getOpenFileName.assert_not_called()
        QFileDialog.getOpenFileNames.assert_not_called()
    finally:
        shutdown_controller(controller)


@pytest.mark.ui
def test_default_picker_is_lazy_and_uses_late_window_owner(monkeypatch):
    monkeypatch.setattr("models.device_store.DeviceStore.load", Mock())
    chooser = Mock(return_value=("", ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", chooser)
    controller = ADBController(Mock())
    parents = [None, QWidget(), QWidget()]
    try:
        assert isinstance(controller.apk_picker, QtApkFilePicker)
        chooser.assert_not_called()
        for parent in parents:
            controller.window_owner = parent
            controller.parse_apk_info()
            assert chooser.call_args.args[0] is parent
        assert chooser.call_count == 3
    finally:
        shutdown_controller(controller)
        for parent in parents[1:]:
            parent.deleteLater()


@pytest.mark.parametrize("entry", ENTRIES[:2])
def test_missing_devices_never_opens_install_picker(controller, entry):
    assert run_entry(controller, entry, []) is None
    controller.apk_picker.select_one.assert_not_called()
    controller.apk_picker.select_many.assert_not_called()
    controller._start_install_batch.assert_not_called()
    result = controller.action_results.recent()[0]
    assert result.state == "failed"
    assert "No devices selected" in result.message


@pytest.mark.parametrize("entry", ENTRIES)
def test_cancel_preserves_each_entry_result(controller, entry):
    assert run_entry(controller, entry) is None
    result = controller.action_results.recent()[0]
    if entry == "parse_apk_info":
        assert result.state == "cancelled"
        controller.signals.operation_completed.emit.assert_not_called()
    else:
        assert result.state == "failed"
        assert "APK selection canceled" in result.message
        controller.signals.operation_completed.emit.assert_called_once_with(
            "install" if entry == "install_apk" else "batch_install",
            False, "APK selection canceled",
        )
    controller._start_install_batch.assert_not_called()
    controller.app_model.parse_apk_info_async.assert_not_called()
    assert capture_action_job("probe") is None


def test_batch_request_order_and_paths_are_unchanged(controller):
    controller.apk_picker.select_many.return_value = ("b.apk", "目录/demo one.APK", "b.apk")
    assert controller.batch_install_apk(["device-a", "device-b"]) == "operation-test"
    kind, requests = controller._start_install_batch.call_args.args
    assert kind == "batch_install"
    assert [(r.apk_path, r.device_id) for r in requests] == [
        ("b.apk", "device-a"), ("b.apk", "device-b"),
        ("目录/demo one.APK", "device-a"), ("目录/demo one.APK", "device-b"),
        ("b.apk", "device-a"), ("b.apk", "device-b"),
    ]
    assert [r.apk_name for r in requests] == [
        "b.apk", "b.apk", "demo one.APK", "demo one.APK", "b.apk", "b.apk",
    ]


@pytest.mark.parametrize("entry", ENTRIES)
def test_picker_exception_creates_no_job_and_releases_scope(controller, entry):
    picker = (controller.apk_picker.select_many if entry == "batch_install_apk"
              else controller.apk_picker.select_one)
    picker.side_effect = RuntimeError("picker failed")
    with pytest.raises(RuntimeError, match="picker failed"):
        run_entry(controller, entry)
    result = controller.action_results.recent()[0]
    assert result.state == "failed"
    assert "picker failed" in result.message
    controller._start_install_batch.assert_not_called()
    controller.app_model.parse_apk_info_async.assert_not_called()
    assert capture_action_job("probe") is None


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("closing", ["results", "controller", "window"])
def test_nonempty_picker_return_after_close_does_not_submit_or_revive_request(
    controller, tmp_path, entry, closing,
):
    path = tmp_path / "synthetic selection.APK"
    path.write_text("synthetic picker fixture", encoding="utf-8")
    published = []
    store = ActionResults(published.append)
    controller.action_results = store
    shutdown_events = []
    frame = closing_frame(controller, shutdown_events)
    picker = (controller.apk_picker.select_many if entry == "batch_install_apk"
              else controller.apk_picker.select_one)

    def select():
        assert len(store.recent()) == 1
        assert store.recent()[0].state == "running"
        controller._start_install_batch.assert_not_called()
        controller.app_model.parse_apk_info_async.assert_not_called()
        if closing == "results":
            store.close()
        elif closing == "controller":
            controller._shutting_down = True
            store.close()
        else:
            CloseController(frame).handle_close_event(Mock())
            assert frame._closing
            assert not controller._shutting_down
        return (str(path),) if entry == "batch_install_apk" else str(path)

    picker.side_effect = select
    returned = run_entry(controller, entry)

    picker.assert_called_once_with()
    controller._start_install_batch.assert_not_called()
    controller.app_model.parse_apk_info_async.assert_not_called()
    controller.signals.operation_completed.emit.assert_not_called()
    assert returned is None
    assert capture_action_job("probe") is None
    assert store.recent() == ()
    assert len(published) == 1
    if closing == "window":
        assert shutdown_events == [
            (stage, ()) for stage in ("begin", "register", "prepare", "stop")
        ]


@pytest.mark.parametrize("entry", ENTRIES[:2])
@pytest.mark.parametrize("closing", ["results", "controller", "window"])
def test_cancelled_picker_return_after_close_does_not_publish_late_feedback(
    controller, entry, closing,
):
    events = []
    frame = closing_frame(controller, events)
    picker = (controller.apk_picker.select_many if entry == "batch_install_apk"
              else controller.apk_picker.select_one)

    def select():
        if closing == "window":
            CloseController(frame).handle_close_event(Mock())
            assert frame._closing
            assert not controller._shutting_down
        else:
            controller.action_results.close()
            controller._shutting_down = closing == "controller"
        return () if entry == "batch_install_apk" else None

    picker.side_effect = select

    assert run_entry(controller, entry) is None

    controller.signals.operation_completed.emit.assert_not_called()
    controller.log_service.log.assert_not_called()
    controller._start_install_batch.assert_not_called()
    assert controller.action_results.recent() == ()
    assert capture_action_job("probe") is None


def test_window_close_seals_action_results_before_shutdown_dispatch(controller):
    events = []
    frame = closing_frame(controller, events)
    closer = CloseController(frame)
    event = Mock()

    controller.action_results.run(
        ActionSpec("picker", "apps.packages", "APK"), (),
        lambda: closer.handle_close_event(event),
    )
    closer.handle_close_event(event)

    assert frame._closing
    assert not controller._shutting_down
    assert events == [(stage, ()) for stage in ("begin", "register", "prepare", "stop")]
    assert controller.action_results.recent() == ()
    event.accept.assert_not_called()
    assert event.ignore.call_count == 2
    assert capture_action_job("probe") is None


def test_action_results_closed_is_read_only_and_close_is_idempotent():
    store = ActionResults(lambda _result: None)
    assert store.closed is False
    with pytest.raises(AttributeError):
        store.closed = True

    store.close()
    store.close()

    assert store.closed is True
    callback = Mock()
    assert store.run(ActionSpec("picker", "apps.packages", "APK"), (), callback) is None
    callback.assert_not_called()
    assert store.recent() == ()
