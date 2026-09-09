"""文件页嵌入标题、图标类型列及保留的浏览语义回归。"""

import os
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation, QSize, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea, QStyleOptionViewItem
from qfluentwidgets import CommandBar, RoundMenu

from gui.features.file_explorer import FileExplorerPage
from gui.styles import BaseStyles
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry, wait_until

LISTING = "\n".join([
    "drwxr-xr-x 2 shell shell 4096 Sep 05 Documents",
    "-rw-r--r-- 1 shell shell 2048 Sep 05 sample.apk",
    "-rw-r--r-- 1 shell shell 4096 Sep 05 demo.png",
    "-rw-r--r-- 1 shell shell 1024 Sep 05 notes.txt",
])


@pytest.fixture
def file_menu_page(qt_application, monkeypatch, tmp_path):
    """保留真实页面、菜单及结果连接，仅截住外部传输和系统保存窗口。"""
    submitted = []
    for worker_type in ("ADBWorker", "TransferWorker"):
        monkeypatch.setattr(
            f"models.file_explorer_worker.{worker_type}.start",
            lambda worker: submitted.append(worker),
        )
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.FileExplorerOps._global_save_dir",
        staticmethod(lambda: str(tmp_path)),
    )
    monkeypatch.setattr(
        "gui.dialogs.file_explorer_ops.QFileDialog.getSaveFileName",
        lambda _parent, _title, path: (path, ""),
    )
    page = FileExplorerPage(device_ip="demo-a")
    page.resize(900, 700)
    page._on_ls_result(LISTING, False)
    page.show()
    qt_application.processEvents()
    try:
        yield page, submitted
    finally:
        page.close()
        qt_application.processEvents()


def _open_file_menu(page, name, qt_application):
    row = next(row for row in range(page.table.rowCount()) if page._file_name_at(row) == name)
    point = page.table.visualItemRect(page.table.item(row, page.NAME_COL)).center()
    QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    menus = [menu for menu in page.findChildren(RoundMenu) if menu.isVisible()]
    assert len(menus) == 1
    menu = menus[0]
    wait_until(
        qt_application, lambda: menu.aniManager.ani.state() == QAbstractAnimation.State.Stopped,
    )
    return menu


