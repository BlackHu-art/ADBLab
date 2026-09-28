"""通过实际重命名入口验证目标冲突保护；本地 shell 行为不能替代 Android 工具实测。"""

import os
import posixpath
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from gui.dialogs import file_explorer_ops
from services import file_explorer as service

pytestmark = pytest.mark.integration


@pytest.fixture
def local_shell(tmp_path):
    shell = shutil.which("bash")
    environment = dict(os.environ)
    if os.name == "nt":
        git = shutil.which("git")
        directory = Path(git).parent.parent / "usr/bin" if git else None
        if directory is not None and (directory / "bash.exe").is_file():
            shell = str(directory / "bash.exe")
            environment["PATH"] = str(directory) + os.pathsep + environment.get("PATH", "")
            # Git 的链接仿真可验证 -L，无需 Windows 原生链接创建权限。
            environment["MSYS"] = "winsymlinks"
    if shell is None:
        pytest.skip("Local rename contract probe requires Bash or Git Bash")

    def run(command):
        return subprocess.run(
            [shell, "-c", command], cwd=tmp_path, env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )

    return run


@pytest.fixture
def rename_local(monkeypatch, local_shell):
    def rename(source, target, *, directory=".", shell_prefix=""):
        feedback, results, callbacks = [], [], []

        class Worker:
            result_ready = object()

            def __init__(self, command):
                self.command = command

            def start(self):
                result = local_shell(shell_prefix + self.command)
                results.append(result)
                for callback in callbacks:
                    callback(result.stdout + result.stderr, result.returncode != 0)

        frame = SimpleNamespace(
            _can_operate=lambda: True,
            current_path=directory,
            _safe_name=service.safe_name,
            _dpath=posixpath.join,
            _root=lambda command: command,
            _run_adb=lambda _shell, command: Worker(command),
            _connect_worker_ui=lambda worker, signal, callback: callbacks.append(callback),
        )
        controller = file_explorer_ops.FileExplorerOps(frame)
        monkeypatch.setattr(
            file_explorer_ops.FluentInputDialog, "getText", lambda *a, **kw: (target, True),
        )
        monkeypatch.setattr(
            controller, "_on_file_op_done",
            lambda output, failed, message: feedback.append((failed, output, message)),
        )
        controller._rename_item(source)
        assert len(results) == len(feedback) == 1
        return results[0], feedback[0]

    return rename


@pytest.mark.parametrize("target_kind", ["file", "directory", "dangling_link"])
def test_rename_rejects_existing_target_without_changing_either_item(
    tmp_path, local_shell, rename_local, target_kind,
):
    source, target = tmp_path / "source.txt", tmp_path / "existing"
    source.write_bytes(b"source content")
    if target_kind == "file":
        target.write_bytes(b"valuable existing content")
    elif target_kind == "directory":
        target.mkdir()
        (target / "keep.txt").write_bytes(b"directory content")
    else:
        created = local_shell("ln -s absent.txt existing")
        assert created.returncode == 0, created.stderr

    result, feedback = rename_local(source.name, target.name)

    assert result.returncode != 0
    assert feedback[0] is True
    assert source.read_bytes() == b"source content"
    if target_kind == "file":
        assert target.read_bytes() == b"valuable existing content"
    elif target_kind == "directory":
        assert [entry.name for entry in target.iterdir()] == ["keep.txt"]
        assert (target / "keep.txt").read_bytes() == b"directory content"
    else:
        assert local_shell("test -L existing && test ! -e existing").returncode == 0
        assert local_shell("readlink existing").stdout.strip() == "absent.txt"


@pytest.mark.parametrize("source_kind", [
    "file", "directory",
    pytest.param(
        "dangling_link",
        marks=pytest.mark.skipif(
            os.name == "nt",
            reason="Git simulated links lose identity on mv; native links need Windows privilege",
        ),
    ),
])
def test_rename_to_unused_name_preserves_source_contents(
    tmp_path, local_shell, rename_local, source_kind,
):
    source, target = tmp_path / "source", tmp_path / "renamed"
    if source_kind == "file":
        source.write_bytes(b"source content")
    elif source_kind == "directory":
        source.mkdir()
        (source / "child.txt").write_bytes(b"child content")
    else:
        assert local_shell("ln -s absent.txt source").returncode == 0

    result, feedback = rename_local(source.name, target.name)

    assert result.returncode == 0, result.stderr
    assert feedback[0] is False
    assert local_shell("test ! -e source && test ! -L source").returncode == 0
    if source_kind == "file":
        assert target.read_bytes() == b"source content"
    elif source_kind == "directory":
        assert (target / "child.txt").read_bytes() == b"child content"
    else:
        assert local_shell("test -L renamed && readlink renamed").stdout.strip() == "absent.txt"


def test_rename_does_not_report_success_when_move_skips_with_zero_exit(tmp_path, rename_local):
    source = tmp_path / "source.txt"
    source.write_bytes(b"source content")

    result, feedback = rename_local("source.txt", "new.txt", shell_prefix="mv() { return 0; }; ")

    assert result.returncode != 0
    assert feedback[0] is True
    assert source.read_bytes() == b"source content"
    assert not (tmp_path / "new.txt").exists()


@pytest.mark.parametrize("target_kind", ["file", "directory"])
def test_rename_preserves_target_created_just_before_move(tmp_path, rename_local, target_kind):
    source, target = tmp_path / "source.txt", tmp_path / "new.txt"
    source.write_bytes(b"source content")
    create = "printf existing > new.txt" if target_kind == "file" else "mkdir new.txt"

    result, feedback = rename_local(
        source.name, target.name, shell_prefix=f'mv() {{ {create}; command mv "$@"; }}; ',
    )

    assert result.returncode != 0
    assert feedback[0] is True
    assert source.read_bytes() == b"source content"
    if target_kind == "file":
        assert target.read_bytes() == b"existing"
    else:
        assert list(target.iterdir()) == []


def test_rename_quotes_parent_path_with_shell_characters(tmp_path, rename_local):
    directory = "parent's $notes"
    parent = tmp_path / directory
    parent.mkdir()
    (parent / "source.txt").write_bytes(b"source content")

    result, feedback = rename_local("source.txt", "new.txt", directory=directory)

    assert result.returncode == 0, result.stderr
    assert feedback[0] is False
    assert not (parent / "source.txt").exists()
    assert (parent / "new.txt").read_bytes() == b"source content"
