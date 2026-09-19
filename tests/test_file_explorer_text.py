"""文本预览字节完整性、后台保存及资源归属回归。"""

import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from core.exec import CommandResult
from services import file_explorer as service


@pytest.mark.parametrize("payload", [
    b"    line one\r\nline two \r\n", b"\xef\xbb\xbf text\r\n", b"first\rsecond\r",
    b"mixed\r\nline\nend\r", b"", "a\u2029b".encode(),
])
def test_unedited_text_round_trip_preserves_every_byte(payload):
    preview = service.decode_text_preview(payload, 2 * 1024 * 1024)
    assert preview.editable
    qt_text = preview.text.replace("\r\n", "\n").replace("\r", "\n")
    assert preview.encode(qt_text, modified=False) == payload


@pytest.mark.parametrize("payload", [b"x" + b" " * 32, b"x" * 32 + b"\n", b"x" * 31 + b"\xe4\xb8"])
def test_raw_byte_overflow_disables_editing_even_when_decode_shrinks(payload):
    preview = service.decode_text_preview(payload, 32)
    assert not preview.editable
    with pytest.raises(ValueError):
        preview.encode("replacement", modified=True)


def test_invalid_utf8_preview_cannot_be_saved():
    preview = service.decode_text_preview(b"abc\xffdef", 32)
    assert not preview.editable
    assert "abc" in preview.text and "def" in preview.text


@pytest.mark.parametrize(("original", "expected"), [
    (b"\xef\xbb\xbfa\r\nb\r\n", b"\xef\xbb\xbfchanged\r\nb\r\n"),
    (b"a\rb\r", b"changed\rb\r"),
    (b"a\nb\n", b"changed\nb\n"),
])
def test_edited_text_retains_bom_and_original_newline_style(original, expected):
    preview = service.decode_text_preview(original, 1024)
    assert preview.encode("changed\nb\n", modified=True) == expected


def test_text_reader_preserves_raw_bytes_and_removes_local_temporary_file(monkeypatch):
    from models import file_explorer_worker as workers

    payload = b"    line\r\nend \r\n"
    paths = []

    def capture(command, output_path, **kwargs):
        assert command[:5] == ["adb", "-s", "test-device", "shell", "-T"]
        assert "head -c 33" in command[-1]
        assert not kwargs["cancelled"]()
        paths.append(Path(output_path))
        Path(output_path).write_bytes(payload + shlex.split(command[-1])[-1].encode())
        return CommandResult(success=True)

    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    worker = workers.TextReadWorker("test-device", "/notes.txt", False, 32)
    results = []
    worker.result_ready.connect(lambda value, error: results.append((value, error)))
    worker.run()
    assert results == [(payload, False)]
    assert paths and all(not path.exists() for path in paths)


@pytest.mark.parametrize("use_root", [False, True])
@pytest.mark.parametrize("outcome", ["success", "push_failed", "cancelled", "publish_failed"])
def test_save_uses_bounded_arguments_and_cleans_only_owned_staging(monkeypatch, use_root, outcome):
    from models import file_explorer_worker as workers

    payload = b"  content\r\n" * 12000
    calls = []
    uploads = []
    worker = workers.TextSaveWorker("original-device", "/link.txt", payload, use_root)

    def command(argv, **kwargs):
        calls.append((argv, kwargs))
        assert argv[:3] == ["adb", "-s", "original-device"]
        assert len(" ".join(argv)) < 4096
        if argv[3] == "push":
            uploads.append(Path(argv[4]))
            assert uploads[-1].read_bytes() == payload
            if outcome == "cancelled":
                worker.abort()
            return CommandResult(success=outcome != "push_failed", error="push failure")
        shell = argv[-1]
        if "readlink" in shell:
            return CommandResult(success=True, output="ADBLAB_TARGET:/actual/file.txt:END")
        if "mv " in shell:
            assert "cp -p " in shell
            assert "/actual/file.txt" in shell
            assert "/link.txt" not in shell
            return CommandResult(success=outcome != "publish_failed", error="publish failure")
        return CommandResult(success=True)

    monkeypatch.setattr(workers.CommandRunner, "run", command)
    results = []
    worker.result_ready.connect(lambda output, failed: results.append((output, failed)))
    worker.run()

    assert uploads and all(not path.exists() for path in uploads)
    cleanup = [(args[-1], kw) for args, kw in calls if "rm -f " in args[-1]]
    assert cleanup and all("adblab-save-" in shell for shell, _ in cleanup)
    assert all(kw.get("cancelled") is None for _, kw in cleanup)
    assert all("rm -rf" not in shell for shell, _ in cleanup)
    published = any("mv " in args[-1] for args, _ in calls)
    assert published == (outcome in {"success", "publish_failed"})
    if outcome == "cancelled":
        assert not results
    else:
        assert results and results[-1][1] == (outcome != "success")


