"""文件预览的版本判断、像素归属和真实请求生命周期回归。"""

import ntpath
import shlex
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSize, Qt, QThread, qInstallMessageHandler
from PySide6.QtGui import QImage, QPixmap

from gui.dialogs.file_explorer_image import FileExplorerImagePreview
from services import file_explorer as service

pytestmark = pytest.mark.ui


def test_preview_uses_full_android_path_for_colon_filename(qt_application, monkeypatch):
    from gui.dialogs.file_explorer import FileExplorerPage
    from models.file_explorer_worker import ADBWorker

    monkeypatch.setattr(ADBWorker, "start", lambda _worker: None)
    monkeypatch.setattr(service, "os", SimpleNamespace(path=ntpath), raising=False)
    page = FileExplorerPage(device_ip="device-test")
    observed = []
    monkeypatch.setattr(page._view_controller, "_view_image", lambda *args: observed.append(args))
    try:
        page.current_path = "/data/local/tmp"
        page._view_controller._view_file("C:photo.png", is_image=True)
        assert observed == [("C:photo.png", "/data/local/tmp/C:photo.png")]
    finally:
        page.close()


def test_real_decoder_completion_advances_nested_preview_stages(qt_application, monkeypatch):
    """前一线程的排队终态内创建真实解码线程，完成后必须在 GUI 收口。"""
    from gui.dialogs.file_explorer import FileExplorerPage
    from models.file_explorer_worker import ADBWorker, TransferWorker
    from tests.ui_geometry_helpers import wait_until

    completion_threads = []

    def stat(worker):
        worker.result_ready.emit("unsupported stat", True)
        worker.finished.emit()

    def pull(worker):
        image = QImage(24, 16, QImage.Format.Format_RGB32)
        image.fill(0xFF123456)
        assert image.save(worker.args[-1])
        worker.result_ready.emit("OK", False, worker.args[-1])
        worker.finished.emit()

    monkeypatch.setattr(ADBWorker, "start", stat)
    monkeypatch.setattr(TransferWorker, "start", pull)
    page = FileExplorerPage(device_ip="device-test")
    show = page._show_image_preview

    def displayed(*args):
        completion_threads.append(QThread.currentThread())
        show(*args)

    monkeypatch.setattr(page, "_show_image_preview", displayed)
    try:
        for index in range(12):
            page._view_image(f"image{index}.png", f"/image{index}.png")
            wait_until(
                qt_application,
                lambda: page.preview_stack.currentWidget() is page.preview_image
                and not page._workers,
            )
        assert len(completion_threads) == 12
        assert all(thread == qt_application.thread() for thread in completion_threads)
        assert not page._transfers.is_running()
    finally:
        page.close()


@pytest.mark.parametrize("preview_state", ["empty", "pending", "displayed"])
def test_closing_image_preview_releases_fluent_image(qt_application, preview_state):
    preview = FileExplorerImagePreview()
    if preview_state != "empty":
        image = QImage(32, 24, QImage.Format.Format_RGB32)
        image.fill(0xFF336699)
        preview.set_image_source(QPixmap.fromImage(image), "photo.png")
        assert preview._fit_timer.isActive()
        if preview_state == "displayed":
            preview._refit_image()
            assert not preview.image_label.image.isNull()

    messages = []
    previous_handler = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message),
    )
    try:
        for _ in range(2):
            preview.release_image_source()
            qt_application.processEvents()
            assert preview.image_label.image.isNull()
            assert preview.image_label.size() == QSize(0, 0)
            assert preview._source_pixmap.isNull()
            assert not preview._fit_timer.isActive()
        assert not [message for message in messages if "Negative sizes" in message]
    finally:
        qInstallMessageHandler(previous_handler)


def test_remote_version_retains_exact_size_and_subsecond_changes():
    first = service.parse_preview_version(
        "102401|345|2026-09-13 12:30:00.123456789 +0800|2026-09-13 12:30:00.234567891 +0800\n"
    )
    next_size = service.parse_preview_version(
        "102449|345|2026-09-13 12:30:00.123456789 +0800|2026-09-13 12:30:00.234567891 +0800\n"
    )
    next_time = service.parse_preview_version(
        "102401|345|2026-09-13 12:30:00.123456790 +0800|2026-09-13 12:30:00.234567892 +0800\n"
    )
    assert first is not None
    assert first.size == 102401
    assert first != next_size
    assert first != next_time


@pytest.mark.parametrize("output", [
    "", "stat: bad format", "102401|345|%y|%z",
    "102401|345|2026-09-13 12:30:00 +0800|2026-09-13 12:30:00 +0800",
    "102401|345|2026-09-13 12:30:00.000000000 +0800|2026-09-13 12:30:00.000000000 +0800",
    "-1|345|2026-09-13 12:30:00.123456789 +0800|2026-09-13 12:30:00.234567891 +0800",
])
def test_unverifiable_remote_version_disables_cache(output):
    assert service.parse_preview_version(output) is None


