# ADR-0003 Phase 2：拆分自 tests/test_model_execution.py。

import configparser
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from models.base.process_runner import ProcessRunner
from services.mobileperf_runner import MobilePerfMonkeyConfig, MobilePerfRunConfig, MobilePerfRunner


def _mobileperf_config_signature(path: Path) -> tuple[bytes, int, str]:
    content = path.read_bytes()
    return content, path.stat().st_mtime_ns, hashlib.sha256(content).hexdigest()


def _parse_mobileperf_config_without_device(path: Path) -> dict[str, object]:
    from mobileperf.android.startup import StartUp

    startup = StartUp.__new__(StartUp)
    startup.config_path = str(path)
    return startup.parse_data_from_config()


_MOBILEPERF_TEST_BOM_PREFIXES = (
    ("unicode", "\ufeff"),
    ("historical-be", "\xfe\xff"),
    ("historical-le", "\xff\xfe"),
    ("historical-utf8", "\xef\xbb\xbf"),
)
_MOBILEPERF_CONSECUTIVE_BOM_CASES = [
    pytest.param(prefix + prefix, id=f"repeat-{name}")
    for name, prefix in _MOBILEPERF_TEST_BOM_PREFIXES
] + [
    pytest.param(first + second, id=f"mixed-{first_name}-{second_name}")
    for first_name, first in _MOBILEPERF_TEST_BOM_PREFIXES
    for second_name, second in _MOBILEPERF_TEST_BOM_PREFIXES
]


def test_mobileperf_config_generation_does_not_touch_default_config(tmp_path):
    default_config = Path("mobileperf/config.conf")
    before = default_config.read_text(encoding="utf-8")
    cfg = MobilePerfRunConfig(
        device_id="device-1",
        package="com.example.app",
        frequency_seconds=2,
        timeout_minutes=3,
        dumpheap_minutes=4,
        monkey_enabled=True,
        exception_keywords=["fatal exception", "has died"],
        phone_log_paths=["/data/anr", "/sdcard/logs"],
        save_path=str(tmp_path / "out"),
        mailbox="qa@example.com",
        monkey_config=MobilePerfMonkeyConfig(
            throttle_ms=1000,
            seed=42,
            ignore_crashes=False,
            ignore_timeouts=True,
            ignore_security=False,
            kill_after_error=True,
            pct_touch=40,
            pct_motion=20,
            pct_nav=30,
            pct_anyevent=10,
            pct_trackball=0,
            pct_majornav=0,
            pct_syskeys=0,
            pct_appswitch=0,
            pct_flip=0,
            pct_pinchzoom=0,
        ),
    )

    generated = Path(cfg.write_config(tmp_path))

    assert generated.name == "mobileperf_run.conf"
    text = generated.read_text(encoding="utf-8")
    assert "package = com.example.app" in text
    assert "monkey = true" in text
    assert "monkey_throttle = 1000" in text
    assert "monkey_seed = 42" in text
    assert "monkey_ignore_crashes = false" in text
    assert "monkey_pct_touch = 40" in text
    assert "monkey_pct_nav = 30" in text
    assert "mailbox = qa@example.com" in text
    assert "phone_log_path = /data/anr;/sdcard/logs" in text
    assert default_config.read_text(encoding="utf-8") == before


