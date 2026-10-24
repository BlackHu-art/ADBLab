"""验证设置 owner 的终止、真实线程排空和冻结快照。"""

import json
import threading
from copy import deepcopy
from pathlib import Path

import pytest

from core import settings_manager


@pytest.fixture
def owner(tmp_path, monkeypatch):
    previous = settings_manager.AppSettings._instance
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings_manager, "LEGACY_SETTINGS_FILE", str(tmp_path / "legacy.json"))
    settings_manager.AppSettings._instance = None
    settings = settings_manager.AppSettings.instance()
    try:
        yield settings
    finally:
        settings.close()
        settings_manager.AppSettings._instance = previous


class WriteGate:
    """在写锁准入处提供确定性事件，保持真实磁盘保存。"""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.second_entered = threading.Event()
        self._count_lock = threading.Lock()
        self._entries = 0

    def __enter__(self):
        with self._count_lock:
            self._entries += 1
            if self._entries > 1:
                self.second_entered.set()
        self.entered.set()
        assert self.release.wait(3)
        self.lock.acquire()

    def __exit__(self, *_args):
        self.lock.release()


def _close_in_thread(owner):
    close = owner.close
    done = threading.Event()
    results = []

    def run():
        results.append(close())
        done.set()

    thread = threading.Thread(target=run)
    thread.start()
    return thread, done, results


def test_close_waits_replaced_running_timer(owner, tmp_path, monkeypatch):
    gate = WriteGate()
    owner._write_lock = gate
    real_timer = threading.Timer
    created = []

    def timer_factory(interval, callback):
        timer = real_timer(0 if not created else interval, callback)
        created.append(timer)
        return timer

    monkeypatch.setattr(settings_manager.threading, "Timer", timer_factory)
    closer = None
    try:
        owner.set("theme", "Dark")
        assert gate.entered.wait(2)
        owner.set("theme", "Light")
        closer, done, results = _close_in_thread(owner)
        assert not done.wait(0.05)
        assert not gate.second_entered.is_set()
        gate.release.set()
        closer.join(3)
        assert results == [True]
        assert all(not timer.is_alive() for timer in created)
        sentinel = tmp_path / "sentinel.json"
        sentinel.write_text("unchanged", encoding="utf-8")
        monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(sentinel))
        assert sentinel.read_text(encoding="utf-8") == "unchanged"
    finally:
        gate.release.set()
        for timer in created:
            timer.cancel()
            timer.join(3)
        if closer is not None:
            closer.join(3)


def test_close_waits_timer_thread_exit_after_callback(owner, monkeypatch):
    callback_done, release = threading.Event(), threading.Event()
    real_timer = threading.Timer

    class ExitGateTimer(real_timer):
        def run(self):
            super().run()
            callback_done.set()
            assert release.wait(3)

    monkeypatch.setattr(settings_manager.threading, "Timer", lambda _, cb: ExitGateTimer(0, cb))
    closer = None
    try:
        owner.set("theme", "Dark")
        assert callback_done.wait(2)
        closer, done, results = _close_in_thread(owner)
        assert not done.wait(0.05)
        release.set()
        closer.join(3)
        assert results == [True]
        assert not owner._save_timer.is_alive()
    finally:
        release.set()
        if closer is not None:
            closer.join(3)


def test_close_serializes_timer_start(owner, monkeypatch):
    start_entered, release = threading.Event(), threading.Event()
    real_timer = threading.Timer
    created = []

    class StartGateTimer(real_timer):
        def start(self):
            start_entered.set()
            assert release.wait(3)
            super().start()

    def factory(interval, callback):
        timer = StartGateTimer(interval, callback)
        created.append(timer)
        return timer

    monkeypatch.setattr(settings_manager.threading, "Timer", factory)
    updater = threading.Thread(target=lambda: owner.set("theme", "Dark"))
    closer = None
    try:
        updater.start()
        assert start_entered.wait(2)
        closer, done, results = _close_in_thread(owner)
        assert not done.wait(0.05)
        release.set()
        updater.join(3)
        closer.join(3)
        assert results == [True]
        assert all(not timer.is_alive() for timer in created)
    finally:
        release.set()
        updater.join(3)
        if closer is not None:
            closer.join(3)


@pytest.mark.parametrize("started_before_error", [False, True])
def test_timer_start_failure_retains_other_owners(owner, monkeypatch, started_before_error):
    gate = WriteGate()
    owner._write_lock = gate
    real_timer = threading.Timer
    first = real_timer(0, owner._save_atomic)

    class BrokenTimer(real_timer):
        def start(self):
            if started_before_error:
                super().start()
            raise RuntimeError("synthetic start failure")

    failed_timer = BrokenTimer(0.5, owner._save_atomic)
    timers = iter((first, failed_timer))
    monkeypatch.setattr(settings_manager.threading, "Timer", lambda *_: next(timers))
    closer = None
    try:
        owner.set("theme", "Dark")
        assert gate.entered.wait(2)
        with pytest.raises(RuntimeError, match="synthetic start failure"):
            owner.set("theme", "Light")
        closer, done, results = _close_in_thread(owner)
        assert not done.wait(0.05)
        gate.release.set()
        closer.join(3)
        assert results == [True]
        assert not first.is_alive()
        assert not failed_timer.is_alive()
        assert owner.get("theme") == "Light"
    finally:
        gate.release.set()
        first.join(3)
        if closer is not None:
            closer.join(3)


