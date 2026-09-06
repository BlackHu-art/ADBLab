"""验证 Performance 单界面、严格输入和运行状态契约。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QWidget,
)
from qfluentwidgets import EditableComboBox, HeaderCardWidget

from core.settings_manager import DEFAULTS, AppSettings
from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.dialogs.performance_launcher import (
    CONFIG_HINTS,
    MONKEY_PERCENT_FIELDS,
)
from gui.features.performance import PerformancePage
from gui.styles import BaseStyles
from services.mobileperf_runner import MobilePerfMonkeyConfig
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_scroll_target_reachable,
    wait_for_stable_geometry,
    wait_until,
)


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


@pytest.fixture(autouse=True)
def isolated_performance_settings(monkeypatch, tmp_path):
    """页面构造只读取本用例设置，数值编辑不能写入开发者的真实配置。"""
    values = dict(DEFAULTS)
    values["save_directory"] = str(tmp_path)
    settings = SimpleNamespace(
        get=values.get,
        set=lambda key, value: values.update({key: value}),
        set_many=values.update,
        save_directory=str(tmp_path),
    )
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))


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


def test_performance_keeps_persistent_configuration_cards_in_one_scroll_owner(
    qt_application,
):
    """窗口缩放不得再切换 compact/wide 宿主或生成无效下拉入口。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.show()
        qt_application.processEvents()
        config_group = dialog.findChild(QWidget, "performanceConfig")
        assert config_group is not None
        assert dialog.findChild(QTabWidget, "performanceCompactTabs") is None
        assert dialog.findChild(QToolButton, "performanceMoreActions") is None
        assert len(dialog._configuration_sections) == 4
        assert all(
            isinstance(section, HeaderCardWidget) for section in dialog._configuration_sections
        )

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


def test_workspace_performance_uses_one_title_and_keeps_actions_visible(qt_application):
    """嵌入时只收起重复页头，启动与停止按钮仍在同一功能页面内。"""

    dialog, _runner = _build_performance_page()
    try:
        start, stop = dialog.start_btn, dialog.stop_btn
        dialog.prepare_for_workspace()
        dialog.prepare_for_workspace()
        dialog.show()
        qt_application.processEvents()
        assert not dialog.dialog_title.isVisible()
        assert not dialog.dialog_subtitle.isVisible()
        assert dialog.start_btn is start and start.isVisible()
        assert dialog.stop_btn is stop and stop.isVisible()
        assert not start.geometry().intersects(stop.geometry())
        assert dialog._config_scroll.isHidden()
        assert all(section.separator.isHidden() for section in dialog._configuration_sections)
    finally:
        dialog.close()