@pytest.mark.parametrize("name, action_index", [
    ("notes.txt", 0), ("sample.apk", 0), ("notes.txt", 1), ("demo.png", 1),
])
@pytest.mark.parametrize("failed", [False, True])
def test_file_double_click_menu_reaches_transfer_or_inline_preview(
    file_menu_page, qt_application, tmp_path, name, action_index, failed,
):
    page, submitted = file_menu_page
    menu = _open_file_menu(page, name, qt_application)
    assert menu.view.count() == (1 if name == "sample.apk" else 2)
    assert submitted == []
    point = menu.view.visualItemRect(menu.view.item(action_index)).center()
    QTest.mouseClick(menu.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert len(submitted) == 1
    worker = submitted[0]
    assert worker.device_ip == "demo-a"
    remote_path = f"/storage/emulated/0/{name}"
    if action_index == 0:
        assert worker.args == ["pull", remote_path, str(tmp_path / name)]
        worker.result_ready.emit("permission denied" if failed else "OK", failed, worker.args[-1])
        qt_application.processEvents()
        assert len(submitted) == (1 if failed else 2)  # 只有下载成功才刷新目录。
        if failed:
            assert "permission denied" in page.status_bar.text()
        else:
            assert page._directory_loading
            assert submitted[1].args[0] == "shell"
            assert shlex.split(submitted[1].args[1]) == ["ls", "-la", "/storage/emulated/0", "2>&1"]
    elif name == "notes.txt":
        assert worker.args[0] == "shell"
        assert shlex.split(worker.args[1]) == ["head", "-c", "2097153", remote_path]
        worker.result_ready.emit("permission denied" if failed else "file contents", failed)
        qt_application.processEvents()
        expected = page.preview_output if failed else page.preview_text_page
        assert page.preview_stack.currentWidget() is expected
        if not failed:
            assert page.preview_text_edit.toPlainText() == "file contents"
    else:
        assert worker.args[:2] == ["pull", remote_path]
        local_path = worker.args[-1]
        image = QPixmap(24, 16)
        image.fill(Qt.GlobalColor.blue)
        assert image.save(local_path)
        worker.result_ready.emit("permission denied" if failed else "OK", failed, local_path)
        qt_application.processEvents()
        expected = page.preview_output if failed else page.preview_image
        assert page.preview_stack.currentWidget() is expected
        if not failed:
            assert not page.preview_image._source_pixmap.isNull()
        assert not Path(local_path).exists()
    if failed and action_index == 1:
        assert page.preview_output.property("previewError")
        assert "permission denied" in page.preview_output.toPlainText()


@pytest.mark.parametrize("action_index", [0, 1])
@pytest.mark.parametrize("revoke", ["selection", "close"])
def test_file_double_click_menu_rechecks_admission_after_open(
    file_menu_page, qt_application, action_index, revoke,
):
    page, submitted = file_menu_page
    menu = _open_file_menu(page, "notes.txt", qt_application)
    action = menu.view.item(action_index).data(Qt.ItemDataRole.UserRole)
    if revoke == "selection":
        page.set_device_selected(False)
    else:
        page.close()
    action.trigger()
    assert submitted == []


def test_file_double_click_menu_dismissal_does_not_start_work(file_menu_page, qt_application):
    page, submitted = file_menu_page
    menu = _open_file_menu(page, "notes.txt", qt_application)
    menu.close()
    assert submitted == []


def test_file_double_click_menu_cancel_save_does_not_download(
    file_menu_page, qt_application, monkeypatch,
):
    page, submitted = file_menu_page
    save_dialog = Mock(return_value=("", ""))
    monkeypatch.setattr("gui.dialogs.file_explorer_ops.QFileDialog.getSaveFileName", save_dialog)
    menu = _open_file_menu(page, "notes.txt", qt_application)
    menu.view.item(0).data(Qt.ItemDataRole.UserRole).trigger()
    save_dialog.assert_called_once()
    assert submitted == []


@pytest.mark.integration
def test_file_explorer_lifecycle_process_exits_cleanly(tmp_path):
    """覆盖断言已完成、解释器释放图标时仍可能崩溃的独立进程边界。"""
    environment = dict(os.environ)
    environment.update(
        QT_QPA_PLATFORM="offscreen",
        PYTHONUTF8="1",
        PYTHONFAULTHANDLER="1",
        LOCALAPPDATA=str(tmp_path / "profile"),
        XDG_CONFIG_HOME=str(tmp_path / "profile"),
        MOBILEPERF_LOG_DIR=str(tmp_path / "mobileperf-logs"),
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_model_media_adb.py",
         "-k", "file_explorer"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout


def _paint_option(page, row, column):
    option = QStyleOptionViewItem()
    page.table.itemDelegate().initStyleOption(option, page.table.model().index(row, column))
    return option


def _icon_lightness(icon):
    pixels = icon.pixmap(QSize(24, 24)).toImage()
    colors = [
        pixels.pixelColor(x, y)
        for x in range(pixels.width())
        for y in range(pixels.height())
        if pixels.pixelColor(x, y).alpha() >= 128
    ]
    assert len(colors) >= 8, "图标必须具有实际可见的前景像素"
    return sum(color.lightnessF() for color in colors) / len(colors)


def test_file_explorer_theme_round_trip_refreshes_icons_without_replacing_rows(qt_application):
    BaseStyles.switch_theme("Light")
    page = FileExplorerPage(device_ip="demo-a")
    page._on_ls_result(LISTING, False)
    page.show()
    row = next(row for row in range(page.table.rowCount())
               if page._file_name_at(row) == "notes.txt")
    page.table.selectRow(row)
    item = page.table.item(row, page.TYPE_COL)
    names = [page._file_name_at(index) for index in range(page.table.rowCount())]
    try:
        for theme in ("Light", "Dark", "Light"):
            BaseStyles.switch_theme(theme)
            qt_application.processEvents()
            icons = [page.windowIcon(), item.icon()]
            icons.extend(button.icon() for button in (
                page.back_btn, page.fwd_btn, page.up_btn, page.refresh_action, page.mkdir_action,
                page.touch_action, page.pull_action, page.push_action, page.delete_action,
                page.preview_back_btn, page.preview_close_btn, page.preview_image.image_close,
            ))
            for icon in icons:
                lightness = _icon_lightness(icon)
                assert lightness > 0.8 if theme == "Dark" else lightness < 0.2
            assert page.table.item(row, page.TYPE_COL) is item
            assert item.isSelected()
            assert [page._file_name_at(index) for index in range(page.table.rowCount())] == names
            assert page._file_type_at(row) == "TXT"
    finally:
        page.close()


def test_file_explorer_workspace_has_one_header_and_keeps_standalone_title(
    qt_application, monkeypatch
):
    monkeypatch.setattr(FileExplorerPage, "_refresh", Mock())
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("files", QSize(1600, 1100)))
    )
    try:
        frame.show()
        host = frame._workspace_feature_hosts["devices"]
        host.set_device_context(["demo-a"], ["demo-a"])
        assert frame._open_workspace_feature("devices", "files", device_id="demo-a")
        qt_application.processEvents()
        page = host.stack.currentWidget()
        assert page.property("workspace_embedded") is True
        assert not page.header_card.isVisibleTo(frame)
        assert page.path_field.isVisibleTo(frame)
        assert page.table.isVisibleTo(frame)
        assert page.status_bar.isVisibleTo(frame)
        page.set_workspace_embedded(False)
        assert page.header_card.isVisibleTo(frame)
        assert page.dialog_title.text() == "File Explorer"
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize("order", [Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder])
def test_file_explorer_icon_types_preserve_string_sort_and_accessibility(qt_application, order):
    page = FileExplorerPage(device_ip="demo-a")
    page._on_ls_result(LISTING, False)
    page.table.sortByColumn(page.TYPE_COL, order)
    types = [page._file_type_at(row) for row in range(page.table.rowCount())]
    assert types == sorted(["Folder", "Folder", "APK", "PNG", "TXT"],
                           reverse=order == Qt.SortOrder.DescendingOrder)
    for row, file_type in enumerate(types):
        item = page.table.item(row, page.TYPE_COL)
        assert _paint_option(page, row, page.TYPE_COL).text == ""
        assert _paint_option(page, row, page.NAME_COL).text == page._file_name_at(row)
        assert not item.icon().isNull()
        assert item.toolTip() == file_type
        assert item.data(Qt.ItemDataRole.AccessibleTextRole) == file_type
    page.close()


