import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QDialog, QFrame, QWidget
from qfluentwidgets import FluentIcon

from gui.features.media import ScreenshotPage
from gui.pages.workspace_features import WorkspaceFeatureHost
from tests.ui_geometry_helpers import wait_for_stable_geometry


def _write_image(path, color: Qt.GlobalColor) -> str:
    image = QPixmap(48, 32)
    image.fill(color)
    assert image.save(str(path))
    return str(path)


@pytest.mark.parametrize("with_image", [False, True], ids=["empty", "loaded"])
def test_screenshot_workspace_preparation_releases_header_space_without_resetting_content(
    qt_application, tmp_path, with_image,
):
    """嵌入钩子隐藏整组重复页头，空态与有图态均把空间留给原画布。"""

    paths = [_write_image(tmp_path / "shot.png", Qt.GlobalColor.blue)] if with_image else []
    page = ScreenshotPage(paths)
    canvas = page.findChild(QFrame, "canvasFrame")
    assert canvas is not None
    try:
        page.resize(760, 600)
        page.show()
        wait_for_stable_geometry(qt_application, (page, page.header_card, canvas))
        assert page.header_card.isVisibleTo(page)
        assert page.dialog_title.isVisibleTo(page)
        assert page.dialog_subtitle.isVisibleTo(page)
        assert page.status_badge.isVisibleTo(page)
        original_canvas_height = canvas.height()
        header_height = page.header_card.height()
        count_changes = QSignalSpy(page.image_count_changed)
        original_scene = page._scene

        page.prepare_for_workspace()
        page.prepare_for_workspace()
        page._apply_theme()
        wait_for_stable_geometry(qt_application, (page, canvas, page._bottom_dock))

        assert page.header_card.isHidden()
        assert not page.dialog_title.isVisibleTo(page)
        assert not page.dialog_subtitle.isVisibleTo(page)
        assert not page.status_badge.isVisibleTo(page)
        assert canvas.y() == page.layout().contentsMargins().top()
        assert canvas.height() >= original_canvas_height + header_height
        assert page._bottom_dock.isVisibleTo(page)
        assert page._scene is original_scene
        assert page.image_paths == tuple(paths)
        assert count_changes.count() == 0
        assert page._nav_label.text() == ("1 / 1" if with_image else "0 / 0")
        assert page._copy_btn.isEnabled() is with_image
    finally:
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def test_screenshot_workspace_entry_hides_header_and_reuses_the_result_page(qt_application):
    """真实宿主入口调用页面的嵌入钩子，往返导航不重新显示重复标题。"""

    host = WorkspaceFeatureHost("apps", "应用概览", QWidget())
    host.register_feature(
        "media", "截图结果", FluentIcon.PHOTO, lambda _key: ScreenshotPage([]),
        requires_device=False,
    )
    try:
        host.resize(760, 600)
        host.show()
        assert host.open_feature("media")
        page = host.stack.currentWidget()
        assert isinstance(page, ScreenshotPage)
        qt_application.processEvents()
        assert page.header_card.isHidden()
        assert page._view.isVisibleTo(host)
        assert page._bottom_dock.isVisibleTo(host)

        assert host.show_overview()
        assert host.open_feature("media")
        assert host.stack.currentWidget() is page
        assert page.header_card.isHidden()
        assert not page.is_disposed
    finally:
        host.shutdown()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(host, QEvent.Type.DeferredDelete)


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


def test_screenshot_copy_notifies_without_replacing_current_image_metadata(
    qt_application, tmp_path, monkeypatch,
):
    """复制成功使用完整结果提示，底栏保留当前图信息，导航后也不恢复旧内容。"""

    from gui.dialogs import screenshot_viewer_actions as actions

    first = _write_image(tmp_path / "first.png", Qt.GlobalColor.red)
    second = _write_image(tmp_path / "second.png", Qt.GlobalColor.blue)
    notices = []
    monkeypatch.setattr(
        actions, "show_toast", lambda *args, **kwargs: notices.append((args, kwargs)),
        raising=False,
    )
    page = ScreenshotPage([first, second])
    try:
        page.show()
        metadata = page._info_label.text()
        page.copy_to_clipboard()

        assert qt_application.clipboard().pixmap().toImage() == QPixmap(first).toImage()
        assert page._info_label.text() == metadata
        assert page._info_label.toolTip() == metadata
        assert len(notices) == 1
        args, options = notices[0]
        assert args[0] is page
        assert args[2] == "Image copied"
        assert options["duration"] is None
        page.navigate_next()
        assert page._current_path() == second
        assert page._info_label.text() == page._info_label.toolTip()
    finally:
        page.close()


