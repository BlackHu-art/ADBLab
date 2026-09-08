"""验证截图 I/O 的真实线程、缓存预算和图库快照边界。"""

import threading
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader

from adblab.application.supervision import TaskSupervisor
from gui.features.media import ScreenshotPage
from tests.ui_geometry_helpers import wait_until


def _write_image(path, color=Qt.GlobalColor.blue, size=(64, 96)):
    image = QImage(*size, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(path))
    return str(path)


def _ready(app, page):
    wait_until(app, lambda: (
        page._display_path == page._current_path() and page._display_pixmap is not None
    ))


def _close(app, page):
    page.request_dispose("test")
    wait_until(app, lambda: page.is_disposed)
    page.close()


def test_screenshot_decode_leaves_ui_responsive_and_discards_old_navigation(
    qt_application, tmp_path, monkeypatch,
):
    """阻塞真实读取边界时主线程可继续切图，旧图完成不能覆盖新目标。"""
    from gui.dialogs import screenshot_viewer_nav as nav

    paths = [_write_image(tmp_path / f"image-{i}.png") for i in range(2)]
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    reader_threads = []

    class Reader:
        def __init__(self, path):
            self.reader = QImageReader(path)

        def read(self):
            reader_threads.append(threading.get_ident())
            if not entered.is_set():
                entered.set()
                assert release.wait(2)
            return self.reader.read()

    monkeypatch.setattr(nav, "QImageReader", Reader)
    page = ScreenshotPage([])
    try:
        page.activate(paths)
        assert entered.wait(1)
        assert reader_threads[0] != main_thread
        page._navigate_to(1)
        release.set()
        _ready(qt_application, page)
        assert page._display_path == paths[1]
    finally:
        release.set()
        _close(qt_application, page)


def test_screenshot_large_image_cache_avoids_repeat_decode_and_observes_file_change(
    qt_application, tmp_path, monkeypatch,
):
    """超过 Qt 默认缓存的大图可复用；源文件变化后必须重新读取。"""
    from gui.dialogs import screenshot_viewer_nav as nav

    paths = [_write_image(tmp_path / f"large-{i}.png", size=(1440, 3200)) for i in range(2)]
    reads = Counter()

    class Reader:
        def __init__(self, path):
            self.path, self.reader = path, QImageReader(path)

        def read(self):
            reads[self.path] += 1
            return self.reader.read()

    monkeypatch.setattr(nav, "QImageReader", Reader)
    page = ScreenshotPage(paths)
    try:
        _ready(qt_application, page)
        page._navigate_to(1)
        _ready(qt_application, page)
        page._navigate_to(0)
        _ready(qt_application, page)
        assert reads[paths[0]] == 1
        _write_image(paths[0], Qt.GlobalColor.red, size=(1440, 3200))
        page._navigate_to(0)
        wait_until(qt_application, lambda: (
            page._display_pixmap is not None
            and page._display_pixmap.toImage().pixelColor(0, 0) == Qt.GlobalColor.red
        ))
        assert reads[paths[0]] == 2
    finally:
        _close(qt_application, page)


def test_screenshot_append_preserves_existing_items_and_decoded_image(qt_application, tmp_path):
    """追加批次不能重建已有图片项或圆点，当前预览保持不变。"""
    paths = [_write_image(tmp_path / f"image-{i}.png") for i in range(2)]
    page = ScreenshotPage(paths[:1])
    try:
        _ready(qt_application, page)
        item, pip = page._view.item(0), page._pager.item(0)
        before = page._display_pixmap.cacheKey()
        page.receive_payload({"paths": paths[1:], "focus_new": False})
        assert page._view.item(0) is item
        assert page._pager.item(0) is pip
        assert page._display_pixmap.cacheKey() == before
        assert page._view.count() == page._pager.count() == 2
    finally:
        _close(qt_application, page)


