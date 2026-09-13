from unittest.mock import Mock, patch

import pytest

from gui.dialogs.app_manager_batch import AppManagerBatch


class Frame:
    def __init__(self):
        self.device_ip = "mock-device"
        self._batch_workers = set()
        self._closing = False
        self.allowed = True
        self._can_operate = lambda: self.allowed and not self._closing
        self._get_selected_pkgs = lambda: [f"org.example.app{i}" for i in range(100)]
        self._track_worker = Mock()
        self._prune_worker = Mock()
        self._update_selection_ui = Mock()
        self._load_apps = Mock()
        self.status_bar = Mock()
        self.log = Mock()
        self.controller = AppManagerBatch(self)
        self._on_batch_worker_finished = self.controller._on_batch_worker_finished


@pytest.mark.parametrize("stop", [False, True])
def test_batch_has_one_active_worker_and_never_starts_cancelled_queue(stop):
    frame = Frame()
    workers = [Mock() for _ in range(100)]
    with patch("gui.dialogs.app_manager.AppManagerWorker", side_effect=workers):
        frame.controller._modify_selected("disable")
    assert sum(w.start.call_count for w in workers) == 1
    frame.controller._modify_selected("disable")
    assert sum(w.start.call_count for w in workers) == 1
    if stop:
        frame.allowed = False
    frame.controller._on_batch_worker_finished(workers[0])
    assert workers[1].start.call_count == (0 if stop else 1)
    if stop:
        assert frame._batch_workers == set()
        frame._load_apps.assert_not_called()
    else:
        for worker in workers[1:]:
            frame.controller._on_batch_worker_finished(worker)
        frame._load_apps.assert_called_once()
        assert frame._batch_workers == set()


@pytest.mark.parametrize("kind", ["backup", "restore"])
def test_backup_and_restore_share_busy_budget(kind, tmp_path):
    frame = Frame()
    frame._global_save_dir = lambda: str(tmp_path)
    frame._log_backup_progress = Mock()
    workers = [Mock() for _ in range(100)]
    with (
        patch("gui.dialogs.app_manager.AppManagerWorker", side_effect=workers) as constructor,
        patch(
            "gui.dialogs.app_manager_batch.QFileDialog.getExistingDirectory",
            return_value=str(tmp_path),
        ),
        patch(
            "gui.dialogs.app_manager_batch.QFileDialog.getOpenFileNames",
            return_value=([str(tmp_path / "backup.zip")], ""),
        ),
    ):
        submit = (
            frame.controller._backup_selected
            if kind == "backup"
            else frame.controller._restore_apps
        )
        submit()
        created = constructor.call_count
        submit()
        assert constructor.call_count == created
    assert sum(w.start.call_count for w in workers) == 1
    frame._closing = True
    frame.controller.cancel_pending()
    frame.controller._on_batch_worker_finished(workers[0])
    assert sum(w.start.call_count for w in workers) == 1
    assert frame._batch_workers == set()
    frame._load_apps.assert_not_called()


def test_worker_failure_still_advances_and_refreshes_only_at_end():
    frame = Frame()
    frame._get_selected_pkgs = lambda: ["org.example.one", "org.example.two"]
    workers = [Mock(), Mock()]
    with patch("gui.dialogs.app_manager.AppManagerWorker", side_effect=workers):
        frame.controller._modify_selected("disable")
    # Completion is driven by thread termination, including workers without a success signal.
    frame.controller._on_batch_worker_finished(workers[0])
    workers[1].start.assert_called_once()
    frame._load_apps.assert_not_called()
    frame.controller._on_batch_worker_finished(workers[1])
    frame.controller._on_batch_worker_finished(workers[1])
    frame._load_apps.assert_called_once()


@pytest.mark.parametrize("failed_indexes", [{0}, {1}, {0, 1}])
def test_batch_start_failure_releases_busy_and_does_not_report_success(failed_indexes):
    frame = Frame()
    frame._on_operation_feedback = Mock()
    frame._get_selected_pkgs = lambda: ["org.example.one", "org.example.two"]
    workers = [Mock(), Mock()]
    for index in failed_indexes:
        workers[index].start.side_effect = RuntimeError("cannot start")
    with patch("gui.dialogs.app_manager.AppManagerWorker", side_effect=workers):
        frame.controller._modify_selected("disable")
    for index, worker in enumerate(workers):
        if index not in failed_indexes:
            frame.controller._on_batch_worker_finished(worker)
    assert frame._batch_workers == set()
    assert not frame.controller._batch_action_blocked()
    assert frame._batch_total == 0
    assert frame._on_operation_feedback.call_count == len(failed_indexes)
    assert all(call.args[0] == "error" for call in frame._on_operation_feedback.call_args_list)
    for index in failed_indexes:
        workers[index].operation_done.emit.assert_not_called()
        assert any(call.args[0] is workers[index] for call in frame._prune_worker.call_args_list)
    frame._load_apps.assert_called_once()
