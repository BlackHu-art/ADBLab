"""截图交互测试按实际后台加载状态等待，不假设构造或点击同步读取文件。"""

from PySide6.QtWidgets import QApplication

from gui.features.media import ScreenshotPage
from tests.ui_geometry_helpers import wait_until


def wait_for_screenshot(page):
    app = QApplication.instance()
    wait_until(app, lambda: (
        not page._workers and not page._nav_controller._pending
        and (not page.image_paths or (
            page._display_pixmap is not None and page._display_path == page._current_path()
        ))
    ))


def make_screenshot_page(*args, **kwargs):
    page = ScreenshotPage(*args, **kwargs)
    page.activate()
    wait_for_screenshot(page)
    return page


def close_screenshot_page(page):
    page.request_dispose("test")
    wait_until(QApplication.instance(), lambda: page.is_disposed)
    page.close()