def test_mobileperf_run_config_normalizes_semicolon_values_without_mutating_inputs():
    exception_keywords = [" Fatal Exception ", "", " Fatal Exception "]
    phone_log_paths = [" /data/anr ", "  ", "/sdcard/Logs"]
    monkey_config = MobilePerfMonkeyConfig(seed=73)

    cfg = MobilePerfRunConfig(
        device_id=" test-device ",
        package=" Main.App ; child.Pkg ;; Main.App ",
        frequency_seconds=7,
        timeout_minutes=11,
        dumpheap_minutes=13,
        monkey_enabled=True,
        exception_keywords=exception_keywords,
        phone_log_paths=phone_log_paths,
        save_path=" output/path ",
        mailbox=" qa@example.invalid ",
        monkey_config=monkey_config,
    )

    assert cfg.package == "Main.App;child.Pkg;Main.App"
    assert cfg.exception_keywords == ["Fatal Exception", "Fatal Exception"]
    assert cfg.phone_log_paths == ["/data/anr", "/sdcard/Logs"]
    assert cfg.exception_keywords is not exception_keywords
    assert cfg.phone_log_paths is not phone_log_paths
    assert exception_keywords == [" Fatal Exception ", "", " Fatal Exception "]
    assert phone_log_paths == [" /data/anr ", "  ", "/sdcard/Logs"]
    assert cfg.device_id == " test-device "
    assert cfg.frequency_seconds == 7
    assert cfg.timeout_minutes == 11
    assert cfg.dumpheap_minutes == 13
    assert cfg.monkey_enabled is True
    assert cfg.save_path == " output/path "
    assert cfg.mailbox == " qa@example.invalid "
    assert cfg.monkey_config is monkey_config


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        (" ; ; ", ""),
        (" Main.App ; child.Pkg ;; Main.App ", "Main.App;child.Pkg;Main.App"),
    ],
)
def test_mobileperf_package_normalizer_preserves_order_case_and_duplicates(raw, expected):
    from services.mobileperf_runner import _normalize_package

    assert _normalize_package(raw) == expected


def test_mobileperf_startup_parses_bom_readonly_config_without_modifying_input(tmp_path):
    cfg = MobilePerfRunConfig(
        device_id="test-device",
        package=" com.main ; child.Pkg ; ",
        frequency_seconds=5,
        timeout_minutes=10,
        dumpheap_minutes=2,
    )
    path = Path(cfg.write_config(tmp_path))
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    before = _mobileperf_config_signature(path)
    path.chmod(stat.S_IREAD)
    try:
        parsed = _parse_mobileperf_config_without_device(path)

        assert parsed["package"] == ["com.main", "child.Pkg"]
        assert parsed["frequency"] == 5
        assert parsed["timeout"] == 600
        assert parsed["dumpheap_freq"] == 120
        assert _mobileperf_config_signature(path) == before
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("bom_prefixes", _MOBILEPERF_CONSECUTIVE_BOM_CASES)
def test_mobileperf_startup_removes_consecutive_supported_bom_prefixes_at_file_head(
    tmp_path,
    bom_prefixes,
):
    cfg = MobilePerfRunConfig(
        device_id="test-device",
        package="Main.App",
        exception_keywords=["Fatal"],
    )
    path = Path(cfg.write_config(tmp_path))
    path.write_text(bom_prefixes + path.read_text(encoding="utf-8"), encoding="utf-8")
    before = _mobileperf_config_signature(path)

    parsed = _parse_mobileperf_config_without_device(path)

    assert parsed["package"] == ["Main.App"]
    assert parsed["exceptionlog"] == ["Fatal"]
    assert _mobileperf_config_signature(path) == before


@pytest.mark.parametrize(
    "bom_text",
    [pytest.param(prefix, id=name) for name, prefix in _MOBILEPERF_TEST_BOM_PREFIXES],
)
def test_mobileperf_startup_preserves_supported_bom_text_inside_config_values(
    tmp_path,
    bom_text,
):
    expected_keyword = f"Fatal{bom_text}Case"
    cfg = MobilePerfRunConfig(
        device_id="test-device",
        package="Main.App",
        exception_keywords=[expected_keyword],
    )
    path = Path(cfg.write_config(tmp_path))
    before = _mobileperf_config_signature(path)

    parsed = _parse_mobileperf_config_without_device(path)

    assert parsed["exceptionlog"] == [expected_keyword]
    assert _mobileperf_config_signature(path) == before


def test_mobileperf_config_bom_cleanup_accepts_empty_text():
    from mobileperf.android.startup import _remove_config_bom_prefix

    assert _remove_config_bom_prefix("") == ""


