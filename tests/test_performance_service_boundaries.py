"""性能配置与结果服务的导入、兼容入口和持久化契约。"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("module_name", [
    "services.performance", "services.performance.config", "services.performance.results",
])
def test_performance_data_import_does_not_load_execution_infrastructure(module_name):
    script = f"""
import importlib
import sys
importlib.import_module({module_name!r})
for name in ('services.mobileperf_runner', 'core.exec', 'core.owned_process'):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("new_first", [False, True])
@pytest.mark.parametrize(("module_name", "names"), [
    ("config", ("MobilePerfMonkeyConfig", "MobilePerfRunConfig", "normalize_local_path",
                "_split_semicolon", "_normalize_package", "_primary_package")),
    ("results", ("PerformanceArtifacts", "PerformanceResultQuery")),
])
def test_runner_compatibility_exports_share_identity_in_either_import_order(
    module_name, names, new_first,
):
    script = f"""
import importlib
old_name = 'services.mobileperf_runner'
new_name = 'services.performance.' + {module_name!r}
for name in ((new_name, old_name) if {new_first!r} else (old_name, new_name)):
    importlib.import_module(name)
old = importlib.import_module(old_name)
new = importlib.import_module(new_name)
for name in {names!r}:
    assert getattr(old, name) is getattr(new, name), name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_configuration_bytes_preserve_original_fields_order_utf8_and_platform_newlines(tmp_path):
    module = importlib.import_module("services.performance.config")
    config = module.MobilePerfRunConfig(
        device_id=" test-device ", package=" Main.App ; child.Pkg ;; Main.App ",
        frequency_seconds=0, timeout_minutes=11, dumpheap_minutes=13, monkey_enabled=True,
        exception_keywords=[" Fatal Exception ", "", "崩溃"],
        phone_log_paths=[" /data/anr ", " ", "/sdcard/Logs"], save_path=" perf-output ",
        mailbox=" qa%tag@example.invalid ",
        monkey_config=module.MobilePerfMonkeyConfig(
            throttle_ms=0, seed=-1, ignore_crashes=False, ignore_timeouts=True,
            ignore_security=False, kill_after_error=True, pct_touch=140, pct_motion=-3,
        ),
    )
    # 迁移前从原运行器取得并逐项核对的固定输出；仅文本换行遵循宿主平台。
    expected = (
        "[Common]\n"
        "package = Main.App;child.Pkg;Main.App\n"
        "frequency = 1\n"
        "timeout = 11\n"
        "dumpheap_freq = 13\n"
        "serialnum = test-device\n"
        "exceptionlog = Fatal Exception;崩溃\n"
        "monkey = true\n"
        "save_path = perf-output\n"
        "phone_log_path = /data/anr;/sdcard/Logs\n"
        "mailbox = qa%tag@example.invalid\n"
        "pid_change_focus_package = \n"
        "main_activity = \n"
        "activity_list = \n"
        "monkey_throttle = 1\n"
        "monkey_seed = 0\n"
        "monkey_ignore_crashes = false\n"
        "monkey_ignore_timeouts = true\n"
        "monkey_ignore_security = false\n"
        "monkey_kill_after_error = true\n"
        "monkey_pct_touch = 100\n"
        "monkey_pct_motion = 0\n"
        "monkey_pct_trackball = 0\n"
        "monkey_pct_nav = 40\n"
        "monkey_pct_majornav = 30\n"
        "monkey_pct_syskeys = 5\n"
        "monkey_pct_appswitch = 0\n"
        "monkey_pct_anyevent = 5\n"
        "monkey_pct_flip = 0\n"
        "monkey_pct_pinchzoom = 0\n\n"
    ).replace("\n", os.linesep).encode("utf-8")
    generated = Path(config.write_config(tmp_path))
    assert generated.name == "mobileperf_run.conf"
    assert generated.read_bytes() == expected


def test_result_query_ignores_unchanged_baseline_but_finds_changed_report(tmp_path):
    module = importlib.import_module("services.performance.results")
    folder = tmp_path / "run"
    folder.mkdir()
    report = folder / "summary_demo.xlsx"
    report.write_bytes(b"old")
    os.utime(report, ns=(100, 100))
    os.utime(folder, ns=(100, 100))
    query = module.PerformanceResultQuery(
        str(tmp_path), ((module.path_key(folder), (100, folder.stat().st_size)),),
        ((module.path_key(report), (100, 3)),), finished_at_ns=300,
    )
    assert query.discover() == module.PerformanceArtifacts()
    report.write_bytes(b"updated report")
    os.utime(report, ns=(200, 200))
    result = query.discover()
    assert result.result_dir == str(folder)
    assert result.report_file == str(report)
    assert not result.error


def test_result_query_preserves_valid_artifacts_when_another_folder_cannot_be_read(
    tmp_path, monkeypatch,
):
    module = importlib.import_module("services.performance.results")
    broken = tmp_path / "broken"
    broken.mkdir()
    valid = tmp_path / "valid"
    valid.mkdir()
    report = valid / "summary_demo.xlsx"
    report.write_bytes(b"report")
    original_glob = Path.glob

    def glob(path, pattern):
        if path == broken:
            raise OSError("folder unavailable")
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", glob)
    result = module.PerformanceResultQuery(str(tmp_path), (), ()).discover()
    assert result.result_dir == str(valid)
    assert result.report_file == str(report)
    assert result.error


def test_path_key_and_legacy_runner_delegate_keep_absolute_normalized_path_semantics(tmp_path):
    module = importlib.import_module("services.performance.results")
    from services.mobileperf_runner import MobilePerfRunner

    path = tmp_path / "unused" / ".." / "report.xlsx"
    expected = os.path.normcase(str(tmp_path / "report.xlsx"))
    assert module.path_key(path) == expected
    assert MobilePerfRunner._path_key(path) == expected
