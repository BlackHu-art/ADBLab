import json
import os
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QGridLayout, QPushButton, QWidget

from gui.dialogs.app_manager_batch import AppManagerBatch
from gui.dialogs.fluent_dialog import FluentDialog
from gui.features.app_manager import AppDetailsPage, AppManagerPage
from gui.styles import BaseStyles
from gui.styles.typography import FontRole
from tests.ui_geometry_helpers import assert_non_overlapping

_SELECTION_ACTIONS = (
    "卸载所选",
    "停用所选",
    "启用所选",
    "取消全选",
)
_PRESET_ACTIONS = (
    "创建预设",
    "加载预设",
    "备份所选",
    "恢复备份",
    "应用详情",
)


def _app_manager_page():
    app = QApplication.instance() or QApplication([])
    with patch.object(AppManagerPage, "_load_apps"):
        dialog = AppManagerPage(device_ip="device-1")
    return app, dialog


def _action_buttons(dialog):
    buttons = {
        button.accessibleName(): button
        for button in dialog.findChildren(QPushButton)
        if button.accessibleName() in {*_SELECTION_ACTIONS, *_PRESET_ACTIONS}
    }
    assert set(buttons) == {*_SELECTION_ACTIONS, *_PRESET_ACTIONS}
    return buttons


def _set_action_font(dialog, point_size):
    for button in dialog.findChildren(QPushButton):
        if button.text() in {*_SELECTION_ACTIONS, *_PRESET_ACTIONS}:
            button.setFont(QFont("Arial", point_size))
            # qfluentwidgets PushButton 的最小行高由 minimumSizeHint 按点字号给出，
            # 直接 setFont 不会触发 _apply_adaptive_text_heights，需同步最小高度。
            button.setMinimumHeight(button.minimumSizeHint().height())
            button.updateGeometry()


def _assert_buttons_fit(dialog, buttons):
    for button in buttons.values():
        geometry = button.geometry()
        minimum = button.minimumSizeHint()
        assert geometry.width() >= minimum.width()
        assert geometry.height() >= minimum.height()
        assert geometry.left() >= dialog.contentsRect().left()
        assert geometry.right() <= dialog.contentsRect().right()


def _top_controls(dialog):
    return (
        dialog._search_label,
        dialog.search_input,
        dialog._type_label,
        dialog.type_filter,
        dialog.selection_label,
        dialog.view_toggle,
        dialog.refresh_btn,
    )


def _top_layout_signature(dialog):
    return tuple(
        dialog._top_layout.getItemPosition(dialog._top_layout.indexOf(widget))
        for widget in _top_controls(dialog)
    )


def _patch_font_size(monkeypatch, current_size):
    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(
            lambda _cls, role, size=None: QFont(
                "Arial",
                size or (current_size["ui"] if FontRole(role) == FontRole.UI else 12),
            )
        ),
    )


def test_app_manager_family_exposes_pure_widget_pages_without_eager_io():
    app = QApplication.instance() or QApplication([])
    with patch("gui.dialogs.app_manager.AppManagerWorker") as worker_cls:
        manager = AppManagerPage(device_ip="device-1")
        details = AppDetailsPage(manager, "device-1", "com.example.app")
    try:
        assert isinstance(manager, QWidget)
        assert isinstance(details, QWidget)
        assert not isinstance(manager, FluentDialog)
        assert not isinstance(details, FluentDialog)
        assert manager._activated_once is False
        assert details.load_state == "idle"
        worker_cls.assert_not_called()
    finally:
        details.close()
        manager.close()
        app.processEvents()