def test_mobileperf_config_round_trip_preserves_units_and_complete_monkey_values(tmp_path):
    monkey_config = MobilePerfMonkeyConfig(
        throttle_ms=321,
        seed=987654,
        ignore_crashes=False,
        ignore_timeouts=True,
        ignore_security=False,
        kill_after_error=True,
        pct_touch=1,
        pct_motion=2,
        pct_trackball=3,
        pct_nav=4,
        pct_majornav=5,
        pct_syskeys=6,
        pct_appswitch=7,
        pct_anyevent=8,
        pct_flip=9,
        pct_pinchzoom=10,
    )
    cfg = MobilePerfRunConfig(
        device_id="test-device",
        package=" Main.App ; child.Pkg ; Main.App ",
        frequency_seconds=17,
        timeout_minutes=23,
        dumpheap_minutes=29,
        monkey_enabled=True,
        exception_keywords=[" Fatal Exception ", "", "Warn"],
        phone_log_paths=[" /data/anr ", "", "/sdcard/Logs"],
        save_path=str(tmp_path / "output"),
        mailbox="qa@example.invalid",
        monkey_config=monkey_config,
    )
    path = Path(cfg.write_config(tmp_path))
    before = _mobileperf_config_signature(path)

    parsed = _parse_mobileperf_config_without_device(path)

    assert parsed == {
        "package": ["Main.App", "child.Pkg", "Main.App"],
        "pid_change_focus_package": [""],
        "frequency": 17,
        "dumpheap_freq": 29 * 60,
        "timeout": 23 * 60,
        "serialnum": "test-device",
        "mailbox": "qa@example.invalid",
        "exceptionlog": ["Fatal Exception", "Warn"],
        "save_path": os.path.normpath(str(tmp_path / "output")),
        "phone_log_path": ["/data/anr", "/sdcard/Logs"],
        "monkey": "true",
        "monkey_throttle": 321,
        "monkey_seed": 987654,
        "monkey_ignore_crashes": "false",
        "monkey_ignore_timeouts": "true",
        "monkey_ignore_security": "false",
        "monkey_kill_after_error": "true",
        "monkey_pct_touch": 1,
        "monkey_pct_motion": 2,
        "monkey_pct_trackball": 3,
        "monkey_pct_nav": 4,
        "monkey_pct_majornav": 5,
        "monkey_pct_syskeys": 6,
        "monkey_pct_appswitch": 7,
        "monkey_pct_anyevent": 8,
        "monkey_pct_flip": 9,
        "monkey_pct_pinchzoom": 10,
        "main_activity": [""],
        "activity_list": [""],
    }
    assert _mobileperf_config_signature(path) == before


def test_mobileperf_startup_cleans_only_designated_config_lists(tmp_path):
    cfg = MobilePerfRunConfig(
        device_id="test-device",
        package="Main.App",
        exception_keywords=["Fatal"],
        phone_log_paths=["/data/anr"],
    )
    path = Path(cfg.write_config(tmp_path))
    content = path.read_text(encoding="utf-8")
    content = content.replace("package = Main.App", "package = Main.App ;; Child ; Main.App")
    content = content.replace("exceptionlog = Fatal", "exceptionlog = ; Fatal ;; Warn ;")
    content = content.replace(
        "phone_log_path = /data/anr", "phone_log_path = ; /data/anr ;; /sdcard/Logs ;"
    )
    content = content.replace("main_activity = ", "main_activity =  MainActivity ; Child ")
    content = content.replace("activity_list = ", "activity_list =  One ; ; Two ")
    path.write_text(content, encoding="utf-8")
    before = _mobileperf_config_signature(path)

    parsed = _parse_mobileperf_config_without_device(path)

    assert parsed["package"] == ["Main.App", "Child", "Main.App"]
    assert parsed["exceptionlog"] == ["Fatal", "Warn"]
    assert parsed["phone_log_path"] == ["/data/anr", "/sdcard/Logs"]
    assert parsed["main_activity"] == ["MainActivity ", " Child"]
    assert parsed["activity_list"] == ["One ", " ", " Two"]
    assert _mobileperf_config_signature(path) == before