def test_file_explorer_icon_only_rows_keep_parent_folder_symlink_and_file_navigation(
    qt_application, monkeypatch
):
    page = FileExplorerPage(device_ip="demo-a")
    page._on_ls_result(LISTING, False)
    go_parent = Mock()
    navigate = Mock()
    view_or_pull = Mock()
    monkeypatch.setattr(page._list_controller, "_go_parent", go_parent)
    monkeypatch.setattr(page._list_controller, "_navigate", navigate)
    monkeypatch.setattr(page, "_view_or_pull", view_or_pull)
    for name in ("..", "Documents", "notes.txt"):
        row = next(row for row in range(page.table.rowCount())
                   if page._file_name_at(row) == name)
        assert _paint_option(page, row, page.TYPE_COL).text == ""
        page._on_double_click(row, page.TYPE_COL)
    go_parent.assert_called_once_with()
    navigate.assert_called_once_with("/storage/emulated/0/Documents")
    view_or_pull.assert_called_once_with("notes.txt")
    page.symlink_targets["Documents"] = "/shared/documents"
    row = next(row for row in range(page.table.rowCount())
               if page._file_name_at(row) == "Documents")
    page._on_double_click(row, page.NAME_COL)
    navigate.assert_called_with("/shared/documents")
    page.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("font_size", [12, 22])
