"""验证 Performance 单界面、严格输入和运行状态契约。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTabWidget,
    QToolButton,
)
from qfluentwidgets import EditableComboBox, HeaderCardWidget

from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.dialogs.performance_launcher import (
    CONFIG_HINTS,
    MONKEY_PERCENT_FIELDS,
)
from gui.features.performance import PerformancePage
from gui.styles import BaseStyles
from services.mobileperf_runner import MobilePerfMonkeyConfig
from tests.ui_geometry_helpers import assert_contained, assert_scroll_target_reachable


@dataclass
class _RunnerProbe:
    """记录启动边界收到的配置，不模拟外部进程。"""

    start_count: int = 0
    started_config: object | None = None

    def start(self, config, **_callbacks) -> None:
        self.start_count += 1
        self.started_config = config

    @staticmethod
    def is_running() -> bool:
        return False

    @staticmethod
    def latest_result_dir() -> str:
        return ""

    @staticmethod
    def latest_report_file() -> str:
        return ""


def _build_performance_page(*, package: str = "com.example"):
    dialog = PerformancePage(device_ip="device-1", package_name=package)
    runner = _RunnerProbe()
    dialog._runner = runner
    return dialog, runner


def _editor(field) -> QLineEdit:
    if isinstance(field, QLineEdit):
        return field
    editor = field.findChild(QLineEdit)
    assert editor is not None
    return editor


def test_performance_numeric_aliases_use_original_dropdown_style_with_strict_values(
    qt_application,
):
    """分页前数字下拉框保留严格整数接口，且不出现上下微调按钮。"""

    dialog, _runner = _build_performance_page()
    defaults = MobilePerfMonkeyConfig()
    try:
        preset_contract = (
            ("frequency_input", "frequency_combo", 5, (1, 2, 5, 10)),
            ("timeout_input", "timeout_combo", 600, (10, 30, 60, 120, 600, 4320)),
            ("dumpheap_input", "dumpheap_combo", 60, (5, 10, 30, 60, 120)),
            (
                "monkey_throttle_input",
                "monkey_throttle_combo",
                500,
                (100, 200, 300, 500, 1000, 2000),
            ),
        )
        for canonical_name, compatibility_name, value, presets in preset_contract:
            canonical = getattr(dialog, canonical_name)
            assert canonical is getattr(dialog, compatibility_name)
            assert isinstance(canonical, EditableComboBox)
            assert canonical.value() == value
            assert canonical.presets() == presets

        assert dialog.frequency_unit_label.text() == "s"
        assert dialog.timeout_unit_label.text() == "min"
        assert dialog.dumpheap_unit_label.text() == "min"
        assert dialog.monkey_throttle_unit_label.text() == "ms"
        assert dialog.monkey_seed_input is dialog.monkey_seed_edit
        assert isinstance(dialog.monkey_seed_input, QLineEdit)
        assert dialog.monkey_seed_input.value() == defaults.seed
        assert dialog.monkey_pct_inputs is dialog.monkey_pct_combos
        for attr, field in dialog.monkey_pct_inputs.items():
            assert isinstance(field, EditableComboBox)
            assert field.value() == getattr(defaults, attr)
            assert field.minimum() == 0
            assert field.maximum() == 100
        assert dialog.findChildren(QAbstractSpinBox) == []
        assert dialog.findChild(QToolButton, "presetMenuButton") is None
    finally:
        dialog.close()


def test_performance_uses_one_persistent_configuration_group_without_tabs_or_more(
    qt_application,
):
    """窗口缩放不得再切换 compact/wide 宿主或生成无效下拉入口。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.show()
        qt_application.processEvents()
        config_group = dialog.findChild(HeaderCardWidget, "performanceConfig")
        assert config_group is not None
        assert dialog.findChild(QTabWidget, "performanceCompactTabs") is None
        assert dialog.findChild(QToolButton, "performanceMoreActions") is None
        assert dialog._configuration_sections == (config_group,)

        section_ids = tuple(map(id, dialog._configuration_sections))
        for size in (
            QSize(940, 700),
            QSize(1500, 900),
            QSize(1100, 760),
        ):
            dialog.resize(size)
            qt_application.processEvents()
            assert dialog.size() == size
            assert tuple(map(id, dialog._configuration_sections)) == section_ids
            assert all(
                button.isVisibleTo(dialog)
                for button in (
                    dialog.perfetto_btn,
                    dialog.result_btn,
                    dialog.stop_btn,
                    dialog.start_btn,
                )
            )
            assert dialog.findChildren(QScrollArea) == [dialog._config_scroll]
            assert dialog._config_scroll.widget() is config_group
            assert dialog._config_scroll.verticalScrollBar().maximum() > 0
            assert_scroll_target_reachable(dialog._config_scroll, dialog.phone_log_edit)
    finally:
        dialog.close()