def test_mobileperf_startup_parses_default_config_copy_without_modifying_input(tmp_path):
    path = tmp_path / "default.conf"
    shutil.copy2(Path("mobileperf/config.conf"), path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text(
        "".join(
            "serialnum=test-device\n" if line.startswith("serialnum=") else line for line in lines
        ),
        encoding="utf-8",
    )
    before = _mobileperf_config_signature(path)

    parsed = _parse_mobileperf_config_without_device(path)

    assert parsed["package"]
    assert parsed["frequency"] > 0
    assert _mobileperf_config_signature(path) == before


@pytest.mark.parametrize(
    ("replacement", "error_type"),
    [
        (lambda text: text.replace("[Common]", "Common"), configparser.Error),
        (lambda text: text.replace("frequency = 5", "frequency = invalid"), SystemExit),
    ],
)
def test_mobileperf_startup_invalid_config_fails_without_modifying_input(
    tmp_path,
    replacement,
    error_type,
):
    cfg = MobilePerfRunConfig(device_id="test-device", package="Main.App")
    path = Path(cfg.write_config(tmp_path))
    path.write_text(replacement(path.read_text(encoding="utf-8")), encoding="utf-8")
    before = _mobileperf_config_signature(path)

    with pytest.raises(error_type):
        _parse_mobileperf_config_without_device(path)

    assert _mobileperf_config_signature(path) == before


def test_mobileperf_config_normalizes_save_path_before_write(tmp_path):
    cfg = MobilePerfRunConfig(
        device_id="emulator-5554",
        package="com.example.app",
        save_path="E:/Download\\mobileperf\\emulator-5554",
    )

    generated = Path(cfg.write_config(tmp_path))
    text = generated.read_text(encoding="utf-8")
    expected_save_path = os.path.normpath(r"E:\Download\mobileperf\emulator-5554")

    assert f"save_path = {expected_save_path}" in text


def test_mobileperf_excel_truncates_long_csv_sheet_names_for_report(tmp_path):
    from mobileperf.android.excel import Excel

    csv_file = tmp_path / "pss_com.google.android.apps.nexuslauncher.csv"
    csv_file.write_text(
        "datatime,package,pss,java_heap,native_heap,system\n"
        "2026-06-13 20:51:00,com.google.android.apps.nexuslauncher,1,2,3,4\n"
        "2026-06-13 20:51:01,com.google.android.apps.nexuslauncher,2,3,4,5\n",
        encoding="utf-8",
    )
    excel = Excel(str(tmp_path / "summary.xlsx"))

    excel.csv_to_xlsx(
        str(csv_file),
        "pss_detail",
        "datatime",
        "mem(MB)",
        ["pss", "java_heap", "native_heap", "system"],
    )
    excel.save()

    assert (tmp_path / "summary.xlsx").exists()
    assert "pss_com.google.android.apps.nex" in excel._worksheet_names
    assert all(len(name) <= 31 for name in excel._worksheet_names)


def test_mobileperf_excel_generates_unique_valid_sheet_names(tmp_path):
    from mobileperf.android.excel import Excel

    excel = Excel(str(tmp_path / "summary.xlsx"))
    sheet_name = "bad:name?with/slash\\andaverylongworksheetname"

    excel.add_sheet(sheet_name, "time", "value", ["time", "value"], [["1", "2"], ["2", "3"]])
    excel.add_sheet(sheet_name, "time", "value", ["time", "value"], [["1", "2"], ["2", "3"]])
    excel.save()

    names = sorted(excel._worksheet_names)
    assert len(names) == 2
    assert names[0] != names[1]
    assert all(len(name) <= 31 for name in names)
    assert all(not any(char in name for char in "[]:*?/\\") for name in names)


def test_mobileperf_runner_starts_python_module_with_generated_config(tmp_path):
    runner_process = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    runner_process.start.return_value = proc
    runner = MobilePerfRunner(
        process_runner=runner_process,
        project_root=tmp_path,
        python_executable="python-test",
    )
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "out"))

    with patch.object(MobilePerfRunner, "_resolve_adb_path", return_value="adb-test"):
        runner.start(cfg)

    args = runner_process.start.call_args.args
    kwargs = runner_process.start.call_args.kwargs
    assert args[1][:3] == ["python-test", "-m", "mobileperf.android.startup"]
    assert "--config" in args[1]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["ADB_PATH"] == "adb-test"
    assert "MOBILEPERF_STOP_FILE" in kwargs["env"]
    assert Path(args[1][-1]).name == "mobileperf_run.conf"
    runner.stop()


