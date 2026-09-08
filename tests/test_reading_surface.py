"""验证只读长正文的稳定底色、主题焦点样式与复制时的数据完整性。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import PlainTextEdit, TextEdit

from gui.dialogs.performance_launcher import PerformancePage
from gui.styles import BaseStyles
from gui.widgets.action_result_view import ActionResultView
from gui.widgets.run_results import RunResultsWidget
from services.run_library import RunRecord


class _Library(QObject):
    changed = Signal()
    records = (
        RunRecord("demo-run", "performance", "com.example.demo", 1, 2, "succeeded",
                  {"frequency_seconds": 5}, message="Synthetic completion"),
    )
    presets = ()


def _background(reader):
    image = reader.viewport().grab().toImage()
    return image.pixelColor(3, image.height() - 4)


def _focus(reader, application):
    QTest.mouseClick(reader.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    application.processEvents()
    assert reader.hasFocus()


@pytest.fixture(params=("performance", "action_results", "summary", "parameters"))
def reading_widget(request, qt_application, monkeypatch, tmp_path):
    values = {"log_max_lines": 2000, "save_path": str(tmp_path)}
    settings = SimpleNamespace(get=values.get, save_directory=str(tmp_path))
    monkeypatch.setattr("core.settings_manager.AppSettings.instance", lambda: settings)
    if request.param == "performance":
        owner = PerformancePage("", "com.example.demo")
        reader = owner.log_view
    elif request.param == "action_results":
        owner = ActionResultView()
        owner.detail_toggle.setChecked(True)
        reader = owner.output
    else:
        library = _Library()
        owner = RunResultsWidget(library)
        library.setParent(owner)
        owner.parameters_section.toggle_button.setChecked(True)
        reader = owner.summary_edit if request.param == "summary" else owner.parameters_edit
    owner.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    owner.resize(1150, 950)
    owner.show()
    qt_application.processEvents()
    yield owner, reader
    owner.close()
    owner.deleteLater()
    qt_application.processEvents()


def test_long_readers_keep_light_background_when_focused_hovered_and_unfocused(
    qt_application, reading_widget,
):
    owner, reader = reading_widget
    BaseStyles.switch_theme("Light")
    qt_application.processEvents()
    expected = QColor(BaseStyles.color_for("Light", "LOG_BACKGROUND"))
    _focus(reader, qt_application)
    assert _background(reader) == expected, (reader.objectName(), _background(reader).name())
    focus_target = (
        owner.search if isinstance(owner, ActionResultView)
        else owner.package_edit if isinstance(owner, PerformancePage) else owner.search_edit
    )
    focus_target.setFocus()
    QTest.mouseMove(owner, QPoint(2, 2))
    qt_application.processEvents()
    assert not reader.hasFocus()
    assert _background(reader) == expected
    QTest.mouseMove(reader.viewport(), QPoint(20, 20))
    qt_application.processEvents()
    assert _background(reader) == expected


def test_reading_surface_survives_theme_round_trip_focus_rebuild_and_accent_change(
    qt_application, reading_widget,
):
    from gui.styles.fluent import apply_focus_indicator, refresh_fluent_widget_style

    _owner, reader = reading_widget
    original_accent = BaseStyles.accent_color()
    original_text = reader.toPlainText()
    original_font = reader.font()
    try:
        BaseStyles.switch_theme("Dark")
        qt_application.processEvents()
        assert "background" not in str(reader.property("darkCustomQss"))
        BaseStyles.switch_theme("Light")
        BaseStyles.set_accent_color("#9B327D")
        apply_focus_indicator(reader)
        refresh_fluent_widget_style(reader)
        qt_application.processEvents()
        _focus(reader, qt_application)
        assert _background(reader) == QColor(BaseStyles.color_for("Light", "LOG_BACKGROUND"))
        assert "#9b327d" in str(reader.property("lightCustomQss")).lower()
        assert "#9b327d" in str(reader.property("darkCustomQss")).lower()
        assert reader.toPlainText() == original_text
        assert reader.font() == original_font
    finally:
        BaseStyles.set_accent_color(original_accent)
        refresh_fluent_widget_style(reader)


@pytest.mark.parametrize("control_type", (PlainTextEdit, TextEdit))
def test_dark_reading_background_matches_upstream_and_editable_input_is_unchanged(
    qt_application, control_type,
):
    from gui.styles.fluent import apply_reading_surface

    host = QWidget()
    layout = QVBoxLayout(host)
    reader = control_type(host)
    reference = control_type(host)
    reader.setReadOnly(True)
    reference.setReadOnly(True)
    apply_reading_surface(reader)
    layout.addWidget(reader)
    layout.addWidget(reference)
    host.resize(500, 500)
    host.show()
    BaseStyles.switch_theme("Dark")
    qt_application.processEvents()
    _focus(reader, qt_application)
    reader_dark = _background(reader)
    _focus(reference, qt_application)
    assert _background(reference) == reader_dark
    BaseStyles.switch_theme("Light")
    reader.setReadOnly(False)
    reference.setReadOnly(False)
    # 重建样式后重新匹配属性选择器，适配不能改变可编辑控件的上游白色焦点底。
    reader.setStyle(qt_application.style())
    qt_application.processEvents()
    _focus(reader, qt_application)
    reader_light = _background(reader)
    _focus(reference, qt_application)
    assert _background(reference) == reader_light
    assert reader_light.name() == "#ffffff"
    host.close()


def test_copy_from_reading_surface_preserves_text_parameters_and_log_cache(
    qt_application, reading_widget,
):
    owner, reader = reading_widget
    if isinstance(owner, ActionResultView):
        owner.output.setPlainText("Synthetic action result for copying")
    elif isinstance(owner, PerformancePage):
        owner._append_log("INFO", "Synthetic performance log for copying")
        owner._flush_pending_logs()
    before_text = reader.toPlainText()
    assert before_text
    before_entries = deepcopy(getattr(owner, "_entries", None))
    before_parameters = (
        deepcopy(owner.selected_record.parameters) if isinstance(owner, RunResultsWidget) else None
    )
    _focus(reader, qt_application)
    reader.selectAll()
    selected = reader.textCursor().selectedText().replace("\u2029", "\n")
    QTest.keyClick(reader, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    qt_application.processEvents()
    assert qt_application.clipboard().text().replace("\r\n", "\n") == selected
    QTest.keyClicks(reader, "must-not-edit")
    assert reader.toPlainText() == before_text
    assert getattr(owner, "_entries", None) == before_entries
    if isinstance(owner, RunResultsWidget):
        assert owner.selected_record.parameters == before_parameters
    cursor = reader.textCursor()
    cursor.clearSelection()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    reader.setTextCursor(cursor)
