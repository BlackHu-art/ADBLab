"""性能功能归包后保留模块身份、延迟加载与旧路径替换契约。"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PAIRS = (
    ("performance_launcher", "page"),
    ("performance_launcher_form", "form"),
    ("performance_launcher_log", "log"),
    ("performance_launcher_run", "run"),
    ("performance_library", "library"),
    ("performance_result_tasks", "result_tasks"),
)


def _run_import_probe(script, *arguments):
    result = subprocess.run(
        [sys.executable, "-c", script, *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, (
        f"exit code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.mark.parametrize("old_name,new_name", MODULE_PAIRS)
@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_each_module_import_order_preserves_identity(old_name, new_name, old_first):
    _run_import_probe(
        """
import importlib
import sys

old_name, new_name, old_first = sys.argv[1:]
old_path = 'gui.dialogs.' + old_name
new_path = 'gui.features.performance.' + new_name
first, second = (old_path, new_path) if old_first == 'True' else (new_path, old_path)
first_module = importlib.import_module(first)
second_module = importlib.import_module(second)
assert first_module is second_module
assert sys.modules[old_path] is sys.modules[new_path]
assert getattr(importlib.import_module('gui.dialogs'), old_name) is second_module
assert getattr(importlib.import_module('gui.features.performance'), new_name) is second_module
from gui.features.performance import PerformancePage
from gui.dialogs.performance_launcher import PerformancePage as OldPage
from gui.features.performance.page import PerformancePage as NewPage
assert PerformancePage is OldPage is NewPage
""",
        old_name, new_name, str(old_first),
    )


@pytest.mark.parametrize("leaf", ["", "result_tasks"], ids=["package-only", "leaf-first"])
def test_performance_imports_page_only_when_requested(leaf):
    _run_import_probe(
        """
import importlib
import sys

package = importlib.import_module('gui.features.performance')
if sys.argv[1]:
    importlib.import_module('gui.features.performance.' + sys.argv[1])
assert 'gui.features.performance.page' not in sys.modules
assert 'gui.dialogs.performance_launcher' not in sys.modules
assert 'gui.dialogs.performance_result_tasks' not in sys.modules
assert not any(name.startswith(('gui.features.app_manager.', 'gui.features.file_explorer.'))
               for name in sys.modules)
try:
    package.unknown_attribute
except AttributeError:
    pass
else:
    raise AssertionError('unknown package attribute must raise AttributeError')
assert 'gui.features.performance.page' not in sys.modules
from gui.features.performance import PerformancePage
assert PerformancePage is importlib.import_module('gui.features.performance.page').PerformancePage
""",
        leaf,
    )


@pytest.mark.ui
def test_old_page_package_worker_patch_is_used(qt_application, monkeypatch):
    from gui.features.performance import PerformancePage
    from gui.features.performance.page import CurrentPackageWorker

    class HeldPackageWorker(CurrentPackageWorker):
        def start(self):
            self.start_requested = True

    monkeypatch.setattr("gui.dialogs.performance_launcher.CurrentPackageWorker", HeldPackageWorker)
    page = PerformancePage(device_ip="synthetic-device")
    try:
        page.fetch_current_package()
        worker = page._package_worker
        assert isinstance(worker, HeldPackageWorker)
        assert worker.start_requested
        assert worker.device_ip == "synthetic-device"
        assert worker.parent() is None
        assert not page.get_package_btn.isEnabled()
        page.fetch_current_package()
        assert page._package_worker is worker
    finally:
        if page._package_worker is not None:
            page._on_package_worker_finished(page._package_worker)
        assert page.request_dispose()
        page.close()
        page.deleteLater()
        qt_application.processEvents()


@pytest.mark.ui
def test_old_run_and_result_worker_patch_is_used(qt_application, monkeypatch, tmp_path):
    from gui.features.performance import PerformancePage
    from gui.features.performance.result_tasks import PerformanceResultWorker
    from gui.features.performance.run import PerformanceStartWorker
    from services.performance.results import PerformanceArtifacts
    from tests.ui_geometry_helpers import wait_until

    class HeldStartWorker(PerformanceStartWorker):
        def start(self):
            self.start_requested = True

    class HeldResultWorker(PerformanceResultWorker):
        def start(self):
            self.start_requested = True

    monkeypatch.setattr(
        "gui.dialogs.performance_launcher_run.PerformanceStartWorker", HeldStartWorker,
    )
    monkeypatch.setattr(
        "gui.dialogs.performance_result_tasks.PerformanceResultWorker", HeldResultWorker,
    )
    page = PerformancePage("synthetic-device", "com.example.synthetic")
    page.save_path_edit.setText(str(tmp_path))
    run = page._run_controller
    loader = page._result_loader
    config = page.build_config()
    monkeypatch.setattr(page, "build_config", lambda: config)
    try:
        run.start_mobileperf()
        start_worker = run._start_worker
        assert isinstance(start_worker, HeldStartWorker)
        assert start_worker.start_requested
        assert start_worker.config is config
        assert start_worker.runner is page._runner
        assert start_worker.parent() is run
        assert run._generation == 1
        assert page._configuration_locked
        run.start_mobileperf()
        assert run._start_worker is start_worker
        assert run._generation == 1

        run.cancel_start()
        run._finish_start()
        assert run._start_worker is None
        assert not page._configuration_locked

        loader.invalidate()
        generation = loader.generation
        query = SimpleNamespace(discover=lambda: PerformanceArtifacts())
        loader.submit(query, exit_code=7, had_config=False, cancelled_run=True,
                      present_result=False)
        result_worker = loader._workers[0]
        assert isinstance(result_worker, HeldResultWorker)
        assert result_worker.start_requested
        assert result_worker.query is query
        assert result_worker.generation == generation
        assert result_worker.parent() is loader
        assert result_worker.exit_code == 7
        assert not result_worker.had_config
        assert result_worker.cancelled_run
        assert not result_worker.present_result
        result_worker.artifacts_ready.emit()
        wait_until(qt_application, lambda: result_worker.artifacts_delivered)
        loader._poll()
        assert not loader._workers
    finally:
        if run._start_worker is not None:
            run.cancel_start()
            run._finish_start()
        for pending in tuple(loader._workers):
            pending.abort()
            pending.artifacts_ready.emit()
        qt_application.processEvents()
        loader._poll()
        assert page.request_dispose()
        page.close()
        page.deleteLater()
        qt_application.processEvents()


def test_performance_service_types_keep_identity():
    from gui.dialogs import performance_launcher as old_page
    from gui.dialogs import performance_launcher_form as old_form
    from gui.features.performance import form, library, page, result_tasks, run
    from services.mobileperf_runner import MobilePerfRunner
    from services.performance.config import MobilePerfMonkeyConfig, MobilePerfRunConfig
    from services.performance.results import PerformanceArtifacts

    assert page.MobilePerfRunConfig is library.MobilePerfRunConfig is MobilePerfRunConfig
    assert form.MobilePerfMonkeyConfig is MobilePerfMonkeyConfig
    assert run.PerformanceArtifacts is result_tasks.PerformanceArtifacts is PerformanceArtifacts
    assert page.MobilePerfRunner is MobilePerfRunner
    assert old_page.CONFIG_HINTS is page.CONFIG_HINTS is old_form.CONFIG_HINTS is form.CONFIG_HINTS
    assert (old_page.MONKEY_PERCENT_FIELDS is page.MONKEY_PERCENT_FIELDS
            is old_form.MONKEY_PERCENT_FIELDS is form.MONKEY_PERCENT_FIELDS)