def test_file_explorer_type_icons_stay_visible_in_narrow_theme_and_font_changes(
    qt_application, monkeypatch, theme, font_size
):
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, role, size=None: QFont("Microsoft YaHei", size or font_size)
    ))
    page = FileExplorerPage(device_ip="demo-a")
    page.prepare_for_workspace()
    workspace = QScrollArea()
    workspace.setWidgetResizable(True)
    workspace.setWidget(page)
    workspace.resize(480, 700)
    page._on_ls_result(LISTING, False)
    workspace.show()
    BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
    BaseStyles.switch_theme(theme)
    qt_application.processEvents()
    header = page.table.horizontalHeader()
    assert page.table.columnWidth(page.TYPE_COL) < 92
    assert page.table.columnWidth(page.TYPE_COL) >= page.table.iconSize().width() + 16
    assert page.table.columnWidth(page.TYPE_COL) >= header.fontMetrics().horizontalAdvance("Type")
    item = page.table.item(0, page.TYPE_COL)
    cell = page.table.visualItemRect(item)
    assert page.table.viewport().rect().contains(cell)
    assert not item.icon().pixmap(page.table.iconSize()).isNull()
    assert _paint_option(page, 0, page.TYPE_COL).text == ""
    assert workspace.width() == 480
    right = page.table.mapTo(workspace.viewport(), cell.topRight()).x()
    assert right < workspace.viewport().width()
    page.close()
    workspace.close()


