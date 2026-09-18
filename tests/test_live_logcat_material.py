"""日志材质跟随真实宿主，合成背景验证不读取桌面或连接设备。"""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QPainter, QPalette, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget
from qfluentwidgets import PlainTextEdit, TableWidget, setCustomStyleSheet
from shiboken6 import isValid

from gui.dialogs.live_logcat_highlighter import LogcatHighlighter
from gui.dialogs.live_logcat_material import LogcatMaterial
from gui.styles import BaseStyles, FontRole
from tests.ui_geometry_helpers import wait_until

pytestmark = pytest.mark.ui


class PaintedHost(QWidget):
    def __init__(self):
        super().__init__()
        self.backdrop = QColor("#6388ad")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.backdrop)


class MaterialHost(PaintedHost):
    def __init__(self, mica):
        super().__init__()
        self.mica = mica

    def isMicaEffectEnabled(self):
        return self.mica

    def setMicaEffectEnabled(self, enabled):
        self.mica = enabled
        self.update()


@pytest.fixture
def log_surface(qt_application):
    hosts = []

    def build(theme="Light", mica=True, supported=True):
        BaseStyles.switch_theme(theme)
        host = MaterialHost(mica) if supported else PaintedHost()
        hosts.append(host)
        owner = QWidget(host)
        QVBoxLayout(host).addWidget(owner)
        output = PlainTextEdit(owner)
        output.setReadOnly(True)
        output.setLineWrapMode(PlainTextEdit.LineWrapMode.NoWrap)
        output.setUndoRedoEnabled(False)
        output.document().setDocumentMargin(12)
        QVBoxLayout(owner).addWidget(output)
        styles = []
        for name in ("Light", "Dark"):
            styles.append(
                "PlainTextEdit {"
                f"background: {BaseStyles.color_for(name, 'LOG_BACKGROUND')};"
                f"color: {BaseStyles.color_for(name, 'LOG_TEXT_COLOR')};"
                "border: 1px solid gray; border-radius: 6px;}"
            )
        setCustomStyleSheet(output, *styles)
        font = BaseStyles.font_for_role(FontRole.LOG)
        output.setFont(font)
        output.document().setDefaultFont(font)
        material = LogcatMaterial(owner, output)
        host.resize(640, 360)
        host.show()
        qt_application.processEvents()
        return host, owner, output, material

    yield build
    for host in hosts:
        host.close()
        host.deleteLater()


def surface_pixel(host, output):
    image = host.grab().toImage()
    point = output.viewport().mapTo(
        host, QPoint(output.viewport().width() - 25, output.viewport().height() - 25),
    )
    scale = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * scale), round(point.y() * scale))