def test_create_preset_reads_accepted_values_before_explicit_dialog_release(tmp_path):
    """接受预设弹窗后，应在显式释放前复制输入值。"""

    class TrackingPresetDialog(FluentDialog):
        instances = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.release_requested = False
            self.__class__.instances.append(self)

        def exec(self):
            from qfluentwidgets import LineEdit, TextEdit

            name_input, author_input = self.findChildren(LineEdit)
            description_input = self.findChild(TextEdit)
            name_input.setText("Daily Apps")
            author_input.setText("QA")
            description_input.setPlainText("Regression preset")
            QTimer.singleShot(0, self.accept)
            return super().exec()

        def deleteLater(self):
            self.release_requested = True
            return super().deleteLater()

    app, manager = _app_manager_page()
    preset_path = tmp_path / "daily.json"
    manager.selected_packages = {"com.example.two", "com.example.one"}
    try:
        with (
            patch("gui.dialogs.app_manager_batch.FluentDialog", TrackingPresetDialog),
            patch(
                "gui.dialogs.app_manager_batch.QFileDialog.getSaveFileName",
                return_value=(str(preset_path), "JSON (*.json)"),
            ),
        ):
            AppManagerBatch(manager)._create_preset()

        preset_dialog = TrackingPresetDialog.instances[-1]
        assert preset_dialog.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose) is False
        assert preset_dialog.release_requested is True
        assert json.loads(preset_path.read_text(encoding="utf-8")) == {
            "name": "Daily Apps",
            "author": "QA",
            "description": "Regression preset",
            "selected_packages": ["com.example.one", "com.example.two"],
        }
    finally:
        manager.close()
        app.processEvents()


def test_app_manager_top_controls_fit_at_776_and_768_with_22pt(monkeypatch):
    current_size = {"ui": 22}
    _patch_font_size(monkeypatch, current_size)
    app, dialog = _app_manager_page()
    geometry_failures = []
    bounds_failures = []
    signatures = []
    try:
        dialog.show()
        for width in (776, 768):
            # qfluentwidgets ComboBox 比原生 QComboBox 窄，顶部控件在 768px
            # 以下会触发五列重排并把 "已选 0 项" 标签压到最小宽度以下；
            # 断点随收敛上移 8px。qfluentwidgets 控件行高比原生高，22pt 下
            # 内容区至少需要 700px；Fluent 标题栏额外占用 48px。
            dialog.resize(width, 700)
            app.processEvents()
            controls = _top_controls(dialog)
            signatures.append(_top_layout_signature(dialog))
            layout_geometry = dialog._top_layout.geometry()
            for widget in controls:
                geometry = widget.geometry()
                minimum = widget.minimumSizeHint()
                if geometry.width() < minimum.width():
                    geometry_failures.append(
                        (
                            width,
                            widget.__class__.__name__,
                            widget.text() if hasattr(widget, "text") else "",
                            geometry.width(),
                            minimum.width(),
                        )
                    )
                if not layout_geometry.contains(geometry):
                    bounds_failures.append(
                        (width, widget.__class__.__name__, geometry, layout_geometry)
                    )
            assert_non_overlapping(controls, dialog)

        assert geometry_failures == []
        assert bounds_failures == []
        assert len({position[0] for position in signatures[0]}) > 1
        assert signatures[0] == signatures[1]
    finally:
        dialog.close()


def test_app_manager_font_round_trip_restores_action_heights(monkeypatch):
    current_size = {"ui": 8}
    _patch_font_size(monkeypatch, current_size)
    app, dialog = _app_manager_page()
    fresh_dialog = None
    try:
        dialog.show()
        app.processEvents()
        baseline = tuple(button.minimumHeight() for button in _action_buttons(dialog).values())

        current_size["ui"] = 22
        dialog._apply_theme()
        app.processEvents()
        large = tuple(button.minimumHeight() for button in _action_buttons(dialog).values())

        current_size["ui"] = 8
        dialog._apply_theme()
        app.processEvents()
        restored = tuple(button.minimumHeight() for button in _action_buttons(dialog).values())

        _fresh_app, fresh_dialog = _app_manager_page()
        fresh_dialog.show()
        app.processEvents()
        fresh_baseline = tuple(
            button.minimumHeight() for button in _action_buttons(fresh_dialog).values()
        )

        assert all(
            large_height > baseline_height for large_height, baseline_height in zip(large, baseline)
        )
        assert restored == baseline == fresh_baseline
    finally:
        dialog.close()
        if fresh_dialog is not None:
            fresh_dialog.close()


