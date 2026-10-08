"""保护性能采集的目标身份、报告发布与采样写入失败边界。"""

import builtins
import csv
import errno
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from mobileperf.android import cpu_top, startup
from mobileperf.android.globaldata import RuntimeData
from mobileperf.android.report import Report
from mobileperf.extlib.xlsxwriter import workbook
from services.mobileperf_runner import MobilePerfRunConfig


@pytest.fixture(autouse=True)
def _end_runtime():
    yield
    RuntimeData.end_run()


def _write_cpu_csv(directory):
    (directory / "cpuinfo.csv").write_text(
        "datetime,package,pid_cpu%\n"
        "2026-09-29 10:00:00,com.example.app,10\n"
        "2026-09-29 10:00:01,com.example.app,11\n", encoding="utf-8",
    )


def _fail_second_zip_member(monkeypatch):
    class FullDisk(zipfile.ZipFile):
        def write(self, filename, arcname=None, *args, **kwargs):
            if len(self.namelist()) == 1:
                raise OSError(errno.ENOSPC, "synthetic full disk")
            return super().write(filename, arcname, *args, **kwargs)

    monkeypatch.setattr(workbook, "ZipFile", FullDisk)


def test_report_failure_preserves_existing_report_and_removes_incomplete_output(
    monkeypatch, tmp_path,
):
    from mobileperf.android import report

    _write_cpu_csv(tmp_path)
    monkeypatch.setattr(report.TimeUtils, "getCurrentTimeUnderline", lambda: "same-second")
    existing = tmp_path / "summary_same-second.xlsx"
    existing.write_bytes(b"previous complete report")
    _fail_second_zip_member(monkeypatch)

    with pytest.raises(OSError):
        Report(str(tmp_path), ["com.example.app"])

    assert existing.read_bytes() == b"previous complete report"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "cpuinfo.csv", "summary_same-second.xlsx",
    ]


def test_report_success_publishes_complete_workbook(tmp_path):
    _write_cpu_csv(tmp_path)

    Report(str(tmp_path), ["com.example.app"])

    reports = list(tmp_path.glob("summary_*.xlsx"))
    assert len(reports) == 1
    with zipfile.ZipFile(reports[0]) as archive:
        assert archive.testzip() is None
        assert {"[Content_Types].xml", "xl/workbook.xml"} <= set(archive.namelist())
    assert len(list(tmp_path.iterdir())) == 2


def _worker_environment(monkeypatch, tmp_path, package="com.example.app"):
    config = MobilePerfRunConfig(package=package, save_path=str(tmp_path))
    config_path = config.write_config(tmp_path)
    events = []
    checked_packages = []
    adb = SimpleNamespace(
        is_connected=lambda serial: True,
        is_app_installed=lambda target: checked_packages.append(target) or True,
    )
    monkeypatch.setattr(startup, "AndroidDevice", lambda serial: SimpleNamespace(adb=adb))
    execution = SimpleNamespace(
        start=lambda: None, stop_requested=lambda: False,
        begin_cleanup=lambda: events.append("cleanup"),
        close=lambda: events.append("executor-closed"),
    )
    monkeypatch.setattr(startup, "MobilePerfAdbExecutor", lambda *args: execution)
    for name in ("CpuMonitor", "MemMonitor", "TrafficMonitor", "FPSMonitor", "FdMonitor",
                 "ThreadNumMonitor"):
        monkeypatch.setattr(startup, name, lambda *args, **kwargs: SimpleNamespace(
            start=lambda *_args: None, stop=lambda: events.append("monitor-stopped"),
        ))
    for name in ("clear_heapdump", "add_device_info", "pull_heapdump", "pull_log_files"):
        monkeypatch.setattr(startup.StartUp, name,
                            lambda *args, _name=name: events.append(_name))
    monkeypatch.setattr(startup.StartUp, "save_device_info",
                        lambda self: _write_cpu_csv(Path(RuntimeData.package_save_path)))
    monkeypatch.setattr(startup.StartUp, "_collection_finished", lambda *args: True)
    return config, config_path, events, checked_packages


def test_worker_report_failure_reaches_exit_boundary_after_all_cleanup(monkeypatch, tmp_path):
    _config, config_path, events, _packages = _worker_environment(monkeypatch, tmp_path)
    _fail_second_zip_member(monkeypatch)

    with pytest.raises(RuntimeError, match="报告"):
        main._run_mobileperf_worker(["--config", config_path])

    assert events.count("monitor-stopped") == 6
    assert events[-3:] == ["pull_heapdump", "pull_log_files", "executor-closed"]
    assert list(tmp_path.rglob("summary_*.xlsx")) == []
    assert len(list(tmp_path.rglob("cpuinfo.csv"))) == 1
    assert RuntimeData._instance is None


@pytest.mark.parametrize("package", [
    "com.example.app;com.example.app:remote",
    "com.example.app;com.example.app:one.worker;com.example.app:two.worker",
])
def test_worker_preserves_configured_process_names(monkeypatch, tmp_path, package):
    _config, path, _events, _packages = _worker_environment(monkeypatch, tmp_path, package)

    worker = startup.StartUp(config_path=path)

    assert worker.packages == package.split(";")
    assert RuntimeData.packages == package.split(";")