def test_remote_version_command_quotes_path_as_single_argument():
    command = service.preview_version_command("/sdcard/a 'quote'; $(touch x).png")
    args = shlex.split(command)
    assert args == ["stat", "-c", "%s|%i|%y|%z", "--", "/sdcard/a 'quote'; $(touch x).png"]


def _version(size=100):
    return service.PreviewVersion(size, 23, "mtime", "ctime")


def test_preview_cache_evicts_by_bytes_and_rejects_stale_versions():
    from gui.dialogs.file_explorer_preview_tasks import PreviewImageCache

    cache = PreviewImageCache(max_bytes=128)
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0xFF123456)
    keys = [("device-a", f"/{name}.png", False, 0) for name in "abc"]
    cache.add(keys[0], _version(), image)
    cache.add(keys[1], _version(), image)
    assert not cache.get(keys[0], _version()).isNull()
    cache.add(keys[2], _version(), image)
    assert cache.get(keys[1], _version()).isNull()
    assert not cache.get(keys[0], _version()).isNull()
    assert cache.get(keys[0], _version(101)).isNull()
    assert cache.size_bytes <= 128
    cache.clear()
    assert cache.size_bytes == 0
    assert cache.get(keys[2], _version()).isNull()


def test_preview_cache_does_not_own_oversized_or_unversioned_images():
    from gui.dialogs.file_explorer_preview_tasks import PreviewImageCache

    cache = PreviewImageCache(max_bytes=63)
    key = ("device-a", "/a.png", False, 0)
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0xFF123456)
    cache.add(key, _version(), image)
    assert cache.size_bytes == 0
    cache = PreviewImageCache(max_bytes=1024)
    cache.add(key, None, image)
    assert cache.get(key, None).isNull()
    assert cache.size_bytes == 0


def test_image_reader_decodes_on_worker_and_preserves_original_dimensions(
    qt_application, tmp_path, monkeypatch,
):
    from gui.dialogs import file_explorer_preview_tasks as tasks

    path = tmp_path / "large.png"
    image = QImage(3000, 1000, QImage.Format.Format_RGB32)
    image.fill(0xFF123456)
    assert image.save(str(path))
    factory = tasks.QImageReader
    threads = []

    def reader(path):
        threads.append(QThread.currentThread())
        return factory(path)

    monkeypatch.setattr(tasks, "QImageReader", reader)
    worker = tasks.PreviewReadWorker(str(path))
    worker.start()
    assert worker.wait(3000)
    assert threads and all(thread != qt_application.thread() for thread in threads)
    assert worker.image.size().width() == 2048
    assert worker.native_size.width() == 3000
    assert worker.native_size.height() == 1000
    assert not worker.error


def test_cancelled_decode_discards_pixels(qt_application, monkeypatch):
    from gui.dialogs import file_explorer_preview_tasks as tasks

    entered = threading.Event()
    release = threading.Event()

    class Reader:
        def __init__(self, path):
            pass

        def size(self):
            return QImage(4, 4, QImage.Format.Format_RGB32).size()

        def read(self):
            entered.set()
            assert release.wait(3)
            return QImage(4, 4, QImage.Format.Format_RGB32)

    monkeypatch.setattr(tasks, "QImageReader", Reader)
    worker = tasks.PreviewReadWorker("unused.png")
    worker.start()
    try:
        assert entered.wait(3)
        worker.abort()
    finally:
        release.set()
        assert worker.wait(3000)
    assert worker.image.isNull()