def native_surface_colors(application, output, backdrop):
    """用相同父级底色与焦点状态渲染当前安装版本的原生控件。"""
    previous_window = application.activeWindow()
    previous_focus = application.focusWidget()
    focused = output.hasFocus()
    host = PaintedHost()
    host.backdrop = backdrop
    host.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    reference = PlainTextEdit(host)
    reference.setReadOnly(True)
    QVBoxLayout(host).addWidget(reference)
    host.resize(640, 360)
    host.show()
    application.setActiveWindow(host)
    QTest.mouseMove(host, QPoint(2, 2))
    (reference if focused else host).setFocus()
    application.processEvents()
    result = surface_pixel(host, reference), reference.palette().color(QPalette.ColorRole.Text)
    host.close()
    host.deleteLater()
    if previous_window is not None:
        application.setActiveWindow(previous_window)
    if previous_focus is not None:
        previous_focus.setFocus()
    application.processEvents()
    return result


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("state", ["normal", "hover", "focus", "disabled"])
@pytest.mark.parametrize("mica", [True, False, None], ids=["mica", "no-mica", "unsupported"])
def test_output_matches_file_list_background_in_all_interaction_states(
    log_surface, qt_application, theme, state, mica,
):
    host, owner, output, _material = log_surface(theme, bool(mica), supported=mica is not None)
    # 文件管理使用原生 TableWidget + NoFrame，在同一父层验证空白区域的真实像素。
    reference = TableWidget(owner)
    reference.setFrameShape(QFrame.Shape.NoFrame)
    owner.layout().addWidget(reference)
    owner.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    owner.setFocus()
    if state == "hover":
        QTest.mouseMove(output.viewport(), QPoint(30, 30))
    elif state == "focus":
        output.setFocus(Qt.FocusReason.OtherFocusReason)
    elif state == "disabled":
        output.setEnabled(False)
    qt_application.processEvents()
    # 精确投递交互状态，避免上一参数化用例的真实鼠标位置污染普通态像素。
    for widget in (output, output.viewport()):
        if state == "hover":
            point = QPoint(30, 30)
            event = QEnterEvent(
                QPointF(point), QPointF(widget.mapTo(host, point)),
                QPointF(widget.mapToGlobal(point)),
            )
        else:
            event = QEvent(QEvent.Type.Leave)
        qt_application.sendEvent(widget, event)
        assert widget.underMouse() == (state == "hover")
    assert output.hasFocus() == (state == "focus")

    assert surface_pixel(host, output) == surface_pixel(host, reference) == host.backdrop
    assert output.layer.isHidden()
    for widget in (output, output.viewport()):
        for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window):
            brush = widget.palette().brush(role)
            # Qt polish 可将透明 Base 规范化为 NoBrush，其默认 color 本身不代表填充。
            assert brush.style() == Qt.BrushStyle.NoBrush or brush.color().alpha() == 0
    assert not output.autoFillBackground()
    assert not output.viewport().autoFillBackground()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_mica_toggle_without_theme_signal_and_hidden_page_restore(
    log_surface, qt_application, theme,
):
    host, owner, output, _material = log_surface(theme, False)
    assert surface_pixel(host, output) == host.backdrop
    host.setMicaEffectEnabled(True)
    wait_until(qt_application, lambda: surface_pixel(host, output) == host.backdrop)

    owner.hide()
    host.setMicaEffectEnabled(False)
    qt_application.processEvents()
    owner.show()
    wait_until(qt_application, lambda: surface_pixel(host, output) == host.backdrop)


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_unsupported_host_keeps_transparent_background_and_native_text(
    log_surface, qt_application, theme,
):
    host, _owner, output, _material = log_surface(theme, supported=False)
    _background, text = native_surface_colors(qt_application, output, host.backdrop)
    assert surface_pixel(host, output) == host.backdrop
    assert output.palette().color(QPalette.ColorRole.Text) == text


def test_material_rebinds_when_log_page_moves_to_another_window(log_surface, qt_application):
    source, owner, output, _material = log_surface(mica=False)
    target = MaterialHost(True)
    target.backdrop = QColor("#907143")
    target.resize(640, 360)
    QVBoxLayout(target).addWidget(owner)
    target.show()
    try:
        # 重挂后原生窗口会延后分配焦点；先固定正常态，避免参考窗口改变比较状态。
        target.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        qt_application.setActiveWindow(target)
        target.setFocus()
        wait_until(qt_application, lambda: target.hasFocus() and not output.hasFocus())
        wait_until(qt_application, lambda: surface_pixel(target, output) == target.backdrop)
        source.setMicaEffectEnabled(True)
        target.setMicaEffectEnabled(False)
        wait_until(qt_application, lambda: surface_pixel(target, output) == target.backdrop)
    finally:
        target.close()
        target.deleteLater()


def test_refresh_preserves_document_log_font_highlights_selection_and_reading_anchor(
    log_surface, qt_application,
):
    host, _owner, output, material = log_surface(mica=False)
    text = "\n".join(f"historical line {index:03d} " + "detail " * 40 for index in range(180))
    output.setPlainText(text)
    highlighter = LogcatHighlighter(output.document())
    highlighter.set_theme({"U": "#c43535"})
    cursor = QTextCursor(output.document().findBlockByNumber(50))
    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 10)
    output.setTextCursor(cursor)
    qt_application.processEvents()
    output.verticalScrollBar().setValue(45)
    output.horizontalScrollBar().setValue(50)
    document = output.document()
    font = output.font()
    document_font = document.defaultFont()
    selection = output.textCursor().selectedText()
    anchor = output.firstVisibleBlock().text()
    scroll = output.verticalScrollBar().value(), output.horizontalScrollBar().value()

    for theme, mica in (("Dark", True), ("Light", False)):
        host.setMicaEffectEnabled(mica)
        BaseStyles.switch_theme(theme)
        material.refresh(force=True)
        qt_application.processEvents()
        assert output.document() is document
        assert output.toPlainText() == text
        assert output.font() == font
        assert output.document().defaultFont() == document_font
        assert output.textCursor().selectedText() == selection
        assert output.firstVisibleBlock().text() == anchor
        assert (output.verticalScrollBar().value(), output.horizontalScrollBar().value()) == scroll
        assert document.firstBlock().layout().formats()[0].format.foreground().color() == QColor(
            "#c43535",
        )


