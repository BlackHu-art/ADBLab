"""文件页嵌入标题、图标类型列及保留的浏览语义回归。"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QScrollArea, QStyleOptionViewItem

from gui.features.file_explorer import FileExplorerPage
from gui.styles import BaseStyles
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame

LISTING = "\n".join([
    "drwxr-xr-x 2 shell shell 4096 Sep 05 Documents",
    "-rw-r--r-- 1 shell shell 2048 Sep 05 sample.apk",
    "-rw-r--r-- 1 shell shell 4096 Sep 05 demo.png",
    "-rw-r--r-- 1 shell shell 1024 Sep 05 notes.txt",
])


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
                page.back_btn, page.fwd_btn, page.up_btn, page.refresh_btn, page.mkdir_btn,
                page.touch_btn, page.pull_btn, page.push_btn, page.delete_btn,
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
