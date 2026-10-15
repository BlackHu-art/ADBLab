"""helper 候选构建、自检和发布失败均不能破坏上一次正式产物。"""

import errno
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_scrcpy_adb_bridge as builder
from utils.scrcpy_bridge import BRIDGE_NAME, BRIDGE_SOURCES, bridge_source_digest


@pytest.fixture
def bridge_build(tmp_path, monkeypatch):
    for relative in BRIDGE_SOURCES:
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# synthetic source\n", encoding="utf-8")
    output = tmp_path / "build" / "runtime-helpers" / BRIDGE_NAME
    output.mkdir(parents=True)
    filename = BRIDGE_NAME + (".exe" if sys.platform == "win32" else "")
    executable = output / filename
    executable.write_bytes(b"previous helper")
    (output / "source.sha256").write_text("previous digest\n", encoding="ascii")
    state = SimpleNamespace(
        root=tmp_path, output=output, executable=executable, filename=filename,
        builds=[], checks=[], build_failure=False, check_failure=None, on_check=None,
    )

    def run(command, **kwargs):
        if "PyInstaller" in command:
            state.builds.append(command)
            folder = Path(command[command.index("--distpath") + 1]) / BRIDGE_NAME
            folder.mkdir(parents=True, exist_ok=True)
            (folder / state.filename).write_bytes(b"candidate helper")
            (folder / state.filename).chmod(0o755)
            dependency = folder / "_internal" / "dependency.bin"
            dependency.parent.mkdir(exist_ok=True)
            dependency.write_bytes(b"candidate dependency")
            if kwargs.get("stdout") is not None:
                kwargs["stdout"].write(b"synthetic build log\n")
            if state.build_failure:
                raise subprocess.CalledProcessError(8, command)
        else:
            state.checks.append((command, kwargs))
            if kwargs.get("stdout") is not None:
                kwargs["stdout"].write(b"synthetic self-check log\n")
            if state.on_check is not None:
                state.on_check()
            if state.check_failure == "timeout":
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 0))
            if state.check_failure == "exit":
                if kwargs.get("check"):
                    raise subprocess.CalledProcessError(7, command)
                return subprocess.CompletedProcess(command, 7)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder.subprocess, "run", run)
    return state


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_failed_candidate_self_check_preserves_previous_helper(bridge_build, failure):
    state = bridge_build
    state.check_failure = failure
    error = subprocess.TimeoutExpired if failure == "timeout" else subprocess.CalledProcessError
    with pytest.raises(error):
        builder.main()
    assert state.executable.read_bytes() == b"previous helper"
    assert (state.output / "source.sha256").read_text() == "previous digest\n"
    checked = Path(state.checks[0][0][0])
    assert checked.read_bytes() == b"candidate helper"
    assert not checked.is_relative_to(state.output.parent)
    assert not (checked.parent / "source.sha256").exists()
    assert any(path.read_bytes() == b"synthetic self-check log\n"
               for path in state.root.joinpath("build").rglob("self-check.log"))


def test_failed_packager_preserves_previous_helper_and_candidate_diagnostics(bridge_build):
    state = bridge_build
    state.build_failure = True
    with pytest.raises(subprocess.CalledProcessError):
        builder.main()
    assert state.executable.read_bytes() == b"previous helper"
    assert not state.checks
    assert any(path.read_bytes() == b"synthetic build log\n"
               for path in state.root.joinpath("build").rglob("build.log"))


def test_valid_candidate_is_published_only_after_self_check(bridge_build, monkeypatch):
    from utils import scrcpy_bridge

    state = bridge_build

    def verify_previous_still_available():
        assert state.executable.read_bytes() == b"previous helper"
        assert (state.output / "source.sha256").read_text() == "previous digest\n"

    state.on_check = verify_previous_still_available
    assert builder.main() == 0
    assert state.executable.read_bytes() == b"candidate helper"
    assert (state.output / "_internal" / "dependency.bin").read_bytes() == b"candidate dependency"
    assert (state.output / "source.sha256").read_text().strip() == bridge_source_digest(state.root)
    assert {path.name for path in state.output.parent.iterdir()} == {BRIDGE_NAME}
    monkeypatch.setattr(scrcpy_bridge, "SOURCE_ROOT", state.root)
    assert scrcpy_bridge.resolve_scrcpy_bridge() == str(state.executable)


