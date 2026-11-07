"""统一任务表只挂载一处行内详情，后台记录不抢阅读位置。"""

from PySide6.QtCore import QCoreApplication, QEvent

from gui.pages.tasks_page import TaskCenterPage
from gui.run_library import RunLibraryController
from services.run_library import RunLibrary, RunRecord
from services.tasks.action_results import ActionItem, ActionResult, ActionSpec
from services.tasks.operations import OperationManager
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    wait_for_stable_geometry,
    wait_until,
)


def test_task_center_shared_inline_reader_ignores_hidden_archive_detail_height(
    qt_application, tmp_path,
):
    store = RunLibrary(tmp_path / "runs.json")
    for index in range(8):
        store.record_run(RunRecord(
            str(index), "monkey" if index % 2 else "performance", "com.example.app",
            1, 100 + index, "succeeded", {"seed": index},
        ))
    library = RunLibraryController(store)
    manager = OperationManager()
    page = TaskCenterPage(operation_manager=manager, run_library=library)
    page.resize(900, 800)
    try:
        page.show()
        wait_until(qt_application, lambda: len(page.table.rows) == 8)
        page.refresh()
        assert not page.table.expanded_key
        assert not page.run_results.isVisibleTo(page)
        assert not page.action_results.isVisibleTo(page)
        page.table.rows["run:7"].toggle.click()
        wait_for_stable_geometry(qt_application, (page, page._scroll.widget(), page.detail))
        detail = page.detail
        run_height = page.run_results.height()
        assert page.run_results.isVisibleTo(page)
        selected = page.run_results.selected_record
        assert selected.run_id == "7"
        for index in range(80):
            page.present_action_result(ActionResult(
                f"local-operation-{index}", ActionSpec("query", "system.shell", "查询", "text"),
                ("demo-device",), 100 + index, "succeeded",
                items=(ActionItem(
                    f"job-{index}", "demo-device", "设备 1", "succeeded",
                    f"本次操作 {index}\n" + "完整结果\n" * 100,
                ),),
                finished_at=101 + index,
            ))
        page.refresh()
        wait_for_stable_geometry(qt_application, (page._scroll.widget(), page.detail))
        assert len(page.action_results.records_snapshot()) == 20
        assert len(page.table.rows) == 28
        assert page.table.expanded_key == "run:7"
        assert page.detail is detail
        assert page.run_results.selected_record == selected
        assert page.run_results.height() == run_height
        assert not page.action_results.isVisibleTo(page)
        assert page.select_request("local-operation-79")
        page.action_results.detail_toggle.setChecked(True)
        wait_until(qt_application, lambda: page.action_results.isVisibleTo(page))
        wait_for_stable_geometry(qt_application, (page._scroll.widget(), page.detail))
        assert not page.run_results.isVisibleTo(page)
        assert page.detail is detail
        assert page.table.expanded_key == "action:local-operation-79"
        assert page.action_results.output.isVisibleTo(page)
        assert page.action_results.output.toPlainText().startswith("本次操作 79\n")
        assert_scroll_target_reachable(page._scroll, page.action_results.export_button)
        operation_height = page._scroll.widget().height()
        # 未挂载的归档详情改变高度，也不能撑高正在阅读的操作行。
        page.run_results.parameters_section.toggle_button.click()
        wait_for_stable_geometry(qt_application, (page._scroll.widget(), page.detail))
        assert not page.run_results.parameters_section.content.isHidden()
        assert page._scroll.widget().height() == operation_height
        page.run_results.parameters_section.toggle_button.click()
        page.table.rows["run:7"].toggle.click()
        wait_until(qt_application, lambda: page.run_results.isVisibleTo(page))
        wait_for_stable_geometry(qt_application, (page._scroll.widget(), page.detail))
        assert page.detail is detail
        assert not page.action_results.isVisibleTo(page)
        assert len([key for key in page.table.rows if key.startswith("run:")]) == 8
        assert page.run_results.selected_record == selected
        assert page.run_results.parameters_section.content.isHidden()
        assert page.run_results.height() == run_height
        assert_scroll_target_reachable(page._scroll, page.run_results.reuse_button)
        operation = manager.begin("install")
        manager.mark_running(operation.operation_id)
        page.refresh()
        assert len(page.table.rows) == 29
        active_row = page.table.rows[f"operation:{operation.operation_id}"]
        assert active_row.isVisibleTo(page)
        assert active_row.cancel.isVisibleTo(page)
        assert page.table.expanded_key == "run:7"
    finally:
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)
        assert library.shutdown()
        library.deleteLater()
        QCoreApplication.sendPostedEvents(library, QEvent.Type.DeferredDelete)
