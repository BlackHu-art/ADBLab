"""应用管理关闭后必须同时释放原生图标和 Python 引擎，不能在进程收尾时崩溃。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.ui


@pytest.mark.integration
@pytest.mark.parametrize("module", [
    "test_app_manager_header_sort.py",
    "test_app_manager_metadata.py",
])
def test_app_manager_sessions_exit_after_native_and_python_cleanup(tmp_path, module):
    """已有交互回归的断言全绿后，进程 GC 仍必须正常结束。"""
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    for name in (
        "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "LOCALAPPDATA", "APPDATA",
    ):
        directory = tmp_path / name.lower()
        directory.mkdir()
        environment[name] = str(directory)
    environment.update(
        QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="", PYTHONFAULTHANDLER="1",
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
         str(root / "tests" / module)],
        cwd=root, env=environment, text=True, capture_output=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "passed" in completed.stdout


def test_app_manager_preserves_live_icons_until_worker_release(qt_application):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    from qfluentwidgets import CommandButton, PushButton

    from gui.dialogs.app_manager import AppManagerPage
    from gui.styles import BaseStyles

    class PendingWorker:
        running = True

        def isRunning(self):
            return self.running

        def abort(self):
            pass

    page = AppManagerPage()
    worker = PendingWorker()
    page._workers.append(worker)
    buttons = [page.view_toggle, page.refresh_btn, page.retry_btn]
    buttons.extend(button for button in page._command_bar.findChildren(CommandButton)
                   if button.action() is not None)
    buttons.extend(button for button in page.details_page.findChildren(PushButton)
                   if not button.icon().isNull())
    try:
        images = []
        for theme in ("Light", "Dark"):
            BaseStyles.switch_theme(theme)
            rendered = []
            for button in buttons:
                # 检查实际控件当前的图标，兼容原生 QAction 随主题重新绑定。
                icon = button.icon()
                pixmap = icon.pixmap(QSize(24, 24), 2.0)
                assert not pixmap.isNull()
                assert pixmap.width() == 48 and pixmap.devicePixelRatio() == 2.0
                rendered.append(pixmap.toImage())
                assert not icon.pixmap(24, 24, QIcon.Mode.Disabled).isNull()
            images.append(rendered)
        assert all(light != dark for light, dark in zip(*images, strict=True))
        assert page.request_dispose() is False
        assert all(not button.icon().isNull() for button in buttons)
        worker.running = False
        page._maybe_finish_dispose()
        assert page._dispose_finalized
    finally:
        worker.running = False
        page.close()
