"""截图目录归位保留公开模块、旧替换接缝和页面独占资源。"""

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = {
    "actions": ("ScreenshotViewerActions",),
    "nav": ("ScreenshotViewerNav", "MIN_ZOOM", "MAX_ZOOM", "ZOOM_STEP"),
    "tasks": (
        "ImageKey", "ScreenshotIOShutdownTask", "ScreenshotImageCache",
        "ScreenshotReadWorker", "ScreenshotDeleteWorker", "ScreenshotValidateWorker",
    ),
    "ui": ("ScreenshotViewerUI",),
    "widgets": (
        "ScreenshotImageDelegate", "ScreenshotFlipView", "ScreenshotPipsPager",
        "ScreenshotDetailsBar", "_navigation_target",
    ),
}
STATIC_EXPORTS = {
    "actions": (
        *SYMBOLS["actions"], "ScreenshotDeleteWorker", "ScreenshotValidateWorker",
        "ProcessRunner", "QImageReader", "QFileDialog", "QApplication", "show_toast", "os", "sys",
    ),
    "nav": (
        *SYMBOLS["nav"], "ImageKey", "ScreenshotImageCache", "ScreenshotReadWorker",
        "QImageReader", "os",
    ),
    "tasks": (*SYMBOLS["tasks"], "QThread", "QImage", "raster_image_reader", "os"),
    "ui": SYMBOLS["ui"],
    "widgets": SYMBOLS["widgets"],
}


@pytest.mark.parametrize("leaf", SYMBOLS)
@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_each_media_module_import_order_preserves_identity(leaf, old_first):
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib
import sys

leaf, old_first, *symbols = sys.argv[1:]
old_path = 'gui.dialogs.screenshot_viewer_' + leaf
new_path = 'gui.features.media.' + leaf
first, second = (old_path, new_path) if old_first == 'True' else (new_path, old_path)
first_module = importlib.import_module(first)
second_module = importlib.import_module(second)
assert first_module is second_module
assert sys.modules[old_path] is sys.modules[new_path]
assert getattr(importlib.import_module('gui.dialogs'), 'screenshot_viewer_' + leaf) is second_module
assert getattr(importlib.import_module('gui.features.media'), leaf) is second_module
for name in symbols:
    assert getattr(sys.modules[old_path], name) is getattr(sys.modules[new_path], name)