def _until(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QThread.msleep(1)
    app.processEvents()
    assert predicate()


@pytest.fixture
def preview_io(qt_application, tmp_path, monkeypatch, request):
    from core.exec import CommandResult
    from gui.dialogs.file_explorer import FileExplorerPage
    from gui.dialogs.file_explorer_preview_tasks import PreviewReadWorker
    from models import file_explorer_worker as workers

    source = tmp_path / "source.png"
    width, height = getattr(request, "param", (24, 16))
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xFF112233)
    assert image.save(str(source))
    content = source.read_bytes()
    state = SimpleNamespace(
        pulls=[], commands=[], processes=[], decodes=[], block="", copy_entered=threading.Event(),
        release=threading.Event(), cleanup_error=False, version=(
            f"{len(content)}|345|2026-09-13 12:30:00.123456789 +0800|"
            "2026-09-13 12:30:00.234567891 +0800"
        ),
    )

    class Process:
        def __init__(self):
            self.stopped = threading.Event()
            self.stdout = self
            self.read_entered = threading.Event()

        def readline(self):
            self.read_entered.set()
            if state.block == "pull":
                assert self.stopped.wait(3) or state.release.is_set()
            return ""

        def poll(self):
            return None if state.block == "pull" and not self.stopped.is_set() else 0

        def wait(self, timeout=None):
            return 0

    class Runner:
        def __init__(self):
            self.processes = {}

        def start(self, key, cmd, **kwargs):
            assert cmd[-3] == "pull"
            state.pulls.append(tuple(cmd))
            Path(cmd[-1]).write_bytes(content)
            process = Process()
            self.processes[key] = process
            state.processes.append(process)
            return process

        def request_stop(self, key):
            process = self.processes.get(key)
            if process is not None:
                process.stopped.set()
            return process is not None

        def stop(self, key, timeout=0):
            process = self.processes.pop(key, None)
            if process is not None:
                process.stopped.set()
            return 0

        def force_stop(self, key, timeout=0):
            self.stop(key, timeout)
            return True

    def run(cmd, *, timeout=30, cancelled=None, **kwargs):
        state.commands.append(tuple(cmd))
        shell = cmd[-1]
        if "stat -c" in shell:
            return CommandResult(success=True, output=state.version)
        if "dd if=" in shell:
            state.copy_entered.set()
            if state.block == "copy":
                deadline = time.monotonic() + 3
                while not state.release.wait(0.005):
                    if cancelled and cancelled():
                        return CommandResult(success=False, error="Cancelled")
                    assert time.monotonic() < deadline
            return CommandResult(success=True, output="copied")
        if shell.startswith("ls -la"):
            return CommandResult(success=True, output="")
        assert "rm -" in shell
        if state.cleanup_error:
            return CommandResult(success=False, error="offline")
        return CommandResult(success=True, output="")

    monkeypatch.setattr(workers, "ProcessRunner", Runner)
    monkeypatch.setattr(workers.CommandRunner, "run", run)
    start_decode = PreviewReadWorker.start

    def decode(worker):
        state.decodes.append(worker.path)
        start_decode(worker)

    monkeypatch.setattr(PreviewReadWorker, "start", decode)
    page = FileExplorerPage(device_ip="device-preview")
    yield page, state
    state.release.set()
    for process in state.processes:
        process.stopped.set()
    page.request_dispose()
    _until(qt_application, lambda: page._disposed)


def _image_visible(page):
    return page.preview_stack.currentWidget() is page.preview_image


@pytest.mark.parametrize("preview_io", [(1080, 2400)], indirect=True)
def test_scaled_preview_displays_native_dimensions_on_first_read_and_cache(
    preview_io, qt_application,
):
    page, state = preview_io
    for _ in range(2):
        page._view_file("photo.png", True)
        _until(qt_application, lambda: _image_visible(page) and not page._workers)
        assert page.preview_image._source_pixmap.height() == 2048
        assert page.preview_image.image_info.text() == "1080x2400  |  photo.png"
        assert page.preview_image.image_info.accessibleDescription() == "1080x2400  |  photo.png"
        page._close_preview()
    assert len(state.pulls) == 1
    assert len(state.decodes) == 1


def test_reopening_same_remote_image_reuses_download_and_decode(preview_io, qt_application):
    page, state = preview_io
    page._view_file("photo.png", True)
    _until(qt_application, lambda: _image_visible(page) and not page._workers)
    page._close_preview()
    page._view_file("photo.png", True)
    _until(qt_application, lambda: _image_visible(page) and not page._workers)
    assert len(state.pulls) == 1
    assert len(state.decodes) == 1
    assert sum("stat -c" in command[-1] for command in state.commands) == 3

    state.version = state.version.replace("123456789", "123456790")
    page._close_preview()
    page._view_file("photo.png", True)
    _until(qt_application, lambda: _image_visible(page) and not page._workers)
    assert len(state.pulls) == 2
    assert len(state.decodes) == 2


def test_repeated_click_joins_pending_preview_and_close_cancels_pull(preview_io, qt_application):
    page, state = preview_io
    state.block = "pull"
    page._view_file("photo.png", True)
    _until(
        qt_application, lambda: bool(state.processes) and state.processes[0].read_entered.is_set(),
    )
    first_request = page._preview_request_id
    page._view_file("photo.png", True)
    assert page._preview_request_id == first_request
    page._close_preview()
    _until(qt_application, lambda: not page._workers)
    assert len(state.pulls) == 1
    assert state.processes[0].stopped.is_set()
    assert not page._preview_active
    assert not page._view_controller._temporary_files


