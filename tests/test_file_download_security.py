import ntpath
import os
import re
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.exec import CommandResult
from services.file_download import SafeFileDownload, default_save_path, local_child_path


@pytest.mark.parametrize("name", [
    "../escape", "/absolute", "..\\escape", "C:escape", "C:\\escape", "\\\\server\\share",
    "file:stream", "CON", "NUL.txt", "COM1.log", "LPT¹", "name.", "name ", "a\x00b", "a\nb",
])
def test_windows_device_names_cannot_escape_or_alias_host_files(tmp_path, name):
    with pytest.raises(ValueError):
        local_child_path(str(tmp_path), name, windows=True)


@pytest.mark.parametrize("name", [" leading.txt", "draft  final.txt", "资料.txt", "report-old.txt"])
def test_valid_download_names_are_not_silently_renamed(tmp_path, name):
    assert local_child_path(str(tmp_path), name, windows=True) == str(tmp_path / name)


def test_unsafe_dialog_default_stays_inside_selected_directory(tmp_path):
    assert default_save_path(str(tmp_path), "../escape") == str(tmp_path) + os.sep


def test_download_preserves_binary_bytes_when_legacy_shell_expands_linefeeds(tmp_path, monkeypatch):
    content = bytes(range(256)) + b"\x00first\nsecond\r\nthird\rfourth\n\x00"
    destination = tmp_path / "saved.bin"
    destination.write_bytes(b"original")
    progress = []

    def run(cmd, output_path, *, timeout, cancelled):
        assert cmd[:3] == ["adb", "-s", "synthetic-device"]
        assert not cancelled()
        marker = re.search(r"ADBLAB_PULL_END_[a-f0-9]+", cmd[-1])[0].encode()
        if "cat --" in cmd[-1]:
            payload = content + marker
        else:
            assert "printf FILE" in cmd[-1]
            payload = b"FILE" + marker
        # 旧 shell 通道即使带 -T 也可能转换 LF；exec-out 保留原始字节。
        if cmd[3:-1] == ["shell", "-T"]:
            payload = payload.replace(b"\n", b"\r\n")
        else:
            assert cmd[3:-1] == ["exec-out"]
        Path(output_path).write_bytes(payload)
        return CommandResult(success=True)

    monkeypatch.setattr("services.file_download.CommandRunner.run_to_file", run)

    SafeFileDownload("synthetic-device", lambda: False, progress.append).download(
        "/device/file", str(destination),
    )

    assert destination.read_bytes() == content
    assert progress == ["文件下载完成"]
    assert not list(tmp_path.glob(".adblab-pull-*"))


@pytest.fixture
def shell_device(monkeypatch):
    if os.name == "nt":
        pytest.skip("Local POSIX shell probe requires a POSIX host")
    calls = []

    def run(cmd, output_path, timeout, cancelled):
        assert cmd[:4] == ["adb", "-s", "synthetic-device", "exec-out"]
        assert not cancelled()
        calls.append(cmd[-1])
        with open(output_path, "wb") as stream:
            completed = subprocess.run(
                ["sh", "-c", cmd[-1]], stdout=stream, stderr=subprocess.PIPE,
                timeout=timeout, check=False,
            )
        return SimpleNamespace(success=completed.returncode == 0)

    monkeypatch.setattr("services.file_download.CommandRunner.run_to_file", run)
    return calls


