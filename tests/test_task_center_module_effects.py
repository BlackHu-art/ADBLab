"""任务类型筛选沿真实操作目录分类，不遗漏正在执行的 Monkey 操作。"""

import pytest

from controllers.action_catalog import ACTION_SIGNALS
from gui.pages.tasks_page import TaskCenterPage
from services.tasks.action_results import ActionResult, ActionSpec

pytestmark = pytest.mark.ui


@pytest.mark.parametrize(
    "spec,kind,label",
    [
        (ACTION_SIGNALS["start_monkey_requested"], "monkey", "Monkey"),
        (ACTION_SIGNALS["start_monkey_batch_requested"], "monkey", "Monkey"),
        (ACTION_SIGNALS["kill_monkey_requested"], "monkey", "Monkey"),
        (ACTION_SIGNALS["kill_monkey_batch_requested"], "monkey", "Monkey"),
        (ACTION_SIGNALS["shell_command_requested"], "shell", "Shell"),
        (ACTION_SIGNALS["get_program_requested"], "app", "应用"),
        (ActionSpec("extension_query", "extension.tools", "扩展查询"), "other", "其他"),
    ],
    ids=["monkey-start", "monkey-batch", "monkey-stop", "monkey-stop-batch",
         "shell-query", "package-query", "unknown-extension"],
)
def test_catalog_action_remains_visible_under_its_task_type_filter(
    qt_application, spec, kind, label,
):
    page = TaskCenterPage()
    try:
        page.present_action_result(ActionResult("request", spec, (), 100))
        page.show()
        qt_application.processEvents()
        assert page.table.rows["action:request"].isVisibleTo(page)

        page.kind_combo.setCurrentIndex(page.kind_combo.findData(kind))
        qt_application.processEvents()

        assert set(page.table.rows) == {"action:request"}
        row = page.table.rows["action:request"]
        assert row.isVisibleTo(page)
        assert row.data.kind == label
        assert row.data.state == "运行中"

        excluded_kind = "shell" if kind != "shell" else "monkey"
        page.kind_combo.setCurrentIndex(page.kind_combo.findData(excluded_kind))
        assert not page.table.rows
        assert page.empty_label.isVisibleTo(page)
    finally:
        page.shutdown()
        page.close()