def test_screenshot_delete_batch_runs_off_ui_and_keeps_new_arrivals(
    qt_application, tmp_path, monkeypatch,
):
    """删除只处理启动快照，重复点击及期间新增图片不能扩大删除目标。"""
    from gui.dialogs import screenshot_viewer_actions as actions

    paths = [_write_image(tmp_path / f"image-{i}.png") for i in range(3)]
    entered, release = threading.Event(), threading.Event()
    remove = actions.os.remove
    deleted = []
    main_thread = threading.get_ident()

    def slow_remove(path):
        deleted.append((path, threading.get_ident()))
        entered.set()
        assert release.wait(2)
        remove(path)

    page = ScreenshotPage(paths[:2])
    try:
        _ready(qt_application, page)
        monkeypatch.setattr(actions.os, "remove", slow_remove)
        page._delete_all_action.trigger()
        assert entered.wait(1)
        assert deleted[0][1] != main_thread
        page._delete_all_action.trigger()
        page.receive_payload(paths[2:])
        release.set()
        wait_until(qt_application, lambda: page.image_paths == (paths[2],))
        assert [path for path, _ in deleted] == paths[:2]
        assert page._view.count() == page._pager.count() == 1
    finally:
        release.set()
        _close(qt_application, page)


def test_screenshot_dispose_waits_for_delete_worker_and_cancels_remaining_files(
    qt_application, tmp_path, monkeypatch,
):
    """已进入系统调用的删除须等待返回，取消后不删除快照余下文件。"""
    from gui.dialogs import screenshot_viewer_actions as actions

    paths = [_write_image(tmp_path / f"image-{i}.png") for i in range(2)]
    entered, release = threading.Event(), threading.Event()
    remove = actions.os.remove
    deleted = []

    def slow_remove(path):
        deleted.append(path)
        entered.set()
        assert release.wait(2)
        remove(path)

    page = ScreenshotPage(paths)
    try:
        _ready(qt_application, page)
        monkeypatch.setattr(actions.os, "remove", slow_remove)
        page._delete_all_action.trigger()
        assert entered.wait(1)
        supervisor = TaskSupervisor()
        assert page.register_shutdown_tasks(supervisor, owner_id="test", task_prefix="media")
        assert page.request_dispose("test") is False
        assert not page.is_disposed
        release.set()
        wait_until(qt_application, lambda: page.is_disposed)
        assert deleted == paths[:1]
    finally:
        release.set()
        _close(qt_application, page)


def test_hidden_screenshot_batch_defers_decode_until_activation(
    qt_application, tmp_path, monkeypatch,
):
    """后台接收只登记路径，进入页面后才读取图片。"""
    from gui.dialogs import screenshot_viewer_nav as nav

    path = _write_image(tmp_path / "hidden.png")
    reads = []

    def reader(path):
        reads.append(path)
        return QImageReader(path)

    monkeypatch.setattr(nav, "QImageReader", reader)
    page = ScreenshotPage([])
    try:
        page.receive_payload([path])
        qt_application.processEvents()
        assert page.image_paths == (path,)
        assert not page._workers
        assert reads == []
        page.activate()
        _ready(qt_application, page)
        assert reads == [path]
    finally:
        _close(qt_application, page)


def test_screenshot_delete_snapshot_does_not_remove_replaced_same_path(
    qt_application, tmp_path, monkeypatch,
):
    """旧删除队列尚未触及的路径若收到新批次，文件与图库都必须保留新版。"""
    from gui.dialogs import screenshot_viewer_actions as actions

    paths = [_write_image(tmp_path / f"replace-{i}.png") for i in range(2)]
    entered, release = threading.Event(), threading.Event()
    remove = actions.os.remove
    deleted = []

    def slow_remove(path):
        deleted.append(path)
        if path == paths[0]:
            entered.set()
            assert release.wait(2)
        remove(path)

    page = ScreenshotPage(paths)
    try:
        _ready(qt_application, page)
        monkeypatch.setattr(actions.os, "remove", slow_remove)
        page._delete_all_action.trigger()
        assert entered.wait(1)
        _write_image(paths[1], Qt.GlobalColor.red)
        page.receive_payload([paths[1]])
        release.set()
        wait_until(qt_application, lambda: page._delete_worker is None)
        assert deleted == paths[:1]
        assert page.image_paths == (paths[1],)
        assert QImage(paths[1]).pixelColor(0, 0) == Qt.GlobalColor.red
    finally:
        release.set()
        _close(qt_application, page)


