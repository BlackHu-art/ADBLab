import os
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QGridLayout, QPushButton

from gui.dialogs.app_manager import AppManagerDialog
from gui.styles import BaseStyles
from gui.styles.typography import FontRole
from tests.ui_geometry_helpers import assert_non_overlapping

_SELECTION_ACTIONS = (
    "Uninstall Selected",
    "Disable Selected",
    "Enable Selected",
    "Deselect All",
)
_PRESET_ACTIONS = (
    "Create Preset",
    "Load Preset",
    "Backup Selected",
    "Restore Backup",
    "App Details",
)


def _app_manager_dialog():
    app = QApplication.instance() or QApplication([])
    with patch.object(AppManagerDialog, "_load_apps"):
        dialog = AppManagerDialog(device_ip="device-1")
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


def test_app_manager_top_controls_fit_at_776_and_768_with_22pt(monkeypatch):
    current_size = {"ui": 22}
    _patch_font_size(monkeypatch, current_size)
    app, dialog = _app_manager_dialog()
    geometry_failures = []
    bounds_failures = []
    signatures = []
    try:
        dialog.show()
        for width in (776, 768):
            # qfluentwidgets ComboBox 比原生 QComboBox 窄，顶部控件在 768px
            # 以下会触发五列重排并把 "Selected: 0" 标签压到最小宽度以下；
            # 断点随收敛上移 8px。qfluentwidgets 控件行高比原生高，22pt 下
            # 660px 高会让顶部控件溢出布局，高度升到 700 后恢复完整落位。
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
    app, dialog = _app_manager_dialog()
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

        _fresh_app, fresh_dialog = _app_manager_dialog()
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
    app, dialog = _app_manager_dialog()
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
                buttons["Disable Selected"].geometry().right()
                - dialog._selection_action_layout.geometry().right()
            )
            <= 2
        )
        assert (
            abs(
                buttons["App Details"].geometry().right()
                - dialog._preset_action_layout.geometry().right()
            )
            <= 2
        )
        assert [buttons[label].text() for label in _SELECTION_ACTIONS] == [
            "Uninstall",
            "Disable",
            "Enable",
            "Clear",
        ]
        assert [buttons[label].text() for label in _PRESET_ACTIONS] == [
            "Save",
            "Load",
            "Backup",
            "Restore",
            "Details",
        ]
        _assert_buttons_fit(dialog, buttons)
        # 视觉重设计映射：页头卡片固定占用约 60px 纵向空间，600px/22pt 下
        # 栈区（应用列表/图标视图）可用高度从约 127px 降到约 64px；
        # 下界相应重映射，仍保证列表区域不会塌缩消失。
        assert dialog.stack.height() >= 60
    finally:
        dialog.close()


def test_app_manager_short_action_labels_keep_full_accessibility_semantics_when_narrow():
    app, dialog = _app_manager_dialog()
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
            "Uninstall",
            "Disable",
            "Enable",
            "Clear",
        ]
        assert [buttons[label].text() for label in _PRESET_ACTIONS] == [
            "Save",
            "Load",
            "Backup",
            "Restore",
            "Details",
        ]
        expected_help = {
            "Uninstall Selected": "Remove the selected applications",
            "Disable Selected": "Disable the selected applications",
            "Enable Selected": "Enable the selected applications",
            "Deselect All": "Clear the application selection",
            "Create Preset": "Save the selected package list as a preset",
            "Load Preset": "Select applications from a saved preset",
            "Backup Selected": "Back up the selected applications",
            "Restore Backup": "Restore applications from a backup",
            "App Details": "Show details for the selected application",
        }
        for accessible_name, button in buttons.items():
            assert button.toolTip() == expected_help[accessible_name]
            assert button.accessibleDescription() == expected_help[accessible_name]
        details_index = dialog._preset_action_layout.indexOf(buttons["App Details"])
        _row, column, _row_span, column_span = dialog._preset_action_layout.getItemPosition(
            details_index
        )
        assert column == 0
        assert column_span == 2
        _assert_buttons_fit(dialog, buttons)
    finally:
        dialog.close()


def test_app_manager_restores_full_actions_without_rebuilding_buttons_or_duplicate_clicks():
    class TrackingDialog(AppManagerDialog):
        deselect_calls = 0

        def _deselect_all(self):
            self.deselect_calls += 1

    app = QApplication.instance() or QApplication([])
    with patch.object(TrackingDialog, "_load_apps"):
        dialog = TrackingDialog(device_ip="device-1")

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
        wide_buttons["Deselect All"].setEnabled(True)
        wide_buttons["Deselect All"].click()
        assert dialog.deselect_calls == 1
    finally:
        dialog.close()


def test_app_manager_keeps_table_and_icon_selection_in_sync():
    _app = QApplication.instance() or QApplication([])
    with patch.object(AppManagerDialog, "_load_apps"):
        dialog = AppManagerDialog(device_ip="device-1")

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
        assert dialog.selection_label.text() == "Selected: 1"
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
        assert dialog.selection_label.text() == "Selected: 0"
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
    dialog.log = Mock()
    dialog.status_bar = Mock()
    dialog._track_worker = Mock()
    dialog._update_selection_ui = Mock()
    dialog._load_apps = Mock()
    dialog._confirm_dangerous_action = Mock(return_value=True)
    dialog._get_selected_pkgs = lambda: AppManagerDialog._get_selected_pkgs(dialog)
    dialog._on_batch_worker_finished = lambda worker: (
        AppManagerDialog._on_batch_worker_finished(dialog, worker)
    )

    workers = [Mock(), Mock()]
    finished_callbacks = []
    for worker in workers:
        worker.finished.connect.side_effect = lambda cb, *_args: finished_callbacks.append(cb)

    with patch("gui.dialogs.app_manager.AppManagerWorker", side_effect=workers) as worker_cls:
        AppManagerDialog._modify_selected(dialog, "disable")

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
