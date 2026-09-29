"""目录身份在原始字节、界面和变更入口之间保持一致。"""

import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import file_explorer as explorer


def framed(*records):
    raw = bytearray(b"ADBLAB_LIST_V1\0")
    for name, mode, target in records:
        raw.extend(name if isinstance(name, bytes) else name.encode())
        raw.extend(b"\0" + mode.encode() + b"|12|2026-09-29 12:00:00.000000000 +0000\n\0")
        raw.extend(target.encode())
        if mode.startswith("l"):
            raw.extend(b"\n")
        raw.extend(b"\0")
    return bytes(raw)


def test_legacy_symlink_parser_rejects_overlapping_arrow_separators():
    rows, targets = explorer.parse_ls_output(
        "lrwxrwxrwx 1 shell shell 6 May 30 12:34 config -> -> target",
    )
    assert rows == [] and targets == {}


def test_framed_names_and_link_targets_keep_exact_identity():
    names = ["config", "config->new", "config ->", " config ", "name\twith\tspace"]
    result = explorer.parse_directory_listing(framed(
        *((name, "lrwxrwxrwx", "target -> \n") for name in names),
    ))
    assert {entry.name for entry in result.entries} == set(names)
    assert result.symlink_targets == dict.fromkeys(names, "target -> \n")


@pytest.mark.parametrize("raw", [
    b"", b"ADBLAB_LIST_V1", b"ADBLAB_LIST_V1\0partial",
    framed((b"config\xff", "-rw-r--r--", "")),
    framed(("config\ncontinuation", "-rw-r--r--", "")),
    framed(("config\rcontinuation", "-rw-r--r--", "")),
    framed(("../config", "-rw-r--r--", "")),
    framed(("config", "-rw-r--r--", ""), ("config", "-rw-r--r--", "")),
    framed(("config", "invalid", "")),
    framed(("config", "-rw-r--r--", "unexpected target")),
    framed(("config", "lrwxrwxrwx", "")),
    framed(("config", "-rw-r--r--", "")).replace(b"|12|", b"|" + b"9" * 400 + b"|"),
])
def test_ambiguous_or_invalid_directory_response_never_publishes_partial_rows(raw):
    with pytest.raises(ValueError):
        explorer.parse_directory_listing(raw)


@pytest.fixture
def local_shell(monkeypatch):
    if os.name == "nt":
        pytest.skip("Local protocol integration requires a POSIX shell")
    calls = []

    def capture(command, output_path, *, timeout, cancelled):
        assert command[:5] == ["adb", "-s", "synthetic-device", "shell", "-T"]
        assert not cancelled()
        calls.append(command)
        with open(output_path, "wb") as output:
            process = subprocess.run(
                ["sh", "-c", command[-1]], stdout=output, stderr=subprocess.PIPE,
                timeout=timeout, check=False,
            )
        return SimpleNamespace(success=process.returncode == 0, error="synthetic failure")

    monkeypatch.setattr("models.file_explorer_worker.CommandRunner.run_to_file", capture)
    return calls


@pytest.mark.ui
def test_directory_worker_reads_raw_names_and_links_without_text_normalization(
    tmp_path, local_shell,
):
    from models.file_explorer_worker import DirectoryListWorker

    tmp_path = tmp_path / "directory ' ; $() "
    tmp_path.mkdir()
    for name in ("config", "config ", " config", "config->new"):
        (tmp_path / name).write_bytes(b"content")
    (tmp_path / "config ->").symlink_to("target -> \n")
    (tmp_path / " empty ").mkdir()
    worker = DirectoryListWorker("synthetic-device", str(tmp_path), False)
    result = []
    worker.result_ready.connect(lambda *args: result.append(args))
    worker.run()
    assert len(result) == 1 and result[0][1] is False
    listing = result[0][0]
    assert {entry.name for entry in listing.entries} == {
        "config", "config ", " config", "config->new", "config ->", " empty ",
    }
    assert listing.symlink_targets == {"config ->": "target -> \n"}
    assert next(entry for entry in listing.entries if entry.name == " empty ").is_dir