def test_mobileperf_runner_uses_worker_entry_when_frozen(tmp_path, monkeypatch):
    runner_process = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    runner_process.start.return_value = proc
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    runner = MobilePerfRunner(
        process_runner=runner_process,
        project_root=tmp_path,
        python_executable="ADBLab.exe",
    )
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "out"))

    with patch.object(MobilePerfRunner, "_resolve_adb_path", return_value="adb-test"):
        runner.start(cfg)

    args = runner_process.start.call_args.args
    kwargs = runner_process.start.call_args.kwargs
    assert args[1][:2] == ["ADBLab.exe", "--mobileperf-worker"]
    assert "-m" not in args[1]
    assert "--config" in args[1]
    assert kwargs["env"]["MOBILEPERF_LOG_DIR"].endswith(os.path.join("ADBLab", "logs"))
    runner.stop()


def test_mobileperf_runner_stop_requests_mobileperf_report_shutdown(tmp_path):
    runner_process = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    proc.wait.return_value = None
    proc.returncode = 0
    runner_process.start.return_value = proc
    runner = MobilePerfRunner(
        process_runner=runner_process,
        project_root=tmp_path,
        python_executable="python-test",
    )
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "out"))

    runner.start(cfg)
    with patch.object(
        runner,
        "_request_stop_context",
        wraps=runner._request_stop_context,
    ) as request_stop:
        code = runner.stop(timeout=7)

    assert code == 0
    request_stop.assert_called_once()
    assert request_stop.call_args.args[0] is not None
    proc.wait.assert_called_once_with(timeout=7)
    runner_process.stop.assert_called_once()
    assert runner_process.stop.call_args.kwargs["timeout"] == 0


def test_mobileperf_runner_request_stop_writes_stop_file(tmp_path):
    runner = MobilePerfRunner(project_root=tmp_path)
    runner._stop_path = str(tmp_path / "mobileperf.stop")

    runner.request_stop()

    assert Path(runner._stop_path).read_text(encoding="utf-8") == "stop"


def test_mobileperf_runner_stop_force_stops_after_report_timeout(tmp_path):
    runner_process = Mock(spec=ProcessRunner)
    proc = Mock()
    proc.stdout = []
    proc.poll.return_value = None
    proc.wait.side_effect = subprocess.TimeoutExpired(cmd="mobileperf", timeout=7)
    runner_process.start.return_value = proc
    runner_process.stop.return_value = -9
    runner = MobilePerfRunner(
        process_runner=runner_process,
        project_root=tmp_path,
        python_executable="python-test",
    )
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "out"))

    runner.start(cfg)
    code = runner.stop(timeout=7)

    assert code == -9
    runner_process.stop.assert_called_once()