def test_performance_uses_one_reference_header_card_for_configuration(qt_application):
    """扩展功能保持单配置区，并直接使用参考项目的标题卡片。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.show()
        qt_application.processEvents()

        margins = dialog.layout().contentsMargins()
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
            10,
            10,
            10,
            10,
        )
        assert dialog.layout().spacing() == 8
        config_group = dialog.findChild(HeaderCardWidget, "performanceConfig")
        assert config_group is not None
        assert config_group.findChildren(HeaderCardWidget) == []
        assert {label.text() for label in config_group.findChildren(QLabel, "fieldLabel")} >= {
            "package",
            "serialnum",
            "frequency",
            "timeout",
            "dumpheap_freq",
            "exceptionlog",
            "monkey",
            "save_path",
            "phone_log_path",
        }
        hints = config_group.findChildren(QLabel, "configHint")
        assert len(hints) == 9
        assert all(label.wordWrap() and label.text().strip() for label in hints)
        visible_monkey_labels = {
            label.text() for label in config_group.findChildren(QLabel, "inlineLabel")
        }
        assert {label for label, _attr, _option in MONKEY_PERCENT_FIELDS} <= visible_monkey_labels
        assert {
            dialog.monkey_check.text(),
            dialog.monkey_ignore_crashes.text(),
            dialog.monkey_ignore_timeouts.text(),
            dialog.monkey_ignore_security.text(),
            dialog.monkey_kill_after_error.text(),
        } == {
            "Enable monkey",
            "Ignore crashes",
            "Ignore timeouts",
            "Ignore security",
            "Kill after error",
        }
        action_widgets = (
            dialog.status_label,
            dialog.progress_bar,
            dialog.perfetto_btn,
            dialog.result_btn,
            dialog.stop_btn,
            dialog.start_btn,
        )
        assert all(widget.parentWidget() is dialog._action_row for widget in action_widgets)
        assert [widget.x() for widget in action_widgets] == sorted(
            widget.x() for widget in action_widgets
        )
    finally:
        dialog.close()


def test_performance_restores_visible_previous_version_hints(qt_application):
    """旧版关键提示不能只藏在 tooltip 中，单界面必须直接展示。"""

    dialog, _runner = _build_performance_page()
    try:
        visible_hints = {
            label.text()
            for label in dialog.findChildren(QLabel, "configHint")
            if label.text().strip()
        }
        assert {
            CONFIG_HINTS["package"],
            CONFIG_HINTS["frequency"],
            CONFIG_HINTS["timeout"],
            CONFIG_HINTS["dumpheap_freq"],
            CONFIG_HINTS["exceptionlog"],
            CONFIG_HINTS["save_path"],
            CONFIG_HINTS["phone_log_path"],
        } <= visible_hints
    finally:
        dialog.close()


def test_performance_bounds_configuration_in_scroll_and_uses_short_log(
    qt_application,
    monkeypatch,
):
    """配置卡不再顶高窗口，全部字段仍可滚动到达。"""

    monkeypatch.setattr(
        BaseStyles,
        "font_for_role",
        classmethod(lambda _cls, _role, size=None: QFont("Arial", size or 12)),
    )
    dialog, _runner = _build_performance_page()
    try:
        dialog.resize(1200, 900)
        dialog.show()
        for _index in range(4):
            qt_application.processEvents()

        assert dialog.width() <= 1200
        assert dialog.height() == 900
        config_group = dialog._config_group
        assert dialog.findChildren(QScrollArea) == [dialog._config_scroll]
        assert dialog._config_scroll.widget() is config_group
        assert config_group.isVisibleTo(dialog)
        assert_contained(dialog._config_scroll, dialog)
        assert dialog._config_scroll.verticalScrollBar().maximum() > 0
        assert_scroll_target_reachable(dialog._config_scroll, dialog.package_edit)
        assert_scroll_target_reachable(dialog._config_scroll, dialog.phone_log_edit)
        assert dialog.log_view.height() <= 110
        assert dialog.log_view.height() < config_group.height()
    finally:
        dialog.close()


def test_performance_small_window_keeps_configuration_fields_reachable(qt_application):
    """小屏收缩后配置区同时提供纵向与横向到达路径。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.setMinimumSize(640, 420)
        dialog.resize(640, 420)
        dialog.show()
        qt_application.processEvents()

        assert dialog.size() == QSize(640, 420)
        assert dialog._config_scroll.verticalScrollBar().maximum() > 0
        assert dialog._config_scroll.horizontalScrollBar().maximum() > 0
        assert_scroll_target_reachable(dialog._config_scroll, dialog.package_edit)
        assert_scroll_target_reachable(dialog._config_scroll, dialog.phone_log_edit)
    finally:
        dialog.close()