def test_app_manager_reflows_action_buttons_to_two_columns_at_776_with_large_font(monkeypatch):
    app, dialog = _app_manager_page()
    try:
        dialog.resize(776, 600)
        dialog.show()
        app.processEvents()
        monkeypatch.setattr(
            BaseStyles,
            "font_for_role",
            classmethod(
                lambda _cls, role, size=None: QFont(
                    "Arial", size or (22 if FontRole(role) == FontRole.UI else 12)
                )
            ),
        )
        dialog._apply_theme()
        app.processEvents()

        buttons = _action_buttons(dialog)
        assert dialog.width() == 776
        assert isinstance(dialog._selection_action_layout, QGridLayout)
        assert isinstance(dialog._preset_action_layout, QGridLayout)
        assert dialog._selection_action_layout.property("responsiveColumnCount") == 2
        assert dialog._selection_action_layout.rowCount() == 2
        assert dialog._preset_action_layout.property("responsiveColumnCount") == 2
        assert dialog._preset_action_layout.rowCount() == 3
        assert (
            abs(
                buttons["停用所选"].geometry().right()
                - dialog._selection_action_layout.geometry().right()
            )
            <= 2
        )
        assert (
            abs(
                buttons["应用详情"].geometry().right()
                - dialog._preset_action_layout.geometry().right()
            )
            <= 2
        )
        _assert_buttons_fit(dialog, buttons)
        # 视觉重设计映射：页头卡片固定占用约 60px 纵向空间，600px/22pt 下
        # 栈区（应用列表/图标视图）可用高度从约 127px 降到约 64px；
        # 下界相应重映射，仍保证列表区域不会塌缩消失。
        assert dialog.stack.height() >= 60
    finally:
        dialog.close()


def test_app_manager_short_action_labels_keep_full_accessibility_semantics_when_narrow():
    app, dialog = _app_manager_page()
    try:
        _set_action_font(dialog, 22)
        dialog.setMinimumSize(0, 0)
        # qfluentwidgets PushButton 比原生 QPushButton 高（22pt 下 42px vs 37px），
        # 高度从 660 升到 700 后动作按钮行恢复完整最小高度；移除 SCROLLBAR_STYLE 后
        # 表格/列表滚动条回到 Fluent 默认尺寸再占 4px，高度升到 704，其余断言不变。
        dialog.resize(500, 704)
        dialog.show()
        app.processEvents()

        buttons = _action_buttons(dialog)
        assert [buttons[label].text() for label in _SELECTION_ACTIONS] == [
            "卸载",
            "停用",
            "启用",
            "清除",
        ]
        assert [buttons[label].text() for label in _PRESET_ACTIONS] == [
            "保存",
            "加载",
            "备份",
            "恢复",
            "详情",
        ]
        expected_help = {
            "卸载所选": "卸载已选择的应用",
            "停用所选": "停用已选择的应用",
            "启用所选": "启用已选择的应用",
            "取消全选": "清除当前应用选择",
            "创建预设": "将所选应用列表保存为预设",
            "加载预设": "根据已保存的预设选择应用",
            "备份所选": "备份已选择的应用",
            "恢复备份": "从备份文件恢复应用",
            "应用详情": "查看所选应用的详情",
        }
        for accessible_name, button in buttons.items():
            assert button.toolTip() == expected_help[accessible_name]
            assert button.accessibleDescription() == expected_help[accessible_name]
        details_index = dialog._preset_action_layout.indexOf(buttons["应用详情"])
        _row, column, _row_span, column_span = dialog._preset_action_layout.getItemPosition(
            details_index
        )
        assert column == 0
        assert column_span == 2
        _assert_buttons_fit(dialog, buttons)
    finally:
        dialog.close()


def test_app_manager_restores_full_actions_without_rebuilding_buttons_or_duplicate_clicks():
    class TrackingPage(AppManagerPage):
        deselect_calls = 0

        def _deselect_all(self):
            self.deselect_calls += 1

    app = QApplication.instance() or QApplication([])
    with patch.object(TrackingPage, "_load_apps"):
        dialog = TrackingPage(device_ip="device-1")

    try:
        _set_action_font(dialog, 22)
        dialog.setMinimumSize(0, 0)
        dialog.resize(400, 600)
        dialog.show()
        app.processEvents()
        narrow_buttons = _action_buttons(dialog)
        button_ids = {label: id(button) for label, button in narrow_buttons.items()}

        dialog.resize(2200, 700)
        app.processEvents()
        wide_buttons = _action_buttons(dialog)
        assert {label: id(button) for label, button in wide_buttons.items()} == button_ids
        assert dialog._selection_action_layout.property("responsiveColumnCount") == 4
        assert dialog._preset_action_layout.property("responsiveColumnCount") == 5
        assert [wide_buttons[label].text() for label in _SELECTION_ACTIONS] == list(
            _SELECTION_ACTIONS
        )
        assert [wide_buttons[label].text() for label in _PRESET_ACTIONS] == list(_PRESET_ACTIONS)

        dialog.resize(400, 600)
        app.processEvents()
        wide_buttons["取消全选"].setEnabled(True)
        wide_buttons["取消全选"].click()
        assert dialog.deselect_calls == 1
    finally:
        dialog.close()