def test_mobileperf_runner_finds_latest_result_and_report(tmp_path):
    root = tmp_path / "mobileperf" / "com.example.app"
    old_dir = root / "2026_06_13_10_00_00"
    new_dir = root / "2026_06_13_10_05_00"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old_report = old_dir / "summary_old.xlsx"
    new_report = new_dir / "summary_new.xlsx"
    old_report.write_text("old", encoding="utf-8")
    new_report.write_text("new", encoding="utf-8")
    os.utime(old_dir, (1, 1))
    os.utime(new_dir, (2, 2))
    os.utime(old_report, (1, 1))
    os.utime(new_report, (2, 2))
    runner = MobilePerfRunner(project_root=tmp_path)
    cfg = MobilePerfRunConfig(package="com.example.app", save_path=str(tmp_path / "mobileperf"))
    runner._last_config = cfg

    assert runner.latest_result_dir() == str(new_dir)
    assert runner.latest_report_file() == str(new_report)


def test_mobileperf_startup_detects_adblab_stop_file(tmp_path):
    from mobileperf.android.startup import StartUp

    startup = StartUp.__new__(StartUp)
    startup.stop_file = str(tmp_path / "mobileperf.stop")

    assert startup.check_stop_file_quit() is False
    Path(startup.stop_file).write_text("stop", encoding="utf-8")
    assert startup.check_stop_file_quit() is True


def test_mobileperf_monkey_derives_event_count_from_collection_timeout():
    from mobileperf.android.monkey import Monkey

    monkey = Monkey.__new__(Monkey)
    monkey.throttle_ms = 500

    assert Monkey._event_count_for_timeout(monkey, 600) == 1201
    assert Monkey._event_count_for_timeout(monkey, 1) == 3


def test_mobileperf_monkey_keeps_legacy_large_timeout_as_event_count():
    from mobileperf.android.monkey import Monkey

    with patch("mobileperf.android.monkey.AndroidDevice") as android_device:
        monkey = Monkey("device-1", "com.example.app")

    android_device.assert_called_once_with("device-1")
    assert monkey.timeout is None
    assert monkey.event_count == Monkey.DEFAULT_EVENT_COUNT


def test_mobileperf_monkey_builds_command_from_configurable_options():
    from mobileperf.android.monkey import Monkey

    with patch("mobileperf.android.monkey.AndroidDevice"):
        monkey = Monkey(
            "device-1",
            "com.example.app",
            timeout=10,
            throttle_ms=1000,
            seed=42,
            ignore_crashes=False,
            ignore_timeouts=True,
            ignore_security=False,
            kill_after_error=False,
            pct_touch=40,
            pct_motion=20,
            pct_nav=30,
            pct_anyevent=10,
            pct_trackball=0,
            pct_majornav=0,
            pct_syskeys=0,
            pct_appswitch=0,
            pct_flip=0,
            pct_pinchzoom=0,
        )

    cmd = monkey._build_monkey_cmd("com.example.app", 11)

    assert "-s 42" in cmd
    assert "--throttle 1000 11" in cmd
    assert "--pct-touch 40" in cmd
    assert "--pct-motion 20" in cmd
    assert "--pct-nav 30" in cmd
    assert "--pct-anyevent 10" in cmd
    assert "--ignore-timeouts" in cmd
    assert "--ignore-crashes" not in cmd
    assert "--ignore-security-exceptions" not in cmd
    assert "--kill-process-after-error" not in cmd
    assert monkey._event_percentage_total() == 100


