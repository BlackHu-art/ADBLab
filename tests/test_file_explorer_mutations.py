"""文件变更批次的并发、快照和取消回归。"""

import pytest

from gui.dialogs.file_explorer import FileExplorerPage
from models.file_explorer_worker import ADBWorker

pytestmark = pytest.mark.ui


@pytest.fixture
def mutation_page(monkeypatch, qt_application):
    starts, feedback, refreshes = [], [], []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: starts.append(worker))
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.report_feedback",
        lambda *a, **k: feedback.append({**k, "message": a[3]}),
    )
    page = FileExplorerPage(device_ip="synthetic-device")
    page.current_path = "/target"
    monkeypatch.setattr(page, "_refresh", lambda: refreshes.append(True))
    yield page, starts, feedback, refreshes
    page.request_dispose()
    for worker in tuple(page._workers):
        page._prune_worker(worker)
    page.close()


def _submit(page, kind, count=3):
    if kind == "delete":
        page._request_delete([f"item-{i}" for i in range(count)])
    else:
        page.clipboard = [f"/source/item-{i}" for i in range(count)]
        page.copy_mode = kind == "copy"
        page._paste_items()


def _complete(page, worker, qt_application, *, failed=False):
    worker.result_ready.emit("failed" if failed else "ok", failed)
    qt_application.processEvents()
    page._prune_worker(worker)


@pytest.mark.parametrize("kind", ["delete", "copy", "move"])
def test_mutations_are_serial_and_refresh_once_after_partial_failure(
    mutation_page, qt_application, kind,
):
    page, starts, feedback, refreshes = mutation_page
    _submit(page, kind, 100)
    assert len(starts) == 1
    _submit(page, kind)
    assert len(page._workers) == 100
    for i in range(100):
        assert len(starts) == i + 1
        assert not refreshes
        _complete(page, starts[i], qt_application, failed=i == 1)
    assert refreshes == [True]
    assert len(feedback) == 1
    assert feedback[0]["level"] == "error"
    results = page._ops_controller._last_batch_results
    assert len(results) == 100
    assert sum(state == "succeeded" for _, state, _ in results) == 99
    assert results[1][1] == "failed"
    assert not page._workers
    _submit(page, kind, 1)
    assert len(starts) == 101


@pytest.mark.parametrize("kind", ["delete", "copy", "move"])
@pytest.mark.parametrize("reason", ["offline", "deselected", "close"])
def test_mutation_pending_items_are_cancelled_without_replay(mutation_page, reason, kind):
    page, starts, feedback, refreshes = mutation_page
    _submit(page, kind)
    assert len(starts) == 1
    if reason == "offline":
        page.set_device_connected(False)
        page.set_device_connected(True)
    elif reason == "deselected":
        page.set_device_selected(False)
        page.set_device_selected(True)
    else:
        page.request_dispose()
    page._prune_worker(starts[0])
    assert len(starts) == 1
    assert all(state == "cancelled" for _, state, _ in page._ops_controller._last_batch_results)
    assert not page._transfers.is_running()
    assert not page._workers
    if reason == "close":
        assert not feedback
        assert not refreshes


@pytest.mark.parametrize("kind", ["delete", "copy", "move"])
def test_mutations_keep_original_device_path_and_root(mutation_page, qt_application, kind):
    page, starts, _, refreshes = mutation_page
    page.root_cb.setChecked(True)
    _submit(page, kind, 2)
    assert len(starts) == 1
    page.current_path = "/elsewhere"
    page.device_ip = "different-synthetic-device"
    page.root_cb.setChecked(False)
    _complete(page, starts[0], qt_application)
    second = starts[1]
    assert second.device_ip == "synthetic-device"
    assert "/target/item-1" in second.args[1]
    assert "su -c" in second.args[1]
    _complete(page, second, qt_application)
    assert not refreshes


def test_mutation_start_failure_settles_and_runs_next(mutation_page, monkeypatch, qt_application):
    from tests.ui_geometry_helpers import wait_until

    page, starts, feedback, refreshes = mutation_page

    def start(worker):
        starts.append(worker)
        if len(starts) == 1:
            raise RuntimeError("synthetic launch failure")

    monkeypatch.setattr(ADBWorker, "start", start)
    _submit(page, "delete", 2)
    wait_until(qt_application, lambda: len(starts) == 2)
    _complete(page, starts[1], qt_application)
    assert page._ops_controller._last_batch_results[0][1] == "failed"
    assert page._ops_controller._last_batch_results[1][1] == "succeeded"
    assert len(feedback) == len(refreshes) == 1
    assert not page._transfers.is_running()


def test_mutation_failure_summary_preserves_actionable_reason(mutation_page, qt_application):
    page, starts, feedback, _ = mutation_page
    _submit(page, "delete", 1)
    starts[0].result_ready.emit("Permission denied", True)
    qt_application.processEvents()
    page._prune_worker(starts[0])
    assert len(feedback) == 1
    assert "item-0" in feedback[0]["message"]
    assert "Permission denied" in feedback[0]["message"]