def test_app_manager_keeps_table_and_icon_selection_in_sync():
    _app = QApplication.instance() or QApplication([])
    with patch.object(AppManagerPage, "_load_apps"):
        dialog = AppManagerPage(device_ip="device-1")

    try:
        dialog._populate(
            [
                ("One", "com.example.one", "Enabled", "User"),
                ("Two", "com.example.two", "Enabled", "User"),
            ]
        )
        dialog._detail_timer.stop()

        first_checkbox = dialog.model.item(0, 0)
        first_icon = dialog._detail_icon_by_pkg["com.example.one"]
        second_icon = dialog._detail_icon_by_pkg["com.example.two"]
        first_checkbox.setCheckState(Qt.CheckState.Checked)

        assert dialog.selected_packages == {"com.example.one"}
        assert first_icon.isSelected() is True
        assert dialog.selection_label.text() == "已选 1 项"
        assert all(button.isEnabled() for button in dialog._selection_action_buttons)

        dialog._toggle_view()
        assert dialog._view_mode is True
        assert first_icon.isSelected() is True

        first_icon.setSelected(False)
        second_icon.setSelected(True)

        assert dialog.selected_packages == {"com.example.two"}
        assert dialog.model.item(0, 0).checkState() == Qt.CheckState.Unchecked
        assert dialog.model.item(1, 0).checkState() == Qt.CheckState.Checked
        assert dialog._get_selected_pkgs() == ["com.example.two"]

        dialog._deselect_all()
        assert dialog.selected_packages == set()
        assert dialog.selection_label.text() == "已选 0 项"
        assert not any(button.isEnabled() for button in dialog._selection_action_buttons)
    finally:
        dialog.close()


def test_app_manager_refreshes_once_after_entire_modify_batch_finishes():
    class BatchDialog:
        pass

    dialog = BatchDialog()
    dialog.device_ip = "device-1"
    dialog.selected_packages = {"com.example.two", "com.example.one"}
    dialog._batch_workers = set()
    dialog._batch_total = 0
    dialog._batch_action = ""
    dialog._closing = False
    dialog._device_selected = True
    dialog._device_connected = True
    dialog._can_operate = lambda: AppManagerPage._can_operate(dialog)
    dialog.log = Mock()
    dialog.status_bar = Mock()
    dialog._track_worker = Mock()
    dialog._update_selection_ui = Mock()
    dialog._load_apps = Mock()
    dialog._get_selected_pkgs = lambda: AppManagerPage._get_selected_pkgs(dialog)
    dialog._on_batch_worker_finished = lambda worker: (
        AppManagerPage._on_batch_worker_finished(dialog, worker)
    )

    workers = [Mock(), Mock()]
    finished_callbacks = []
    for worker in workers:
        worker.finished.connect.side_effect = lambda cb, *_args: finished_callbacks.append(cb)

    with patch("gui.dialogs.app_manager.AppManagerWorker", side_effect=workers) as worker_cls:
        AppManagerPage._modify_selected(dialog, "disable")

    assert worker_cls.call_args_list == [
        call(
            "device-1",
            "modify_app",
            action="disable",
            package_name="com.example.one",
        ),
        call(
            "device-1",
            "modify_app",
            action="disable",
            package_name="com.example.two",
        ),
    ]
    assert dialog._load_apps.call_count == 0
    assert dialog._batch_workers == set(workers)
    assert all(worker.start.call_count == 1 for worker in workers)

    finished_callbacks[0]()
    assert dialog._load_apps.call_count == 0
    assert dialog._batch_workers == {workers[1]}

    finished_callbacks[1]()
    dialog._load_apps.assert_called_once_with()
    assert dialog._batch_workers == set()
    assert dialog._batch_total == 0
    assert dialog._batch_action == ""


