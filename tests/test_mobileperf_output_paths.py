"""验证性能输出运行快照、安装资源保护与启动失败清理。"""

from __future__ import annotations

import configparser
import os
import sys
import threading
from concurrent.futures import CancelledError
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.exec import ProcessRunner
from services import mobileperf_runner as runner_module
from services.mobileperf_runner import MobilePerfRunConfig, MobilePerfRunner


class _Process:
    """由测试显式停止，避免真实设备及子进程副作用。"""

    stdout = None
    stderr = None
    returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


@pytest.fixture
def output_runner(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(runner_module.tempfile, "tempdir", str(temporary))
    monkeypatch.setattr(runner_module, "user_data_root", lambda: home / "ADBLab")
    monkeypatch.setattr(runner_module, "adb_runtime", lambda: None)
    monkeypatch.setattr(MobilePerfRunner, "_resolve_adb_path", staticmethod(lambda: "adb-test"))
    processes = Mock(spec=ProcessRunner)
    processes.start.return_value = _Process()
    processes.stop.return_value = 0
    runner = MobilePerfRunner(process_runner=processes, project_root=tmp_path / "source")
    yield runner, processes, home
    runner.stop(timeout=0)


@pytest.mark.parametrize("save_path", ["", "  "])
def test_empty_output_uses_user_home_without_creating_prediction(output_runner, save_path):
    runner, _, home = output_runner
    config = MobilePerfRunConfig(save_path=save_path)

    assert runner.expected_result_root(config) == str(home / "ADBLab" / "mobileperf")
    assert runner.expected_result_root() == str(home / "ADBLab" / "mobileperf")
    assert not (home / "ADBLab").exists()
    assert config.save_path == save_path


@pytest.mark.parametrize("frozen", [False, True])
def test_relative_output_is_independent_of_cwd_and_resources(
    output_runner, tmp_path, monkeypatch, frozen,
):
    runner, _, home = output_runner
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    config = MobilePerfRunConfig(save_path="reports/parent/../session")
    expected = str(home / "ADBLab" / "reports" / "session")
    for directory in (tmp_path, home):
        monkeypatch.chdir(directory)
        assert runner.expected_result_root(config) == expected
    assert not (home / "ADBLab").exists()


def test_absolute_output_is_normalized_without_rebasing(output_runner, tmp_path):
    runner, _, _ = output_runner
    config = MobilePerfRunConfig(save_path=str(tmp_path / "parent" / ".." / "output"))
    assert runner.expected_result_root(config) == str(tmp_path / "output")


def test_output_resolution_reads_the_copied_snapshot(output_runner, monkeypatch):
    runner, _, home = output_runner
    config = MobilePerfRunConfig(save_path="first")

    def copy_then_mutate_caller(source):
        snapshot = deepcopy(source)
        if source is config:
            config.save_path = "later"
        return snapshot

    monkeypatch.setattr(runner_module, "deepcopy", copy_then_mutate_caller)
    assert runner.start(config) == str(home / "ADBLab" / "first")
    assert runner.last_config.save_path == str(home / "ADBLab" / "first")


@pytest.mark.skipif(os.name != "nt", reason="Windows 盘符和 UNC 语义")
def test_unc_output_prediction_keeps_absolute_share(output_runner):
    runner, _, _ = output_runner
    config = MobilePerfRunConfig(save_path=r"\\synthetic-host\share\reports\..\output")
    assert runner.expected_result_root(config) == r"\\synthetic-host\share\output"


@pytest.mark.skipif(os.name != "nt", reason="Windows 不完整路径语义")
@pytest.mark.parametrize("save_path", ["C:results", "C:", r"\results", "/results", r"\\host"])
def test_incomplete_windows_output_fails_before_worker(output_runner, save_path):
    runner, processes, _ = output_runner
    with pytest.raises(ValueError):
        runner.start(MobilePerfRunConfig(save_path=save_path))
    processes.start.assert_not_called()
    assert runner.config_path == ""
    assert runner.last_config is None


@pytest.mark.parametrize("save_path", ["", "reports/parent/../session"])
def test_worker_baseline_and_discovery_share_independent_snapshot(output_runner, save_path):
    runner, processes, home = output_runner
    config = MobilePerfRunConfig(package="com.example.app", save_path=save_path)
    original = deepcopy(config)
    serialized = dict(config.to_config_parser()["Common"])
    root = home / "ADBLab" / ("mobileperf" if not save_path else "reports/session")
    old = root / "com.example.app" / "old"
    old.mkdir(parents=True)
    (old / "summary_old.xlsx").write_bytes(b"old report")
    finished = threading.Event()

    result = runner.start(config, on_finished=finished.set)
    try:
        assert result == str(root)
        assert runner.expected_result_root(config) == str(root)
        assert runner.expected_result_root() == str(root)
        assert config == original
        assert dict(config.to_config_parser()["Common"]) == serialized
        snapshot = runner.last_config
        assert snapshot is not config
        assert snapshot.save_path == str(root)
        assert snapshot.exception_keywords is not config.exception_keywords
        assert snapshot.monkey_config is not config.monkey_config
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(runner.config_path, encoding="utf-8")
        assert parser["Common"]["save_path"] == str(root)
        assert processes.start.call_args.kwargs["cwd"] == str(runner._project_root)
        assert runner.latest_result_dir(config) == ""
        current = root / "com.example.app" / "current"
        current.mkdir()
        report = current / "summary_current.xlsx"
        report.write_bytes(b"new report")
        assert runner.latest_result_dir(config) == str(current)
        assert runner.latest_report_file(config) == str(report)
        # 调用方在启动后改字段，已发布的运行归属仍由独立快照保持。
        config.save_path = "other"
        config.exception_keywords.append("later")
        query = runner.freeze_result_query()
        assert query.root == str(root / "com.example.app")
        assert query.discover().report_file == str(report)
        assert snapshot.exception_keywords == original.exception_keywords
        config_directory = Path(runner.config_path).parent
    finally:
        runner.stop(timeout=0)
    assert finished.wait(1)
    assert not config_directory.exists()
    assert not runner.is_running()


@pytest.mark.parametrize("target", ["install", "install/reports", "install/_internal/reports"])
def test_frozen_installation_targets_fail_without_writing(
    output_runner, tmp_path, monkeypatch, target,
):
    runner, processes, _ = output_runner
    install = tmp_path / "install"
    install.mkdir()
    resources = install / "_internal"
    resources.mkdir()
    runner._project_root = resources
    runner._python_executable = str(install / "ADBLab.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resources), raising=False)

    with pytest.raises(ValueError):
        runner.start(MobilePerfRunConfig(save_path=str(tmp_path / target)))
    processes.start.assert_not_called()
    assert list(install.iterdir()) == [resources]
    assert list(resources.iterdir()) == []
    assert runner.config_path == ""


def test_frozen_installation_sibling_remains_valid(output_runner, tmp_path, monkeypatch):
    runner, _, _ = output_runner
    install = tmp_path / "install"
    runner._project_root = install / "_internal"
    runner._python_executable = str(install / "ADBLab.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(runner._project_root), raising=False)
    root = tmp_path / "install-results"
    assert runner.start(MobilePerfRunConfig(save_path=str(root))) == str(root)
    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_frozen_result_query_uses_snapshot_without_filesystem_resolution(
    output_runner, tmp_path, monkeypatch,
):
    runner, _, _ = output_runner
    install = tmp_path / "install"
    runner._project_root = install / "_internal"
    runner._python_executable = str(install / "ADBLab.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(runner._project_root), raising=False)
    root = tmp_path / "reports"
    runner.start(MobilePerfRunConfig(package="com.example.app", save_path=str(root)))

    def unexpected_io(*args, **kwargs):
        raise AssertionError("result snapshot performed filesystem resolution")

    # GUI 终态冻结只复制归属；目录解析与可写性检查应留在后台启动阶段。
    with monkeypatch.context() as guard:
        guard.setattr(Path, "resolve", unexpected_io)
        query = runner.freeze_result_query()
    assert query.root == str(root / "com.example.app")


def test_output_creation_failure_never_spawns_or_allocates_config(output_runner, tmp_path):
    runner, processes, _ = output_runner
    blocked = tmp_path / "file"
    blocked.write_bytes(b"keep")
    with pytest.raises(OSError):
        runner.start(MobilePerfRunConfig(save_path=str(blocked / "reports")))
    assert blocked.read_bytes() == b"keep"
    processes.start.assert_not_called()
    assert runner.config_path == ""
    assert runner._config_dir is None


def test_output_write_denied_never_spawns_or_allocates_config(
    output_runner, tmp_path, monkeypatch,
):
    runner, processes, _ = output_runner
    root = tmp_path / "denied"
    original = runner_module.tempfile.TemporaryFile

    def deny_write(*args, **kwargs):
        if Path(kwargs.get("dir", "")) == root:
            raise PermissionError("synthetic write denied")
        return original(*args, **kwargs)

    monkeypatch.setattr(runner_module.tempfile, "TemporaryFile", deny_write)
    with pytest.raises(PermissionError):
        runner.start(MobilePerfRunConfig(save_path=str(root)))
    processes.start.assert_not_called()
    assert runner.config_path == ""
    assert runner._config_dir is None
    assert list(root.iterdir()) == []


def test_cancel_after_baseline_avoids_config_and_worker(output_runner, monkeypatch):
    runner, processes, home = output_runner
    cancelled = threading.Event()
    capture = runner._capture_result_baseline

    def baseline(config):
        capture(config)
        cancelled.set()

    monkeypatch.setattr(runner, "_capture_result_baseline", baseline)
    with pytest.raises(CancelledError):
        runner.start(MobilePerfRunConfig(), cancelled=cancelled.is_set)
    processes.start.assert_not_called()
    assert runner.config_path == ""
    assert runner._config_dir is None
    assert list((home / "ADBLab" / "mobileperf").iterdir()) == []


def test_cancel_after_config_write_cleans_temporary_resources(output_runner, monkeypatch):
    runner, processes, _ = output_runner
    cancelled = threading.Event()
    write = MobilePerfRunConfig.write_config
    generated = []

    def write_then_cancel(config, directory):
        path = write(config, directory)
        generated.append(Path(path).parent)
        cancelled.set()
        return path

    monkeypatch.setattr(MobilePerfRunConfig, "write_config", write_then_cancel)
    with pytest.raises(CancelledError):
        runner.start(MobilePerfRunConfig(), cancelled=cancelled.is_set)
    processes.start.assert_not_called()
    assert len(generated) == 1
    assert not generated[0].exists()
    assert runner.config_path == ""
    assert runner._config_dir is None


def test_repeated_start_keeps_active_snapshot_and_avoids_output_preparation(
    output_runner, tmp_path,
):
    runner, processes, _ = output_runner
    runner.start(MobilePerfRunConfig(save_path="first"))
    snapshot = runner.last_config
    config_path = runner.config_path
    unused = tmp_path / "second"
    with pytest.raises(RuntimeError, match="already running"):
        runner.start(MobilePerfRunConfig(save_path=str(unused)))
    assert processes.start.call_count == 1
    assert runner.last_config is snapshot
    assert runner.config_path == config_path
    assert Path(config_path).is_file()
    assert not unused.exists()
