"""验证任务中心切换结果与操作记录时，隐藏长列表不参与当前页测高。"""

from PySide6.QtCore import QCoreApplication, QEvent

from adblab.application.action_results import ActionItem, ActionResult, ActionSpec
from adblab.application.operations import OperationManager
from gui.pages.tasks_page import TaskCenterPage
from gui.run_library import RunLibraryController
from services.run_library import RunLibrary, RunRecord
from tests.ui_geometry_helpers import (
    assert_scroll_target_reachable,
    wait_for_stable_geometry,
    wait_until,
)


def test_task_center_result_view_ignores_hidden_operation_history_height(
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
        wait_until(qt_application, lambda: page.run_results.table.rowCount() == 8)
        page.refresh()
        wait_for_stable_geometry(qt_application, (page, page._scroll.widget(), page.history_views))
        content_height = page._scroll.widget().height()
        scroll_maximum = page._scroll.verticalScrollBar().maximum()
        assert page.history_views.current_key == "test_results"
        assert page.run_results.isVisibleTo(page)
        assert not page._history_card.isVisibleTo(page)
        assert not page._active_card.isVisibleTo(page)
        assert page._idle_label.isVisibleTo(page)
        selected = page.run_results.selected_record
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
        wait_for_stable_geometry(qt_application, (page._scroll.widget(), page.history_views))
        assert page.action_results.history.count() == 20
        assert page._scroll.widget().height() == content_height
        assert page._scroll.verticalScrollBar().maximum() == scroll_maximum
        page.history_views.set_current("operations")
        wait_until(qt_application, lambda: page.action_results.isVisibleTo(page))
        wait_for_stable_geometry(qt_application, (page._scroll.widget(), page.history_views))
        assert not page.run_results.isVisibleTo(page)
        assert page._history_card.isHidden()
        assert page.action_results.output.isVisibleTo(page)
        assert page.action_results.output.toPlainText().startswith("本次操作 79\n")
        assert_scroll_target_reachable(page._scroll, page.action_results.export_button)
        operation_height = page._scroll.widget().height()
        # 隐藏结果页展开参数后变高，也不能反过来撑高当前操作阅读器。
        page.run_results.parameters_section.toggle_button.click()
        wait_for_stable_geometry(qt_application, (page._scroll.widget(), page.history_views))
        assert not page.run_results.parameters_section.content.isHidden()
        assert page._scroll.widget().height() == operation_height
        page.run_results.parameters_section.toggle_button.click()
        page.history_views.set_current("test_results")
        wait_until(qt_application, lambda: page.run_results.isVisibleTo(page))
        wait_for_stable_geometry(qt_application, (page._scroll.widget(), page.history_views))
        assert not page._history_card.isVisibleTo(page)
        assert not page.action_results.isVisibleTo(page)
        assert page.run_results.table.rowCount() == 8
        assert page.run_results.selected_record == selected
        assert page.run_results.parameters_section.content.isHidden()
        assert page._scroll.widget().height() == content_height
        assert_scroll_target_reachable(page._scroll, page.run_results.reuse_button)
        operation = manager.begin("install")
        manager.mark_running(operation.operation_id)
        page.refresh()
        assert page._active_card.isVisibleTo(page)
        assert not page._idle_label.isVisibleTo(page)
        assert page._active_card.viewLayout.count() == 1
    finally:
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)
        assert library.shutdown()
        library.deleteLater()
        QCoreApplication.sendPostedEvents(library, QEvent.Type.DeferredDelete)