def test_performance_groups_fields_and_results_in_reference_header_cards(qt_application):
    """配置语义与结果分别使用 Fluent 标题卡片，保留可见帮助及直接动作。"""

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
        assert dialog.layout().spacing() == 12
        config_group = dialog.findChild(QWidget, "performanceConfig")
        assert config_group is not None
        assert tuple(section.objectName() for section in dialog._configuration_sections) == (
            "performanceTarget",
            "performanceSampling",
            "performanceOutput",
            "performanceMonkey",
        )
        assert len(config_group.findChildren(HeaderCardWidget)) == 5
        assert {
            label.property("configurationKey")
            for label in config_group.findChildren(QLabel, "fieldLabel")
        } >= {
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
        assert {attr for _label, attr, _option in MONKEY_PERCENT_FIELDS} == set(
            dialog.monkey_pct_inputs
        )
        assert {
            dialog.monkey_check.text(),
            dialog.monkey_ignore_crashes.text(),
            dialog.monkey_ignore_timeouts.text(),
            dialog.monkey_ignore_security.text(),
            dialog.monkey_kill_after_error.text(),
        } == {
            "同时运行 Monkey",
            "忽略应用崩溃",
            "忽略无响应",
            "忽略安全异常",
            "出错后结束 Monkey",
        }
        assert dialog.header_card.isAncestorOf(dialog.start_btn)
        assert dialog.header_card.isAncestorOf(dialog.stop_btn)
        assert dialog._results_group.isAncestorOf(dialog.perfetto_btn)
        assert dialog._results_group.isAncestorOf(dialog.result_btn)
        assert not dialog.start_btn.geometry().intersects(dialog.stop_btn.geometry())
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


def test_performance_bounds_configuration_and_results_in_one_scroll(
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
        assert dialog.log_view.height() >= 180
        assert dialog._results_group.isAncestorOf(dialog.log_view)
        assert_scroll_target_reachable(dialog._config_scroll, dialog.log_view)
        assert dialog.log_view.height() < config_group.height()
    finally:
        dialog.close()


def test_performance_small_window_keeps_configuration_fields_reachable(qt_application):
    """小屏收缩后字段重排，仅通过纵向滚动即可到达。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.setMinimumSize(640, 420)
        dialog.resize(640, 420)
        dialog.show()
        qt_application.processEvents()

        assert dialog.size() == QSize(640, 420)
        assert dialog._config_scroll.verticalScrollBar().maximum() > 0
        assert dialog._config_scroll.horizontalScrollBar().maximum() == 0
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
        dialog.activateWindow()
        field.focus_editor()
        editor.selectAll()
        editor.setText("7")
        for size in (QSize(760, 520), QSize(1500, 850), QSize(1000, 620)):
            dialog.resize(size)
            qt_application.processEvents()
            assert editor.hasFocus()

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

        field.focus_editor()
        QTest.keyClick(field, Qt.Key.Key_Tab)
        assert field.dropButton.hasFocus()
        activated = QSignalSpy(field.dropButton.clicked)
        QTest.keyClick(field.dropButton, Qt.Key.Key_Space)
        wait_until(
            qt_application, lambda: field.dropMenu is not None and field.dropMenu.isVisible()
        )
        assert activated.count() == 1
        assert [action.text() for action in field.dropMenu.actions()] == [
            str(value) for value in field.presets()
        ]
        assert field.dropButton is not None
        assert field.findChild(QToolButton, "presetMenuButton") is None
        field.dropMenu.close()
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


@pytest.mark.parametrize("theme", ("Light", "Dark"))
@pytest.mark.parametrize("font_size", (12, 22))
@pytest.mark.parametrize("width", (420, 640))
def test_performance_cards_reflow_without_horizontal_scroll_or_clipped_controls(
    qt_application, monkeypatch, theme, font_size, width
):
    """窄窗和大字体只需纵向滚动，展开参数与顶部操作保持完整。"""

    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    BaseStyles.switch_theme(theme)
    dialog, _runner = _build_performance_page()
    try:
        dialog.resize(width, 720)
        dialog.show()
        dialog.monkey_check.setChecked(True)
        wait_for_stable_geometry(qt_application, (dialog, dialog._config_group))
        assert dialog.size() == QSize(width, 720)
        assert dialog._config_scroll.horizontalScrollBar().maximum() == 0
        assert not dialog.start_btn.geometry().intersects(dialog.stop_btn.geometry())
        assert_contained(dialog.start_btn, dialog.header_card)
        assert_contained(dialog.stop_btn, dialog.header_card)
        fields = (
            dialog.package_edit,
            dialog.frequency_input,
            dialog.timeout_input,
            dialog.dumpheap_input,
            dialog.phone_log_edit,
            dialog.monkey_seed_input,
            *dialog.monkey_pct_inputs.values(),
        )
        for field in fields:
            assert field.font().pointSize() == font_size
            assert field.height() >= field.fontMetrics().height() + 10
            assert_scroll_target_reachable(dialog._config_scroll, field)
        assert dialog._results_group not in dialog._configuration_sections
    finally:
        dialog.close()


def test_performance_monkey_expansion_keeps_invalid_input_and_shared_scroll_owner(
    qt_application,
):
    """折叠可选配置保留原文，嵌入工作区不会保留第二层配置滚动视口。"""

    dialog, _runner = _build_performance_page()
    workspace = QScrollArea()
    workspace.setWidgetResizable(True)
    try:
        dialog.prepare_for_workspace()
        dialog.prepare_for_workspace()
        workspace.setWidget(dialog)
        workspace.resize(640, 720)
        workspace.show()
        dialog.monkey_check.setChecked(True)
        field = dialog.monkey_pct_inputs["pct_touch"]
        field.setText("101")
        dialog.monkey_check.setChecked(False)
        assert not dialog._monkey_details.isVisibleTo(dialog)
        dialog.monkey_check.setChecked(True)
        wait_for_stable_geometry(qt_application, (workspace, dialog, dialog._config_group))
        assert dialog.monkey_pct_inputs["pct_touch"] is field
        assert field.text() == "101"
        assert not field.input_is_acceptable()
        assert dialog._config_scroll.widget() is None
        assert not dialog._config_scroll.isVisibleTo(dialog)
        assert workspace.horizontalScrollBar().maximum() == 0
        assert_scroll_target_reachable(workspace, dialog.phone_log_edit)
        assert_scroll_target_reachable(workspace, dialog.log_view)
    finally:
        dialog.close()
        workspace.close()


def test_performance_result_view_switch_keeps_large_font_chart_plot_readable(
    qt_application, monkeypatch
):
    """图表高度随界面字体扩展，切回日志恢复独立字号和视口高度。"""

    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 22)
    dialog, _runner = _build_performance_page()
    try:
        dialog.resize(900, 720)
        dialog.show()
        dialog.log_view.setPlainText("保留日志内容")
        log_height = dialog._chart_stack.height()
        dialog.chart_view.set_series({"CPU": [(0, 10), (1, 30), (2, 20)]})
        dialog._chart_stack.setCurrentIndex(1)
        wait_for_stable_geometry(qt_application, (dialog, dialog._chart_stack))
        assert dialog._chart_stack.height() > log_height
        assert dialog.chart_view._chart.plotArea().height() >= 100
        assert_scroll_target_reachable(dialog._config_scroll, dialog.chart_view)
        for theme in ("Dark", "Light"):
            BaseStyles.switch_theme(theme)
            assert all(
                axis.labelsColor().name() == BaseStyles.color("TEXT_SECONDARY").lower()
                for axis in dialog.chart_view._chart.axes()
            )
        dialog._chart_stack.setCurrentIndex(0)
        assert dialog._chart_stack.height() == log_height
        assert dialog.log_view.toPlainText() == "保留日志内容"
    finally:
        dialog.close()
