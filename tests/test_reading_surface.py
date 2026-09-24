"""验证阅读框的原生回退、宿主材质与复制时的数据完整性。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QEnterEvent, QPalette, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
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
    image = reader.grab().toImage()
    point = reader.viewport().mapTo(reader, QPoint(3, reader.viewport().height() - 4))
    scale = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * scale), round(point.y() * scale))


def _focus(reader, application):
    application.setActiveWindow(reader.window())
    QTest.mouseClick(reader.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    application.processEvents()
    assert reader.hasFocus()


def _composited_frame(host, reader):
    image = host.grab().toImage()
    point = reader.mapTo(host, QPoint())
    scale = image.devicePixelRatio()
    return image.copy(round(point.x() * scale), round(point.y() * scale),
                      round(reader.width() * scale), round(reader.height() * scale))


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
    if isinstance(owner, PerformancePage):
        owner.activate()
    else:
        owner.show()
    qt_application.processEvents()
    yield owner, reader
    owner.close()
    owner.deleteLater()
    qt_application.processEvents()


def test_long_readers_match_native_light_focus_surface(
    qt_application, reading_widget,
):
    owner, reader = reading_widget
    BaseStyles.switch_theme("Light")
    reference = PlainTextEdit(owner)
    reference.setReadOnly(True)
    reference.resize(250, 100)
    reference.show()
    qt_application.processEvents()
    _focus(reference, qt_application)
    expected = _background(reference)
    reference.close()
    reference.deleteLater()
    _focus(reader, qt_application)
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
        assert _background(reader) == QColor("#ffffff")
        assert "border: 2px" not in str(reader.property("lightCustomQss"))
        assert "border: 2px" not in str(reader.property("darkCustomQss"))
        assert reader.toPlainText() == original_text
        assert reader.font() == original_font
    finally:
        BaseStyles.set_accent_color(original_accent)
        refresh_fluent_widget_style(reader)


@pytest.mark.parametrize("control_type", (PlainTextEdit, TextEdit))
@pytest.mark.parametrize("theme", ("Light", "Dark"))
@pytest.mark.parametrize("state", ("normal", "hover", "focus", "disabled"))
def test_reading_surface_without_mica_matches_native_frame_and_background(
    qt_application, control_type, theme, state,
):
    from gui.styles.fluent import apply_reading_surface
    from tests.test_live_logcat_material import MaterialHost

    BaseStyles.switch_theme(theme)
    host = MaterialHost(False)
    host.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    layout = QHBoxLayout(host)
    reader = control_type(host)
    reference = control_type(host)
    reader.setReadOnly(True)
    reference.setReadOnly(True)
    reader.setPlainText("Native reading text 123")
    reference.setPlainText("Native reading text 123")
    apply_reading_surface(reader)
    layout.addWidget(reader)
    layout.addWidget(reference)
    host.resize(640, 320)
    host.show()
    qt_application.processEvents()

    def snapshot(control):
        host.setFocus()
        QTest.mouseMove(host, QPoint(2, 2))
        if state == "focus":
            _focus(control, qt_application)
        elif state == "disabled":
            control.setEnabled(False)
        qt_application.processEvents()
        # 原生鼠标移动异步到达；渲染对照通过正常事件明确外框和视口的同一悬停态。
        for widget in (control, control.viewport()):
            if state == "hover":
                point = QPoint(20, 20)
                event = QEnterEvent(
                    QPointF(point), QPointF(widget.mapTo(host, point)),
                    QPointF(widget.mapToGlobal(point)),
                )
            else:
                event = QEvent(QEvent.Type.Leave)
            qt_application.sendEvent(widget, event)
            assert widget.underMouse() == (state == "hover")
        return _composited_frame(host, control)

    try:
        assert snapshot(reader) == snapshot(reference)
    finally:
        host.close()


@pytest.mark.parametrize("control_type", (PlainTextEdit, TextEdit))
@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_mica_reader_returns_to_native_when_editable_and_transparent_when_readonly(
    qt_application, control_type, theme,
):
    from gui.styles.fluent import apply_reading_surface
    from tests.test_live_logcat_material import MaterialHost, surface_pixel

    BaseStyles.switch_theme(theme)
    host = MaterialHost(True)
    layout = QHBoxLayout(host)
    reader = control_type(host)
    reference = control_type(host)
    reader.setReadOnly(True)
    apply_reading_surface(reader)
    layout.addWidget(reader)
    layout.addWidget(reference)
    host.resize(640, 320)
    host.show()
    qt_application.processEvents()
    try:
        assert surface_pixel(host, reader) == host.backdrop
        reader.setReadOnly(False)
        _focus(reader, qt_application)
        editable = _composited_frame(host, reader)
        _focus(reference, qt_application)
        assert editable == _composited_frame(host, reference)
        reader.setReadOnly(True)
        _focus(reader, qt_application)
        assert surface_pixel(host, reader) == host.backdrop
    finally:
        host.close()


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_repeated_surface_refresh_retains_native_text_palette(qt_application, theme):
    from gui.styles.fluent import apply_reading_surface
    from gui.styles.reading_surface import ensure_reading_surface

    BaseStyles.switch_theme(theme)
    host = QWidget()
    reader = PlainTextEdit(host)
    reference = PlainTextEdit(host)
    reader.setReadOnly(True)
    reference.setReadOnly(True)
    apply_reading_surface(reader)
    reference.ensurePolished()
    material = ensure_reading_surface(reader)
    material.refresh(force=True)
    assert reader.palette().color(QPalette.ColorRole.Text) == reference.palette().color(
        QPalette.ColorRole.Text,
    )
    host.close()


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_app_details_rich_text_uses_material_and_stops_on_dispose(
    qt_application, monkeypatch, theme,
):
    from gui.dialogs.app_manager_details import AppDetailsPage
    from tests.test_live_logcat_material import MaterialHost, surface_pixel

    def reject_worker(*_args, **_kwargs):
        pytest.fail("阅读表面测试不得启动设备 worker")

    monkeypatch.setattr("gui.dialogs.app_manager_details.AppManagerWorker.start", reject_worker)
    BaseStyles.switch_theme(theme)
    host = MaterialHost(True)
    page = AppDetailsPage(host)
    QVBoxLayout(host).addWidget(page)
    page.detail_text.setHtml("<b>Package:</b> com.example.reading")
    document = page.detail_text.document()
    before = document.toHtml()
    host.resize(820, 680)
    host.show()
    try:
        qt_application.processEvents()
        assert surface_pixel(host, page.detail_text) == host.backdrop
        BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
        qt_application.processEvents()
        assert surface_pixel(host, page.detail_text) == host.backdrop
        assert page.detail_text.document() is document
        assert document.toHtml() == before
        material = page.detail_text._adblab_reading_surface
        calls = []
        monkeypatch.setattr(material, "_apply_surface", lambda *args: calls.append(args))
        assert page.request_dispose("test")
        host.setMicaEffectEnabled(False)
        BaseStyles.switch_theme(theme)
        material.refresh(force=True)
        qt_application.processEvents()
        assert calls == []
    finally:
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("theme", ("Light", "Dark"))
def test_file_preview_switches_editing_material_and_stops_both_readers(
    qt_application, monkeypatch, theme,
):
    from gui.dialogs.file_explorer import FileExplorerPage
    from gui.styles import FontRole
    from tests.test_live_logcat_material import MaterialHost, surface_pixel

    def reject_worker(*_args, **_kwargs):
        pytest.fail("阅读表面测试不得启动设备 worker")

    monkeypatch.setattr("models.file_explorer_worker.ADBWorker.start", reject_worker)
    BaseStyles.switch_theme(theme)
    host = MaterialHost(True)
    page = FileExplorerPage(host)
    QVBoxLayout(host).addWidget(page)
    host.resize(1000, 700)
    host.show()

    def card_background():
        image = host.grab().toImage()
        panel = page.preview_panel
        point = panel.mapTo(host, QPoint(panel.width() - 5, panel.height() // 2))
        scale = image.devicePixelRatio()
        return image.pixelColor(round(point.x() * scale), round(point.y() * scale))

    try:
        page._show_text_preview("sample.txt", "preview content", "/sample.txt", editable=False)
        qt_application.processEvents()
        reader = page.preview_text_edit
        assert surface_pixel(host, reader) == card_background()
        assert reader.isReadOnly()
        assert reader.font() == BaseStyles.font_for_role(FontRole.MONO)
        page._show_text_preview("sample.txt", "editable content", "/sample.txt", editable=True)
        _focus(reader, qt_application)
        assert surface_pixel(host, reader) != card_background()
        reader.moveCursor(QTextCursor.MoveOperation.End)
        QTest.keyClicks(reader, " changed")
        assert reader.toPlainText() == "editable content changed"
        reader.setReadOnly(True)
        qt_application.processEvents()
        assert surface_pixel(host, reader) == card_background()
        assert reader.toPlainText() == "editable content changed"

        page._show_output_preview("script.sh", "synthetic script error", error=True)
        qt_application.processEvents()
        assert surface_pixel(host, page.preview_output) == card_background()
        assert page.preview_output.property("previewError")
        assert page.preview_output.font() == BaseStyles.font_for_role(FontRole.LOG)
        materials = [item._adblab_reading_surface for item in (reader, page.preview_output)]
        calls = []
        for material in materials:
            monkeypatch.setattr(material, "_apply_surface", lambda *args: calls.append(args))
        assert page.request_dispose("test")
        host.setMicaEffectEnabled(False)
        BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
        for material in materials:
            material.refresh(force=True)
        qt_application.processEvents()
        assert calls == []
    finally:
        host.close()
        host.deleteLater()


def test_performance_dispose_stops_reader_while_page_is_retained(qt_application, monkeypatch):
    page = PerformancePage()
    material = page.log_view._adblab_reading_surface
    calls = []
    monkeypatch.setattr(material, "_apply_surface", lambda *args: calls.append(args))
    try:
        assert page.request_dispose("test")
        material.refresh(force=True)
        BaseStyles.theme_changed.emit(BaseStyles.resolved_theme())
        qt_application.processEvents()
        assert calls == []
    finally:
        page.close()
        page.deleteLater()


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
