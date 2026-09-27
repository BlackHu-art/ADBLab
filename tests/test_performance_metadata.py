"""验证性能环境快照的白名单、持久化和归属边界。"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

RUN_ID = "a" * 32


def _capture(**overrides):
    from services.performance_metadata import capture_metadata

    outputs = {
        "getprop ro.product.brand": "Example",
        "getprop ro.product.model": "Test Model",
        "getprop ro.build.version.release": "15",
        "getprop ro.build.version.sdk": "35",
        "getprop ro.product.cpu.abilist": "x86_64,arm64-v8a,x86",
        "dumpsys package com.example.app": (
            "Package [com.example.app] (abc):\n"
            "  versionCode=123 minSdk=23 targetSdk=35\n"
            "  versionName=1.2 beta\n  userId=99999\n  secret=do-not-store\n"
        ),
        "dumpsys package com.example.other": (
            "versionCode=8 minSdk=23\nversionName=2.0\n"
        ),
    }
    arguments = {
        "query": lambda command: outputs.get(command, ""),
        "run_id": RUN_ID,
        "target_processes": ["com.example.app", "com.example.other", "com.example.app"],
        "sampling": {"frequency_seconds": 3, "timeout_seconds": 120,
                     "dumpheap_seconds": 600, "monkey_enabled": False},
        "collector_version": "3.2.25",
        "captured_at": 10.0,
    }
    arguments.update(overrides)
    return capture_metadata(**arguments)


def _write(tmp_path, document=None):
    from services.performance_metadata import write_metadata

    return Path(write_metadata(tmp_path, _capture() if document is None else document))


def test_capture_preserves_each_version_and_only_named_environment_fields():
    document = _capture()

    assert document["status"] == "complete"
    assert document["run_id"] == RUN_ID
    assert document["device"] == {
        "brand": "Example", "model": "Test Model", "android_version": "15",
        "api_level": 35, "abis": ["x86_64", "arm64-v8a", "x86"],
    }
    assert document["targets"] == [
        {"process": "com.example.app", "package": "com.example.app",
         "version_name": "1.2 beta", "version_code": 123},
        {"process": "com.example.other", "package": "com.example.other",
         "version_name": "2.0", "version_code": 8},
    ]
    assert document["collector"] == {"name": "ADBLab MobilePerf", "version": "3.2.25"}
    text = json.dumps(document)
    assert "99999" not in text and "do-not-store" not in text and "userId" not in text


def test_capture_snapshots_mutable_sampling_before_queries():
    sampling = {"frequency_seconds": 3, "timeout_seconds": 120,
                "dumpheap_seconds": 600, "monkey_enabled": False}
    processes = ["com.example.app"]

    def query(_command):
        sampling["frequency_seconds"] = 99
        processes.append("com.example.late")
        return ""

    document = _capture(query=query, sampling=sampling, target_processes=processes)

    assert document["sampling"]["frequency_seconds"] == 3
    assert [item["process"] for item in document["targets"]] == ["com.example.app"]
    assert document["status"] == "partial"
    assert document["targets"][0]["version_code"] is None


@pytest.mark.parametrize("raw", ["", "versionCode=not-a-number\nversionName=null\n",
                                "versionCode=12\nversionCode=13\nversionName=one\n"])
def test_missing_or_ambiguous_package_version_is_unknown(raw):
    document = _capture(query=lambda _command: raw, target_processes=["com.example.app"])

    assert document["status"] == "partial"
    assert document["targets"][0]["version_code"] is None
    assert document["missing_fields"]


def test_capture_query_failure_keeps_parameters_and_does_not_persist_error_text():
    def failed(_command):
        raise OSError("private-device-id and local path")

    document = _capture(query=failed)

    assert document["status"] == "partial"
    assert document["sampling"]["frequency_seconds"] == 3
    assert "private-device-id" not in json.dumps(document)


def test_subprocess_targets_share_one_package_version_query():
    queries = []

    def query(command):
        queries.append(command)
        return "versionCode=1 minSdk=23\nversionName=one\n" if "dumpsys" in command else ""

    document = _capture(
        query=query, target_processes=["com.example.app", "com.example.app:service"],
    )

    assert queries.count("dumpsys package com.example.app") == 1
    assert [target["process"] for target in document["targets"]] == [
        "com.example.app", "com.example.app:service",
    ]


def test_reader_never_reads_unbounded_bytes(tmp_path, monkeypatch):
    from services.performance_metadata import MAX_METADATA_BYTES, read_metadata

    path = _write(tmp_path)
    path.write_bytes(b" " * (MAX_METADATA_BYTES * 2))
    original = Path.open
    sizes = []

    class LimitedRead:
        def __enter__(self):
            self.stream = original(path, "rb")
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            sizes.append(size)
            assert 0 < size <= MAX_METADATA_BYTES + 1
            return self.stream.read(size)

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: LimitedRead())
    result = read_metadata(path, expected_run_id=RUN_ID)
    assert result.status == "invalid" and sizes == [MAX_METADATA_BYTES + 1]


def test_atomic_metadata_round_trip_and_distinct_run_files(tmp_path):
    from services.performance_metadata import read_metadata

    first = _write(tmp_path)
    second_document = _capture(run_id="b" * 32)
    second = _write(tmp_path, second_document)

    assert first != second and first.is_file() and second.is_file()
    loaded = read_metadata(first, expected_run_id=RUN_ID)
    assert loaded.status == "complete"
    assert loaded.path == str(first)
    assert loaded.app_version == "com.example.app: 1.2 beta (123); com.example.other: 2.0 (8)"


def test_partial_multi_target_version_uses_neutral_missing_marker(tmp_path):
    from services.performance_metadata import read_metadata

    document = _capture(query=lambda command: (
        "versionCode=1\nversionName=one\n" if command.endswith("com.example.app") else ""
    ))
    loaded = read_metadata(_write(tmp_path, document), expected_run_id=RUN_ID)

    assert loaded.app_version == "com.example.app: one (1); com.example.other: —"
    assert loaded.status == "partial"


def test_unknown_single_target_version_keeps_empty_index_value(tmp_path):
    from services.performance_metadata import read_metadata

    document = _capture(query=lambda _command: "", target_processes=["com.example.app"])
    loaded = read_metadata(_write(tmp_path, document), expected_run_id=RUN_ID)

    assert loaded.app_version == ""
    assert loaded.status == "partial" and loaded.path


def test_version_exceeding_index_limit_stays_only_in_metadata(tmp_path):
    from services.performance_metadata import read_metadata

    document = _capture(
        query=lambda _command: "versionCode=1\nversionName=" + "v" * 200,
        target_processes=["com.example.app"],
    )
    path = _write(tmp_path, document)
    loaded = read_metadata(path, expected_run_id=RUN_ID)

    assert loaded.app_version == ""
    assert loaded.path == str(path)
    assert json.loads(path.read_text(encoding="utf-8"))["targets"][0]["version_name"] == "v" * 200
    assert loaded.status == "partial"


def test_failed_atomic_publish_preserves_previous_document(tmp_path, monkeypatch):
    from services import performance_metadata as module

    path = _write(tmp_path)
    original = path.read_bytes()
    monkeypatch.setattr(module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError()))
    changed = _capture(collector_version="3.2.26")

    with pytest.raises(OSError):
        module.write_metadata(tmp_path, changed)

    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("kind", ["missing", "broken", "oversized", "future", "wrong_run",
                                  "unknown_field", "partial"])
def test_reader_bounds_and_failure_states(tmp_path, kind):
    from services.performance_metadata import MAX_METADATA_BYTES, read_metadata

    document = _capture()
    if kind == "future":
        document["schema_version"] = 99
    if kind == "unknown_field":
        document["device"]["serial"] = "must-not-be-imported"
    if kind == "partial":
        document = _capture(query=lambda _command: "")
    path = tmp_path / "metadata.json"
    if kind != "missing":
        raw = json.dumps(document).encode()
        if kind == "broken":
            raw = b"{"
        elif kind == "oversized":
            raw = b" " * (MAX_METADATA_BYTES + 1)
        path.write_bytes(raw)
    result = read_metadata(path, expected_run_id="b" * 32 if kind == "wrong_run" else RUN_ID)

    expected = {"missing": "missing", "future": "unsupported", "wrong_run": "mismatch",
                "partial": "partial"}.get(kind, "invalid")
    assert result.status == expected
    assert result.app_version == ""
    assert bool(result.path) == (kind == "partial")


def test_result_query_imports_only_its_metadata_even_after_next_run_changes_folder(tmp_path):
    from services.mobileperf_runner import PerformanceResultQuery

    directory = tmp_path / "run"
    directory.mkdir()
    old_path = _write(directory)
    os.utime(old_path, ns=(100, 100))
    old_query = PerformanceResultQuery(str(tmp_path), (), (), finished_at_ns=200, run_id=RUN_ID)
    new_path = _write(directory, _capture(run_id="b" * 32))
    os.utime(new_path, ns=(300, 300))
    os.utime(directory, ns=(300, 300))

    result = old_query.discover()

    assert result.result_dir == str(directory)
    assert result.metadata_file == str(old_path)
    assert result.metadata_status == "complete"
    assert result.app_version.startswith("com.example.app: 1.2 beta")
    assert result.report_file == ""


def test_new_run_missing_metadata_keeps_report_and_marks_metadata_unknown(tmp_path):
    from services.mobileperf_runner import PerformanceResultQuery

    directory = tmp_path / "run"
    directory.mkdir()
    report = directory / "summary_demo.xlsx"
    report.write_bytes(b"report")

    result = PerformanceResultQuery(str(tmp_path), (), (), run_id=RUN_ID).discover()

    assert result.report_file == str(report)
    assert result.metadata_status == "missing"
    assert result.app_version == "" and not result.error


def test_legacy_result_query_keeps_compatibility_without_metadata(tmp_path):
    from services.mobileperf_runner import PerformanceResultQuery

    directory = tmp_path / "old"
    directory.mkdir()
    (directory / "summary_old.xlsx").write_bytes(b"report")

    result = PerformanceResultQuery(str(tmp_path), (), ()).discover()

    assert result.metadata_status == "legacy"
    assert result.metadata_file == "" and not result.error


def test_new_run_without_result_root_marks_metadata_unknown(tmp_path):
    from services.mobileperf_runner import PerformanceResultQuery

    result = PerformanceResultQuery(
        str(tmp_path / "not-created"), (), (), run_id=RUN_ID,
    ).discover()

    assert result.metadata_status == "missing"
    assert result.metadata_file == "" and not result.error


def _worker(tmp_path, monkeypatch, query):
    from mobileperf.android.globaldata import RuntimeData
    from mobileperf.android.startup import StartUp

    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    worker = StartUp.__new__(StartUp)
    worker.serialnum = "test-device-private"
    worker.packages = ["com.example.app"]
    worker.frequency = 3
    worker.timeout = 120
    worker.stop_file = ""
    worker.config_dic = {"dumpheap_freq": 600, "monkey": "false"}
    worker.device = SimpleNamespace(adb=SimpleNamespace(run_shell_cmd=query))
    monkeypatch.setenv("MOBILEPERF_RUN_ID", RUN_ID)
    return worker


def test_worker_writes_metadata_and_reuses_package_query(tmp_path, monkeypatch):
    from mobileperf.android.globaldata import RuntimeData
    from services.performance_metadata import metadata_filename, read_metadata

    queries = []

    def query(command, **_kwargs):
        queries.append(command)
        if command.startswith("dumpsys package"):
            return "versionCode=42 minSdk=23\nversionName=4.2\nraw-private-field=secret\n"
        return {"getprop ro.product.brand": "Example", "getprop ro.product.model": "Model",
                "getprop ro.build.version.release": "15", "getprop ro.build.version.sdk": "35",
                "getprop ro.product.cpu.abilist": "x86_64"}.get(command, "")

    worker = _worker(tmp_path, monkeypatch, query)
    try:
        worker.save_device_info()
        result = read_metadata(tmp_path / metadata_filename(RUN_ID), expected_run_id=RUN_ID)
        assert result.app_version == "4.2 (42)"
        assert sum(command.startswith("dumpsys package") for command in queries) == 1
        raw = Path(result.path).read_text(encoding="utf-8")
        assert "test-device-private" not in raw and "raw-private-field" not in raw
        legacy = (tmp_path / "device_test_info.txt").read_text(encoding="utf-8")
        assert "device serialnum:test-device-private" in legacy
        assert "test package ver:versionCode=42" in legacy
    finally:
        RuntimeData.end_run()


@pytest.mark.parametrize("cancelled", [False, True])
def test_worker_query_budget_and_cancellation_keep_unknown_metadata(
    tmp_path, monkeypatch, cancelled,
):
    from mobileperf.android import startup as module
    from mobileperf.android.globaldata import RuntimeData
    from services.performance_metadata import metadata_filename, read_metadata

    clock = [0.0]
    budgets = []

    def query(_command, **options):
        budgets.append(options["timeout"])
        clock[0] += options["timeout"]
        return ""

    worker = _worker(tmp_path, monkeypatch, query)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    try:
        if cancelled:
            RuntimeData.exit_event.set()
        worker.save_device_info()
        result = read_metadata(tmp_path / metadata_filename(RUN_ID), expected_run_id=RUN_ID)
        assert result.status == "partial" and result.app_version == ""
        assert sum(budgets) <= 15
        assert budgets == ([] if cancelled else [3] * 5)
    finally:
        RuntimeData.end_run()


def test_worker_metadata_write_failure_preserves_legacy_output_and_does_not_escape(
    tmp_path, monkeypatch,
):
    from mobileperf.android import startup as module
    from mobileperf.android.globaldata import RuntimeData

    worker = _worker(tmp_path, monkeypatch, lambda *_args, **_kwargs: "")
    monkeypatch.setattr(module, "write_metadata", lambda *_args: (_ for _ in ()).throw(OSError()))
    try:
        worker.save_device_info()
        assert (tmp_path / "device_test_info.txt").is_file()
        assert not list(tmp_path.glob("performance_metadata_*.json"))
    finally:
        RuntimeData.end_run()


def test_runner_freezes_metadata_identity_and_copy_of_configuration(tmp_path, monkeypatch):
    import io
    import threading
    from unittest.mock import Mock

    from core.exec import ProcessRunner
    from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner

    process = SimpleNamespace(
        stdout=io.StringIO(), stderr=io.StringIO(), returncode=0, poll=lambda: 0,
    )
    launcher = Mock(spec=ProcessRunner)
    launcher.start.return_value = process
    runner = MobilePerfRunner(process_runner=launcher, project_root=tmp_path)
    monkeypatch.setattr(runner, "_resolve_adb_path", lambda: "test-adb")
    config = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "first"))
    completed = threading.Event()
    runner.start(config, on_finished=completed.set)
    assert completed.wait(3)
    first = runner.freeze_result_query()
    first_environment = launcher.start.call_args.kwargs["env"]
    config.package = "com.example.changed"
    config.save_path = str(tmp_path / "changed")
    config.monkey_config.seed = 7

    assert runner.last_config.package == "com.example.app"
    assert runner.last_config.monkey_config.seed != 7
    assert runner.freeze_result_query().root == first.root
    assert first.run_id == first_environment["MOBILEPERF_RUN_ID"]
    runner.stop(timeout=2)
    launcher.start.return_value = SimpleNamespace(
        stdout=io.StringIO(), stderr=io.StringIO(), returncode=0, poll=lambda: 0,
    )
    completed.clear()
    runner.start(config, on_finished=completed.set)
    assert completed.wait(3)
    second = runner.freeze_result_query()
    assert second.run_id != first.run_id and second.root != first.root
    assert first.run_id == first_environment["MOBILEPERF_RUN_ID"]
    runner.stop(timeout=2)


def test_collection_publishes_metadata_before_first_monitor_and_keeps_it_on_cancel(
    tmp_path, monkeypatch,
):
    from mobileperf.android import startup as module
    from mobileperf.android.globaldata import RuntimeData
    from services.performance_metadata import read_metadata

    worker = _worker(tmp_path, monkeypatch, lambda *_args, **_kwargs: "")
    worker.device.adb.is_connected = lambda _device: True
    worker.device.adb.is_app_installed = lambda _package: True
    worker.config_dic.update(
        main_activity="", activity_list="", save_path=str(tmp_path), timeout=120,
    )
    worker.monitors = []
    worker.logcat_monitor = None
    worker.exceptionlog_list = []
    worker.clear_heapdump = lambda: None
    worker.stop = lambda: None
    seen = []

    def start(_timestamp):
        artifacts = list(Path(RuntimeData.package_save_path).glob("performance_metadata_*.json"))
        assert len(artifacts) == 1
        record = read_metadata(artifacts[0], expected_run_id=RUN_ID)
        assert record.path and record.status == "partial"
        seen.append(json.loads(artifacts[0].read_text(encoding="utf-8")))
        RuntimeData.exit_event.set()

    for name in ("CpuMonitor", "MemMonitor", "TrafficMonitor", "FPSMonitor",
                 "FdMonitor", "ThreadNumMonitor"):
        monkeypatch.setattr(module, name, lambda *_args, **_kwargs: SimpleNamespace(start=start))
    try:
        worker._run_collection(time_out=10)
        assert len(seen) == 1
        assert seen[0]["sampling"]["timeout_seconds"] == 10
        assert list(tmp_path.rglob("performance_metadata_*.json"))
    finally:
        RuntimeData.end_run()
