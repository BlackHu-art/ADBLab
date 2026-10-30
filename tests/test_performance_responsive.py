"""验证 Performance 单界面、严格输入和运行状态契约。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    EditableComboBox,
    FluentIcon,
    HeaderCardWidget,
    PlainTextEdit,
    SmoothScrollArea,
)
from shiboken6 import isValid

from core.settings_manager import DEFAULTS, AppSettings
from gui.dialogs.fluent_dialog import FluentMessageBox
from gui.dialogs.performance_launcher import (
    CONFIG_HINTS,
    MONKEY_PERCENT_FIELDS,
    CurrentPackageWorker,
)
from gui.features.performance import PerformancePage
from gui.pages.workspace_features import WorkspaceFeatureHost
from gui.styles import BaseStyles
from gui.widgets.collapsible_tools import CollapsibleTools
from gui.widgets.frame_animation import FrameAnimation
from services.mobileperf_runner import MobilePerfMonkeyConfig
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    assert_scroll_target_reachable,
    mapped_rect,
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
    def has_active_resources() -> bool:
        return False

    @staticmethod
    def is_current_run_complete() -> bool:
        return True

    @staticmethod
    def wait(timeout: float) -> bool:
        return True

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


def test_monkey_reveal_clips_full_layout_and_reverses_without_resetting_values(qt_application):
    page, _runner = _build_performance_page()
    try:
        page.resize(980, 900)
        page.show()
        qt_application.processEvents()
        page.monkey_check.setChecked(True)
        reveal = page._monkey_reveal
        assert reveal.animation.state() == QAbstractAnimation.State.Running
        qt_application.processEvents()
        reveal.animation.setCurrentTime(reveal.animation.duration() // 2)
        full_height = page._monkey_details.height()
        assert 0 < reveal.height() < full_height
        field = page.monkey_seed_edit
        position = field.mapTo(page._monkey_details, QPoint())
        field.setText("123456")
        height = reveal.height()
        page.monkey_check.setChecked(False)
        assert reveal.height() == height
        assert not field.isEnabled()
        reveal.animation.setCurrentTime(reveal.animation.duration() // 2)
        assert reveal.height() < height
        assert page._monkey_details.height() == full_height
        assert field.mapTo(page._monkey_details, QPoint()) == position
        page.monkey_check.setChecked(True)
        reveal.animation.setCurrentTime(reveal.animation.duration())
        assert reveal.height() == page._monkey_details.height()
        assert field.text() == "123456"
        assert field.isEnabled()
        page.monkey_check.setChecked(False)
        page.hide()
        assert reveal.animation.state() == QAbstractAnimation.State.Stopped
        assert reveal.height() == 0 and page._monkey_details.isHidden()
    finally:
        page.close()


def _editor(field) -> QLineEdit:
    if isinstance(field, QLineEdit):
        return field
    editor = field.findChild(QLineEdit)
    assert editor is not None
    return editor


def _wait_for_monkey_reveal(app, dialog):
    """终态布局断言先等待真实动画结束，中间帧测试仍单独推进时钟。"""
    wait_until(app, lambda: dialog._monkey_reveal.animation.state()
               == QAbstractAnimation.State.Stopped)


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
        assert len(dialog._configuration_sections) == 1
        assert not isinstance(dialog._diagnostic_tools, CollapsibleTools)
        assert all(field.isVisibleTo(dialog) for field in (
            dialog.dumpheap_input, dialog.exception_edit, dialog.phone_log_edit,
        ))

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
            assert dialog.findChildren(QScrollArea) == [
                dialog._config_scroll, dialog.chart_view._chart_scroll,
            ]
            assert not dialog.chart_view._chart_scroll.isVisibleTo(dialog)
            assert dialog.chart_view._chart_scroll.widget() is dialog.chart_view._chart_view
            assert dialog._config_scroll.widget() is config_group
            qt_application.processEvents()
            diagnostic_fields = (
                dialog.dumpheap_input, dialog.exception_edit, dialog.phone_log_edit,
            )
            assert all(field.isVisibleTo(dialog) for field in diagnostic_fields)
            assert_non_overlapping(diagnostic_fields, dialog._diagnostic_tools)
            # 标签改为同行后按整组宽度减少列数，不能为保持三列而压缩或换行标签。
            for label in dialog._diagnostic_tools.findChildren(QLabel, "fieldLabel"):
                assert not label.wordWrap()
                title_rect = mapped_rect(label, dialog._diagnostic_tools)
                field_rect = mapped_rect(label.buddy(), dialog._diagnostic_tools)
                assert title_rect.right() < field_rect.left()
                assert abs(title_rect.center().y() - field_rect.center().y()) <= 2
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
        content_margins = dialog._config_group.layout().contentsMargins()
        assert (content_margins.left(), content_margins.right()) == (32, 32)
        for section in (*dialog._configuration_sections, dialog._results_group):
            title_margins = section.headerLayout.contentsMargins()
            body_margins = section.viewLayout.contentsMargins()
            assert (title_margins.left(), title_margins.right()) == (0, 0)
            assert (body_margins.left(), body_margins.right()) == (0, 0)
            assert section.headerView.height() == section.headerLayout.sizeHint().height()
        assert all(
            isinstance(section, HeaderCardWidget) for section in dialog._configuration_sections
        )
        assert not dialog._device_context.isVisible()
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
            0,
            0,
            0,
            0,
        )
        assert dialog.layout().spacing() == 12
        config_group = dialog.findChild(QWidget, "performanceConfig")
        assert config_group is not None
        assert tuple(section.objectName() for section in dialog._configuration_sections) == (
            "performanceTarget",
        )
        assert len(config_group.findChildren(HeaderCardWidget)) == 2
        for card in config_group.findChildren(HeaderCardWidget):
            assert card.headerLabel.property("fontRole") == "ui"
            assert card.headerLabel.font().bold()
            assert card.viewLayout.contentsMargins().left() == 0
            assert card.viewLayout.spacing() == 8
        assert {
            label.property("configurationKey")
            for label in config_group.findChildren(QLabel, "fieldLabel")
        } >= {
            "package",
            "frequency",
            "timeout",
            "dumpheap_freq",
            "exceptionlog",
            "save_path",
            "phone_log_path",
        }
        assert all(
            not label.font().bold()
            for label in config_group.findChildren(QLabel, "fieldLabel")
        )
        assert dialog._configuration_sections[0].isAncestorOf(dialog._diagnostic_tools)
        assert dialog._configuration_sections[0].isAncestorOf(dialog.monkey_check)
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


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_performance_sections_inherit_blank_surface_but_keep_log_reading_background(
    qt_application, theme,
):
    """真实像素区分结构底板与阅读底板，悬停和主题往返不能重新叠加卡片白层。"""

    original_theme = BaseStyles.current_theme()
    BaseStyles.switch_theme(theme)
    host = QWidget()
    base = QColor("#b8cad8" if theme == "Light" else "#243849")
    palette = host.palette()
    palette.setColor(QPalette.ColorRole.Window, base)
    host.setPalette(palette)
    host.setAutoFillBackground(True)
    host.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    reference_host = QWidget()
    reference_host.setPalette(palette)
    reference_host.setAutoFillBackground(True)
    reference_host.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    reference = PlainTextEdit(reference_host)
    reference.setReadOnly(True)
    QVBoxLayout(reference_host).addWidget(reference)
    reference_host.resize(250, 180)
    dialog, _runner = _build_performance_page()
    layout = QVBoxLayout(host)
    layout.addWidget(dialog)
    dialog.prepare_for_workspace()
    dialog.log_view.clear()
    host.resize(1200, 1250)
    host.show()
    try:
        wait_for_stable_geometry(qt_application, (host, dialog, dialog._results_group))
        for current_theme in (theme, "Dark" if theme == "Light" else "Light", theme):
            BaseStyles.switch_theme(current_theme)
            # 无云母的阅读框沿用 Fluent 原生绘制，在相同底色及焦点/悬停态下对照。
            reference_host.show()
            qt_application.setActiveWindow(reference_host)
            reference_host.setFocus()
            qt_application.processEvents()
            for control in (reference, reference.viewport()):
                qt_application.sendEvent(control, QEvent(QEvent.Type.Leave))
                assert not control.underMouse()
            assert not reference.hasFocus()
            reference_image = reference_host.grab().toImage()
            reference_point = reference.viewport().mapTo(
                reference_host, QPoint(3, reference.viewport().height() // 2),
            )
            reference_scale = reference_image.devicePixelRatio()
            expected_background = reference_image.pixelColor(
                round(reference_point.x() * reference_scale),
                round(reference_point.y() * reference_scale),
            )
            reference_host.hide()
            qt_application.setActiveWindow(host)
            host.setFocus()
            QTest.mouseMove(dialog._action_row, QPoint(4, 10))
            QTest.qWait(180)
            for control in (dialog.log_view, dialog.log_view.viewport()):
                qt_application.sendEvent(control, QEvent(QEvent.Type.Leave))
                assert not control.underMouse()
            assert not dialog.log_view.hasFocus()
            # 页头右侧现在容纳功能按钮，取左上留白验证结构透明，避开按钮和字形。
            plan = dialog._configuration_sections[0]
            results = dialog._results_group
            for section in (plan, results):
                assert section.width() - 4 > section.headerLabel.fontMetrics().horizontalAdvance(
                    section.headerLabel.text()
                )
            surfaces = {
                "actions": (dialog._action_row, QPoint(4, 10)),
                "plan_header": (plan.headerView, QPoint(1, 1)),
                "plan_body": (dialog._configuration_sections[0].view, QPoint(4, 2)),
                "results_header": (results.headerView, QPoint(1, 1)),
                "results_body": (dialog._results_group.view, QPoint(4, 2)),
                "progress_container": (dialog.progress_display.indicators, QPoint(2, 2)),
            }
            image = host.grab().toImage()
            scale = image.devicePixelRatio()
            colors = {}
            for name, (widget, point) in surfaces.items():
                position = widget.mapTo(host, point)
                colors[name] = image.pixelColor(
                    round(position.x() * scale), round(position.y() * scale)
                ).name()
            assert set(colors.values()) == {base.name()}, colors
            for section in (*dialog._configuration_sections, dialog._results_group):
                assert not section.separator.isVisible()
            viewport = dialog.log_view.viewport()
            position = viewport.mapTo(host, QPoint(3, viewport.height() // 2))
            log_background = image.pixelColor(
                round(position.x() * scale), round(position.y() * scale)
            )
            assert log_background != base
            assert log_background == expected_background
    finally:
        dialog.close()
        host.close()
        reference_host.close()
        reference_host.deleteLater()
        BaseStyles.switch_theme(original_theme)


def test_performance_keeps_configuration_help_on_fields_and_accessibility(qt_application):
    """收起常驻说明后，字段与无障碍描述仍提供完整输入规则。"""

    dialog, _runner = _build_performance_page()
    try:
        for key, field in (
            ("package", dialog.package_edit),
            ("frequency", dialog.frequency_input),
            ("timeout", dialog.timeout_input),
            ("dumpheap_freq", dialog.dumpheap_input),
            ("exceptionlog", dialog.exception_edit),
            ("save_path", dialog.save_path_edit),
            ("phone_log_path", dialog.phone_log_edit),
            ("monkey", dialog.monkey_check),
        ):
            assert CONFIG_HINTS[key] in field.toolTip()
            assert CONFIG_HINTS[key] in field.accessibleDescription()
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
        assert dialog.findChildren(QScrollArea) == [
            dialog._config_scroll, dialog.chart_view._chart_scroll,
        ]
        assert not dialog.chart_view._chart_scroll.isVisibleTo(dialog)
        assert dialog.chart_view._chart_scroll.widget() is dialog.chart_view._chart_view
        assert dialog._config_scroll.widget() is config_group
        assert config_group.isVisibleTo(dialog)
        assert_contained(dialog._config_scroll, dialog)
        assert dialog._configuration_group.x() == dialog._results_group.x()
        assert dialog._results_group.y() > dialog._configuration_group.geometry().bottom()
        assert_scroll_target_reachable(dialog._config_scroll, dialog.log_view)
        qt_application.processEvents()
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
        qt_application.processEvents()
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
        wait_until(qt_application, lambda: dialog._status_state == "running")
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


@pytest.mark.parametrize("field_name,invalid", [("pct_touch", "101"), ("seed", "bad")])
def test_disabled_invalid_monkey_value_does_not_block_and_survives_reenable(
    qt_application,
    monkeypatch,
    field_name,
    invalid,
):
    """关闭 Monkey 后非法子项不阻止启动，也不清除用户原文。"""

    dialog, runner = _build_performance_page()
    monkeypatch.setattr(FluentMessageBox, "warning", lambda *_args, **_kwargs: None)
    try:
        dialog.monkey_check.setChecked(True)
        field = (
            dialog.monkey_seed_input if field_name == "seed"
            else dialog.monkey_pct_combos[field_name]
        )
        editor = _editor(field)
        editor.setText(invalid)
        assert field.isError()

        dialog.start_mobileperf()
        assert runner.start_count == 0
        dialog.monkey_check.setChecked(False)
        dialog.start_mobileperf()
        wait_until(qt_application, lambda: dialog._status_state == "running")
        assert runner.start_count == 1

        dialog._set_running(False)
        dialog.monkey_check.setChecked(True)
        assert editor.text() == invalid
        assert field.input_is_acceptable() is False
        assert field.isError()
        if field_name == "seed":
            editor.setText("2026")
            assert field.commit_value()
            assert not field.isError() and field.value() == 2026
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
        diagnostic_fields = (
            dialog.dumpheap_input, dialog.exception_edit, dialog.phone_log_edit,
        )
        assert all(
            field.isVisibleTo(dialog) and not field.isEnabled() for field in diagnostic_fields
        )
        assert dialog.log_view.isEnabled()
        assert dialog.status_label.isEnabled()
        assert dialog.progress_bar.isEnabled()
        assert dialog.stop_btn.isEnabled()
        assert not dialog.start_btn.isEnabled()

        dialog._set_running(False)
        assert all(section.isEnabled() for section in dialog._configuration_sections)
        assert all(field.isVisibleTo(dialog) and field.isEnabled() for field in diagnostic_fields)
    finally:
        dialog._set_running(False)
        dialog.close()


def test_late_package_callbacks_do_not_mutate_or_unlock_running_configuration(
    qt_application,
):
    """启动后的晚到包名结果不得改写本次运行配置。"""

    dialog, _runner = _build_performance_page(package="com.before")

    worker = CurrentPackageWorker("session-device")
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
        _wait_for_monkey_reveal(qt_application, dialog)
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
            dialog.exception_edit,
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


def test_duration_first_preset_click_reaches_collection_config(qt_application):
    """采集时长默认 600 后点击首项 10，配置提交必须使用用户实际选中的值。"""
    dialog, _runner = _build_performance_page()
    dialog.resize(1100, 800)
    dialog.show()
    field = dialog.timeout_input
    try:
        assert_scroll_target_reachable(dialog._config_scroll, field)
        QTest.mouseClick(field.dropButton, Qt.MouseButton.LeftButton)
        wait_until(
            qt_application, lambda: field.dropMenu is not None and field.dropMenu.isVisible()
        )
        menu = field.dropMenu
        first = menu.view.item(0)
        menu.view.scrollToItem(first)
        QTest.mouseClick(
            menu.view.viewport(), Qt.MouseButton.LeftButton,
            pos=menu.view.visualItemRect(first).center(),
        )
        dialog.package_edit.setFocus()
        assert field.text() == "10"
        assert field.value() == 10
        assert dialog.build_config().timeout_minutes == 10
    finally:
        if field.dropMenu is not None:
            field.dropMenu.close()
        dialog.close()


@pytest.mark.parametrize(
    "embedded,theme,width,font_size",
    [(False, "Light", 640, 12), (False, "Dark", 640, 22),
     (True, "Light", 1100, 12), (True, "Dark", 780, 22)],
)
def test_performance_cards_leave_overlay_scrollbar_clearance(
    qt_application, monkeypatch, embedded, theme, width, font_size,
):
    """实际 Fluent 覆盖式滚动条与卡片、输入和动作区域保持分离。"""
    BaseStyles.switch_theme(theme)
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    dialog, _runner = _build_performance_page()
    workspace = SmoothScrollArea() if embedded else None
    if workspace is not None:
        workspace.setWidgetResizable(True)
        dialog.prepare_for_workspace()
        workspace.setWidget(dialog)
    owner = workspace or dialog
    scroll = workspace or dialog._config_scroll
    try:
        owner.resize(width, 600)
        owner.show()
        dialog.monkey_check.setChecked(True)
        _wait_for_monkey_reveal(qt_application, dialog)
        wait_for_stable_geometry(qt_application, (owner, dialog, dialog._config_group))
        bar = scroll.delegate.vScrollBar
        assert bar.maximum() > 0
        bar_rect = mapped_rect(bar, scroll)
        for card in (dialog.header_card, dialog._configuration_group, dialog._results_group):
            card_rect = mapped_rect(card, scroll)
            assert card_rect.right() < bar_rect.left()
        for control in (dialog.timeout_input, dialog.save_path_edit, dialog.result_btn):
            assert_scroll_target_reachable(scroll, control)
            assert mapped_rect(control, scroll).right() < bar_rect.left()
        assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        dialog.close()
        if workspace is not None:
            workspace.close()


@pytest.mark.parametrize(
    "embedded,width,height,font_size",
    [(False, 1100, 800, 12), (False, 640, 550, 22),
     (True, 1100, 800, 12), (True, 640, 550, 22)],
)
def test_monkey_real_paint_frames_keep_workspace_plan_and_results_in_sync(
    qt_application, monkeypatch, embedded, width, height, font_size,
):
    """独立页及真实工作区的每个绘制帧都不能先压缩再弹回采集计划。"""
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    host = WorkspaceFeatureHost("system", "系统工具", QWidget()) if embedded else None
    records = []
    probe = None

    class PaintProbe(QObject):
        def eventFilter(self, watched, event):
            if (event.type() == QEvent.Type.Paint and isinstance(watched, QWidget)
                    and (watched is scroll.viewport() or dialog.isAncestorOf(watched))):
                offset = scroll.verticalScrollBar().value()
                records.append((
                    dialog._monkey_reveal.height(),
                    dialog.monkey_check.mapTo(scroll.viewport(), QPoint()).y() + offset,
                    dialog._results_group.mapTo(scroll.viewport(), QPoint()).y() + offset,
                    offset,
                ))
            return False

    try:
        if host is not None:
            host.set_external_device_controls(True)
            host.feature_selector.hide()
            host.register_feature(
                "performance", "性能采集", FluentIcon.SPEED_HIGH,
                lambda _key: _build_performance_page()[0],
            )
            host.set_device_context(["device-1"], ["device-1"])
            host.resize(width, height)
            host.show()
            host.open_feature("performance")
            dialog = host.stack.currentWidget()
            scroll = host.content_scroll
        else:
            dialog, _runner = _build_performance_page()
            dialog.resize(width, height)
            dialog.show()
            scroll = dialog._config_scroll
        owner = host or dialog
        wait_for_stable_geometry(qt_application, (owner, dialog, dialog._config_group))
        scroll.ensureWidgetVisible(dialog.monkey_check, 0, 4)
        qt_application.processEvents()
        offset = scroll.verticalScrollBar().value()
        check_top = dialog.monkey_check.mapTo(scroll.viewport(), QPoint()).y() + offset
        result_top = dialog._results_group.mapTo(scroll.viewport(), QPoint()).y() + offset
        probe = PaintProbe(owner)
        # 独立页的 viewport 可被不透明内容完全覆盖，须观察页面实际参与绘制的子控件。
        qt_application.installEventFilter(probe)
        for _checked in (True, False):
            records.clear()
            previous_height = dialog._monkey_reveal.height()
            previous_offset = scroll.verticalScrollBar().value()
            QTest.mouseClick(
                dialog.monkey_check, Qt.MouseButton.LeftButton,
                pos=QPoint(8, dialog.monkey_check.height() // 2),
            )
            _wait_for_monkey_reveal(qt_application, dialog)
            wait_for_stable_geometry(
                qt_application, (owner, dialog, dialog._config_group),
            )
            assert len({row[0] for row in records}) >= 3, records
            mismatches = [row for row in records
                          if row[1] != check_top or row[2] - row[0] != result_top]
            assert not mismatches, (check_top, result_top, mismatches[:8])
            for current_height, _check, _result, current_offset in records:
                assert abs(current_offset - previous_offset) <= abs(
                    current_height - previous_height
                )
                previous_height, previous_offset = current_height, current_offset
    finally:
        if probe is not None:
            qt_application.removeEventFilter(probe)
        if host is not None:
            host.shutdown()
            host.close()
        else:
            dialog.close()


@pytest.mark.parametrize("embedded,font_size", [(False, 12), (False, 22), (True, 12), (True, 22)])
def test_monkey_reveal_boundaries_do_not_shift_content_outside_animation(
    qt_application, monkeypatch, embedded, font_size,
):
    """首帧前及末帧隐藏时，结果区的移动必须完全由当前裁切高度解释。"""
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    dialog, _runner = _build_performance_page()
    workspace = SmoothScrollArea() if embedded else None
    if workspace is not None:
        workspace.setWidgetResizable(True)
        dialog.prepare_for_workspace()
        workspace.setWidget(dialog)
    owner = workspace or dialog
    try:
        owner.resize(780, 720)
        owner.show()
        wait_for_stable_geometry(qt_application, (owner, dialog._config_group))
        reveal = dialog._monkey_reveal
        animation = reveal.animation
        # 尺寸重测会重新启动同一时钟，手动逐帧采样时不能混入真实经过时间。
        def keep_clock_paused(state, _previous):
            if state == QAbstractAnimation.State.Running:
                animation.pause()

        animation.stateChanged.connect(keep_clock_paused)
        baseline = mapped_rect(dialog._results_group, dialog._config_group).top()
        plan_geometry = mapped_rect(dialog.package_edit, dialog._config_group)
        for checked in (True, False, True, False):
            dialog.monkey_check.setChecked(checked)
            animation.pause()
            for time_ms in (0, 1, 40, 100, 190, 199, animation.duration()):
                animation.setCurrentTime(time_ms)
                wait_for_stable_geometry(qt_application, (reveal, dialog._results_group))
                result_top = mapped_rect(dialog._results_group, dialog._config_group).top()
                assert result_top - baseline == reveal.height(), (
                    checked, time_ms, baseline, result_top, reveal.height(),
                )
                assert mapped_rect(dialog.package_edit, dialog._config_group) == plan_geometry
        assert not dialog._monkey_details.isVisibleTo(dialog)
        assert mapped_rect(dialog._results_group, dialog._config_group).top() == baseline
    finally:
        dialog.close()
        if workspace is not None:
            workspace.close()


@pytest.mark.parametrize("embedded,width,font_size", [(False, 640, 12), (True, 780, 22)])
def test_monkey_options_reveal_moves_following_content_through_intermediate_frames(
    qt_application, monkeypatch, embedded, width, font_size,
):
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    dialog, _runner = _build_performance_page()
    workspace = QScrollArea() if embedded else None
    if workspace is not None:
        workspace.setWidgetResizable(True)
        dialog.prepare_for_workspace()
        workspace.setWidget(dialog)
    owner = workspace or dialog
    try:
        owner.resize(width, 720)
        owner.show()
        wait_for_stable_geometry(qt_application, (owner, dialog._config_group))
        (workspace or dialog._config_scroll).ensureWidgetVisible(dialog.monkey_check, 0, 4)
        qt_application.processEvents()
        QTest.mouseClick(
            dialog.monkey_check, Qt.MouseButton.LeftButton,
            pos=QPoint(8, dialog.monkey_check.height() // 2),
        )
        assert dialog.monkey_check.isChecked()
        reveal = dialog._monkey_details.parentWidget()
        animation = reveal.findChild(FrameAnimation)
        assert animation is not None, "Monkey 参数不能直接切换显隐，必须具有展开中间帧"
        animation.pause()
        heights, following = [], []
        for time_ms in (0, 40, 100, animation.duration()):
            animation.setCurrentTime(time_ms)
            wait_for_stable_geometry(qt_application, (reveal, dialog._results_group))
            heights.append(reveal.height())
            following.append(mapped_rect(dialog._results_group, dialog._config_group).top())
            assert dialog._monkey_details.height() >= reveal.height()
            assert dialog._monkey_details.y() == 0
        assert heights[0] == 0
        assert heights[0] < heights[1] < heights[2] < heights[3]
        assert all(a < b for a, b in zip(following, following[1:])), following
        assert_contained(dialog._monkey_details, reveal)
        assert (workspace or dialog._config_scroll).horizontalScrollBar().maximum() == 0
    finally:
        dialog.close()
        if workspace is not None:
            workspace.close()


def test_monkey_reversal_preserves_input_focus_and_stops_when_hidden(qt_application):
    dialog, _runner = _build_performance_page()
    try:
        dialog.resize(780, 720)
        dialog.show()
        wait_for_stable_geometry(qt_application, dialog._config_group)
        dialog.monkey_check.setChecked(True)
        reveal = dialog._monkey_details.parentWidget()
        animation = reveal.findChild(FrameAnimation)
        assert animation is not None
        animation.pause()
        animation.setCurrentTime(80)
        middle = reveal.height()
        field = dialog.monkey_pct_inputs["pct_touch"]
        field.setText("101")
        field.setFocus()
        assert field.hasFocus()
        middle = reveal.height()
        dialog.monkey_check.setChecked(False)
        assert reveal.height() == middle
        assert not field.isEnabled()
        assert not field.hasFocus()
        animation.pause()
        animation.setCurrentTime(max(1, animation.duration() // 2))
        smaller = reveal.height()
        assert 0 < smaller < middle
        dialog.monkey_check.setChecked(True)
        assert reveal.height() == smaller
        dialog.hide()
        assert animation.state() == QAbstractAnimation.State.Stopped
        assert not animation._timer.isActive()
        dialog.show()
        wait_for_stable_geometry(qt_application, (reveal, dialog._config_group))
        assert field.text() == "101" and not field.input_is_acceptable()
        assert_contained(dialog._monkey_details, reveal)
        dialog.monkey_check.setChecked(False)
        dialog.close()
        assert animation.state() == QAbstractAnimation.State.Stopped
        assert not animation._timer.isActive()
    finally:
        dialog.close()


def test_monkey_reveal_remeasures_on_resize_and_finishes_on_deactivate(
    qt_application, monkeypatch,
):
    dialog, _runner = _build_performance_page()
    try:
        dialog.resize(1100, 720)
        dialog.show()
        wait_for_stable_geometry(qt_application, dialog._config_group)
        dialog.monkey_check.setChecked(True)
        animation = dialog._monkey_reveal.animation
        animation.setCurrentTime(80)
        dialog.resize(640, 720)
        monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 22)
        dialog._apply_theme()
        _wait_for_monkey_reveal(qt_application, dialog)
        wait_for_stable_geometry(qt_application, (dialog._monkey_reveal, dialog._config_group))
        assert_contained(dialog._monkey_details, dialog._monkey_reveal)
        for field in dialog.monkey_pct_inputs.values():
            assert_contained(field, dialog._monkey_details)
        assert dialog._config_scroll.horizontalScrollBar().maximum() == 0
        dialog.monkey_check.setChecked(False)
        animation.pause()
        animation.setCurrentTime(40)
        dialog.deactivate()
        assert not dialog._monkey_details.isVisibleTo(dialog)
        assert animation.state() == QAbstractAnimation.State.Stopped
        assert not animation._timer.isActive()
        dialog.activate()
        assert not dialog.monkey_check.isChecked()
        assert not dialog._monkey_details.isVisibleTo(dialog)
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
        _wait_for_monkey_reveal(qt_application, dialog)
        assert not dialog._monkey_details.isVisibleTo(dialog)
        dialog.monkey_check.setChecked(True)
        _wait_for_monkey_reveal(qt_application, dialog)
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
        wait_for_stable_geometry(qt_application, (dialog, dialog._chart_stack))
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
        wait_for_stable_geometry(qt_application, (dialog, dialog._chart_stack))
        assert dialog._chart_stack.height() == log_height
        assert dialog.log_view.toPlainText() == "保留日志内容"
    finally:
        dialog.close()


def test_performance_plan_and_results_stay_full_width_without_shared_height(qt_application):
    """配置与日志始终纵排且分别测高，切换宽度不重建输入或放大配置空白。"""

    dialog, _runner = _build_performance_page()
    field = dialog.frequency_input
    try:
        dialog.show()
        for width in (1200, 640, 1200):
            dialog.resize(width, 900)
            wait_for_stable_geometry(qt_application, (dialog, dialog._config_group))
            # 字体同步可能刚使布局失效；等布局矩形提交后再读取正文可用宽度。
            wait_until(qt_application, lambda: (
                dialog._config_group.layout().geometry().width() == dialog._config_group.width()
            ))
            plan = dialog._configuration_group.geometry()
            results = dialog._results_group.geometry()
            assert 0 < results.top() - plan.bottom() <= 13
            assert results.left() == plan.left() == 0
            content_width = dialog._config_group.layout().contentsRect().width()
            assert results.width() == plan.width() == content_width
            assert dialog._chart_toggle.height() == dialog._chart_toggle.sizeHint().height()
            assert_scroll_target_reachable(dialog._config_scroll, dialog.log_view)
            configuration_height = dialog._configuration_group.height()
            dialog._chart_stack.setCurrentIndex(1)
            wait_for_stable_geometry(qt_application, (dialog, dialog._config_group))
            assert dialog._configuration_group.height() == configuration_height
            dialog._chart_stack.setCurrentIndex(0)
            wait_for_stable_geometry(qt_application, (dialog, dialog._config_group))
            if width == 1200:
                centers = [
                    mapped_rect(field, dialog).center().y()
                    for field in (dialog.package_edit, dialog.frequency_input, dialog.timeout_input)
                ]
                assert max(centers) - min(centers) <= 1
                assert len({
                    mapped_rect(label, dialog).top()
                    for label in dialog.findChildren(QLabel, "fieldLabel")
                    if label.property("configurationKey") in {"package", "frequency", "timeout"}
                }) == 1
            assert dialog._config_scroll.horizontalScrollBar().maximum() == 0
            assert dialog.frequency_input is field
    finally:
        dialog.close()


@pytest.mark.parametrize("font_size,width", ((12, 1200), (22, 1200), (22, 420)))
def test_performance_preset_and_common_fields_follow_one_clear_vertical_order(
    qt_application, monkeypatch, font_size, width,
):
    """方案位于计划页头，常用参数和保存目录顺序稳定，窄屏仍能完整操作。"""

    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    dialog, _runner = _build_performance_page()
    dialog.run_preset_bar.show()
    try:
        dialog.resize(width, 900)
        dialog.show()
        wait_for_stable_geometry(qt_application, (dialog, dialog._config_group))
        card = dialog._configuration_sections[0]
        preset = mapped_rect(dialog.run_preset_bar, card)
        common = (dialog.package_edit, dialog.frequency_input, dialog.timeout_input)
        rectangles = tuple(mapped_rect(field, card) for field in common)
        save = mapped_rect(dialog.save_path_edit, card)
        assert_contained(dialog.run_preset_bar, card.headerView)
        assert_non_overlapping((card.headerLabel, dialog.run_preset_bar), card.headerView)
        assert preset.bottom() < min(rect.top() for rect in rectangles)
        assert max(rect.bottom() for rect in rectangles) < save.top()
        assert save.bottom() < mapped_rect(dialog._diagnostic_tools, card).top()
        assert_non_overlapping(common, card.view)
        for field in (*common, dialog.save_path_edit):
            assert_contained(field, card.view)
            assert_scroll_target_reachable(dialog._config_scroll, field)
        for control in (
            dialog.run_preset_bar.combo, dialog.run_preset_bar.load_button,
            dialog.run_preset_bar.save_button, dialog.run_preset_bar.delete_button,
        ):
            assert_contained(control, dialog.run_preset_bar)
            assert_scroll_target_reachable(dialog._config_scroll, control)
        assert dialog._config_scroll.horizontalScrollBar().maximum() == 0
    finally:
        dialog.close()


@pytest.mark.parametrize("width", (420, 764, 1200))
def test_performance_large_font_running_summary_and_actions_remain_readable(
    qt_application, monkeypatch, width,
):
    """运行详情变长后按实际换行测高，百分比与时间不能被状态卡裁掉。"""

    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 22)
    dialog, _runner = _build_performance_page()
    dialog.prepare_for_workspace()
    try:
        dialog.resize(width, 900)
        dialog.show()
        dialog._run_duration_seconds = 3600
        dialog._run_elapsed_seconds = 1512
        dialog._set_running(True)
        dialog._set_progress(42)
        wait_for_stable_geometry(qt_application, (dialog, dialog.header_card))
        progress = dialog.progress_display
        for label in (progress.status_label, progress.detail_label):
            assert_contained(label, progress)
            assert label.height() >= label.heightForWidth(label.width())
        assert "00:25:12" in progress.detail_label.text()
        assert "01:00:00" in progress.detail_label.text()
        assert progress.ring.width() == progress.ring.height()
        assert progress.ring.width() >= progress.ring.fontMetrics().horizontalAdvance("100%") + 16
        assert_non_overlapping(
            (progress, dialog.start_btn, dialog.stop_btn), dialog.header_card,
        )
        for button in (dialog.start_btn, dialog.stop_btn):
            assert_contained(button, dialog.header_card)
            assert button.width() >= button.sizeHint().width()
    finally:
        dialog._set_running(False)
        dialog.close()


@pytest.mark.parametrize("width", (420, 1200))
def test_performance_result_buttons_sync_click_keyboard_and_programmatic_selection(
    qt_application, width,
):
    """切换入口保持单选；点击、空格、方向键和程序切图都只发布一次变化。"""

    dialog, _runner = _build_performance_page()
    try:
        dialog.resize(width, 900)
        dialog.show()
        toggle = dialog._chart_toggle
        log_button, chart_button = (toggle.items[key] for key in ("log", "chart"))
        for button in (log_button, chart_button):
            assert button.accessibleName() == button.text()
            assert button.accessibleDescription() == button.toolTip()
            assert button.accessibleDescription()
        changes = QSignalSpy(toggle.currentItemChanged)
        views = QSignalSpy(dialog._chart_stack.currentChanged)
        assert log_button.isChecked() and not chart_button.isChecked()
        assert toggle._group.exclusive()
        assert toggle._group.parent() is toggle
        assert_scroll_target_reachable(dialog._config_scroll, chart_button)
        QTest.mouseClick(chart_button, Qt.MouseButton.LeftButton)
        assert dialog._chart_stack.currentIndex() == 1
        assert chart_button.isChecked() and not log_button.isChecked()
        assert changes.count() == views.count() == 1
        QTest.mouseClick(chart_button, Qt.MouseButton.LeftButton)
        assert chart_button.isChecked()
        assert changes.count() == views.count() == 1
        dialog._chart_stack.setCurrentIndex(0)
        assert log_button.isChecked() and not chart_button.isChecked()
        assert changes.count() == views.count() == 2
        chart_button.setFocus()
        QTest.keyClick(chart_button, Qt.Key.Key_Space)
        assert chart_button.isChecked() and dialog._chart_stack.currentIndex() == 1
        assert changes.count() == views.count() == 3
        QTest.keyClick(chart_button, Qt.Key.Key_Left)
        assert log_button.hasFocus() and log_button.isChecked()
        assert dialog._chart_stack.currentIndex() == 0
        assert changes.count() == views.count() == 4
        QTest.keyClick(log_button, Qt.Key.Key_Tab)
        focused = dialog.focusWidget()
        assert focused is not None and not toggle.isAncestorOf(focused)
        QTest.keyClick(focused, Qt.Key.Key_Backtab)
        assert log_button.hasFocus()
        assert_non_overlapping((log_button, chart_button), toggle)
        assert abs(log_button.width() - chart_button.width()) <= 1
    finally:
        dialog.close()


def test_performance_close_stops_progress_and_releases_result_button_group(qt_application):
    """关闭先停止绘制动画，页面与互斥组随后在同一对象树中释放一次。"""

    dialog, _runner = _build_performance_page()
    dialog.show()
    toggle = dialog._chart_toggle
    group = toggle._group
    stack = dialog._chart_stack
    controls = (toggle, group, stack, *toggle.items.values())
    destroyed = tuple(QSignalSpy(control.destroyed) for control in controls)
    try:
        dialog._set_running(True)
        dialog._set_progress(42)
        assert dialog.request_dispose()
        assert dialog.progress_bar.ani.state() == QAbstractAnimation.State.Stopped
        assert (
            dialog.progress_display.busy_ring.aniGroup.state() == QAbstractAnimation.State.Stopped
        )
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert all(signal.count() == 1 for signal in destroyed)
        assert not any(isValid(control) for control in controls)
    finally:
        if isValid(dialog):
            dialog.close()


def test_invalid_visible_diagnostic_field_is_focused_without_committing_other_fields(
    qt_application, monkeypatch
):
    """常显诊断校验失败必须定位原文，不能启动或改掉其他有效字段。"""

    dialog, runner = _build_performance_page()
    monkeypatch.setattr(FluentMessageBox, "warning", lambda *_args, **_kwargs: None)
    try:
        dialog.resize(640, 720)
        dialog.show()
        dialog.dumpheap_input.setText("bad")
        dialog.frequency_input.setText("7")
        assert dialog.dumpheap_input.isVisibleTo(dialog)

        dialog.start_mobileperf()
        wait_for_stable_geometry(qt_application, (dialog, dialog._config_group))

        assert runner.start_count == 0
        assert dialog.dumpheap_input.isVisibleTo(dialog)
        assert dialog.dumpheap_input.hasFocus()
        assert dialog.dumpheap_input.text() == "bad"
        assert dialog.frequency_input.value() == 5
        assert_scroll_target_reachable(dialog._config_scroll, dialog.dumpheap_input)
    finally:
        dialog.close()


def test_performance_reselected_device_clears_stale_admission_status(qt_application):
    """重新选中在线设备恢复待机，已运行采集的状态不会被准入刷新覆盖。"""

    dialog, _runner = _build_performance_page()
    try:
        initial_status = dialog.status_label.text()
        dialog.set_device_selected(False)
        assert not dialog.start_btn.isEnabled()
        assert dialog.status_label.text() != initial_status
        dialog.set_device_selected(True)
        assert dialog.start_btn.isEnabled()
        assert dialog.status_label.text() == initial_status
        dialog._set_running(True)
        running_status = dialog.status_label.text()
        dialog.set_device_selected(False)
        dialog.set_device_selected(True)
        assert dialog.status_label.text() == running_status
        assert dialog.stop_btn.isEnabled()
    finally:
        dialog._set_running(False)
        dialog.close()


def test_performance_package_fetch_feedback_covers_success_and_retry(
    qt_application, monkeypatch
):
    """包查询显示忙碌和就地结果；失败恢复重试且保留已经填入的包名。"""

    from gui.dialogs.performance_launcher import CurrentPackageWorker
    from gui.i18n import tr

    monkeypatch.setattr(CurrentPackageWorker, "start", lambda _worker: None)
    dialog, _runner = _build_performance_page()
    try:
        dialog.show()
        dialog.fetch_current_package()
        worker = dialog._package_worker
        assert worker is not None
        assert not dialog.get_package_btn.isEnabled()
        assert dialog.get_package_btn.text() == tr("读取中…")
        assert dialog.package_feedback.isVisibleTo(dialog)
        dialog._on_current_package("com.example.foreground")
        dialog._on_package_worker_finished(worker)
        assert dialog.get_package_btn.isEnabled()
        assert dialog.package_feedback.text() == tr("已填入当前应用，可继续编辑包名。")

        dialog.fetch_current_package()
        worker = dialog._package_worker
        assert worker is not None
        dialog._on_package_worker_finished(worker)
        assert dialog.get_package_btn.isEnabled()
        assert dialog.get_package_btn.text() == tr("获取当前应用")
        assert dialog.package_edit.text() == "com.example.foreground"
        assert dialog.package_feedback.text() == tr("未能读取当前应用，请手动输入包名或重试。")
    finally:
        dialog.close()


@pytest.mark.parametrize("width", (420, 640, 760))
def test_large_font_sampling_units_stay_beside_editors(qt_application, monkeypatch, width):
    """大字窄屏的单位不能掉到下一行，同排的采样标题与输入保持对齐。"""

    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 22)
    dialog, _runner = _build_performance_page()
    try:
        dialog.resize(width, 900)
        dialog.show()
        dialog.monkey_check.setChecked(True)
        wait_for_stable_geometry(qt_application, (dialog, dialog._config_group))

        for editor, unit in (
            (dialog.frequency_input, dialog.frequency_unit_label),
            (dialog.timeout_input, dialog.timeout_unit_label),
            (dialog.dumpheap_input, dialog.dumpheap_unit_label),
            (dialog.monkey_throttle_input, dialog.monkey_throttle_unit_label),
        ):
            editor_top = editor.mapTo(dialog, QPoint())
            unit_top = unit.mapTo(dialog, QPoint())
            assert unit_top.x() >= editor_top.x() + editor.width()
            assert editor_top.y() <= unit_top.y() + unit.height() / 2 <= (
                editor_top.y() + editor.height()
            )
            assert_scroll_target_reachable(dialog._config_scroll, editor)
            assert_scroll_target_reachable(dialog._config_scroll, unit)

        frequency = dialog.frequency_input.mapTo(dialog, QPoint())
        timeout = dialog.timeout_input.mapTo(dialog, QPoint())
        diagnostic_fields = (
            dialog.dumpheap_input, dialog.exception_edit, dialog.phone_log_edit,
        )
        diagnostic_labels = {
            label.property("configurationKey"): label
            for label in dialog._diagnostic_tools.findChildren(QLabel, "fieldLabel")
        }
        for key in ("dumpheap_freq", "exceptionlog", "phone_log_path"):
            label = diagnostic_labels[key]
            assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
        assert len({
            mapped_rect(field, dialog._diagnostic_tools).top() for field in diagnostic_fields
        }) >= 2
        if frequency.x() != timeout.x():
            assert frequency.y() == timeout.y()
            labels = {
                label.property("configurationKey"): label
                for label in dialog.findChildren(QLabel, "fieldLabel")
            }
            assert labels["frequency"].mapTo(dialog, QPoint()).y() == (
                labels["timeout"].mapTo(dialog, QPoint()).y()
            )
        else:
            assert timeout.y() > frequency.y() + dialog.frequency_input.height()
        assert dialog._config_scroll.horizontalScrollBar().maximum() == 0
    finally:
        dialog.close()


def test_embedded_expanded_performance_keeps_result_content_inside_card(
    qt_application, monkeypatch
):
    """大字展开配置后，外滚动宿主必须给结果卡分配完整日志和动作所需高度。"""

    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 22)
    dialog, _runner = _build_performance_page()
    workspace = QScrollArea()
    workspace.setWidgetResizable(True)
    try:
        dialog.prepare_for_workspace()
        workspace.setWidget(dialog)
        workspace.resize(780, 900)
        workspace.show()
        dialog.monkey_check.setChecked(True)
        wait_until(qt_application, lambda: (
            dialog._monkey_reveal.animation.state() == QAbstractAnimation.State.Stopped
        ))
        for result_index in (0, 1, 0):
            dialog._chart_stack.setCurrentIndex(result_index)
            wait_for_stable_geometry(qt_application, (workspace, dialog, dialog._config_group))
            assert_contained(dialog._results_group, dialog._config_group)
            assert_contained(dialog._chart_stack, dialog._results_group.view)
            assert_contained(dialog.result_btn, dialog._results_group.headerView)
            assert_contained(dialog.perfetto_btn, dialog._results_group.headerView)
            assert dialog._chart_stack.height() >= dialog.log_view.fontMetrics().height() * 8
            assert_scroll_target_reachable(workspace, dialog._chart_stack)
            assert_scroll_target_reachable(workspace, dialog.result_btn)
            assert workspace.horizontalScrollBar().maximum() == 0
    finally:
        dialog.close()
        workspace.close()