@pytest.mark.ui
@pytest.mark.parametrize("name", [b"config\xff", b"config\ntrailer"])
def test_worker_rejects_names_that_could_become_another_existing_file(tmp_path, local_shell, name):
    from models.file_explorer_worker import DirectoryListWorker

    (tmp_path / "config").write_text("untouched")
    descriptor = os.open(os.fsencode(tmp_path) + b"/" + name, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(descriptor)
    result = []
    worker = DirectoryListWorker("synthetic-device", str(tmp_path), False)
    worker.result_ready.connect(lambda *args: result.append(args))
    worker.run()
    assert len(result) == 1 and result[0][1] is True
    assert (tmp_path / "config").read_text() == "untouched"


@pytest.mark.ui
@pytest.mark.parametrize("failure", ["command", "truncated", "cancelled"])
def test_directory_worker_failure_or_cancel_never_delivers_usable_rows(
    tmp_path, monkeypatch, failure,
):
    from models.file_explorer_worker import DirectoryListWorker

    worker = DirectoryListWorker("synthetic-device", "/device", False)
    result, paths = [], []
    worker.result_ready.connect(lambda *args: result.append(args))

    def capture(_command, output_path, **_kwargs):
        paths.append(Path(output_path))
        Path(output_path).write_bytes(framed(("config", "-rw-r--r--", "")))
        if failure == "cancelled":
            worker.abort()
        return SimpleNamespace(success=failure != "command", error="synthetic failure")

    monkeypatch.setattr("models.file_explorer_worker.CommandRunner.run_to_file", capture)
    worker.run()
    if failure == "cancelled":
        assert result == []
    else:
        assert len(result) == 1 and result[0][1] is True
    assert paths and all(not path.exists() for path in paths)


@pytest.mark.ui
def test_refresh_preserves_directory_identity_and_rejects_legacy_text_results(
    monkeypatch, qt_application,
):
    from gui.dialogs.file_explorer import FileExplorerPage
    from models.file_explorer_worker import ADBWorker, DirectoryListWorker

    started = []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: started.append(worker))
    page = FileExplorerPage(device_ip="synthetic-device")
    try:
        page._navigate("/device/folder ")
        worker = started[-1]
        assert isinstance(worker, DirectoryListWorker)
        assert worker.path == "/device/folder "
        worker.result_ready.emit("-rw-r--r-- 1 shell shell 4 May 30 12:34 guessed", False)
        qt_application.processEvents()
        assert page.current_path != "/device/folder "
        assert all(page._file_name_at(row) != "guessed" for row in range(page.table.rowCount()))
        page._navigate("/device/folder ")
        started[-1].result_ready.emit(explorer.parse_directory_listing(framed(
            ("config", "-rw-r--r--", ""), ("config ", "-rw-r--r--", ""),
            ("config ->", "lrwxrwxrwx", "target"),
        )), False)
        qt_application.processEvents()
        assert page.current_path == "/device/folder "
        assert {page._file_name_at(row) for row in range(page.table.rowCount())} == {
            "..", "config", "config ", "config ->",
        }
        opened = []
        monkeypatch.setattr(page, "_view_or_pull", opened.append)
        row = next(row for row in range(page.table.rowCount())
                   if page._file_name_at(row) == "config ")
        page._on_double_click(row, 0)
        assert opened == ["config "]
        deleted = []
        monkeypatch.setattr(
            page._ops_controller, "_enqueue_batch", lambda *args: deleted.append(args),
        )
        page._request_delete(["config ", "config ->"])
        assert deleted == [("delete", [
            ("config ", "/device/folder /config ", ""),
            ("config ->", "/device/folder /config ->", ""),
        ], "/device/folder ")]
        page._refresh()
        assert started[-1].path == "/device/folder "
    finally:
        page.close()


@pytest.mark.ui
@pytest.mark.parametrize("payload", ["/device/folder ", {"path": "/device/folder "}])
def test_programmatic_activation_preserves_directory_name(monkeypatch, qt_application, payload):
    from gui.dialogs.file_explorer import FileExplorerPage
    from models.file_explorer_worker import ADBWorker

    started = []
    monkeypatch.setattr(ADBWorker, "start", lambda worker: started.append(worker))
    page = FileExplorerPage(device_ip="synthetic-device")
    try:
        page.activate(payload)
        assert started[-1].path == "/device/folder "
    finally:
        page.close()


@pytest.mark.ui
def test_closing_directory_reader_cancels_and_waits_without_delivering_late_rows(
    monkeypatch, qt_application,
):
    from gui.dialogs.file_explorer import FileExplorerPage
    from tests.ui_geometry_helpers import wait_until

    entered, release = threading.Event(), threading.Event()
    callbacks = []

    def capture(_command, _output_path, *, cancelled, **_kwargs):
        callbacks.append(cancelled)
        entered.set()
        assert release.wait(2)
        assert cancelled()
        return SimpleNamespace(success=False)

    monkeypatch.setattr("models.file_explorer_worker.CommandRunner.run_to_file", capture)
    page = FileExplorerPage(device_ip="synthetic-device")
    try:
        page._refresh()
        wait_until(qt_application, entered.is_set)
        assert page.request_dispose() is False
        assert callbacks[0]()
        assert not page._disposed
        release.set()
        wait_until(qt_application, lambda: page._disposed)
        assert not page._workers
        assert page.table.rowCount() == 0
    finally:
        release.set()
        page.close()