def test_download_tree_keeps_binary_empty_and_quoted_files(tmp_path, shell_device):
    remote = tmp_path / "device"
    remote.mkdir()
    (remote / "empty").mkdir()
    (remote / " sub").mkdir()
    content = bytes(range(256)) * 20
    (remote / " sub" / "a'$();.bin").write_bytes(content)
    (remote / "zero").write_bytes(b"")
    destination = tmp_path / "download"
    SafeFileDownload("synthetic-device", lambda: False, lambda _: None).download(
        str(remote), str(destination),
    )
    assert (destination / " sub" / "a'$();.bin").read_bytes() == content
    assert (destination / "zero").read_bytes() == b""
    assert (destination / "empty").is_dir()
    assert not list(destination.rglob(".adblab-pull-*"))


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_download_keeps_symlink_parent_semantics(tmp_path, shell_device, directory):
    logical = tmp_path / "logical"
    logical.mkdir()
    physical = tmp_path / "physical"
    (physical / "nested").mkdir(parents=True)
    (logical / "alias").symlink_to(physical / "nested", target_is_directory=True)
    if directory:
        (logical / "files").mkdir()
        (physical / "files").mkdir()
        name = "files/note.txt"
        remote = f"{logical}/alias/../files/"
    else:
        name = "note.txt"
        remote = f"{logical}/alias/../note.txt"
    (logical / name).write_bytes(b"wrong logical target")
    (physical / name).write_bytes(b"expected physical target")
    destination = tmp_path / "download"

    SafeFileDownload("synthetic-device", lambda: False, lambda _: None).download(
        remote, str(destination),
    )

    saved = destination / "note.txt" if directory else destination
    assert saved.read_bytes() == b"expected physical target"
    assert (logical / name).read_bytes() == b"wrong logical target"


def test_download_does_not_remove_missing_parent_component(tmp_path, shell_device):
    remote = tmp_path / "device"
    remote.mkdir()
    (remote / "note.txt").write_bytes(b"must not be downloaded")
    destination = tmp_path / "saved.txt"
    destination.write_bytes(b"original local content")

    with pytest.raises(OSError):
        SafeFileDownload("synthetic-device", lambda: False, lambda _: None).download(
            f"{remote}/missing/../note.txt", str(destination),
        )

    assert destination.read_bytes() == b"original local content"
    assert not list(tmp_path.glob(".adblab-pull-*"))


def test_local_symlink_cannot_redirect_recursive_download(tmp_path, shell_device):
    remote = tmp_path / "device"
    remote.mkdir()
    (remote / "redirect").mkdir()
    (remote / "redirect" / "victim").write_text("new")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim").write_text("old")
    destination = tmp_path / "download"
    destination.mkdir()
    (destination / "redirect").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="链接"):
        SafeFileDownload("synthetic-device", lambda: False, lambda _: None).download(
            str(remote), str(destination),
        )
    assert (outside / "victim").read_text() == "old"


def test_remote_symlink_cycle_fails_without_unbounded_directory_growth(tmp_path, shell_device):
    remote = tmp_path / "device"
    remote.mkdir()
    (remote / "loop").symlink_to(remote, target_is_directory=True)
    destination = tmp_path / "download"
    with pytest.raises(ValueError, match="循环"):
        SafeFileDownload("synthetic-device", lambda: False, lambda _: None).download(
            str(remote), str(destination),
        )
    assert not (destination / "loop").exists()


@pytest.mark.parametrize("child", [b"../escape", b"C:escape", b"a\\..\\escape", b"bad\xff"])
def test_untrusted_recursive_child_is_checked_before_any_file_write(tmp_path, monkeypatch, child):
    import services.file_download as download_module

    def capture(self, command, path, **_kwargs):
        path.write_bytes(b"/device/" + child + b"\0" if "find " in command else b"/device\n")

    native_validator = local_child_path
    monkeypatch.setattr(
        download_module, "local_child_path",
        lambda directory, name, **kwargs: native_validator(directory, name, windows=True, **kwargs),
    )
    monkeypatch.setattr(SafeFileDownload, "_capture", capture)
    destination = tmp_path / "download"
    with pytest.raises((ValueError, UnicodeDecodeError)):
        SafeFileDownload("synthetic-device", lambda: False, lambda _: None).download(
            "/device", str(destination),
        )
    assert not destination.exists()