@pytest.mark.ui
@pytest.mark.parametrize("payload", [
    b"    first\r\nlast \r\n", b"\xef\xbb\xbfhello\r\n", b"mixed\r\nsecond\nthird\r",
])
def test_page_unedited_save_sends_original_bytes(qt_application, monkeypatch, payload):
    from gui.dialogs.file_explorer import FileExplorerPage

    page = FileExplorerPage(device_ip="original-device")
    saved = []
    monkeypatch.setattr(page, "_save_to_device", lambda name, content, path: saved.append(content))
    try:
        page._view_controller._show_text_viewer("text.txt", payload, False, "/text.txt")
        page._save_preview_to_device()
        assert saved == [payload]
    finally:
        page.close()


@pytest.mark.ui
@pytest.mark.parametrize(
    "payload", [b"x" + b" " * (2 * 1024 * 1024), b"invalid\xff"], ids=["truncated", "invalid"],
)
def test_page_incomplete_or_invalid_preview_refuses_programmatic_save(
    qt_application, monkeypatch, payload,
):
    from gui.dialogs.file_explorer import FileExplorerPage

    page = FileExplorerPage(device_ip="original-device")
    saved = []
    monkeypatch.setattr(page, "_save_to_device", lambda *args: saved.append(args))
    try:
        page._view_controller._show_text_viewer("text.txt", payload, False, "/text.txt")
        page._save_preview_to_device()
        assert page.preview_text_edit.isReadOnly()
        assert not page.preview_save_device_btn.isEnabled()
        assert not saved
    finally:
        page.close()


def test_cancel_during_remote_reservation_still_attempts_owned_cleanup(monkeypatch):
    from models import file_explorer_worker as workers

    worker = workers.TextSaveWorker("original-device", "/text.txt", b"text", False)
    cleanup = []

    def run(argv, **kwargs):
        command = argv[-1]
        if "readlink" in command:
            return CommandResult(success=True, output="ADBLAB_TARGET:/text.txt:END")
        if "mkdir " in command:
            worker.abort()
            return CommandResult(success=False, outcome="cancelled")
        cleanup.append(command)
        assert kwargs.get("cancelled") is None
        return CommandResult(success=True)

    monkeypatch.setattr(workers.CommandRunner, "run", run)
    worker.run()
    assert cleanup and "rm -f " in cleanup[0]


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_text_reader_failed_or_cancelled_capture_discards_output_and_cleans(monkeypatch, outcome):
    from models import file_explorer_worker as workers

    paths = []
    worker = workers.TextReadWorker("original-device", "/text.txt", False, 32)
    results = []
    worker.result_ready.connect(lambda *args: results.append(args))

    def capture(command, output_path, **kwargs):
        paths.append(Path(output_path))
        paths[-1].write_bytes(b"partial")
        if outcome == "cancelled":
            worker.abort()
        return CommandResult(success=False, error="Read failed", outcome=outcome)

    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    worker.run()
    assert paths and all(not path.exists() for path in paths)
    assert results == ([] if outcome == "cancelled" else [("Read failed", True)])