def test_app_manager_first_activate_is_lazy_and_duplicate_refreshes_are_coalesced():
    app = QApplication.instance() or QApplication([])
    worker = Mock()
    worker.isRunning.return_value = False
    with patch("gui.dialogs.app_manager.AppManagerWorker", return_value=worker) as worker_cls:
        page = AppManagerPage(device_ip="device-1")
        try:
            worker_cls.assert_not_called()

            page.activate()
            assert worker_cls.call_count == 1
            assert page.load_state == "loading"

            page.retry_load()
            page.retry_load()
            assert worker_cls.call_count == 1
            assert page._load_refresh_pending is True

            page._record_load_success(page._active_load_request, 0)
            page._on_load_worker_finished(page._active_load_request)
            app.processEvents()
            assert worker_cls.call_count == 2
            assert page._load_refresh_pending is False
        finally:
            page.close()


def test_app_manager_load_failure_exposes_retry_state():
    app = QApplication.instance() or QApplication([])
    workers = [Mock(), Mock()]
    for worker in workers:
        worker.isRunning.return_value = False
    with patch("gui.dialogs.app_manager.AppManagerWorker", side_effect=workers) as worker_cls:
        page = AppManagerPage(device_ip="device-1")
        try:
            page.activate()
            request_id = page._active_load_request
            page._on_load_log(request_id, "Failed to list apps: device offline")
            page._on_load_worker_finished(request_id)

            assert page.load_state == "error"
            assert page.load_error_panel.isHidden() is False
            assert "device offline" in page.load_error_label.text()

            page.retry_btn.click()
            assert worker_cls.call_count == 2
            assert page.load_state == "loading"
            assert page.load_error_panel.isHidden() is True
        finally:
            page.close()
            app.processEvents()


def test_app_details_page_loads_on_activate_and_exposes_retry_after_failure():
    app = QApplication.instance() or QApplication([])
    workers = [Mock(), Mock(), Mock(), Mock()]
    for worker in workers:
        worker.isRunning.return_value = False
    with patch(
        "gui.dialogs.app_manager_details.AppManagerWorker",
        side_effect=workers,
    ) as worker_cls:
        page = AppDetailsPage(device_ip="device-1", package_name="com.example.app")
        try:
            worker_cls.assert_not_called()
            page.activate()
            assert worker_cls.call_count == 2
            generation = page._load_generation

            page._on_load_part_finished(generation, "details")
            assert page.load_state == "error"
            assert page.retry_btn.isHidden() is False

            page.retry_btn.click()
            assert worker_cls.call_count == 4
            assert page.load_state == "loading"
            assert page.retry_btn.isHidden() is True
        finally:
            page.close()
            app.processEvents()


def test_app_manager_successful_refresh_preserves_only_valid_selection():
    app = QApplication.instance() or QApplication([])
    page = AppManagerPage(device_ip="device-1")
    try:
        page._populate(
            [
                ("One", "com.example.one", "Enabled", "User"),
                ("Two", "com.example.two", "Enabled", "User"),
            ]
        )
        page._detail_timer.stop()
        page.selected_packages.update({"com.example.one", "com.example.two"})
        page._sync_selection_views()

        page._populate(
            [
                ("Two", "com.example.two", "Disabled", "User"),
                ("Three", "com.example.three", "Enabled", "User"),
            ]
        )
        page._detail_timer.stop()

        assert page.selected_packages == {"com.example.two"}
        assert page.model.item(0, 0).checkState() == Qt.CheckState.Checked
        assert page.model.item(1, 0).checkState() == Qt.CheckState.Unchecked
    finally:
        page.close()
        app.processEvents()


