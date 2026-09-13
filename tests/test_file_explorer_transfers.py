import threading
from types import SimpleNamespace

import pytest

from models.file_explorer_worker import TransferWorker

pytestmark = pytest.mark.ui


def test_cancel_only_requests_stop(monkeypatch):
    worker = TransferWorker("device-test", ["pull", "/a", "a"])
    requests = []
    monkeypatch.setattr(worker._process_runner, "request_stop", lambda key: requests.append(key))
    monkeypatch.setattr(
        worker._process_runner, "stop", lambda *a, **k: pytest.fail("blocking stop")
    )
    worker.abort()
    worker.abort()
    assert worker._aborted.is_set()
    assert requests


def test_cancel_before_run_never_launches(monkeypatch):
    worker = TransferWorker("device-test", ["pull", "/a", "a"])
    monkeypatch.setattr(
        worker._process_runner, "start", lambda *a, **k: pytest.fail("cancelled launch")
    )
    worker.request_stop()
    worker.run()
    assert not worker.is_active()


def test_force_stop_keeps_residual_until_actual_process_exit(monkeypatch):
    worker = TransferWorker("device-test", ["pull", "/a", "a"])
    alive = [True]
    worker._proc = SimpleNamespace(poll=lambda: None if alive[0] else 0)
    monkeypatch.setattr(worker._process_runner, "request_stop", lambda key: True)
    monkeypatch.setattr(worker._process_runner, "force_stop", lambda *a, **k: True)
    assert not worker.force_stop(0)
    assert worker.is_active()
    alive[0] = False
    assert worker.wait_stopped(0)


def test_cancel_during_start_reissues_stop_and_preserves_live_process(monkeypatch):
    worker = TransferWorker("device-test", ["pull", "/a", "a"])
    requests = []
    proc = SimpleNamespace(poll=lambda: None, stdout=None)

    def launch(*args, **kwargs):
        worker.request_stop()
        return proc

    monkeypatch.setattr(worker._process_runner, "start", launch)
    monkeypatch.setattr(worker._process_runner, "request_stop", lambda key: requests.append(key))
    monkeypatch.setattr(
        worker._process_runner, "stop", lambda *a, **k: pytest.fail("live process forgotten")
    )
    worker.run()
    assert len(requests) >= 2
    assert worker.is_active()


def test_cancel_unblocks_stdout_reader(monkeypatch):
    worker = TransferWorker("device-test", ["pull", "/a", "a"])
    reading = threading.Event()
    stopped = threading.Event()

    def readline():
        reading.set()
        assert stopped.wait(2)
        return ""

    proc = SimpleNamespace(
        stdout=SimpleNamespace(readline=readline), poll=lambda: 0 if stopped.is_set() else None
    )
    monkeypatch.setattr(worker._process_runner, "start", lambda *a, **k: proc)
    monkeypatch.setattr(worker._process_runner, "request_stop", lambda key: stopped.set())
    monkeypatch.setattr(worker._process_runner, "stop", lambda *a, **k: 0)
    worker.start()
    try:
        assert reading.wait(2)
        worker.abort()
        assert worker.wait(2000)
        assert not worker.is_active()
    finally:
        stopped.set()
        worker.wait(2000)


def test_queue_serial_preview_priority_and_cancelled_terminal(qt_application):
    from PySide6.QtCore import QObject, Signal

    from gui.dialogs.file_explorer_transfers import FileTransferCoordinator

    starts = []
    terminals = []

    class Worker(QObject):
        finished = Signal()

        def __init__(self, name):
            super().__init__()
            self.name = name
            self.running = False

        def start(self):
            self.running = True
            starts.append(self.name)

        def isRunning(self):
            return self.running

        def abort(self):
            self.running = False

    frame = SimpleNamespace(
        _can_operate=lambda: True, _workers=[], _finish_async_dispose=lambda: None
    )
    coordinator = FileTransferCoordinator(frame)
    first, second, preview = (Worker(name) for name in ("first", "second", "preview"))
    for worker in (first, second):
        coordinator.enqueue(worker, on_terminal=lambda w=worker: terminals.append(w.name))
    coordinator.enqueue(preview, preview=True, on_terminal=lambda: terminals.append("preview"))
    assert starts == ["first"]
    first.running = False
    coordinator.worker_finished(first)
    assert starts == ["first", "preview"]
    coordinator.cancel_pending()
    assert terminals == ["first", "second"]
    preview.running = False
    coordinator.worker_finished(preview)
    assert terminals == ["first", "second", "preview"]
    assert starts == ["first", "preview"]


def test_cleanup_obligation_keeps_dynamic_shutdown_active():
    from gui.dialogs.file_explorer_transfers import FileTransferCoordinator

    frame = SimpleNamespace(
        _can_operate=lambda: True, _workers=[], _finish_async_dispose=lambda: None
    )
    coordinator = FileTransferCoordinator(frame)
    token = coordinator.hold_cleanup()
    coordinator.request_stop()
    assert coordinator.is_running()
    assert not coordinator.wait(0)
    coordinator.release_cleanup(token)
    assert not coordinator.is_running()