def test_text_reader_rejects_success_status_without_remote_completion(monkeypatch):
    from models import file_explorer_worker as workers

    def capture(argv, output_path, **kwargs):
        Path(output_path).write_bytes(b"head: Permission denied\n")
        return CommandResult(success=True)

    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    worker = workers.TextReadWorker("original-device", "/text.txt", False, 32)
    results = []
    worker.result_ready.connect(lambda *args: results.append(args))
    worker.run()
    assert results and results[-1][1] is True


def test_local_save_preserves_bytes_and_cancellation_preserves_old_file(monkeypatch, tmp_path):
    from models import file_explorer_worker as workers

    path = tmp_path / "local.txt"
    path.write_bytes(b"old")
    payload = b"\xef\xbb\xbf text \r\n"
    worker = workers.LocalTextSaveWorker(str(path), payload)
    worker.abort()
    worker.run()
    assert path.read_bytes() == b"old"
    worker = workers.LocalTextSaveWorker(str(path), payload)
    worker.run()
    assert path.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.ui
def test_page_reads_raw_text_on_worker_and_discards_late_preview(qt_application, monkeypatch):
    from gui.dialogs.file_explorer import FileExplorerPage
    from models import file_explorer_worker as workers
    from tests.ui_geometry_helpers import wait_until

    entered = threading.Event()
    release = threading.Event()
    threads = []

    def capture(argv, output_path, **kwargs):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        Path(output_path).write_bytes(b"  raw\r\n" + shlex.split(argv[-1])[-1].encode())
        return CommandResult(success=True)

    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    page = FileExplorerPage(device_ip="original-device")
    try:
        page._view_file("text.txt")
        wait_until(qt_application, entered.is_set)
        page._close_preview()
        release.set()
        wait_until(qt_application, lambda: not page._workers)
        assert page.preview_stack.currentWidget() is page.preview_empty_page
        assert threads == [threads[0]] and threads[0] != threading.get_ident()
        page._view_file("text.txt")
        wait_until(qt_application, lambda: not page._workers)
        assert page._preview_bytes() == b"  raw\r\n"
    finally:
        release.set()
        page.close()


@pytest.mark.ui
@pytest.mark.parametrize("boundary", ["offline", "deselected", "root"])
def test_context_change_cancels_loading_text_without_stuck_spinner(
    qt_application, monkeypatch, boundary,
):
    from gui.dialogs.file_explorer import FileExplorerPage
    from models import file_explorer_worker as workers
    from tests.ui_geometry_helpers import wait_until

    entered = threading.Event()
    release = threading.Event()

    def capture(argv, output_path, **kwargs):
        entered.set()
        assert release.wait(3)
        Path(output_path).write_bytes(b"late" + shlex.split(argv[-1])[-1].encode())
        return CommandResult(success=True)

    monkeypatch.setattr(workers.CommandRunner, "run_to_file", capture)
    page = FileExplorerPage(device_ip="original-device")
    try:
        page._view_file("text.txt")
        wait_until(qt_application, entered.is_set)
        assert page.preview_stack.currentWidget() is page.preview_loading_page
        if boundary == "offline":
            page.set_device_connected(False)
        elif boundary == "deselected":
            page.set_device_selected(False)
        else:
            page.root_cb.setChecked(True)
        release.set()
        wait_until(qt_application, lambda: not page._workers)
        assert page.preview_stack.currentWidget() is page.preview_empty_page
        assert not page._preview_active
    finally:
        release.set()
        page.close()


@pytest.mark.ui
def test_refresh_and_root_change_preserve_displayed_text_edits(qt_application):
    from gui.dialogs.file_explorer import FileExplorerPage

    page = FileExplorerPage(device_ip="original-device")
    try:
        page._show_text_viewer("text.txt", b"original\r\n", False, "/text.txt")
        page.preview_text_edit.insertPlainText("edited ")
        edited = page._preview_bytes()
        assert edited == b"edited original\r\n"
        page._view_controller.invalidate_cache()
        page.root_cb.setChecked(True)
        assert page.preview_stack.currentWidget() is page.preview_text_page
        assert page._preview_bytes() == edited
    finally:
        page.close()


