"""真实工作区验证主窗口配色同步不会覆盖阅读框材质；设备调用使用替身。"""

import pytest
from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget
from qfluentwidgets import FluentWindow, TableWidget

from gui.styles import BaseStyles
from tests.test_live_logcat_visual import _contrast
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame
from tests.test_navigation_rendering import _native_content_color
from tests.ui_geometry_helpers import wait_for_stable_geometry, wait_until

pytestmark = pytest.mark.ui


def _pixel(root, editor):
    image = root.grab().toImage()
    point = editor.viewport().mapTo(root, QPoint(30, editor.viewport().height() - 30))
    scale = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * scale), round(point.y() * scale))


def _file_list_color(background, application):
    host = QWidget()
    host.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    palette = host.palette()
    palette.setColor(QPalette.ColorRole.Window, background)
    host.setPalette(palette)
    host.setAutoFillBackground(True)
    editor = TableWidget(host)
    editor.setFrameShape(QFrame.Shape.NoFrame)
    QVBoxLayout(host).addWidget(editor)
    host.resize(250, 180)
    host.show()
    host.activateWindow()
    host.setFocus()
    for control in (editor, editor.viewport()):
        application.sendEvent(control, QEvent(QEvent.Type.Leave))
        assert not control.underMouse()
    application.processEvents()
    result = _pixel(host, editor)
    host.close()
    host.deleteLater()
    return result


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_workspace_palette_accent_and_mica_round_trip_preserve_transparent_log(
    qt_application, monkeypatch, theme,
):
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda self: None,
    )

    def native_mica(window, enabled):
        window._isMicaEnabled = enabled
        window.setBackgroundColor(window._normalBackgroundColor())

    monkeypatch.setattr(FluentWindow, "setMicaEffectEnabled", native_mica)
    monkeypatch.setattr("gui.window_effects.sync_mica_backdrop", lambda *_args: True)
    BaseStyles.switch_theme(theme)
    frame = build_main_frame(
        screen_adapter=_FakeScreenAdapter(_FakeScreen("reader", QSize(1600, 1100))),
    )
    original_background = frame._normalBackgroundColor
    monkeypatch.setattr(
        frame, "_normalBackgroundColor",
        lambda: QColor("#7191ab") if frame.isMicaEffectEnabled() else original_background(),
    )
    original_accent = BaseStyles.accent_color()
    try:
        frame.show()
        host = frame._workspace_feature_hosts["system"]
        host.set_device_context(["demo-a"], ["demo-a"])
        assert frame._open_workspace_feature("system", "logcat", device_id="demo-a")
        page = host.stack.currentWidget()
        levels = "VDIWEFSU"
        original_text = "\n".join(
            f"09-17 11:06:12.123  1024  1030 {level} DemoService: synthetic reading content"
            for level in levels
        )
        page.output.setPlainText(original_text)
        wait_for_stable_geometry(qt_application, (frame, page, page.output))
        assert page.output.isVisibleTo(frame)
        for mica in (False, True, False):
            frame.setMicaEffectEnabled(mica)
            # 覆盖主窗口的 palette 与强调色重建路径，不能只验证独立阅读框。
            frame._refresh_window_chrome_theme()
            BaseStyles.set_accent_color("#9B327D" if mica else "#0F6CBD")
            page.pkg_input.setFocus()
            qt_application.processEvents()
            content = _native_content_color(frame.backgroundColor)
            expected = _file_list_color(content, qt_application)
            assert expected == content
            frame.activateWindow()
            page.pkg_input.setFocus()
            for control in (page.output, page.output.viewport()):
                qt_application.sendEvent(control, QEvent(QEvent.Type.Leave))
                assert not control.underMouse()
            try:
                wait_until(qt_application, lambda: _pixel(frame, page.output) == expected)
            except AssertionError as error:
                raise AssertionError((
                    theme, mica, _pixel(frame, page.output).name(), expected.name(),
                )) from error
            assert page.output.toPlainText() == original_text
            if not mica:
                page.highlighter.rehighlight()
                for hovered in (False, True):
                    if hovered:
                        QTest.mouseMove(page.output.viewport(), QPoint(30, 30))
                        wait_until(qt_application, page.output.viewport().underMouse)
                    background = _pixel(frame, page.output)
                    for index, level in enumerate(levels):
                        block = page.output.document().findBlockByNumber(index)
                        formats = block.layout().formats()
                        foreground = formats[0].format.foreground().color()
                        assert _contrast(foreground, background) >= 4.5, (
                            theme, level, hovered, foreground.name(), background.name(),
                        )
            assert page.worker is None and page._pkg_worker is None
    finally:
        BaseStyles.set_accent_color(original_accent)
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
