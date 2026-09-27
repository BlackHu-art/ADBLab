"""验证性能采集与内嵌 Monkey 的同行字段、最小读宽和状态保留。"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLabel, QScrollArea, QStyle, QStyleOptionFrame

from gui.styles import BaseStyles
from tests.test_dialog_languages import dialog_language as dialog_language
from tests.test_performance_compact_layout import _show
from tests.test_performance_responsive import (
    _build_performance_page,
    _editor,
)
from tests.test_performance_responsive import (
    isolated_performance_settings as isolated_performance_settings,
)
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    assert_scroll_target_reachable,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)

pytestmark = pytest.mark.ui


def _labels(page):
    return tuple(page.findChildren(QLabel, "fieldLabel"))


def _numeric_inputs(page):
    return (
        page.frequency_input, page.timeout_input, page.dumpheap_input,
        page.monkey_throttle_input, page.monkey_seed_input, *page.monkey_pct_inputs.values(),
    )


@pytest.mark.parametrize("width,font_size,language", [
    (1000, 12, "zh_CN"), (1200, 22, "zh_CN"), (1200, 12, "en_US"),
])
def test_performance_labels_align_right_without_wrapping_before_fields(
    qt_application, monkeypatch, dialog_language, width, font_size, language,
):
    """正常可用宽度将标题放在选项前方，常规中文占比仍保持三组一排。"""
    dialog_language(language)
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    page, _runner = _build_performance_page()
    try:
        _show(page, qt_application, width)
        page.monkey_check.setChecked(True)
        labels = _labels(page)
        assert labels
        wait_for_stable_geometry(qt_application, (page, page._config_group, *labels))
        for label in labels:
            field = label.buddy()
            assert field is not None, label.property("configurationKey")
            assert not label.wordWrap(), label.text()
            assert label.alignment() == (
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
            title_rect, field_rect = mapped_rect(label, page), mapped_rect(field, page)
            assert title_rect.right() < field_rect.left(), label.text()
            assert abs(title_rect.center().y() - field_rect.center().y()) <= 2, label.text()
            assert_contained(label, page._config_group)
            assert_contained(field, page._config_group)
        if language == "zh_CN" and font_size == 12:
            first_row = tuple(page.monkey_pct_inputs.values())[:3]
            assert len({mapped_rect(field, page).top() for field in first_row}) == 1
            assert_non_overlapping(first_row, page)
    finally:
        page.close()


@pytest.mark.parametrize("width,font_size,language", [
    (420, 12, "zh_CN"), (640, 22, "zh_CN"), (640, 22, "en_US"),
])
def test_performance_numeric_options_reserve_full_maximum_value_width(
    qt_application, monkeypatch, dialog_language, width, font_size, language,
):
    """最小宽度保护选项交互，合法最大值在实际编辑区域内完整可读。"""
    dialog_language(language)
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    page, _runner = _build_performance_page()
    try:
        _show(page, qt_application, width)
        page.monkey_check.setChecked(True)
        fields = _numeric_inputs(page)
        for field in fields:
            field.setValue(field.maximum())
        wait_for_stable_geometry(qt_application, (page, page._config_group, *fields))
        for field in fields:
            editor = _editor(field)
            assert field.minimumWidth() >= 96
            assert field.width() >= field.minimumWidth()
            option = QStyleOptionFrame()
            editor.initStyleOption(option)
            contents = editor.style().subElementRect(
                QStyle.SubElement.SE_LineEditContents, option, editor,
            )
            margins = editor.textMargins()
            available = contents.width() - margins.left() - margins.right() - 2
            required = editor.fontMetrics().horizontalAdvance(editor.text())
            assert required <= available, (editor.text(), required, available)
            assert_contained(field, page._config_group)
        for label in _labels(page):
            assert not label.wordWrap()
            assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
        assert page.width() == width
        assert page._config_scroll.horizontalScrollBar().maximum() == 0
    finally:
        page.close()


@pytest.mark.parametrize("language,font_size", [("zh_CN", 12), ("en_US", 22)])
def test_performance_inline_reflow_preserves_editors_and_monkey_state(
    qt_application, monkeypatch, dialog_language, language, font_size,
):
    """重排不重建字段或提交编辑，收起和运行锁也保留 Monkey 非法原文。"""
    dialog_language(language)
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", font_size)
    page, runner = _build_performance_page()
    try:
        _show(page, qt_application, 1200)
        page.monkey_check.setChecked(True)
        field, seed = page.frequency_input, page.monkey_seed_input
        editor = _editor(field)
        seed.setText("bad")
        page.activateWindow()
        field.focus_editor()
        editor.setText("7")
        committed = QSignalSpy(field.valueChanged)
        wait_until(qt_application, editor.hasFocus)
        for width in (420, 1200, 640, 1200):
            page.resize(width, 900)
            wait_for_stable_geometry(qt_application, (page, page._config_group, field, seed))
            assert page.frequency_input is field and _editor(field) is editor
            assert editor.hasFocus() and editor.text() == "7"
            assert page.monkey_seed_input is seed and seed.text() == "bad"
            assert committed.count() == 0
            assert page._config_scroll.horizontalScrollBar().maximum() == 0
        page.monkey_check.setChecked(False)
        assert not page._monkey_details.isVisibleTo(page)
        page.monkey_check.setChecked(True)
        assert page._monkey_details.isVisibleTo(page) and seed.text() == "bad"
        page._set_running(True)
        assert not seed.isEnabled() and page.stop_btn.isEnabled()
        page._set_running(False)
        assert seed.isEnabled() and seed.text() == "bad" and seed.isError()
        assert runner.start_count == 0
    finally:
        page._set_running(False)
        page.close()


def test_embedded_performance_monkey_parents_reserve_complete_field_height(
    qt_application, monkeypatch, dialog_language,
):
    """嵌入宿主后按真实字体测高，展开 Monkey 不得以裁剪字段换取紧凑布局。"""
    dialog_language("zh_CN")
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_FAMILY", "Microsoft YaHei UI")
    monkeypatch.setattr(BaseStyles, "DEFAULT_FONT_SIZE", 12)
    page, _runner = _build_performance_page()
    workspace = QScrollArea()
    workspace.setWidgetResizable(True)
    try:
        page.prepare_for_workspace()
        _show(page, qt_application, 820)
        workspace.setWidget(page)
        workspace.resize(820, 900)
        workspace.show()
        page.monkey_check.setChecked(True)
        fields = _numeric_inputs(page)
        labels = _labels(page)
        checks = (
            page.monkey_check, page.monkey_ignore_crashes, page.monkey_ignore_timeouts,
            page.monkey_ignore_security, page.monkey_kill_after_error,
        )
        initial_height = None
        for width in (820, 420, 820):
            workspace.resize(width, 900)
            wait_for_stable_geometry(
                qt_application,
                (workspace, page, page._config_group, page._monkey_details, *fields, *labels),
            )
            for widget in (*fields, *checks, *labels):
                parent = widget.parentWidget()
                while parent is not None:
                    assert_contained(widget, parent)
                    if parent is page._config_group:
                        break
                    parent = parent.parentWidget()
                assert parent is page._config_group
            for label in labels:
                assert label.height() >= label.fontMetrics().height(), label.text()
            assert_non_overlapping((*fields, *checks, *labels), page._config_group)
            assert workspace.horizontalScrollBar().maximum() == 0
            if width == 820:
                if initial_height is None:
                    initial_height = page._configuration_group.height()
                else:
                    assert page._configuration_group.height() == initial_height
        for control in (*fields, *checks):
            assert_scroll_target_reachable(workspace, control)
    finally:
        page.close()
        workspace.close()