def test_matching_source_reuses_helper_with_a_bounded_self_check(bridge_build):
    state = bridge_build
    (state.output / "source.sha256").write_text(bridge_source_digest(state.root), encoding="ascii")
    assert builder.main() == 0
    assert not state.builds
    command, options = state.checks[0]
    assert command == [str(state.executable), "--self-check"]
    assert 0 < options.get("timeout", 0) <= 60
    assert state.executable.read_bytes() == b"previous helper"


@pytest.mark.parametrize("failure_at", ["backup", "publish", "interrupt"])
def test_failed_directory_switch_preserves_previous_helper(bridge_build, monkeypatch, failure_at):
    state = bridge_build
    rename = Path.rename

    def fail_switch(path, target):
        if failure_at == "backup" and path == state.output:
            raise PermissionError("previous helper is in use")
        if path.parent.name == "dist" and path.name == BRIDGE_NAME:
            if failure_at == "interrupt":
                raise KeyboardInterrupt()
            if failure_at == "publish":
                raise PermissionError("candidate rename failed")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_switch)
    expected = KeyboardInterrupt if failure_at == "interrupt" else PermissionError
    with pytest.raises(expected):
        builder.main()
    assert state.executable.read_bytes() == b"previous helper"
    assert (state.output / "source.sha256").read_text() == "previous digest\n"
    candidate = Path(state.checks[0][0][0])
    assert candidate.read_bytes() == b"candidate helper"
    assert not candidate.is_relative_to(state.output.parent)


def test_failed_rollback_keeps_both_trees_for_recovery(bridge_build, monkeypatch):
    state = bridge_build
    rename = Path.rename

    def fail_publish_and_restore(path, target):
        if path == state.output:
            return rename(path, target)
        raise PermissionError("directory is in use")

    monkeypatch.setattr(Path, "rename", fail_publish_and_restore)
    with pytest.raises(RuntimeError, match="无法恢复旧 helper"):
        builder.main()
    candidate = Path(state.checks[0][0][0])
    assert candidate.read_bytes() == b"candidate helper"
    previous = candidate.parents[2] / "previous"
    assert (previous / state.filename).read_bytes() == b"previous helper"
    assert (previous / "source.sha256").read_text() == "previous digest\n"
    assert not previous.is_relative_to(state.output.parent)


def test_changed_source_cannot_publish_a_candidate_with_an_obsolete_digest(bridge_build):
    state = bridge_build

    def change_source():
        state.root.joinpath(BRIDGE_SOURCES[0]).write_text("# changed source\n", encoding="utf-8")

    state.on_check = change_source
    with pytest.raises(RuntimeError, match="源码已变化"):
        builder.main()
    assert state.executable.read_bytes() == b"previous helper"
    assert not Path(state.checks[0][0][0]).with_name("source.sha256").exists()


def test_failed_build_can_retry_without_removing_earlier_diagnostics(bridge_build):
    state = bridge_build
    state.check_failure = "exit"
    with pytest.raises(subprocess.CalledProcessError):
        builder.main()
    failed_candidate = Path(state.checks[0][0][0])
    state.check_failure = None
    assert builder.main() == 0
    assert failed_candidate.read_bytes() == b"candidate helper"
    assert state.executable.read_bytes() == b"candidate helper"
    assert builder.main() == 0
    assert len(state.builds) == 2
    assert len(state.checks) == 3
    assert state.checks[-1][0] == [str(state.executable), "--self-check"]
    assert {path.name for path in state.output.parent.iterdir()} == {BRIDGE_NAME}


def test_competing_builder_is_rejected_and_releasing_lock_allows_retry(bridge_build):
    state = bridge_build
    lock = state.root / "build" / "adb-bridge-build.lock"
    with builder._build_lock(lock):
        with pytest.raises(RuntimeError, match="构建锁"):
            builder.main()
    assert not state.builds
    assert state.executable.read_bytes() == b"previous helper"
    assert builder.main() == 0


@pytest.mark.integration
def test_build_lock_blocks_another_process_without_waiting(bridge_build):
    state = bridge_build
    lock = state.root / "build" / "adb-bridge-build.lock"
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.build_scrcpy_adb_bridge import _build_lock
try:
    with _build_lock(Path(sys.argv[2])):
        print('acquired')
except RuntimeError:
    print('busy')