@pytest.mark.parametrize("entry", ["_save_atomic", "flush_deferred_save", "reset"])
def test_close_waits_admitted_synchronous_save(owner, entry):
    gate = WriteGate()
    owner._write_lock = gate
    owner._deferred_save_pending = True
    with owner._lock:
        owner._data["theme"] = "Dark"
    worker = threading.Thread(target=getattr(owner, entry))
    closer = None
    try:
        worker.start()
        assert gate.entered.wait(2)
        closer, done, results = _close_in_thread(owner)
        assert not done.wait(0.05)
        assert not gate.second_entered.is_set(), "close must await admitted save before final I/O"
        gate.release.set()
        worker.join(3)
        closer.join(3)
        assert results == [True]
        assert not worker.is_alive()
        stored = json.loads(Path(settings_manager.SETTINGS_FILE).read_text(encoding="utf-8"))
        assert stored["theme"] == ("System" if entry == "reset" else "Dark")
    finally:
        gate.release.set()
        worker.join(3)
        if closer is not None:
            closer.join(3)


@pytest.mark.parametrize("entry,args", [
    ("set", ("theme", "Dark")), ("update", ({"theme": "Dark"},)),
    ("set_many", ({"theme": "Dark"},)), ("reset", ()),
    ("update", ({},)), ("update", ({"schema_version": 99},)),
])
def test_closed_settings_reject_mutations(owner, entry, args):
    assert owner.close()
    before = deepcopy(owner._data)
    with open(settings_manager.SETTINGS_FILE, encoding="utf-8") as file:
        stored = file.read()
    with pytest.raises(RuntimeError, match="AppSettings is closed"):
        getattr(owner, entry)(*args)
    assert owner._data == before
    assert owner._save_timer is None
    with open(settings_manager.SETTINGS_FILE, encoding="utf-8") as file:
        assert file.read() == stored
    assert owner.get("theme") == before["theme"]


def test_closed_save_entries_return_false_without_io(owner, monkeypatch):
    assert owner.flush_deferred_save() is True
    assert not Path(settings_manager.SETTINGS_FILE).exists()
    assert owner.close()
    monkeypatch.setattr(settings_manager.os, "replace", lambda *_: pytest.fail("late write"))
    assert owner._save_atomic() is False
    assert owner.flush_deferred_save() is False
    assert owner.close() is True


def test_schema_warning_sink_runs_without_settings_lock(owner):
    """诊断 sink 可以等待其他读取者，不能在状态锁内调用它。"""
    observed = []
    readers = []

    def sink(_level, _message):
        read = threading.Event()

        def inspect():
            owner.get("theme")
            read.set()

        reader = threading.Thread(target=inspect)
        readers.append(reader)
        reader.start()
        observed.append(read.wait(0.3))

    settings_manager.set_error_sink(sink)
    try:
        owner.update({"schema_version": 99, "theme": "Dark"})
    finally:
        settings_manager.set_error_sink(None)
        for reader in readers:
            reader.join(3)
    assert observed == [True]
    assert owner.get("theme") == "Dark"


def test_snapshot_failure_still_drains_threads_and_rejects_retry_io(owner):
    """无法冻结的设置也必须完成终止屏障，不能回退到可变数据保存。"""
    class Uncopyable:
        def __deepcopy__(self, _memo):
            raise ValueError("synthetic snapshot failure")

    gate = WriteGate()
    owner._write_lock = gate
    done = threading.Event()
    results, errors = [], []

    def close():
        try:
            results.append(owner.close())
        except Exception as error:
            errors.append(error)
        finally:
            done.set()

    closer = threading.Thread(target=close)
    try:
        owner.set("theme", "Dark")
        old_timer = owner._save_timer
        assert gate.entered.wait(2)
        owner.set("unserializable", Uncopyable())
        latest_timer = owner._save_timer
        closer.start()
        assert not done.wait(0.05)
        gate.release.set()
        closer.join(3)
        assert results == [False]
        assert not errors
        assert not old_timer.is_alive()
        assert not latest_timer.is_alive()
        assert owner.close() is False
        assert owner._save_atomic() is False
        assert not Path(settings_manager.SETTINGS_FILE).exists()
    finally:
        gate.release.set()
        if closer.ident is not None:
            closer.join(3)


def test_concurrent_close_is_idempotent(owner, monkeypatch):
    dump = settings_manager.json.dump
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked_dump(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return dump(*args, **kwargs)

    monkeypatch.setattr(settings_manager.json, "dump", blocked_dump)
    first = second = None
    try:
        first, _, a = _close_in_thread(owner)
        assert entered.wait(2)
        second, done, b = _close_in_thread(owner)
        assert not done.wait(0.05)
        release.set()
        first.join(3)
        second.join(3)
        assert a == b == [True]
        assert calls == [1]
    finally:
        release.set()
        for thread in (first, second):
            if thread is not None:
                thread.join(3)


@pytest.mark.parametrize("failure", ["dump", "replace"])
def test_close_failure_retries_frozen_snapshot(owner, tmp_path, monkeypatch, failure):
    path = tmp_path / "settings.json"
    path.write_text("old", encoding="utf-8")
    owner._future_extra = {"future": {"value": [1]}}
    owner._seen_version = 99
    owner._deferred_save_pending = True
    target = settings_manager.json if failure == "dump" else settings_manager.os
    with monkeypatch.context() as patch:
        def fail(*_args, **_kwargs):
            raise OSError("synthetic failure")
        patch.setattr(target, failure, fail)
        assert owner.close() is False
    assert path.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob("adblab_settings_*"))
    assert owner._deferred_save_pending
    owner._future_extra["future"]["value"].append(2)
    owner._data["theme"] = "Dark"
    assert owner.close() is True
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["future"] == {"value": [1]}
    assert stored["schema_version"] == 99
    assert stored["theme"] == "System"
    assert not owner._deferred_save_pending
    monkeypatch.setattr(settings_manager.os, "replace", lambda *_: pytest.fail("duplicate close"))
    assert owner.close() is True