def test_start_commits_focused_valid_number_before_building_config(
    qt_application,
    monkeypatch,
):
    """焦点字段的有效原文必须在 Start 边界统一提交。"""

    dialog, runner = _build_performance_page()
    monkeypatch.setattr(FluentMessageBox, "warning", lambda *_args, **_kwargs: None)
    try:
        editor = _editor(dialog.frequency_input)
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        editor.selectAll()
        editor.setText("7")
        qt_application.processEvents()

        dialog.start_mobileperf()

        assert runner.start_count == 1
        assert runner.started_config.frequency_seconds == 7
        assert dialog.frequency_input.value() == 7
    finally:
        dialog._set_running(False)
        dialog.close()


def test_monkey_total_ignores_disabled_invalid_then_restores_invalid_state(qt_application):
    """禁用 Monkey 只忽略非法值，重新启用后仍恢复原文和错误状态。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.monkey_check.setChecked(True)
        field = dialog.monkey_pct_combos["pct_touch"]
        editor = _editor(field)
        editor.setText("101")
        assert dialog.monkey_total_label.text() == "Total: Invalid"

        dialog.monkey_check.setChecked(False)
        assert dialog.monkey_total_label.text() == "Total: 100%"
        dialog.monkey_check.setChecked(True)

        assert editor.text() == "101"
        assert dialog.monkey_total_label.text() == "Total: Invalid"
    finally:
        dialog.close()


def test_start_checks_all_enabled_fields_before_committing_any_value(
    qt_application,
    monkeypatch,
):
    """后续字段失败时不得留下前面字段的半提交配置。"""

    dialog, runner = _build_performance_page()
    monkeypatch.setattr(FluentMessageBox, "warning", lambda *_args, **_kwargs: None)
    try:
        dialog.show()
        qt_application.processEvents()
        frequency_editor = _editor(dialog.frequency_input)
        timeout_editor = _editor(dialog.timeout_input)
        frequency_editor.setText("7")
        timeout_editor.setText("bad")

        dialog.start_mobileperf()
        qt_application.processEvents()

        assert runner.start_count == 0
        assert dialog.frequency_input.value() == 5
        assert frequency_editor.text() == "7"
        assert timeout_editor.text() == "bad"
        assert timeout_editor.hasFocus()
    finally:
        dialog.close()


def test_disabled_invalid_monkey_value_does_not_block_and_survives_reenable(
    qt_application,
    monkeypatch,
):
    """关闭 Monkey 后非法子项不阻止启动，也不清除用户原文。"""

    dialog, runner = _build_performance_page()
    monkeypatch.setattr(FluentMessageBox, "warning", lambda *_args, **_kwargs: None)
    try:
        dialog.monkey_check.setChecked(True)
        field = dialog.monkey_pct_combos["pct_touch"]
        editor = _editor(field)
        editor.setText("101")

        dialog.start_mobileperf()
        assert runner.start_count == 0
        dialog.monkey_check.setChecked(False)
        dialog.start_mobileperf()
        assert runner.start_count == 1

        dialog._set_running(False)
        dialog.monkey_check.setChecked(True)
        assert editor.text() == "101"
        assert field.input_is_acceptable() is False
    finally:
        dialog._set_running(False)
        dialog.close()


def test_single_layout_preserves_focus_identity_and_signal_count(qt_application):
    """尺寸往返不得重建输入控件、丢失原文或重复连接信号。"""

    dialog, _runner = _build_performance_page()
    field = dialog.frequency_input
    editor = _editor(field)
    committed = QSignalSpy(field.valueChanged)
    try:
        dialog.show()
        field.focus_editor()
        editor.selectAll()
        editor.setText("7")
        for size in (QSize(760, 520), QSize(1500, 850), QSize(1000, 620)):
            dialog.resize(size)
            qt_application.processEvents()

        assert dialog.frequency_input is field
        assert _editor(dialog.frequency_input) is editor
        assert editor.text() == "7"
        assert field.commit_value() is True
        assert field.value() == 7
        assert committed.count() == 1
    finally:
        dialog.close()


def test_original_dropdown_remains_keyboard_reachable_without_extra_button(qt_application):
    """数字预设使用 EditableComboBox 自带下拉按钮，且不出现额外 presetMenuButton。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.show()
        field = dialog.frequency_input
        qt_application.processEvents()

        # EditableComboBox 自带 dropButton（LineEditButton），可 Tab 聚焦后回车展开下拉。
        assert field.dropButton is not None
        assert field.findChild(QToolButton, "presetMenuButton") is None
    finally:
        dialog.close()


