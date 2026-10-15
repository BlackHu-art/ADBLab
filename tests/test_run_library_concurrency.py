"""结果库多实例写入在最新快照上合并，失败不得污染磁盘或已发布内存。"""

import multiprocessing
import os
import sys
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from services import run_library as module
from services.run_library import RunLibrary
from tests.test_run_library import record


def test_stale_instances_merge_runs_and_updates_by_identity(tmp_path):
    path = tmp_path / "runs.json"
    first, second = RunLibrary(path), RunLibrary(path)
    first.load()
    second.load()
    first.record_run(record("one"))
    second.record_run(record("two"))
    first.record_run(replace(record("one"), state="cancelled"))
    restored = RunLibrary(path)
    restored.load()
    assert {r.run_id: r.state for r in restored.records} == {
        "one": "cancelled", "two": "succeeded",
    }
    assert first.records == restored.records


def test_stale_run_writer_preserves_preset_changes_and_deletions(tmp_path):
    path = tmp_path / "runs.json"
    first, second = RunLibrary(path), RunLibrary(path)
    first.save_preset("remove", "monkey", {"seed": 1})
    removed = first.presets[0].preset_id
    second.load()
    first.save_preset("keep", "performance", {"frequency_seconds": 2})
    first.delete_preset(removed)
    second.record_run(record())
    assert [p.name for p in second.presets] == ["keep"]
    first.delete_preset(removed)
    assert first.records == (record(),)
    assert [p.name for p in first.presets] == ["keep"]


def test_stale_named_preset_save_reuses_latest_identity(tmp_path):
    path = tmp_path / "runs.json"
    first, second = RunLibrary(path), RunLibrary(path)
    second.load()
    first.save_preset("shared", "monkey", {"seed": 1})
    identifier = first.presets[0].preset_id
    second.save_preset("shared", "monkey", {"seed": 2})
    assert len(second.presets) == 1
    assert second.presets[0].preset_id == identifier
    assert second.presets[0].parameters == {"seed": 2}


def test_capacity_is_applied_to_latest_combined_records(tmp_path):
    path = tmp_path / "runs.json"
    first, second = RunLibrary(path, capacity=2), RunLibrary(path, capacity=2)
    first.record_run(replace(record("one"), finished_at=21))
    second.load()
    first.record_run(replace(record("three"), finished_at=23))
    second.record_run(replace(record("two"), finished_at=22))
    assert [r.run_id for r in second.records] == ["three", "two"]


@pytest.mark.parametrize("raw", [b"{broken", b'{"version":2,"runs":[],"presets":[]}'])
def test_write_revalidates_file_changed_since_load(tmp_path, raw):
    path = tmp_path / "runs.json"
    library = RunLibrary(path)
    library.record_run(record())
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        library.record_run(record("two"))
    assert path.read_bytes() == raw
    assert library.records == (record(),)


def test_failed_merge_write_preserves_callers_previous_memory(tmp_path, monkeypatch):
    path = tmp_path / "runs.json"
    first, second = RunLibrary(path), RunLibrary(path)
    first.record_run(record("one"))
    second.load()
    first.record_run(record("two"))
    original = path.read_bytes()
    original_replace = module.os.replace

    def fail_replace(*_args):
        raise PermissionError("denied")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        second.record_run(record("three"))
    assert second.records == (record("one"),)
    assert path.read_bytes() == original
    assert list(tmp_path.glob(".runs-*")) == []
    monkeypatch.setattr(module.os, "replace", original_replace)
    first.record_run(record("after-failure"))
    assert {r.run_id for r in first.records} == {"one", "two", "after-failure"}


def test_stale_preset_capacity_uses_latest_disk_snapshot(tmp_path):
    path = tmp_path / "runs.json"
    first, second = RunLibrary(path), RunLibrary(path)
    second.load()
    for index in range(50):
        first.save_preset(f"preset-{index}", "monkey", {"seed": index})
    original = path.read_bytes()
    with pytest.raises(ValueError, match="50"):
        second.save_preset("overflow", "monkey", {})
    assert second.presets == () and path.read_bytes() == original
    second.save_preset("preset-0", "monkey", {"seed": 500})
    assert len(second.presets) == 50
    assert next(p for p in second.presets if p.name == "preset-0").parameters == {"seed": 500}