"""
    with builder._build_lock(lock):
        with subprocess.Popen(
            [sys.executable, "-I", "-c", code, str(Path(builder.__file__).parents[1]), str(lock)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) as child:
            try:
                output, error = child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                raise
    assert child.returncode == 0, error
    assert output.strip() == "busy"
    assert not state.builds


def test_first_build_creates_the_formal_collection_directory(bridge_build):
    state = bridge_build
    state.output.parent.rename(state.root / "previous-test-fixture")
    assert builder.main() == 0
    assert state.executable.read_bytes() == b"candidate helper"
    assert {path.name for path in state.output.parent.iterdir()} == {BRIDGE_NAME}


def test_linux_named_bundle_keeps_its_file_mode_when_published(bridge_build, monkeypatch):
    state = bridge_build
    state.filename = BRIDGE_NAME
    monkeypatch.setattr(
        builder, "sys", SimpleNamespace(platform="linux", executable=sys.executable),
    )
    candidate_modes = []

    def remember_mode():
        candidate = Path(state.checks[-1][0][0])
        candidate_modes.append(stat.S_IMODE(candidate.stat().st_mode))

    state.on_check = remember_mode
    assert builder.main() == 0
    executable = state.output / BRIDGE_NAME
    assert executable.read_bytes() == b"candidate helper"
    assert stat.S_IMODE(executable.stat().st_mode) == candidate_modes[0]
    assert not executable.with_suffix(".exe").exists()


def test_cleanup_failure_does_not_invalidate_published_helper(bridge_build, monkeypatch):
    state = bridge_build

    def fail_cleanup(path):
        assert path.resolve().parent == (state.root / "build" / "adb-bridge-staging").resolve()
        raise PermissionError("backup is still in use")

    monkeypatch.setattr(builder.shutil, "rmtree", fail_cleanup)
    assert builder.main() == 0
    assert state.executable.read_bytes() == b"candidate helper"
    previous = Path(state.checks[0][0][0]).parents[2] / "previous"
    assert (previous / state.filename).read_bytes() == b"previous helper"
    assert {path.name for path in state.output.parent.iterdir()} == {BRIDGE_NAME}


def test_cross_filesystem_candidate_is_rejected_before_touching_output(bridge_build, monkeypatch):
    state = bridge_build
    candidate = state.root / "candidate"
    candidate.mkdir()
    original_stat = Path.stat

    def other_filesystem(path, **kwargs):
        result = original_stat(path, **kwargs)
        if path == candidate:
            return SimpleNamespace(st_dev=result.st_dev + 1)
        return result

    monkeypatch.setattr(Path, "stat", other_filesystem)
    with pytest.raises(OSError) as failure:
        builder._publish(candidate, state.output, state.root / "previous")
    assert failure.value.errno == errno.EXDEV
    assert state.executable.read_bytes() == b"previous helper"


@pytest.mark.parametrize("failure", [None, "exit", "timeout"], ids=["success", "exit", "timeout"])
def test_existing_helper_without_stamp_requires_a_validated_rebuild(
    bridge_build, monkeypatch, failure,
):
    from utils import scrcpy_bridge

    state = bridge_build
    stamp = state.output / "source.sha256"
    stamp.unlink()
    state.check_failure = failure
    monkeypatch.setattr(scrcpy_bridge, "SOURCE_ROOT", state.root)
    assert state.executable.is_file()
    assert scrcpy_bridge.resolve_scrcpy_bridge() is None

    def verify_candidate_is_checked_before_publish():
        assert len(state.builds) == 1
        checked = Path(state.checks[-1][0][0])
        assert checked.read_bytes() == b"candidate helper"
        assert not checked.is_relative_to(state.output.parent)
        assert state.executable.read_bytes() == b"previous helper"
        assert not stamp.exists()
        assert scrcpy_bridge.resolve_scrcpy_bridge() is None

    state.on_check = verify_candidate_is_checked_before_publish
    if failure is None:
        assert builder.main() == 0
        assert state.executable.read_bytes() == b"candidate helper"
        assert stamp.read_text(encoding="ascii").strip() == bridge_source_digest(state.root)
        assert scrcpy_bridge.resolve_scrcpy_bridge() == str(state.executable)
    else:
        error = subprocess.TimeoutExpired if failure == "timeout" else subprocess.CalledProcessError
        with pytest.raises(error):
            builder.main()
        assert state.executable.read_bytes() == b"previous helper"
        assert not stamp.exists()
        assert scrcpy_bridge.resolve_scrcpy_bridge() is None
        checked = Path(state.checks[0][0][0])
        assert checked.read_bytes() == b"candidate helper"
        assert not checked.with_name("source.sha256").exists()
    assert len(state.builds) == 1
    assert len(state.checks) == 1
    assert 0 < state.checks[0][1]["timeout"] <= 60