""", leaf, str(old_first), *SYMBOLS[leaf]],
        cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, f"exit={result.returncode}\n{result.stdout}{result.stderr}"


def test_media_public_entry_keeps_real_globals():
    from gui.features import media

    assert media.__all__ == ["ScreenshotPage"]
    assert media.ScreenshotPage.__module__ == "gui.features.media"
    for name in ("_start_io_worker", "_reap_io_workers", "register_shutdown_tasks"):
        assert getattr(media.ScreenshotPage, name).__globals__ is vars(media)
    source = Path(media.__file__)
    assert source.name == "__init__.py"
    assert any(
        isinstance(node, ast.ClassDef) and node.name == "ScreenshotPage"
        for node in ast.parse(source.read_text(encoding="utf-8")).body
    )


def _write_image(path):
    from PySide6.QtGui import QImage

    image = QImage(32, 48, QImage.Format.Format_RGB32)
    image.fill(0xFF3355AA)
    assert image.save(str(path))
    return str(path)


def _close_page_with_held_workers(page, app, held):
    from PySide6.QtCore import QCoreApplication, QEvent

    from tests.screenshot_helpers import close_screenshot_page

    for worker in held:
        assert not worker.isRunning()
        worker.abort()
        page._workers.discard(worker)
        if page._nav_controller._worker is worker:
            page._nav_controller._worker = None
        if page._add_worker is worker:
            page._add_worker = None
        if page._delete_worker is worker:
            page._delete_worker = None
        worker.deleteLater()
    close_screenshot_page(page)
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.mark.ui
def test_old_nav_worker_and_reader_patch_reaches_navigation(qt_application, tmp_path, monkeypatch):
    from gui.dialogs import screenshot_viewer_nav as nav
    from gui.features.media import ScreenshotPage

    held = []

    class HeldReadWorker(nav.ScreenshotReadWorker):
        def start(self):
            self.start_requested = True
            held.append(self)

    reader = object()
    monkeypatch.setattr(nav, "ScreenshotReadWorker", HeldReadWorker)
    monkeypatch.setattr(nav, "QImageReader", reader)
    paths = tuple(_write_image(tmp_path / f"nav-{i}.png") for i in range(3))
    page = ScreenshotPage([])
    try:
        page.activate({"paths": paths, "current_index": 1})
        worker = page._nav_controller._worker
        assert isinstance(worker, HeldReadWorker)
        assert worker.reader_factory is reader
        assert worker.paths == (paths[1], paths[0], paths[2])
        assert worker.parent() is page
        assert worker in page._workers
        assert worker.start_requested
    finally:
        _close_page_with_held_workers(page, qt_application, held)


@pytest.mark.ui
def test_old_actions_worker_and_reader_patch_reaches_add(qt_application, tmp_path, monkeypatch):
    from gui.dialogs import screenshot_viewer_actions as actions
    from gui.features.media import ScreenshotPage

    held = []

    class HeldValidateWorker(actions.ScreenshotValidateWorker):
        def start(self):
            self.start_requested = True
            held.append(self)

    paths = tuple(_write_image(tmp_path / f"add-{i}.png") for i in range(2))
    reader = object()
    monkeypatch.setattr(actions, "ScreenshotValidateWorker", HeldValidateWorker)
    monkeypatch.setattr(actions, "QImageReader", reader)
    monkeypatch.setattr(actions.QFileDialog, "getOpenFileNames", lambda *_: (list(paths), ""))
    page = ScreenshotPage([])
    try:
        page._add_images()
        worker = page._add_worker
        assert isinstance(worker, HeldValidateWorker)
        assert worker.paths == paths
        assert worker.reader_factory is reader
        assert worker.parent() is page
        assert worker in page._workers
        assert worker.start_requested
        page._add_images()
        assert page._add_worker is worker
        assert held == [worker]
    finally:
        _close_page_with_held_workers(page, qt_application, held)


@pytest.mark.ui
def test_old_actions_worker_patch_reaches_delete_snapshot(qt_application, tmp_path, monkeypatch):
    from gui.dialogs import screenshot_viewer_actions as actions
    from tests.screenshot_helpers import make_screenshot_page

    held = []

    class HeldDeleteWorker(actions.ScreenshotDeleteWorker):
        def start(self):
            self.start_requested = True
            held.append(self)

    paths = tuple(_write_image(tmp_path / f"delete-{i}.png") for i in range(3))
    page = make_screenshot_page(paths[:2])
    monkeypatch.setattr(actions, "ScreenshotDeleteWorker", HeldDeleteWorker)
    try:
        versions = dict(page._path_versions)
        page._delete_all_files()
        worker = page._delete_worker
        assert isinstance(worker, HeldDeleteWorker)
        assert worker.paths == paths[:2]
        assert worker.versions == versions
        assert worker.versions is not page._path_versions
        assert worker.parent() is page
        assert worker in page._workers
        assert worker.start_requested
        page.receive_payload({"paths": paths[2:], "focus_new": False})
        page._delete_all_files()
        assert page._delete_worker is worker
        assert held == [worker]
        assert worker.paths == paths[:2]
        assert worker.versions == versions
        assert page.image_paths == paths
        assert all(Path(path).exists() for path in paths)
    finally:
        _close_page_with_held_workers(page, qt_application, held)


@pytest.mark.ui
def test_media_shutdown_factory_patch_is_used_at_registration(qt_application, monkeypatch):
    from gui.features import media

    page = media.ScreenshotPage([])
    worker = media.ScreenshotValidateWorker((), object(), page)
    handle = SimpleNamespace(request_stop=object(), wait=object(), is_running=object())
    snapshots, registrations = [], []

    def factory(workers):
        snapshots.append(workers)
        return handle

    def register(task_id, **kwargs):
        registrations.append((task_id, kwargs))

    monkeypatch.setattr(media, "ScreenshotIOShutdownTask", factory)
    page._workers.add(worker)
    try:
        assert page.register_shutdown_tasks(
            SimpleNamespace(register=register), owner_id="media-owner", task_prefix="close-7",
        ) == ("close-7-screenshot-io",)
        assert snapshots == [[worker]]
        assert snapshots[0] is not page._workers
        assert registrations == [("close-7-screenshot-io", {
            "owner_id": "media-owner", "kind": "screenshot_io",
            "request_stop": handle.request_stop, "wait": handle.wait,
            "is_running": handle.is_running,
        })]
    finally:
        _close_page_with_held_workers(page, qt_application, [worker])


def test_media_sources_keep_static_internal_imports_and_exports():
    package = ROOT / "gui/features/media"
    assert package.is_dir()
    assert not (ROOT / "gui/features/media.py").exists()
    for leaf, exports in STATIC_EXPORTS.items():
        shim = ast.parse((ROOT / f"gui/dialogs/screenshot_viewer_{leaf}.py").read_text("utf-8"))
        assert any(
            isinstance(node, ast.ImportFrom) and node.module == "gui.features.media"
            and any(alias.name == leaf and alias.asname == "_implementation"
                    for alias in node.names)
            for node in shim.body
        )
        guarded = [node for node in shim.body if isinstance(node, ast.If)
                   and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"]
        assert len(guarded) == 1
        static = {
            alias.name for node in guarded[0].body if isinstance(node, ast.ImportFrom)
            and node.module == f"gui.features.media.{leaf}"
            for alias in node.names if alias.name == alias.asname
        }
        assert set(exports) <= static
    page_definitions = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        page_definitions.extend(path.name for node in tree.body
                                if isinstance(node, ast.ClassDef) and node.name == "ScreenshotPage")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("gui.dialogs.screenshot_viewer_")
            if isinstance(node, ast.Name):
                assert node.id not in {"__file__", "ModuleType"}
            if isinstance(node, ast.FunctionDef):
                assert node.name != "__getattr__"
    assert page_definitions == ["__init__.py"]
    widgets = ast.parse((package / "widgets.py").read_text("utf-8"))
    page_imports = [node for node in ast.walk(widgets) if isinstance(node, ast.ImportFrom)
                    and any(alias.name == "ScreenshotPage" for alias in node.names)]
    assert len(page_imports) == 1
    guarded_imports = [node for guard in widgets.body if isinstance(guard, ast.If)
                       and isinstance(guard.test, ast.Name) and guard.test.id == "TYPE_CHECKING"
                       for node in guard.body]
    assert page_imports[0] in guarded_imports
    assert page_imports[0].level == 1 and page_imports[0].module is None