def test_mobileperf_startup_passes_collection_timeout_to_monkey():
    from mobileperf.android import startup as startup_module
    from mobileperf.android.startup import StartUp

    startup = StartUp.__new__(StartUp)
    startup.serialnum = "device-1"
    startup.packages = ["com.example.app"]
    startup.frequency = 5
    startup.timeout = 600
    startup.config_dic = {
        "monkey": "true",
        "main_activity": "",
        "activity_list": "",
        "save_path": "",
        "monkey_throttle": 1000,
        "monkey_seed": 42,
        "monkey_ignore_crashes": "false",
        "monkey_ignore_timeouts": "true",
        "monkey_ignore_security": "false",
        "monkey_kill_after_error": "true",
        "monkey_pct_touch": 40,
        "monkey_pct_motion": 20,
        "monkey_pct_trackball": 0,
        "monkey_pct_nav": 30,
        "monkey_pct_majornav": 0,
        "monkey_pct_syskeys": 0,
        "monkey_pct_appswitch": 0,
        "monkey_pct_anyevent": 10,
        "monkey_pct_flip": 0,
        "monkey_pct_pinchzoom": 0,
    }
    startup.exceptionlog_list = []
    startup.monitors = []
    startup.device = Mock()
    startup.device.adb.is_connected.return_value = True
    startup.device.adb.is_app_installed.return_value = False

    with (
        patch.object(startup_module, "CpuMonitor"),
        patch.object(startup_module, "MemMonitor"),
        patch.object(startup_module, "TrafficMonitor"),
        patch.object(startup_module, "FPSMonitor"),
        patch.object(startup_module, "FdMonitor"),
        patch.object(startup_module, "ThreadNumMonitor"),
        patch.object(startup_module, "Monkey") as monkey_cls,
    ):
        startup.add_monitor = Mock()
        startup.clear_heapdump = Mock()
        startup.run()

    monkey_cls.assert_not_called()

    startup.device.adb.is_app_installed.return_value = True
    with (
        patch.object(startup_module, "CpuMonitor"),
        patch.object(startup_module, "MemMonitor"),
        patch.object(startup_module, "TrafficMonitor"),
        patch.object(startup_module, "FPSMonitor"),
        patch.object(startup_module, "FdMonitor"),
        patch.object(startup_module, "ThreadNumMonitor"),
        patch.object(startup_module, "Monkey") as monkey_cls,
        patch.object(startup_module, "LogcatMonitor"),
        patch.object(startup_module.FileUtils, "makedir"),
        patch.object(
            startup_module.TimeUtils, "getCurrentTimeUnderline", return_value="2026_06_13_10_00_00"
        ),
    ):
        startup.monitors = []
        startup.add_monitor = Mock(side_effect=lambda monitor: startup.monitors.append(monitor))
        startup.save_device_info = Mock()
        startup.stop = Mock(side_effect=SystemExit)
        monkey_cls.return_value = Mock()

        try:
            startup.run(time_out=0)
        except SystemExit:
            pass

    monkey_cls.assert_called_once_with(
        "device-1",
        "com.example.app",
        timeout=600,
        throttle_ms=1000,
        seed=42,
        ignore_crashes=False,
        ignore_timeouts=True,
        ignore_security=False,
        kill_after_error=True,
        pct_touch=40,
        pct_motion=20,
        pct_trackball=0,
        pct_nav=30,
        pct_majornav=0,
        pct_syskeys=0,
        pct_appswitch=0,
        pct_anyevent=10,
        pct_flip=0,
        pct_pinchzoom=0,
    )


def test_mobileperf_startup_uses_default_monkey_options_for_legacy_config():
    from mobileperf.android.startup import StartUp

    startup = StartUp.__new__(StartUp)
    startup.config_dic = {}

    defaults = startup._optional_config_defaults()
    options = startup._monkey_options()

    assert defaults["monkey_throttle"] == 500
    assert options["throttle_ms"] == 500
    assert options["seed"] == 1000000
    assert options["ignore_crashes"] is True
    assert options["pct_touch"] == 15
    assert options["pct_nav"] == 40


def test_mobileperf_runner_batches_subprocess_log_lines_and_notifies_finish():
    runner = MobilePerfRunner(process_runner=Mock(spec=ProcessRunner))
    runner.LOG_BATCH_SIZE = 3
    runner.LOG_BATCH_INTERVAL_SECONDS = 60
    proc = Mock()
    proc.stdout = iter(["one\n", "two\n", "three\n", "four\n"])
    proc.poll.return_value = 0
    runner._proc = proc
    received = []
    runner._on_log = received.append
    runner._on_finished = Mock()

    runner._read_logs()

    assert received == ["one\ntwo\nthree", "four"]
    runner._on_finished.assert_called_once()