@pytest.mark.parametrize("invalid", [
    "com.example.app:../remote", "com.example.app:remote/child", "com.example.app:",
    "com.example.app:one:two", "com.example.app:remote$(id)", ".bad", "com..example",
])
def test_worker_rejects_invalid_target_instead_of_silently_dropping_it(
    monkeypatch, tmp_path, invalid,
):
    _config, path, _events, _packages = _worker_environment(
        monkeypatch, tmp_path, f"com.example.app;{invalid}",
    )

    with pytest.raises(ValueError):
        startup.StartUp(config_path=path)


def test_child_only_run_is_rejected_before_device_queries(monkeypatch, tmp_path):
    _config, path, _events, checked = _worker_environment(
        monkeypatch, tmp_path, "com.example.app:remote",
    )

    with pytest.raises(ValueError):
        startup.StartUp(config_path=path)

    assert checked == []


@pytest.mark.parametrize("persistent", [False, True])
def test_cpu_write_failure_does_not_join_samples_and_keeps_cancelable_wait(
    monkeypatch, tmp_path, persistent,
):
    collector = cpu_top.CpuCollector.__new__(cpu_top.CpuCollector)
    collector.packages = ["com.example.app"]
    collector._interval = 5
    collector._timeout = 60
    samples = []
    waits = []
    collector._stop_event = SimpleNamespace(
        is_set=lambda: len(samples) >= 2, wait=lambda delay: waits.append(delay),
    )

    def sample():
        samples.append(len(samples) + 1)
        return SimpleNamespace(
            source="top", package_list=[{"package": "com.example.app", "pid": "42",
                                         "pid_cpu": str(samples[-1])}],
            device_cpu_rate=samples[-1], user_rate="1", system_rate="0", idle_rate="99",
        )

    collector._top_cpuinfo = sample
    real_open = builtins.open
    opens = 0

    def open_with_failure(path, *args, **kwargs):
        nonlocal opens
        if str(path).endswith("cpuinfo.csv"):
            opens += 1
            if opens == 2 or (persistent and opens > 2):
                raise OSError(errno.ENOSPC, "synthetic full disk")
        return real_open(path, *args, **kwargs)

    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    monkeypatch.setattr(cpu_top, "open", open_with_failure, raising=False)

    collector._collect_package_cpu_thread("unused")

    with (tmp_path / "cpuinfo.csv").open() as source:
        rows = list(csv.reader(source))
    assert len(waits) == 2
    assert all(0 < delay <= 5 for delay in waits)
    if persistent:
        assert len(rows) == 1
    else:
        assert [len(row) for row in rows] == [8, 8]
        assert rows[1][-1] == "2"


def test_child_pss_files_keep_full_identity_and_all_reach_report(monkeypatch, tmp_path):
    from mobileperf.android import meminfos

    packages = ["com.example.app", "com.example.app:one.worker", "com.example.app:two.worker"]
    clock = [0.0]
    monkeypatch.setattr(meminfos, "time", SimpleNamespace(time=lambda: clock[0]))
    adb = SimpleNamespace(run_shell_cmd=lambda command: "",
                          cleanup_owned_heapdumps=lambda *args: None,
                          dumpheap=lambda *args: None)
    collector = meminfos.MemInfoPackageCollector(
        SimpleNamespace(adb=adb), packages, interval=1, timeout=1,
    )
    collector._stop_event.wait = lambda delay: clock.__setitem__(0, clock[0] + delay)
    collector._dumpsys_process_meminfo = lambda package: SimpleNamespace(
        totalPSS=10 + packages.index(package), pid=42, javaHeap=1, nativeHeap=2, system=3,
    )
    collector._dumpsys_meminfo = lambda: SimpleNamespace(
        package_pid_pss_list=[{"package": name, "pid": "42", "pss": "10"}
                              for name in packages],
        totalmem=1024, freemem=500, total_pss=30,
    )
    RuntimeData.begin_run()
    RuntimeData.package_save_path = str(tmp_path)
    RuntimeData.config_dic = {"dumpheap_freq": 3600, "pid_change_focus_package": []}

    collector._collect_memory_thread("1970_01_01_07_30_00")

    files = sorted(tmp_path.glob("pss_*.csv"))
    assert len(files) == 3
    assert (tmp_path / "pss_com.example.app.csv").exists()
    observed = {}
    for path in files:
        assert ":" not in path.name
        with path.open() as source:
            rows = list(csv.DictReader(source))
        assert len(rows) == 1
        observed[rows[0]["package"]] = float(rows[0]["pss"])
    assert observed == {"com.example.app": 10, "com.example.app:one.worker": 11,
                        "com.example.app:two.worker": 12}
    Report(str(tmp_path), packages)
    with zipfile.ZipFile(next(tmp_path.glob("summary_*.xlsx"))) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode()
        assert workbook_xml.count("<sheet ") == 5


def test_child_file_identity_survives_case_insensitive_filesystems():
    from mobileperf.android.process_target import process_file_segment

    targets = ["com.example.app:worker", "com.example.app:Worker", "com.example.app_worker"]
    segments = [process_file_segment(target) for target in targets]

    assert len({segment.casefold() for segment in segments}) == 3
    assert process_file_segment("Main.Example") == "Main.Example"
