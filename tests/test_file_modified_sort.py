"""文件时间按明确年份或未知年份分组排序，不猜测设备日期。"""

import pytest

from services import file_explorer as service


def test_date_keys_order_known_years_and_do_not_invent_missing_years():
    dates = ["Dec 02 12:00", "Oct 01 12:00", "Sep 09 12:00"]
    assert sorted(dates, key=service.modified_sort_key) == dates[::-1]
    known = ["Sep 05 2026", "2025-12-01 08:00", "Jan 02 2025"]
    assert sorted(known, key=service.modified_sort_key) == known[::-1]
    assert service.modified_sort_key("Sep 09 12:00")[0] > service.modified_sort_key(
        "2099-01-01 00:00",
    )[0]


@pytest.mark.parametrize("value", [
    "unknown", "-", "2026-02-29 00:00", "2026-13-01 00:00", "Jan 32 12:00", "Feb 28 25:00",
])
def test_invalid_modified_time_remains_in_unknown_group(value):
    assert service.modified_sort_key(value)[0] == 2


def test_missing_year_leap_day_is_not_rejected_or_assigned_current_year():
    key = service.modified_sort_key("Feb 29 12:34")
    assert key[:2] == (1, (0, 2, 29, 12, 34, 0))


@pytest.mark.ui
@pytest.mark.parametrize("descending", [False, True])
def test_modified_sort_is_numeric_and_keeps_unknown_years_after_known(qt_application, descending):
    from PySide6.QtCore import Qt

    from gui.dialogs.file_explorer import FileExplorerPage

    entries = [
        ("sep.txt", "Sep 09 12:00"), ("dec.txt", "Dec 02 12:00"),
        ("oct.txt", "Oct 01 12:00"), ("older.txt", "2025-12-31 23:59"),
        ("newer.txt", "2026-01-01 00:00"),
    ]
    page = FileExplorerPage(device_ip="")
    try:
        page._on_ls_result("drwxr-xr-x 2 shell shell 10 Sep 09 12:00 Folder\n" + "\n".join(
            f"-rw-r--r-- 1 shell shell 1 {modified} {name}" for name, modified in entries
        ), False)
        page.table.sortByColumn(
            page.MODIFIED_COL,
            Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder,
        )
        expected = (["newer.txt", "older.txt", "dec.txt", "oct.txt", "sep.txt"]
                    if descending else ["older.txt", "newer.txt", "sep.txt", "oct.txt", "dec.txt"])
        assert [page._file_name_at(i) for i in range(page.table.rowCount())] == [
            "..", "Folder", *expected,
        ]
    finally:
        page.close()


@pytest.mark.ui
@pytest.mark.parametrize("descending", [False, True])
def test_unparseable_times_stay_after_all_dates(qt_application, descending):
    from PySide6.QtCore import Qt

    from gui.dialogs.file_explorer import FileExplorerPage

    page = FileExplorerPage(device_ip="")
    try:
        page.table.setSortingEnabled(False)
        page.table.setRowCount(3)
        for row, (name, modified) in enumerate([
            ("unknown", "unsupported"), ("month", "Sep 09 12:00"), ("dated", "2026-09-09 12:00"),
        ]):
            page._list_controller._set_file_row(row, name, "File", "0", modified)
        page.table.setSortingEnabled(True)
        page.table.sortByColumn(
            page.MODIFIED_COL,
            Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder,
        )
        assert [page._file_name_at(i) for i in range(3)] == ["dated", "month", "unknown"]
    finally:
        page.close()