@pytest.fixture
def blocked_save(monkeypatch):
    from models import file_explorer_worker as workers

    entered = threading.Event()
    release = threading.Event()
    cleanup_entered = threading.Event()
    cleanup_release = threading.Event()
    cleanup_release.set()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[3] == "push":
            assert Path(argv[4]).read_bytes() == b" original\r\n"
            entered.set()
            assert release.wait(3)
            return CommandResult(success=not kwargs["cancelled"](), error="cancelled")
        command = argv[-1]
        if "readlink" in command:
            return CommandResult(success=True, output="ADBLAB_TARGET:/original.txt:END")
        if "rm -f " in command:
            cleanup_entered.set()
            assert cleanup_release.wait(3)
            assert kwargs["cancelled"] is None
        return CommandResult(success=True)

    monkeypatch.setattr(workers.CommandRunner, "run", run)
    try:
        yield entered, release, cleanup_entered, cleanup_release, calls
    finally:
        release.set()
        cleanup_release.set()


@pytest.mark.ui
def test_save_deduplicates_clicks_and_does_not_change_new_preview(
    qt_application, monkeypatch, blocked_save,
):
    from gui.dialogs.file_explorer import FileExplorerPage
    from tests.ui_geometry_helpers import wait_until

    entered, release, _, _, calls = blocked_save
    reported = []
    page = FileExplorerPage(device_ip="original-device")
    monkeypatch.setattr(
        page._ops_controller, "_on_save_result", lambda *args: reported.append(args),
    )
    try:
        page._show_text_viewer("original.txt", b" original\r\n", False, "/original.txt")
        page._save_preview_to_device()
        wait_until(qt_application, entered.is_set)
        page._save_preview_to_device()
        page._begin_preview_request("new.txt")
        page._show_text_viewer("new.txt", b"new\n", False, "/new.txt")
        release.set()
        wait_until(qt_application, lambda: not page._workers)
        assert len([call for call in calls if call[3] == "push"]) == 1
        assert not reported
        assert page.preview_title.text() == "new.txt"
        assert page._preview_bytes() == b"new\n"
        assert page.preview_save_device_btn.isEnabled()
        assert not page._ops_controller.saving
    finally:
        release.set()
        page.close()


@pytest.mark.ui
@pytest.mark.parametrize("reason", ["close", "offline", "deselected"])
def test_cancelled_save_waits_for_cleanup_without_publishing(qt_application, blocked_save, reason):
    from gui.dialogs.file_explorer import FileExplorerPage
    from tests.ui_geometry_helpers import wait_until

    entered, release, cleanup_entered, cleanup_release, calls = blocked_save
    page = FileExplorerPage(device_ip="original-device")
    try:
        page._show_text_viewer("original.txt", b" original\r\n", False, "/original.txt")
        page._save_preview_to_device()
        wait_until(qt_application, entered.is_set)
        cleanup_release.clear()
        if reason == "close":
            assert not page.request_dispose("test")
        elif reason == "offline":
            page.set_device_connected(False)
        else:
            page.set_device_selected(False)
        release.set()
        wait_until(qt_application, cleanup_entered.is_set)
        assert not page._disposed
        assert page._transfers.is_running()
        cleanup_release.set()
        wait_until(qt_application, lambda: not page._workers)
        assert not any("mv " in command[-1] for command in calls)
        assert all(command[2] == "original-device" for command in calls)
        if reason == "close":
            wait_until(qt_application, lambda: page._disposed)
        else:
            assert not page.preview_save_device_btn.isEnabled()
    finally:
        release.set()
        cleanup_release.set()
        page.close()