@pytest.mark.parametrize("checking", [[True, False], [True, True, False]])
def test_natural_completion_join_race_retries_terminal_without_abort(monkeypatch, checking):
    from gui.dialogs.file_explorer import FileExplorerPage
    from models.file_explorer_worker import ADBWorker

    monkeypatch.setattr(ADBWorker, "start", lambda worker: None)
    page = FileExplorerPage(device_ip="device-test")
    worker = page._run_adb("shell", "unused")
    terminal = []
    coordinator = page._transfers
    coordinator.enqueue(worker, on_terminal=lambda: terminal.append(True))
    checks = list(checking)

    def active(candidate):
        return checks.pop(0) if checks else False

    monkeypatch.setattr(coordinator, "worker_active", active)
    page._prune_worker(worker)
    assert worker in page._workers
    coordinator._poll()
    coordinator._poll()
    assert terminal == [True]
    assert worker not in page._workers
    assert not worker._aborted.is_set()
    assert not coordinator.is_running()
    page.close()


@pytest.mark.parametrize(
    "direction,origin_changed,refreshes",
    [("pull", False, 0), ("push", False, 1), ("push", True, 0)],
)
def test_batch_serial_partial_failure_and_refresh(
    monkeypatch, direction, origin_changed, refreshes
):
    from gui.dialogs.file_explorer import FileExplorerPage

    starts = []
    feedback = []
    monkeypatch.setattr(TransferWorker, "start", lambda worker: starts.append(worker))
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.report_feedback", lambda *a, **k: feedback.append(k)
    )
    page = FileExplorerPage(device_ip="device-test")
    refreshed = []
    monkeypatch.setattr(page, "_refresh", lambda: refreshed.append(True))
    page._ops_controller._enqueue_batch(
        direction, [("a", "/a", "a"), ("b", "/b", "b")], page.current_path
    )
    assert len(starts) == 1
    first = starts[0]
    first.result_ready.emit("first failed", True, "a")
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    page._prune_worker(first)
    assert len(starts) == 2
    if origin_changed:
        page.current_path = "/other"
    second = starts[1]
    second.result_ready.emit("second OK", False, "b")
    QApplication.processEvents()
    page._prune_worker(second)
    assert len(refreshed) == refreshes
    assert len(feedback) == 1
    assert page._ops_controller._last_batch_results == (
        ("a", "failed", "first failed"),
        ("b", "succeeded", "second OK"),
    )
    page.close()


@pytest.mark.parametrize("stop_reason", ["deselected", "offline", "close"])
def test_batch_drops_pending_without_reconnect_replay(monkeypatch, stop_reason):
    from gui.dialogs.file_explorer import FileExplorerPage

    starts = []
    monkeypatch.setattr(TransferWorker, "start", lambda worker: starts.append(worker))
    monkeypatch.setattr("gui.dialogs.file_explorer_ops.report_feedback", lambda *a, **k: None)
    page = FileExplorerPage(device_ip="device-test")
    page._ops_controller._enqueue_batch(
        "pull", [("a", "/a", "a"), ("b", "/b", "b")], page.current_path
    )
    if stop_reason == "deselected":
        page.set_device_selected(False)
        page.set_device_selected(True)
    elif stop_reason == "offline":
        page.set_device_connected(False)
        page.set_device_connected(True)
    else:
        page.request_dispose()
    page._prune_worker(starts[0])
    assert len(starts) == 1
    assert page._ops_controller._last_batch_results[1] == ("b", "cancelled", "")
    assert not page._workers
    page.close()


def test_root_pull_cancelled_copy_cleans_owned_path_on_fixed_device(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from gui.dialogs.file_explorer import FileExplorerPage
    from models.file_explorer_worker import ADBWorker

    starts = []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: starts.append(worker))
    monkeypatch.setattr(TransferWorker, "start", lambda worker: starts.append(worker))
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.QFileDialog.getSaveFileName",
        lambda *a, **k: ("unused-local", ""),
    )
    page = FileExplorerPage(device_ip="device-test")
    page.root_cb.setChecked(True)
    page._pull_file("same.png")
    prepare = starts[0]
    assert "/data/local/tmp/same.png" not in prepare.args[1]
    assert "adblab-pull-" in prepare.args[1]
    page.root_cb.setChecked(False)
    assert page.request_dispose() is False
    assert len(starts) == 2
    cleanup = starts[1]
    assert cleanup.device_ip == "device-test"
    assert "su -c" in cleanup.args[1]
    assert "rm " in cleanup.args[1]
    assert not cleanup._aborted.is_set()
    cleanup.finished.emit()
    QApplication.processEvents()
    assert not page._transfers.is_running()
    assert page._disposed