def _concurrent_writer(path, index, ready):
    library = RunLibrary(path)
    library.load()
    ready.wait(timeout=10)
    for number in range(8):
        library.record_run(record(f"{index}-{number}"))
    library.save_preset(f"preset-{index}", "monkey", {"seed": index})


def test_real_processes_preserve_each_others_records_and_presets(tmp_path):
    path = tmp_path / "runs.json"
    context = multiprocessing.get_context("spawn")
    ready = context.Barrier(3)
    processes = [context.Process(target=_concurrent_writer, args=(path, index, ready))
                 for index in range(2)]
    try:
        for process in processes:
            process.start()
        ready.wait(timeout=10)
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        library = RunLibrary(path)
        library.load()
        assert {r.run_id for r in library.records} == {
            f"{index}-{number}" for index in range(2) for number in range(8)
        }
        assert {p.name for p in library.presets} == {"preset-0", "preset-1"}
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(5)
                process.close()


def test_busy_writer_times_out_without_changes_and_allows_later_retry(tmp_path, monkeypatch):
    path = tmp_path / "runs.json"
    first, second = RunLibrary(path), RunLibrary(path)
    first.record_run(record("initial"))
    second.load()
    original = path.read_bytes()
    entered, release = threading.Event(), threading.Event()
    errors = []
    original_replace = module.os.replace

    def delayed_replace(source, target):
        if threading.current_thread() is writer:
            entered.set()
            assert release.wait(3)
        original_replace(source, target)

    def write():
        try:
            first.record_run(record("first"))
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(module, "WRITE_LOCK_TIMEOUT", .05, raising=False)
    monkeypatch.setattr(module.os, "replace", delayed_replace)
    writer = threading.Thread(target=write)
    try:
        writer.start()
        assert entered.wait(1)
        with pytest.raises(TimeoutError):
            second.record_run(record("second"))
        assert second.records == (record("initial"),)
        assert path.read_bytes() == original
    finally:
        release.set()
        writer.join(3)
    assert not writer.is_alive() and errors == []
    second.record_run(record("second"))
    assert {r.run_id for r in second.records} == {"initial", "first", "second"}


def _writer_stopped_before_replace(path, entered):
    def wait_before_replace(*_args):
        entered.set()
        threading.Event().wait(30)
        raise AssertionError("test owner was not stopped")

    module.os.replace = wait_before_replace
    RunLibrary(path).record_run(record("uncommitted"))


def test_os_releases_lock_when_writer_process_exits_abruptly(tmp_path):
    path = tmp_path / "runs.json"
    library = RunLibrary(path)
    library.record_run(record("initial"))
    original = path.read_bytes()
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    process = context.Process(target=_writer_stopped_before_replace, args=(path, entered))
    try:
        process.start()
        assert entered.wait(10)
        process.terminate()
        process.join(5)
        assert not process.is_alive()
        assert path.read_bytes() == original
        library.record_run(record("after-exit"))
        assert {r.run_id for r in library.records} == {"initial", "after-exit"}
    finally:
        if process.is_alive():
            process.terminate()
        if process.pid is not None:
            process.join(5)
            process.close()


def test_posix_lock_uses_nonblocking_exclusive_mode_and_closes_descriptor(tmp_path, monkeypatch):
    calls = []
    fake = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda fd, flags: calls.append((fd, flags)))
    monkeypatch.setitem(sys.modules, "fcntl", fake)
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
    library = RunLibrary(tmp_path / "runs.json")
    library.record_run(record())
    assert library.records == (record(),)
    assert len(calls) == 1 and calls[0][1] == fake.LOCK_EX | fake.LOCK_NB
    with pytest.raises(OSError):
        os.fstat(calls[0][0])