def test_root_cancel_without_result_still_cleans_owned_original_target(preview_io, qt_application):
    page, state = preview_io
    state.block = "copy"
    page.root_cb.setChecked(True)
    page._view_file("photo.png", True)
    _until(qt_application, state.copy_entered.is_set)
    page.root_cb.setChecked(False)
    page.request_dispose()
    _until(qt_application, lambda: page._disposed)
    copies = [command for command in state.commands if "dd if=" in command[-1]]
    cleanups = [command for command in state.commands if "rm -" in command[-1]]
    assert len(copies) == len(cleanups) == 1
    assert not state.pulls
    assert cleanups[0][2] == "device-preview"
    assert cleanups[0][-1].startswith("su -c ")
    assert "/data/local/tmp/photo.png" not in copies[0][-1]
    assert "adblab-preview-" in copies[0][-1]
    assert "adblab-preview-" in cleanups[0][-1]
    assert not page._view_controller._temporary_files


def test_unavailable_metadata_downloads_again(preview_io, qt_application):
    page, state = preview_io
    state.version = "stat: bad format"
    for _ in range(2):
        page._view_file("photo.png", True)
        _until(qt_application, lambda: _image_visible(page) and not page._workers)
        page._close_preview()
    assert len(state.pulls) == 2


def test_remote_cleanup_failure_is_recorded_as_warning(
    preview_io, qt_application, monkeypatch,
):
    page, state = preview_io
    state.cleanup_error = True
    records = []
    logger = SimpleNamespace(log=lambda level, message: records.append((level, message)))
    monkeypatch.setattr("gui.dialogs.file_explorer_view.LogService", lambda: logger)
    page.root_cb.setChecked(True)
    page._view_file("photo.png", True)
    _until(qt_application, lambda: _image_visible(page) and not page._workers)
    assert len(records) == 1
    assert records[0][0] == "WARNING"
    assert "清理失败" in records[0][1]
    assert "device-preview" not in records[0][1]


def test_temporary_file_cleanup_failure_keeps_retry_and_warning(monkeypatch):
    from gui.dialogs.file_explorer_view import FileExplorerView

    view = FileExplorerView(SimpleNamespace())
    view._temporary_files.add("preview.png")
    records = []
    logger = SimpleNamespace(log=lambda level, message: records.append((level, message)))
    monkeypatch.setattr("gui.dialogs.file_explorer_view.LogService", lambda: logger)

    def locked(path):
        raise PermissionError("file in use")

    monkeypatch.setattr("gui.dialogs.file_explorer_view.os.remove", locked)
    view._remove_temporary_file("preview.png")
    assert "preview.png" in view._temporary_files
    assert len(records) == 1 and records[0][0] == "WARNING"
    assert "重试" in records[0][1]


@pytest.mark.parametrize("boundary", ["refresh", "reconnect"])
def test_refresh_or_reconnect_invalidates_preview_cache(preview_io, qt_application, boundary):
    page, state = preview_io
    page._view_file("photo.png", True)
    _until(qt_application, lambda: _image_visible(page) and not page._workers)
    if boundary == "refresh":
        page._refresh()
        _until(qt_application, lambda: not page._workers)
    else:
        page.set_device_connected(False)
        page.set_device_connected(True)
    page._view_file("photo.png", True)
    _until(qt_application, lambda: _image_visible(page) and not page._workers)
    assert len(state.pulls) == 2
    assert len(state.decodes) == 2


def test_file_row_keeps_raw_metadata_independent_of_rounded_size(qt_application):
    from gui.dialogs.file_explorer import FileExplorerPage

    page = FileExplorerPage(device_ip="device-preview")
    page._on_ls_result(
        "-rw-r--r-- 1 shell shell 102401 2026-09-13 12:30 photo.png", False,
    )
    row = next(i for i in range(page.table.rowCount()) if page._file_name_at(i) == "photo.png")
    assert page.table.item(row, page.SIZE_COL).text() == "100.0 KB"
    entry = page.table.item(row, page.NAME_COL).data(Qt.ItemDataRole.UserRole)
    assert entry.size == 102401


def test_single_pull_cleanup_failure_is_diagnostic_after_close(
    preview_io, qt_application, monkeypatch, tmp_path,
):
    page, state = preview_io
    state.block = "copy"
    state.cleanup_error = True
    records = []
    monkeypatch.setattr(
        "core.log_service.LogService.log",
        lambda self, level, message: records.append((level, message)),
    )
    monkeypatch.setattr("gui.dialogs.file_explorer_ops.report_feedback", lambda *a, **k: None)
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.FileExplorerOps._global_save_dir",
        staticmethod(lambda: str(tmp_path)),
    )
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.QFileDialog.getSaveFileName",
        lambda *args: (str(tmp_path / "download.png"), ""),
    )
    page.root_cb.setChecked(True)
    page._pull_file("photo.png")
    _until(qt_application, state.copy_entered.is_set)
    page.request_dispose()
    _until(qt_application, lambda: page._disposed)
    assert any(level == "WARNING" and "清理失败" in message for level, message in records)