def test_screenshot_delete_confirmation_notifies_full_text_and_still_requires_second_click(
    qt_application, tmp_path, monkeypatch,
):
    """长确认提示完整交给 Toast，首次点击只确认意图，不能提前删除文件。"""

    from gui.dialogs import screenshot_viewer_actions as actions

    path = _write_image(tmp_path / "confirm.png", Qt.GlobalColor.green)
    confirmation = "请再次点击删除以确认删除这张截图。" * 12
    notices = []
    original_tr = actions.tr
    monkeypatch.setattr(
        actions, "tr",
        lambda text: confirmation if text == "Click Delete again to confirm" else original_tr(text),
    )
    monkeypatch.setattr(
        actions, "show_toast", lambda *args, **kwargs: notices.append((args, kwargs)),
        raising=False,
    )
    page = ScreenshotPage([path])
    try:
        page.show()
        metadata = page._info_label.text()
        page._delete_file()

        assert os.path.exists(path)
        assert page._pending_delete_path == path
        assert page._delete_confirm_timer.isActive()
        assert page._info_label.text() == metadata
        args, options = notices[0]
        assert args[2] == confirmation
        assert options["duration"] == page.DELETE_CONFIRM_TIMEOUT_MS

        page._delete_file()
        assert not os.path.exists(path)
        assert page._image_paths == []
    finally:
        page.close()


def test_screenshot_delete_error_notifies_complete_message_and_preserves_file(
    qt_application, tmp_path, monkeypatch,
):
    """删除失败通过非阻塞错误提示返回完整异常，保留截图并重置确认意图。"""

    from gui.dialogs import screenshot_viewer_actions as actions
    from gui.dialogs.fluent_dialog import FluentMessageBox

    path = _write_image(tmp_path / "cannot-delete.png", Qt.GlobalColor.cyan)
    error_text = "无法删除截图：文件正在使用。\n" + str(tmp_path / ("long-name-" * 15 + ".png"))
    notices, dialogs = [], []
    monkeypatch.setattr(
        actions, "show_toast", lambda *args, **kwargs: notices.append((args, kwargs)),
        raising=False,
    )
    monkeypatch.setattr(
        FluentMessageBox, "warning", lambda *args: dialogs.append(args),
    )

    def fail_remove(_path):
        raise PermissionError(error_text)

    monkeypatch.setattr(actions.os, "remove", fail_remove)
    page = ScreenshotPage([path])
    try:
        page.show()
        page._delete_file()
        page._delete_file()

        assert dialogs == []
        assert os.path.exists(path)
        assert page._image_paths == [path]
        assert page._pending_delete_path == ""
        assert not page._delete_confirm_timer.isActive()
        args, options = notices[-1]
        assert args == (page, "Delete Failed", error_text)
        assert options["level"] == "error"
    finally:
        page.close()


@pytest.mark.parametrize("reset", ["expired", "navigation"])
def test_screenshot_delete_confirmation_notice_closes_when_intent_expires(
    qt_application, tmp_path, monkeypatch, reset,
):
    """提示悬停可以延长阅读，但删除意图结束后不得继续显示失效确认。"""

    from gui.dialogs import screenshot_viewer_actions as actions

    first = _write_image(tmp_path / "first.png", Qt.GlobalColor.red)
    second = _write_image(tmp_path / "second.png", Qt.GlobalColor.blue)
    notices = []

    def show_notice(parent, *_args, **_kwargs):
        notice = QWidget(parent)
        notice.show()
        notices.append(notice)
        return notice

    monkeypatch.setattr(actions, "show_toast", show_notice)
    page = ScreenshotPage([first, second])
    try:
        page.show()
        page._delete_file()
        assert notices[0].isVisible()
        assert page._pending_delete_path == first

        if reset == "expired":
            page._delete_confirm_timer.timeout.emit()
        else:
            page.navigate_next()

        assert not notices[0].isVisible()
        assert not page._delete_confirm_timer.isActive()
        assert page._pending_delete_path == ""
        assert os.path.exists(first)
    finally:
        page.close()