def test_screenshot_cache_enforces_pixel_budget_without_global_cache_change():
    """加入新图驱逐旧像素，超大单图不会突破页面缓存预算。"""
    from PySide6.QtGui import QPixmapCache

    from gui.dialogs.screenshot_viewer_tasks import ScreenshotImageCache

    limit = QPixmapCache.cacheLimit()
    cache = ScreenshotImageCache(max_bytes=80)
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    cache.add(("first", 1, 1), image)
    cache.add(("second", 1, 1), image)
    assert cache.image("first").isNull()
    assert not cache.image("second").isNull()
    assert cache.size_bytes == 64
    cache.add(("large", 1, 1), QImage(8, 8, QImage.Format.Format_RGB32))
    assert cache.image("large").isNull()
    assert cache.size_bytes == 64
    assert QPixmapCache.cacheLimit() == limit


def test_screenshot_current_image_is_published_before_slow_neighbor_finishes(
    qt_application, tmp_path, monkeypatch,
):
    """邻图预读仍阻塞时当前图已可见，首图发布不能等待完整预读批次。"""
    from gui.dialogs import screenshot_viewer_nav as nav

    paths = [_write_image(tmp_path / f"neighbor-{i}.png") for i in range(2)]
    entered, release = threading.Event(), threading.Event()

    class Reader:
        def __init__(self, path):
            self.path, self.reader = path, QImageReader(path)

        def read(self):
            if self.path == paths[1]:
                entered.set()
                assert release.wait(2)
            return self.reader.read()

    monkeypatch.setattr(nav, "QImageReader", Reader)
    page = ScreenshotPage(paths)
    try:
        assert entered.wait(1)
        qt_application.processEvents()
        assert page._display_path == paths[0]
        assert page._display_pixmap is not None
        assert page._nav_controller._worker.isRunning()
        assert page.request_dispose() is False
    finally:
        release.set()
        _close(qt_application, page)


def test_screenshot_supervisor_and_dispose_wait_for_native_join(
    qt_application, tmp_path, monkeypatch,
):
    """finished 已发出但原生 join 尚未完成时，监督器不能报告资源已停止。"""
    from gui.dialogs.screenshot_viewer_tasks import ScreenshotReadWorker

    join_ready = threading.Event()
    real_wait = ScreenshotReadWorker.wait

    def delayed_join(worker, timeout):
        return real_wait(worker, timeout) if join_ready.is_set() else False

    monkeypatch.setattr(ScreenshotReadWorker, "wait", delayed_join)
    page = ScreenshotPage([_write_image(tmp_path / "join.png")])
    try:
        wait_until(qt_application, lambda: all(worker.isFinished() for worker in page._workers))
        supervisor = TaskSupervisor()
        (task_id,) = page.register_shutdown_tasks(supervisor, owner_id="test", task_prefix="join")
        assert page.request_dispose() is False
        result = supervisor.stop(task_id, graceful_timeout=0, force_timeout=0)
        assert not result.stopped
        assert not page.is_disposed
        join_ready.set()
        wait_until(qt_application, lambda: page.is_disposed)
        assert supervisor.stop(task_id, graceful_timeout=0, force_timeout=0).stopped
    finally:
        join_ready.set()
        _close(qt_application, page)


def test_screenshot_read_during_delete_does_not_publish_partial_gallery_counts(
    qt_application, tmp_path, monkeypatch,
):
    """删除尚未完成时读取到缺失文件，交由同一删除结果合并而不逐项改变图库。"""
    from PySide6.QtTest import QSignalSpy

    from gui.dialogs import screenshot_viewer_actions as actions

    paths = [_write_image(tmp_path / f"delete-read-{i}.png") for i in range(2)]
    entered, release = threading.Event(), threading.Event()
    remove = actions.os.remove

    def slow_remove(path):
        remove(path)
        if path == paths[0]:
            entered.set()
            assert release.wait(2)

    page = ScreenshotPage(paths)
    try:
        _ready(qt_application, page)
        wait_until(qt_application, lambda: not page._workers)
        changes = QSignalSpy(page.image_count_changed)
        monkeypatch.setattr(actions.os, "remove", slow_remove)
        page._delete_all_action.trigger()
        assert entered.wait(1)
        page._navigate_to(0)
        wait_until(qt_application, lambda: page._nav_controller._worker is None)
        assert page.image_paths == tuple(paths)
        assert changes.count() == 0
        release.set()
        wait_until(qt_application, lambda: page._delete_worker is None)
        assert page.image_paths == ()
        assert changes.count() == 1 and changes.at(0) == [0]
    finally:
        release.set()
        _close(qt_application, page)