@pytest.mark.parametrize("failure", ["cancel", "missing-marker", "command-error"])
def test_partial_content_never_replaces_original_file(tmp_path, monkeypatch, failure):
    original = tmp_path / "saved"
    original.write_bytes(b"original")
    aborted = threading.Event()

    def run(cmd, output_path, **_kwargs):
        marker = re.search(r"ADBLAB_PULL_END_[a-f0-9]+", cmd[-1])[0].encode()
        if "cat --" not in cmd[-1]:
            Path(output_path).write_bytes(b"FILE" + marker)
            return SimpleNamespace(success=True)
        Path(output_path).write_bytes(b"partial")
        if failure == "cancel":
            aborted.set()
        return SimpleNamespace(success=failure != "command-error")

    monkeypatch.setattr("services.file_download.CommandRunner.run_to_file", run)
    with pytest.raises(OSError):
        SafeFileDownload("synthetic-device", aborted.is_set, lambda _: None).download(
            "/device/file", str(original),
        )
    assert original.read_bytes() == b"original"
    assert not list(tmp_path.glob(".adblab-pull-*"))


@pytest.mark.ui
def test_pull_worker_cancel_unblocks_raw_download_without_publishing(monkeypatch, tmp_path):
    from models.file_explorer_worker import TransferWorker

    reading = threading.Event()
    terminal = []
    worker = TransferWorker("synthetic-device", ["pull", "/file", str(tmp_path / "file")])

    def run(cmd, output_path, *, cancelled, **kwargs):
        reading.set()
        assert worker._aborted.wait(2)
        assert cancelled()
        return SimpleNamespace(success=False)

    monkeypatch.setattr("services.file_download.CommandRunner.run_to_file", run)
    worker.result_ready.connect(lambda *args: terminal.append(args))
    worker.start()
    try:
        assert reading.wait(2)
        worker.abort()
        assert worker.wait(2000)
        assert not worker.is_active()
        assert not terminal
        assert not (tmp_path / "file").exists()
    finally:
        worker.abort()
        worker.wait(2000)


@pytest.mark.ui
@pytest.mark.parametrize("operation", ["pull", "save-as", "batch", "batch-collision"])
def test_gui_download_entries_never_submit_untrusted_default_paths(
    monkeypatch, tmp_path, qt_application, operation,
):
    from unittest.mock import Mock

    from gui.dialogs.file_explorer_ops import FileExplorerOps

    root = str(tmp_path)
    names = ["A.txt", "a.txt"] if operation == "batch-collision" else ["normal.txt", "../outside"]
    if operation == "batch-collision":
        monkeypatch.setattr("gui.dialogs.file_explorer_ops.os", SimpleNamespace(path=ntpath))
    frame = SimpleNamespace(
        _closing=False, _can_operate=lambda: True, device_ip="synthetic-device",
        current_path="/device", _dpath=lambda *parts: "/".join(parts),
        root_cb=SimpleNamespace(isChecked=lambda: False),
        table=SimpleNamespace(),
        _file_name_at=lambda index: names[index],
    )
    frame.table.selectedIndexes = lambda: [SimpleNamespace(row=lambda i=i: i) for i in range(2)]
    ops = FileExplorerOps(frame)
    monkeypatch.setattr(ops, "_global_save_dir", lambda: root)
    batch = Mock()
    monkeypatch.setattr(ops, "_enqueue_batch", batch)
    failure = Mock()
    monkeypatch.setattr(ops, "_on_file_op_done", failure)
    defaults = []

    def save_dialog(_frame, _title, default):
        defaults.append(default)
        return "", ""

    monkeypatch.setattr("gui.dialogs.file_explorer_ops.QFileDialog.getSaveFileName", save_dialog)
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.QFileDialog.getExistingDirectory", lambda *args: root,
    )
    monkeypatch.setattr(
        Path, "resolve", lambda *args, **kwargs: pytest.fail("GUI must not probe filesystem"),
    )
    if operation == "pull":
        ops._pull_file("../outside")
    elif operation == "save-as":
        ops._save_as("../outside", b"content")
    else:
        ops._pull_selected()
        failure.assert_called_once()
        assert failure.call_args.args[1] is True
    batch.assert_not_called()
    assert defaults == ([] if operation.startswith("batch") else [root + os.sep])
