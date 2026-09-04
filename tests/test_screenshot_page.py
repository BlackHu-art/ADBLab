import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QDialog, QWidget

from gui.features.media import ScreenshotPage


def _write_image(path, color: Qt.GlobalColor) -> str:
    image = QPixmap(48, 32)
    image.fill(color)
    assert image.save(str(path))
    return str(path)


def test_screenshot_page_is_plain_widget_and_incrementally_appends_batches(
    qt_application,
    tmp_path,
):
    first = _write_image(tmp_path / "first.png", Qt.GlobalColor.red)
    second = _write_image(tmp_path / "second.png", Qt.GlobalColor.green)
    page = ScreenshotPage([first])
    try:
        assert isinstance(page, QWidget)
        assert not isinstance(page, QDialog)

        page.activate({"paths": [first, second]})

        assert page._image_paths == [first, second]
        assert page._current_path() == second
        assert page._nav_label.text() == "2 / 2"

        page.deactivate("navigation")
        page.activate([second])

        assert page._image_paths == [first, second]
        assert page._current_path() == second
    finally:
        page.close()


def test_screenshot_page_requires_second_delete_click_and_keeps_empty_page_open(
    qt_application,
    tmp_path,
):
    path = _write_image(tmp_path / "last.png", Qt.GlobalColor.blue)
    parent = QWidget()
    page = ScreenshotPage([path], parent=parent)
    parent.show()
    page.show()
    qt_application.processEvents()
    try:
        page._delete_file()

        assert os.path.exists(path)
        assert page._image_paths == [path]
        assert page._pending_delete_path == path
        assert "confirm" in page._delete_btn.toolTip().lower()

        page._delete_file()

        assert not os.path.exists(path)
        assert page._image_paths == []
        assert page._nav_label.text() == "0 / 0"
        assert page._info_label.text() == "No screenshot available"
        assert page.isVisible()
        assert parent.isVisible()
    finally:
        parent.close()


def test_screenshot_page_lifecycle_preserves_navigation_state_until_dispose(
    qt_application,
    tmp_path,
):
    path = _write_image(tmp_path / "shot.png", Qt.GlobalColor.cyan)
    page = ScreenshotPage([path])
    try:
        page.activate()
        page.deactivate("overview")

        assert page._image_paths == [path]
        assert page.property("deactivation_reason") == "overview"
        assert page.register_shutdown_tasks(
            object(),
            owner_id="test-owner",
            task_prefix="screenshot",
        ) == ()

        assert page.request_dispose("application_shutdown") is True
        assert page.is_disposed is True
        assert page._image_paths == []
        assert page.request_dispose("application_shutdown") is True
    finally:
        page.close()


def test_screenshot_page_escape_requests_back_navigation_without_closing(
    qt_application,
):
    page = ScreenshotPage([])
    back_spy = QSignalSpy(page.back_requested)
    try:
        page.show()
        page.setFocus()
        qt_application.processEvents()

        QTest.keyClick(page, Qt.Key.Key_Escape)
        qt_application.processEvents()

        assert back_spy.count() == 1
        assert page.isVisible()
        assert page.is_disposed is False
    finally:
        page.close()