@pytest.mark.ui
def test_local_save_runs_off_gui_and_preserves_preview_bytes(qt_application, monkeypatch, tmp_path):
    from gui.dialogs import file_explorer_ops as ops
    from gui.dialogs.file_explorer import FileExplorerPage
    from models import file_explorer_worker as workers
    from tests.ui_geometry_helpers import wait_until

    target = tmp_path / "copy.txt"
    monkeypatch.setattr(
        ops.FileExplorerOps, "_global_save_dir", staticmethod(lambda: str(tmp_path)),
    )
    monkeypatch.setattr(ops.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    threads = []
    replace = workers.os.replace

    def publish(source, destination):
        threads.append(threading.get_ident())
        replace(source, destination)

    monkeypatch.setattr(workers.os, "replace", publish)
    page = FileExplorerPage(device_ip="original-device")
    try:
        page._show_text_viewer(
            "original.txt", b"\xef\xbb\xbf original \r\n", False, "/original.txt",
        )
        page._save_preview_as()
        wait_until(qt_application, lambda: not page._workers)
        assert target.read_bytes() == b"\xef\xbb\xbf original \r\n"
        assert threads and all(thread != threading.get_ident() for thread in threads)
    finally:
        page.close()


@pytest.fixture
def local_shell():
    shell = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).parent.parent / "bin/bash.exe" if git else None
        if candidate is not None and candidate.is_file():
            shell = str(candidate)
    if shell is None:
        pytest.skip("Local shell contract probe requires Bash or Git Bash")

    def run(command):
        return subprocess.run(
            [shell, "-c", command], capture_output=True, text=True, encoding="utf-8", timeout=10,
            env={**os.environ, "MSYS": "winsymlinks:nativestrict"},
        )

    return run


@pytest.mark.parametrize("linked", [False, True], ids=["regular", "symlink"])
@pytest.mark.skipif(
    os.name == "nt", reason="POSIX mode and symlink probe requires a POSIX filesystem",
)
def test_real_shell_publish_preserves_link_and_target_permissions(local_shell, tmp_path, linked):
    target = tmp_path / "actual file.txt"
    target.write_bytes(b"old")
    link = tmp_path / "link.txt"
    directory = tmp_path / ".adblab-save-controlled"
    quote = service.shell_quote
    if linked:
        created = local_shell(f"ln -s {quote(target.as_posix())} {quote(link.as_posix())}")
        if os.name == "nt" and "Operation not permitted" in created.stderr:
            pytest.skip("Windows account lacks native symlink creation privilege")
        assert created.returncode == 0, created.stderr
    assert local_shell(f"chmod 640 {quote(target.as_posix())}").returncode == 0
    original_mode = local_shell(f"stat -c %a {quote(target.as_posix())}").stdout
    resolved = local_shell(service.resolve_text_target_command(
        (link if linked else target).as_posix(),
    ))
    assert resolved.returncode == 0, resolved.stderr
    actual = resolved.stdout[len("ADBLAB_TARGET:"):-len(":END")]
    prepared = local_shell(service.prepare_text_directory_command(directory.as_posix()))
    assert prepared.returncode == 0, prepared.stderr
    (directory / "upload").write_bytes(b"  new\r\n")
    published = local_shell(service.publish_text_command(
        actual, directory.as_posix(), (directory / "upload").as_posix(),
    ))
    assert published.returncode == 0, published.stderr
    assert target.read_bytes() == b"  new\r\n"
    if linked:
        assert link.is_symlink()
        assert link.read_bytes() == b"  new\r\n"
    assert local_shell(f"stat -c %a {quote(target.as_posix())}").stdout == original_mode
    cleaned = local_shell(service.cleanup_text_directory_command(directory.as_posix()))
    assert cleaned.returncode == 0, cleaned.stderr
    assert not directory.exists()


def test_real_shell_cleanup_refuses_unowned_directory(local_shell, tmp_path):
    directory = tmp_path / ".adblab-save-controlled"
    directory.mkdir()
    (directory / "upload").write_bytes(b"belongs to someone else")
    (directory / "owner").write_text("wrong owner")
    cleaned = local_shell(service.cleanup_text_directory_command(directory.as_posix()))
    assert cleaned.returncode != 0
    assert (directory / "upload").read_bytes() == b"belongs to someone else"