def test_running_locks_only_configuration_and_keeps_log_and_actions_available(
    qt_application,
):
    """运行锁只覆盖配置叶区，日志、状态和停止入口保持可用。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.show()
        dialog._set_running(True)
        qt_application.processEvents()

        assert all(not section.isEnabled() for section in dialog._configuration_sections)
        assert dialog.log_view.isEnabled()
        assert dialog.status_label.isEnabled()
        assert dialog.progress_bar.isEnabled()
        assert dialog.stop_btn.isEnabled()
        assert not dialog.start_btn.isEnabled()

        dialog._set_running(False)
        assert all(section.isEnabled() for section in dialog._configuration_sections)
    finally:
        dialog._set_running(False)
        dialog.close()


def test_late_package_callbacks_do_not_mutate_or_unlock_running_configuration(
    qt_application,
):
    """启动后的晚到包名结果不得改写本次运行配置。"""

    dialog, _runner = _build_performance_page(package="com.before")

    class _FinishedWorker:
        def deleteLater(self):
            return None

    worker = _FinishedWorker()
    dialog._package_worker = worker
    try:
        dialog._set_running(True)
        dialog._on_current_package("com.late")
        dialog._on_package_worker_finished(worker)

        assert dialog.package_edit.text() == "com.before"
        assert not dialog.get_package_btn.isEnabled()
    finally:
        dialog._set_running(False)
        dialog.close()


def test_direct_action_buttons_share_canonical_actions(monkeypatch, qt_application):
    """直接按钮保留 QAction 状态同步，且每次点击只调用一次业务入口。"""

    dialog, _runner = _build_performance_page()
    opened = {"perfetto": 0, "result": 0}
    monkeypatch.setattr(
        dialog,
        "open_perfetto",
        lambda: opened.__setitem__("perfetto", opened["perfetto"] + 1),
    )
    monkeypatch.setattr(
        dialog,
        "open_result",
        lambda: opened.__setitem__("result", opened["result"] + 1),
    )
    try:
        dialog.result_action.setEnabled(True)
        dialog.perfetto_btn.click()
        dialog.result_btn.click()

        assert opened == {"perfetto": 1, "result": 1}
        assert dialog.perfetto_btn.toolTip() == dialog.perfetto_action.toolTip()
        assert dialog.result_btn.isEnabled() == dialog.result_action.isEnabled()
    finally:
        dialog.close()


def test_result_availability_updates_canonical_action(tmp_path, qt_application):
    """结果可用状态由 canonical QAction 发布，并同步到直接按钮。"""

    result_root = tmp_path / "result"
    result_root.mkdir()
    dialog, _runner = _build_performance_page()
    try:
        dialog._last_result_root = str(result_root)
        dialog._update_result_action()
        assert dialog.result_action.isEnabled()
        assert dialog.result_btn.isEnabled()

        dialog._last_result_root = ""
        dialog._update_result_action()
        assert not dialog.result_action.isEnabled()
        assert not dialog.result_btn.isEnabled()
    finally:
        dialog.close()