def test_stop_ignores_late_events_without_mutating_a_new_page(
    log_surface, qt_application, monkeypatch,
):
    host, _owner, _output, material = log_surface(mica=False)
    updates = []
    monkeypatch.setattr(material, "_apply_surface", lambda *args: updates.append(args))
    material.stop()
    material.stop()
    other_host, _other_owner, other_output, _other_material = log_surface(mica=True)
    host.setMicaEffectEnabled(True)
    BaseStyles.switch_theme("Dark")
    material.refresh(force=True)
    qt_application.processEvents()
    assert updates == []
    assert surface_pixel(other_host, other_output) == other_host.backdrop


def test_deleting_page_releases_material_and_removes_callbacks(log_surface, qt_application):
    host, owner, output, material = log_surface()
    owner.deleteLater()
    qt_application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(owner)
    assert not isValid(output)
    assert not isValid(material)
    host.setMicaEffectEnabled(False)
    BaseStyles.switch_theme("Dark")
    qt_application.processEvents()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_live_page_integration_keeps_reading_state_and_stops_callbacks(
    qt_application, monkeypatch, theme,
):
    from gui.dialogs.live_logcat import LiveLogcatPage

    def reject_worker(*_args, **_kwargs):
        pytest.fail("日志材质测试不得启动设备 worker")

    monkeypatch.setattr("gui.dialogs.live_logcat.LogcatWorker", reject_worker)
    monkeypatch.setattr("gui.dialogs.live_logcat.CurrentPackageWorker", reject_worker)
    BaseStyles.switch_theme(theme)
    host = MaterialHost(False)
    page = LiveLogcatPage(host)
    QVBoxLayout(host).addWidget(page)
    host.resize(820, 680)
    host.show()
    try:
        qt_application.processEvents()
        output = page.output
        assert surface_pixel(host, output) == host.backdrop
        text = "\n".join(f"historical log {index:03d}" for index in range(150))
        output.setPlainText(text)
        cursor = QTextCursor(output.document().findBlockByNumber(40))
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 10)
        output.setTextCursor(cursor)
        output.verticalScrollBar().setValue(35)
        anchor = output.firstVisibleBlock().text()
        selection = output.textCursor().selectedText()
        scroll = output.verticalScrollBar().value()
        output.setFocus()

        host.setMicaEffectEnabled(True)
        wait_until(qt_application, lambda: surface_pixel(host, output) == host.backdrop)
        BaseStyles.switch_theme("Dark" if theme == "Light" else "Light")
        qt_application.processEvents()
        assert surface_pixel(host, output) == host.backdrop
        assert output.toPlainText() == text
        assert output.textCursor().selectedText() == selection
        assert output.firstVisibleBlock().text() == anchor
        assert output.verticalScrollBar().value() == scroll
        assert output.font() == BaseStyles.font_for_role(FontRole.LOG)
        assert not page.follow_btn.isChecked()

        host.setMicaEffectEnabled(False)
        wait_until(qt_application, lambda: surface_pixel(host, output) == host.backdrop)
        updates = []
        material = page._form_controller._material
        monkeypatch.setattr(material, "_apply_surface", lambda *args: updates.append(args))
        assert page.request_dispose("test")
        assert isValid(page)
        host.setMicaEffectEnabled(True)
        BaseStyles.switch_theme(theme)
        qt_application.processEvents()
        assert updates == []
    finally:
        page.close()
        host.close()
        host.deleteLater()
