"""隔离升级验收器的边界测试；不在当前宿主安装任何 fixture。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.fixtures.windows_installer import upgrade_smoke as fixture


@pytest.mark.parametrize("disposable", [False, True])
def test_upgrade_refuses_desktop_before_compiling(tmp_path, monkeypatch, disposable):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    target = tmp_path / "run"
    with pytest.raises(ValueError, match="一次性|disposable"):
        fixture.run_upgrade_fixture(tmp_path / "ISCC.exe", target, disposable=disposable)
    assert not target.exists()


def test_upgrade_requires_explicit_disposable_context(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setenv("RUNNER_OS", "Windows")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    with pytest.raises(ValueError, match="一次性"):
        fixture.run_upgrade_fixture(tmp_path / "ISCC.exe", tmp_path / "run")


@pytest.mark.parametrize("returncode,reject", [(1, False), (0, True)])
def test_fixture_commands_propagate_unexpected_exit(tmp_path, monkeypatch, returncode, reject):
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=returncode)
    )
    with pytest.raises(RuntimeError, match="退出码"):
        fixture._run(["not-executed"], tmp_path / "command.log", reject=reject)


def test_fixture_timeout_is_not_rejection(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("not-executed", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        fixture._run(["not-executed"], tmp_path / "command.log", reject=True)


def test_fixture_compiler_success_without_output_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, "verify_compiler", lambda path: None)
    monkeypatch.setattr(fixture, "_run", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="编译产物"):
        fixture.compile_versions(tmp_path / "ISCC.exe", tmp_path)


def test_fixture_compilation_failure_never_runs_installer(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(fixture, "verify_compiler", lambda path: None)

    def fail(command, log, **kwargs):
        commands.append(command)
        raise RuntimeError("compiler failed")

    monkeypatch.setattr(fixture, "_run", fail)
    with pytest.raises(RuntimeError, match="compiler failed"):
        fixture.compile_versions(tmp_path / "ISCC.exe", tmp_path)
    assert len(commands) == 1
    assert Path(commands[0][0]).name == "ISCC.exe"


def test_rejection_must_preserve_all_installation_bytes(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    marker = app / ".adblab-install.ini"
    marker.write_bytes(b"before")
    monkeypatch.setattr(fixture, "_registrations", lambda app_id: [])

    def mutate(*args, **kwargs):
        marker.write_bytes(b"after")

    monkeypatch.setattr(fixture, "_run", mutate)
    with pytest.raises(RuntimeError, match="修改"):
        fixture._expect_rejected(["not-executed"], app, tmp_path / "reject.log")


def test_fake_zero_uninstall_with_remaining_files_fails(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    (app / "ADBLab.exe").write_bytes(b"remaining")
    monkeypatch.setattr(fixture, "_registrations", lambda app_id: [])
    with pytest.raises(RuntimeError, match="残留"):
        fixture._assert_absent(app, {"ADBLab.exe"})


def test_preserve_installation_moves_only_within_owned_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    app = workspace / "app"
    app.mkdir(parents=True)
    (app / "keep.dat").write_bytes(b"original")
    preserved = workspace / "preserved"
    fixture._preserve_installation(app, preserved, workspace)
    assert not app.exists()
    assert (preserved / "keep.dat").read_bytes() == b"original"


@pytest.mark.parametrize("outside", ["source", "destination"])
def test_preserve_installation_rejects_path_outside_workspace(tmp_path, outside):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = (tmp_path if outside == "source" else workspace) / "app"
    app.mkdir()
    (app / "keep.dat").write_bytes(b"original")
    preserved = (tmp_path if outside == "destination" else workspace) / "preserved"
    with pytest.raises(ValueError, match="workspace"):
        fixture._preserve_installation(app, preserved, workspace)
    assert (app / "keep.dat").read_bytes() == b"original"
    assert not preserved.exists()


def test_preserve_installation_never_overwrites_existing_destination(tmp_path):
    app, preserved = tmp_path / "app", tmp_path / "preserved"
    app.mkdir()
    preserved.mkdir()
    (preserved / "keep.dat").write_bytes(b"user")
    with pytest.raises(ValueError, match="存在"):
        fixture._preserve_installation(app, preserved, tmp_path)
    assert app.is_dir()
    assert (preserved / "keep.dat").read_bytes() == b"user"