@pytest.mark.parametrize("width", [700, 1100])
@pytest.mark.parametrize("content", ["loading", "text", "image", "output", "error"])
def test_file_preview_close_restores_full_file_list_and_can_reopen(
    qt_application, width, content
):
    page = FileExplorerPage(device_ip="demo-a")
    page.resize(width, 700)
    page._on_ls_result(LISTING, False)
    page.show()
    qt_application.processEvents()
    names = [page._file_name_at(row) for row in range(page.table.rowCount())]
    image = QPixmap(90, 160)
    image.fill(Qt.GlobalColor.blue)
    try:
        if content == "loading":
            page._begin_preview_request("notes.txt")
        elif content == "text":
            page._show_text_preview("notes.txt", "hello", "/sdcard/notes.txt")
        elif content == "image":
            page._show_image_preview("demo.png", image)
        elif content == "output":
            page._show_script_output("demo.sh", "done", False)
        else:
            page._show_preview_error("notes.txt", "Unable to read file")
        qt_application.processEvents()
        assert page.preview_panel.isVisible()
        close_button = page.preview_back_btn if width < 880 else page.preview_close_btn
        assert close_button.isVisible()
        QTest.mouseClick(close_button, Qt.MouseButton.LeftButton)
        qt_application.processEvents()

        assert not page.preview_panel.isVisible()
        assert page.table.isVisible()
        assert page.table.hasFocus()
        assert abs(page.browser_panel.width() - page.content_splitter.width()) <= 2
        assert [page._file_name_at(row) for row in range(page.table.rowCount())] == names
        assert page.preview_image._source_pixmap.isNull()
        assert not page.preview_image._fit_timer.isActive()

        for resized_width in (700, 1100, width):
            page.resize(resized_width, 700)
            qt_application.processEvents()
            assert not page.preview_panel.isVisible()
            assert page.table.isVisible()
            assert abs(page.browser_panel.width() - page.content_splitter.width()) <= 2

        page._show_image_preview("demo.png", image)
        qt_application.processEvents()
        assert page.preview_panel.isVisible()
        assert page.preview_image.isVisible()
        assert page.browser_panel.isVisible() is (width >= 880)
        assert close_button.isVisible()
        QTest.mouseClick(close_button, Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        assert not page.preview_panel.isVisible()
        assert page.table.isVisible()
    finally:
        page.close()


@pytest.mark.parametrize("width", [952, 500])
@pytest.mark.parametrize("font_size", [12, 22])
def test_file_explorer_command_bar_keeps_root_inline_and_narrow_actions_reachable(
    qt_application, monkeypatch, width, font_size
):
    monkeypatch.setattr(BaseStyles, "font_for_role", classmethod(
        lambda _cls, role, size=None: QFont("Microsoft YaHei", size or font_size)
    ))
    page = FileExplorerPage(device_ip="demo-a")
    page.prepare_for_workspace()
    page.resize(width, 800)
    page.show()
    qt_application.processEvents()
    try:
        assert page.width() == width
        bar = page.command_bar
        assert isinstance(bar, CommandBar)
        assert len(bar.actions()) == 6
        assert len(bar.commandButtons) == 6
        assert page.root_cb.parentWidget() is not bar
        assert abs(page.root_cb.geometry().center().y() - bar.geometry().center().y()) <= 2
        assert page.root_cb.geometry().left() > bar.geometry().right()
        assert page.rect().contains(page.root_cb.geometry())
        path_y = page.path_field.mapTo(page, page.path_field.rect().center()).y()
        for button in (page.back_btn, page.fwd_btn, page.up_btn):
            assert abs(button.mapTo(page, button.rect().center()).y() - path_y) <= 2
        for button in (*bar.commandButtons, bar.moreButton):
            assert button.height() >= button.fontMetrics().height() + 12
            if button.isVisible():
                assert bar.rect().contains(button.geometry())
        assert bar.height() <= max(button.height() for button in bar.commandButtons) + 2
        if width == 500:
            assert bar.moreButton.isVisible()
            menus = []
            monkeypatch.setattr(
                "qfluentwidgets.components.widgets.command_bar.CommandMenu.exec",
                lambda menu, *_args, **_kwargs: menus.append(menu),
            )
            QTest.mouseClick(bar.moreButton, Qt.MouseButton.LeftButton)
            assert len(menus) == 1
            visible_actions = {
                button.action() for button in bar.commandButtons if button.isVisible()
            }
            assert set(menus[0].actions()) | visible_actions == set(bar.actions())
            assert set(menus[0].actions()).isdisjoint(visible_actions)
    finally:
        page.close()


def test_file_explorer_overflow_actions_follow_selection_and_loading(qt_application, monkeypatch):
    submitted = []
    monkeypatch.setattr(
        "models.file_explorer_worker.ADBWorker.start", lambda worker: submitted.append(worker)
    )
    monkeypatch.setattr(
        "models.file_explorer_worker.TransferWorker.start", lambda worker: submitted.append(worker)
    )
    monkeypatch.setattr("core.exec.CommandRunner.run", Mock(side_effect=AssertionError("real ADB")))
    monkeypatch.setattr(
        "core.exec.ProcessRunner.start", Mock(side_effect=AssertionError("real process"))
    )
    page = FileExplorerPage(device_ip="demo-a")
    page.prepare_for_workspace()
    page.resize(500, 700)
    page.show()
    qt_application.processEvents()
    menus = []
    monkeypatch.setattr(
        "qfluentwidgets.components.widgets.command_bar.CommandMenu.exec",
        lambda menu, *_args, **_kwargs: menus.append(menu),
    )
    try:
        page.set_device_selected(True)
        assert all(action.isEnabled() for action in page.command_bar.actions())
        QTest.mouseClick(page.command_bar.moreButton, Qt.MouseButton.LeftButton)
        assert menus and menus[0].actions()
        page.set_device_selected(False)
        assert all(not action.isEnabled() for action in menus[0].actions())
        for action in page.command_bar.actions():
            action.trigger()
        assert submitted == []
        page.set_device_selected(True)
        page._set_directory_loading(True)
        assert page.refresh_action.isEnabled()
        assert all(not action.isEnabled() for action in page.command_bar.actions()
                   if action is not page.refresh_action)
        page._set_directory_loading(False)
        page.refresh_action.trigger()
        assert len(submitted) == 1
        assert submitted[0].device_ip == "demo-a"
    finally:
        page.close()


def test_file_explorer_main_window_toolbar_does_not_force_horizontal_scroll(
    qt_application, monkeypatch
):
    monkeypatch.setattr(FileExplorerPage, "_refresh", Mock())
    monkeypatch.setattr("core.exec.CommandRunner.run", Mock(side_effect=AssertionError("real ADB")))
    monkeypatch.setattr(
        "core.exec.ProcessRunner.start", Mock(side_effect=AssertionError("real process"))
    )
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("files", QSize(1600, 1100)))
    )
    try:
        frame._on_devices_updated(["demo-a"])
        frame._global_device_bar.selection_requested.emit(["demo-a"])
        frame.show()
        frame.navigationInterface.widget("filesPage").click()
        wait_until(qt_application, lambda: (
            frame.navigationInterface.panel.expandAni.state() == QAbstractAnimation.State.Stopped
            and frame.stackedWidget.view._ani.state() == QAbstractAnimation.State.Stopped
        ))
        host = frame._workspace_feature_hosts["devices"]
        page = host.stack.currentWidget()
        for window_width, page_width in ((1048, 1000), (860, 812), (1048, 1000)):
            frame.resize(window_width, 900)
            qt_application.processEvents()
            frame.navigationInterface.panel.collapse()
            wait_until(qt_application, lambda: (
                frame.navigationInterface.panel.expandAni.state()
                == QAbstractAnimation.State.Stopped
                and frame.navigationInterface.width() == 48
            ))
            wait_for_stable_geometry(qt_application, (frame, page, page.command_bar, page.table))
            assert frame.size() == QSize(window_width, 900)
            assert frame.navigationInterface.width() == 48
            assert page.width() == page_width
            assert host.content_scroll.horizontalScrollBar().maximum() == 0
            assert mapped_rect(page.command_bar, frame).left() == 80
            assert mapped_rect(page.root_cb, page).bottom() < mapped_rect(page.table, page).top()
            for selected in (False, True):
                frame._global_device_bar.selection_requested.emit(["demo-a"] if selected else [])
                qt_application.processEvents()
                assert host.content_scroll.horizontalScrollBar().maximum() == 0
                assert page.command_bar.height() == page.command_bar.commandButtons[0].height()
                assert all(action.isEnabled() == selected for action in page.command_bar.actions())
    finally:
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()