def test_app_manager_master_detail_contract_switches_split_and_stack_modes():
    app = QApplication.instance() or QApplication([])
    page = AppManagerPage(device_ip="device-1")
    try:
        page.resize(1400, 700)
        page.show()
        app.processEvents()
        with patch.object(page.details_page, "_load_data", return_value=True):
            assert page.open_details("com.example.app") is page.details_page
        app.processEvents()

        assert page.master_detail_mode == "split"
        assert page._master_panel.isHidden() is False
        assert page.details_page.isHidden() is False

        page.resize(800, 700)
        app.processEvents()
        assert page.master_detail_mode == "stack"
        assert page._master_panel.isHidden() is True
        assert page.details_page.isHidden() is False

        page.close_details()
        assert page._master_panel.isHidden() is False
        assert page.details_page.isHidden() is True
    finally:
        page.close()
        app.processEvents()


def test_app_manager_reports_workspace_content_minimum_for_visible_master_detail_mode():
    app = QApplication.instance() or QApplication([])
    page = AppManagerPage(device_ip="device-1")
    try:
        page.resize(623, 300)
        page.show()
        app.processEvents()

        master_minimum = page._master_panel.minimumSizeHint()
        assert page.workspace_content_minimum_size() == master_minimum
        assert isinstance(page.workspace_content_minimum_size(), QSize)
        assert page.minimumSize() == QSize(0, 0)

        with patch.object(page.details_page, "_load_data", return_value=True):
            page.open_details("com.example.app")
        app.processEvents()

        detail_minimum = page.details_page.minimumSizeHint()
        assert page.master_detail_mode == "stack"
        assert page.workspace_content_minimum_size() == detail_minimum

        page.resize(1400, 700)
        app.processEvents()
        master_minimum = page._master_panel.minimumSizeHint()
        detail_minimum = page.details_page.minimumSizeHint()
        expected_split = QSize(
            master_minimum.width()
            + detail_minimum.width()
            + page._master_detail_splitter.handleWidth(),
            max(master_minimum.height(), detail_minimum.height()),
        )
        assert page.master_detail_mode == "split"
        assert page.workspace_content_minimum_size() == expected_split

        page.close_details()
        app.processEvents()
        assert page.workspace_content_minimum_size() == page._master_panel.minimumSizeHint()
    finally:
        page.close()
        app.processEvents()


def test_app_manager_dispose_waits_for_worker_then_emits_ready():
    app = QApplication.instance() or QApplication([])
    page = AppManagerPage(device_ip="device-1")
    worker = Mock()
    worker.isRunning.return_value = True
    page._workers.append(worker)
    emitted = []
    page.dispose_ready.connect(lambda: emitted.append(True))
    try:
        assert page.request_dispose("test") is False
        worker.abort.assert_called_once_with()
        assert emitted == []

        worker.isRunning.return_value = False
        page._prune_worker(worker)
        assert emitted == [True]
        assert page._dispose_finalized is True
    finally:
        page.close()
        app.processEvents()


def test_app_manager_offline_state_keeps_cached_content_and_blocks_new_adb_work():
    app = QApplication.instance() or QApplication([])
    page = AppManagerPage(device_ip="device-1")
    try:
        page._populate([("One", "com.example.one", "Enabled", "User")])
        page._detail_timer.stop()
        page.selected_packages.add("com.example.one")
        page._sync_selection_views()
        with patch.object(page.details_page, "_load_data", return_value=True):
            page.open_details("com.example.one")
        page.details_page.detail_text.setPlainText("cached details")

        with patch("gui.dialogs.app_manager.AppManagerWorker") as worker_cls:
            page.set_device_connected(False)
            assert page._load_apps() is False

        buttons = _action_buttons(page)
        assert page.status_badge.text() == "离线"
        assert page.refresh_btn.isEnabled() is False
        assert buttons["卸载所选"].isEnabled() is False
        assert buttons["备份所选"].isEnabled() is False
        assert buttons["恢复备份"].isEnabled() is False
        assert buttons["应用详情"].isEnabled() is False
        assert buttons["创建预设"].isEnabled() is True
        assert buttons["取消全选"].isEnabled() is True
        assert page.model.rowCount() == 1
        assert page.selected_packages == {"com.example.one"}
        assert page.details_page.detail_text.toPlainText() == "cached details"
        assert page.details_page.grant_btn.isEnabled() is False
        worker_cls.assert_not_called()

        page.set_device_connected(True)
        assert page.status_badge.text() == "就绪"
        assert page.refresh_btn.isEnabled() is True
        worker_cls.assert_not_called()
    finally:
        page.close()
        app.processEvents()
