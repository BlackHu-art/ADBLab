"""独立升级交接包的候选验证、源码失效和平台构建契约。"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def helper_build(tmp_path, monkeypatch):
    from scripts import build_installer_update_handoff as builder
    from utils.installer_update_helper import HELPER_NAME, HELPER_SOURCES

    for relative in HELPER_SOURCES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic source\n", encoding="utf-8")
    output = tmp_path / "build/runtime-helpers" / HELPER_NAME
    output.mkdir(parents=True)
    executable = output / f"{HELPER_NAME}.exe"
    executable.write_bytes(b"previous")
    (output / "source.sha256").write_text("stale\n", encoding="ascii")
    state = SimpleNamespace(
        root=tmp_path, output=output, executable=executable,
        builds=[], checks=[], archive_checks=[], failure=None, on_check=None,
    )

    def run(command, **kwargs):
        if "PyInstaller" in command:
            state.builds.append(command)
            destination = Path(command[command.index("--distpath") + 1])
            destination.mkdir(parents=True, exist_ok=True)
            (destination / f"{HELPER_NAME}.exe").write_bytes(b"candidate")
            if state.failure == "build":
                raise subprocess.CalledProcessError(8, command)
        else:
            state.checks.append((command, kwargs))
            if state.on_check is not None:
                state.on_check()
            if state.failure == "timeout":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            if state.failure == "self_check":
                raise subprocess.CalledProcessError(9, command)
        return subprocess.CompletedProcess(command, 0)

    def check_archive(path):
        state.archive_checks.append(path)
        if state.failure == "archive":
            raise ValueError("third-party module in helper")

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(
        builder, "sys", SimpleNamespace(platform="win32", executable=sys.executable),
    )
    monkeypatch.setattr(builder.subprocess, "run", run)
    monkeypatch.setattr(builder, "_check_archive", check_archive)
    state.builder = builder
    return state


@pytest.mark.parametrize("failure", ["build", "timeout", "self_check", "archive"])
def test_failed_candidate_keeps_previous_helper_and_diagnostics(helper_build, failure):
    state = helper_build
    state.failure = failure
    with pytest.raises((subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError)):
        state.builder.main()
    assert state.executable.read_bytes() == b"previous"
    assert (state.output / "source.sha256").read_text() == "stale\n"
    assert list((state.root / "build/update-handoff-staging").glob("candidate-*"))


def test_onefile_candidate_is_checked_before_atomic_publish(helper_build):
    from utils.installer_update_helper import helper_source_digest

    state = helper_build
    def previous_is_still_available():
        assert state.executable.read_bytes() == b"previous"

    state.on_check = previous_is_still_available
    assert state.builder.main() == 0
    assert state.executable.read_bytes() == b"candidate"
    assert (state.output / "source.sha256").read_text().strip() == helper_source_digest(state.root)
    assert {path.name for path in state.output.iterdir()} == {
        "adblab-update-handoff.exe", "source.sha256",
    }
    command = state.builds[0]
    assert "--onefile" in command and "--console" in command and "--onedir" not in command
    assert command[-1] == str(state.root / "scripts/installer_update_handoff.py")
    excluded = [
        command[index + 1] for index, arg in enumerate(command) if arg == "--exclude-module"
    ]
    assert "PySide6" in excluded and "utils.adb_resolver" in excluded
    assert state.archive_checks
    assert 0 < state.checks[0][1]["timeout"] <= 60


def test_existing_digest_reuses_only_after_archive_and_bounded_self_check(helper_build):
    from utils.installer_update_helper import helper_source_digest

    state = helper_build
    (state.output / "source.sha256").write_text(helper_source_digest(state.root), encoding="ascii")
    assert state.builder.main() == 0
    assert not state.builds
    assert state.archive_checks == [state.executable]
    assert state.checks[0][0] == [str(state.executable), "--self-check"]


def test_changed_source_during_build_preserves_old_helper(helper_build):
    state = helper_build

    def change_source():
        (state.root / "services/app_update.py").write_text("# changed\n", encoding="utf-8")

    state.on_check = change_source
    with pytest.raises(RuntimeError, match="源码已变化"):
        state.builder.main()
    assert state.executable.read_bytes() == b"previous"


def test_source_digest_tracks_all_runtime_dependencies_and_ignores_git_newlines(tmp_path):
    from utils.installer_update_helper import HELPER_SOURCES, helper_source_digest

    expected = {
        "scripts/installer_update_handoff.py", "core/installer_update_protocol.py",
        "core/installer_update_process.py", "services/app_update.py", "utils/app_metadata.py",
        "utils/user_data.py", "utils/__init__.py", "utils/resource_path.py",
    }
    assert expected.issubset(HELPER_SOURCES)
    for relative in HELPER_SOURCES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# fixture\n")
    initial = helper_source_digest(tmp_path)
    for relative in expected:
        path = tmp_path / relative
        path.write_bytes(b"# changed\n")
        assert helper_source_digest(tmp_path) != initial
        path.write_bytes(b"# fixture\r\n")
        assert helper_source_digest(tmp_path) == initial


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_non_windows_does_not_build_or_create_output(helper_build, monkeypatch, platform):
    state = helper_build
    monkeypatch.setattr(state.builder, "sys", SimpleNamespace(platform=platform))
    assert state.builder.main() == 0
    assert state.builds == [] and state.checks == []
    assert state.executable.read_bytes() == b"previous"


def test_new_helper_builder_reuses_existing_build_lock(helper_build):
    from scripts.build_scrcpy_adb_bridge import _build_lock

    state = helper_build
    with _build_lock(state.root / "build/update-handoff-build.lock"):
        with pytest.raises(RuntimeError, match="构建锁"):
            state.builder.main()
    assert not state.builds


@pytest.mark.parametrize("module", ["PySide6.QtCore", "numpy", "utils.adb_resolver"])
def test_frozen_archive_rejects_non_protocol_or_third_party_modules(tmp_path, monkeypatch, module):
    from PyInstaller.archive import readers

    from scripts import build_installer_update_handoff as builder

    fake_pyz = SimpleNamespace(toc={module: ()})
    archive = SimpleNamespace(toc={"PYZ.pyz": ()}, open_embedded_archive=lambda _name: fake_pyz)
    monkeypatch.setattr(readers, "CArchiveReader", lambda _path: archive)
    with pytest.raises(ValueError):
        builder._check_archive(tmp_path / "helper.exe")


def test_source_resolver_refuses_stale_helper_then_accepts_current_digest(
    helper_build, monkeypatch,
):
    from utils import installer_update_helper as helper

    state = helper_build
    monkeypatch.setattr(helper, "SOURCE_ROOT", state.root)
    monkeypatch.setattr(helper, "sys", SimpleNamespace(platform="win32"))
    assert helper.resolve_installer_update_helper() is None
    (state.output / "source.sha256").write_text(
        helper.helper_source_digest(state.root), encoding="ascii",
    )
    assert helper.resolve_installer_update_helper() == state.executable
    (state.root / "utils/user_data.py").write_text("# modified\n", encoding="utf-8")
    assert helper.resolve_installer_update_helper() is None


@pytest.mark.parametrize("platform,exists", [("win32", True), ("win32", False), ("linux", True)])
def test_frozen_resolver_uses_only_packaged_windows_helper(tmp_path, monkeypatch, platform, exists):
    from utils import installer_update_helper as helper

    executable = tmp_path / "adblab-update-handoff.exe"
    if exists:
        executable.write_bytes(b"frozen fixture")
    monkeypatch.setattr(helper, "sys", SimpleNamespace(platform=platform, frozen=True))
    monkeypatch.setattr(helper, "resource_path", lambda _relative: str(executable))
    assert helper.resolve_installer_update_helper() == (
        executable if platform == "win32" and exists else None
    )


def test_staging_outside_owned_build_root_is_rejected_before_build(helper_build, monkeypatch):
    state = helper_build
    original_resolve = Path.resolve
    staging = state.root / "build/update-handoff-staging"

    def redirected(path, *args, **kwargs):
        if path == staging:
            return state.root.parent / "external-fixture"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(ValueError, match="构建目录"):
        state.builder.main()
    assert not state.builds
    assert state.executable.read_bytes() == b"previous"