@pytest.mark.parametrize("error", [False, True])
def test_file_preview_ignores_dismissed_results_and_accepts_new_request(qt_application, error):
    page = FileExplorerPage(device_ip="demo-a")
    page.resize(1100, 700)
    page.show()
    try:
        previous_request = page._begin_preview_request("old.txt")
        qt_application.processEvents()
        QTest.mouseClick(page.preview_close_btn, Qt.MouseButton.LeftButton)
        page._view_controller._show_text_viewer(
            "old.txt", "late text", error, "/sdcard/old.txt", request_id=previous_request
        )
        page._show_script_output("old.sh", "late output", error, request_id=previous_request)
        qt_application.processEvents()
        assert not page.preview_panel.isVisible()
        assert page.table.isVisible()

        current_request = page._begin_preview_request("current.txt")
        page._view_controller._show_text_viewer(
            "current.txt", "current text", False, "/sdcard/current.txt", request_id=current_request
        )
        page._view_controller._show_text_viewer(
            "old.txt", "late text", error, "/sdcard/old.txt", request_id=previous_request
        )
        qt_application.processEvents()
        assert page.preview_panel.isVisible()
        assert page.preview_title.text() == "current.txt"
        assert page.preview_text_edit.toPlainText() == "current text"
        assert page.preview_stack.currentWidget() is page.preview_text_page
    finally:
        page.close()


@pytest.mark.parametrize("error", [False, True])
def test_file_preview_closed_image_result_cleans_temporary_download(
    qt_application, tmp_path, error
):
    page = FileExplorerPage(device_ip="demo-a")
    page.resize(1100, 700)
    page.show()
    image_path = tmp_path / "preview.png"
    image = QPixmap(90, 160)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(image_path))
    page._view_controller._temporary_files.add(str(image_path))
    try:
        request = page._begin_preview_request("preview.png")
        qt_application.processEvents()
        QTest.mouseClick(page.preview_close_btn, Qt.MouseButton.LeftButton)
        page._show_image(request, "preview.png", str(image_path), "", error=error)
        qt_application.processEvents()
        assert not page.preview_panel.isVisible()
        assert page.table.isVisible()
        assert not image_path.exists()
        assert page.preview_image._source_pixmap.isNull()
    finally:
        page.close()
