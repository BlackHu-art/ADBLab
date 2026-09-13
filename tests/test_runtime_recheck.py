"""运行中重检合并、代次隔离和 INFO 摘要的入口回归。"""

import threading

import pytest

from core import adb_runtime as module
from core.adb_runtime import AdbRuntime
from core.adb_transport import ExecutionResult


@pytest.mark.parametrize("blocked_stage", ["resolver", "capture"])
def test_pending_rechecks_reset_mode_and_probe_latest_path_once(monkeypatch, blocked_stage):
    entered = threading.Event()
    release = threading.Event()
    latest_entered = threading.Event()
    latest_release = threading.Event()
    paths = ["old-adb"]
    resolved = []
    threads = []
    published = []

    def resolver():
        value = paths[0]
        resolved.append(value)
        threads.append(threading.get_ident())
        if len(resolved) == 1 and blocked_stage == "resolver":
            entered.set()
            assert release.wait(3)
        elif len(resolved) == 2:
            latest_entered.set()
            assert latest_release.wait(3)
        return value

    runtime = AdbRuntime(resolver, changed=published.append)

    def capture(*args, **kwargs):
        if len(resolved) == 1 and blocked_stage == "capture":
            entered.set()
            assert release.wait(3)
        return ExecutionResult(b"List of devices attached\n")

    monkeypatch.setattr(module, "capture", capture)
    monkeypatch.setattr(runtime, "_probe_backends", lambda *args: None)
    try:
        assert runtime.start()
        assert entered.wait(2)
        runtime.set_mode("native")
        for path in ("middle-adb", "latest-adb", "latest-adb"):
            paths[0] = path
            assert runtime.recheck()
        assert runtime.selection_mode == "auto"
        assert runtime.snapshot().checking
        release.set()
        assert latest_entered.wait(2)
        assert not runtime.snapshot().available
        assert not any(snapshot.available for snapshot in published)
        latest_release.set()
        assert runtime.wait(2)
        assert resolved == ["old-adb", "latest-adb"]
        assert len(set(threads)) == 1
        assert runtime._path == "latest-adb"
        assert runtime.snapshot().available
        assert not runtime.snapshot().checking
    finally:
        release.set()
        latest_release.set()
        runtime.close()
        assert runtime.wait(2)


def test_shutdown_discards_pending_recheck(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    resolved = []

    def resolver():
        resolved.append(True)
        entered.set()
        assert release.wait(3)
        return None

    runtime = AdbRuntime(resolver)
    try:
        assert runtime.start()
        assert entered.wait(2)
        assert runtime.recheck()
        runtime.prepare_shutdown()
        release.set()
        assert runtime.wait(2)
        assert resolved == [True]
        assert not runtime.recheck()
    finally:
        release.set()
        runtime.close()
        assert runtime.wait(2)


def test_runtime_mode_and_completion_reach_info_event_when_debug_disabled(monkeypatch):
    events = []
    monkeypatch.setattr(module.adb_debug, "enabled", lambda level="DEBUG": level == "INFO")
    monkeypatch.setattr(module.adb_debug, "event", lambda name, **fields: events.append(name))
    runtime = AdbRuntime(lambda: None)
    runtime.set_mode("native")
    assert runtime.start()
    assert runtime.wait(2)
    assert "mode" in events
    assert "probe_complete" in events
    runtime.close()


@pytest.mark.ui
def test_qt_pending_reset_publishes_auto_and_preserves_later_manual_choice(
    monkeypatch, qt_application,
):
    from adblab.presentation.qt_adb_runtime import QtAdbRuntime

    entered, release = threading.Event(), threading.Event()
    resolutions = []

    def resolver():
        resolutions.append(True)
        entered.set()
        assert release.wait(3)
        return None

    adapter = QtAdbRuntime()
    adapter.runtime._resolver = resolver
    snapshots = []
    adapter.changed.connect(snapshots.append)
    monkeypatch.setattr(
        "adblab.presentation.qt_adb_runtime.invalidate_adb_path_cache", lambda: None
    )
    monkeypatch.setattr(
        "adblab.presentation.qt_adb_runtime.reset_adb_program_cache", lambda: None
    )
    try:
        assert adapter.runtime.start()
        assert entered.wait(2)
        adapter.set_selection_mode("native")
        adapter.recheck()
        assert snapshots[-1].selection_mode == "auto"
        assert snapshots[-1].checking
        adapter.set_selection_mode("native")
        release.set()
        assert adapter.runtime.wait(2)
        qt_application.processEvents()
        assert len(resolutions) == 2
        assert snapshots[-1].selection_mode == "native"
        assert not snapshots[-1].checking
    finally:
        release.set()
        adapter.close()
        assert adapter.runtime.wait(2)
        adapter.deleteLater()
