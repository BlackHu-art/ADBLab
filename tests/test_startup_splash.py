"""启动画面仅改变原液体的亮度，并在首绘、关闭和缩放时保持契约。"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QElapsedTimer,
    QEvent,
    QEventLoop,
    QPoint,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCursor, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from utils.resource_path import resource_path


def _original_frame(dpr=1.0, source=None):
    frame = QImage(round(240 * dpr), round(240 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    frame.setDevicePixelRatio(dpr)
    frame.fill(Qt.GlobalColor.transparent)
    if source is None:
        source = QImage(resource_path("resources/app-icon.png"))
    source = source.scaled(
        round(192 * dpr), round(192 * dpr),
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )
    source.setDevicePixelRatio(dpr)
    painter = QPainter(frame)
    painter.drawImage(QPoint(24, 24), source)
    painter.end()
    return frame


def _pixel(image, x, y):
    dpr = image.devicePixelRatio()
    return image.pixelColor(round((24 + x * .75) * dpr), round((24 + y * .75) * dpr))


def _wait_until(predicate, timeout=1500):
    deadline = QElapsedTimer()
    deadline.start()
    while not predicate() and deadline.elapsed() < timeout:
        QTest.qWait(10)
    assert predicate()


@pytest.fixture
def splash(qt_application):
    from gui.widgets.startup_splash import StartupSplash

    widget = StartupSplash()
    widget.show()
    qt_application.processEvents()
    yield widget
    widget.finish()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_liquid_progress_preserves_original_art_and_alpha(splash):
    original = _original_frame(splash.devicePixelRatioF())
    frames = []
    for progress in (0, 50, 100):
        splash.set_progress(progress, animate=False)
        image = splash.grab().toImage()
        frames.append(image)
        # 瓶口、瓶身、白色符号和液体之外的下边缘不能被进度遮罩染色。
        for x, y in ((128, 38), (89, 135), (151, 157), (20, 200), (128, 233)):
            assert _pixel(image, x, y) == _pixel(original, x, y)
        assert image.pixelColor(0, 0).alpha() == 0
        actual_alpha = bytes(image.convertToFormat(QImage.Format.Format_RGBA8888).constBits())[3::4]
        source_alpha = bytes(
            original.convertToFormat(QImage.Format.Format_RGBA8888).constBits(),
        )[3::4]
        assert actual_alpha == source_alpha
    assert _pixel(frames[0], 70, 200) != _pixel(original, 70, 200)
    assert _pixel(frames[0], 185, 200) != _pixel(original, 185, 200)
    assert _pixel(frames[1], 70, 200) == _pixel(original, 70, 200)
    assert _pixel(frames[1], 185, 200) != _pixel(original, 185, 200)
    assert frames[2] == original
    assert splash.size() == QSize(240, 240)
    assert splash.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not splash.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose)
    assert splash.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert not splash.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_animation_only_advances_and_stops_at_the_completed_stage(splash):
    original = _original_frame(splash.devicePixelRatioF())
    samples = []
    splash.set_progress(100)
    splash.set_progress(30)
    assert any(timer.isActive() for timer in splash.findChildren(QTimer))
    deadline = QElapsedTimer()
    deadline.start()
    while deadline.elapsed() < 1500:
        image = splash.grab().toImage()
        samples.append(sum(
            _pixel(image, x, 200) != _pixel(original, x, 200) for x in range(40, 215)
        ))
        if not any(timer.isActive() for timer in splash.findChildren(QTimer)):
            break
        QTest.qWait(10)
    assert samples[0] > 0 and samples[-1] == 0
    assert samples == sorted(samples, reverse=True)
    assert not any(timer.isActive() for timer in splash.findChildren(QTimer))
    splash.set_progress(-5, animate=False)
    assert splash.grab().toImage() == original


def test_blocking_startup_stages_paint_intermediate_progress_without_extra_wait(qt_application):
    from gui.startup import StartupController
    from gui.widgets.startup_splash import StartupSplash

    painted = []

    class ObservedSplash(StartupSplash):
        def paintEvent(self, event):
            painted.append(self._progress)
            super().paintEvent(event)

    class Window(QWidget):
        startup_aborted = Signal()

        def abort_startup(self):
            self.hide()
            self.startup_aborted.emit()

    widget = ObservedSplash()
    window = Window()
    startup = StartupController(widget)
    loop = QEventLoop()
    ready = []
    startup.ready.connect(lambda _window: (ready.append(True), loop.quit()))
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)

    def stages():
        startup.set_window(window)
        for index in range(11):
            # 模拟 QWidget 构造占用 GUI 线程，期间动画定时器没有机会触发。
            time.sleep(.08)
            yield f"stage-{index}", (index + 1) * 8

    startup.start(stages())
    watchdog.start(3000)
    loop.exec()
    watchdog.stop()
    assert ready == [True]
    intermediate = {progress for progress in painted if 0 < progress < 100}
    assert len(intermediate) >= 5, painted
    assert painted == sorted(painted)
    assert not widget.isVisible()
    window.close()
    startup.deleteLater()


@pytest.mark.parametrize("termination", ["finish", "close"])
def test_completion_and_user_close_stop_animation_without_duplicate_signals(splash, termination):
    cancelled = []
    splash.cancelled.connect(lambda: cancelled.append(True))
    splash.set_progress(90)
    getattr(splash, termination)()
    assert not splash.isVisible()
    assert not any(timer.isActive() for timer in splash.findChildren(QTimer))
    assert cancelled == ([] if termination == "finish" else [True])
    splash.finish()
    splash.finish()
    splash.close()
    splash.set_progress(100)
    assert not any(timer.isActive() for timer in splash.findChildren(QTimer))
    assert cancelled == ([] if termination == "finish" else [True])


def test_first_painted_is_queued_once_and_hidden_render_does_not_start(qt_application):
    from gui.widgets.startup_splash import StartupSplash

    class ObservedSplash(StartupSplash):
        painting = False

        def paintEvent(self, event):
            self.painting = True
            super().paintEvent(event)
            self.painting = False

    widget = ObservedSplash()
    painted = []
    widget.first_painted.connect(lambda: painted.append(widget.painting))
    target = QPixmap(widget.size())
    widget.render(target)
    qt_application.processEvents()
    assert not painted
    widget.show()
    _wait_until(lambda: bool(painted))
    assert painted == [False]
    position = widget.pos()
    for progress in (20, 60, 100):
        widget.set_progress(progress, animate=False)
        widget.repaint()
        qt_application.processEvents()
    assert painted == [False]
    assert widget.pos() == position
    widget.finish()


def test_finish_before_first_paint_delivery_cancels_start_signal(qt_application):
    from gui.widgets.startup_splash import StartupSplash

    widget = StartupSplash()
    painted = []
    widget.first_painted.connect(lambda: painted.append(True))
    widget.show()
    widget.repaint()
    widget.finish()
    qt_application.processEvents()
    assert painted == []


def test_first_visible_paint_already_uses_screen_center(qt_application):
    from gui.widgets.startup_splash import StartupSplash

    positions = []

    class ObservedSplash(StartupSplash):
        def paintEvent(self, event):
            if self.isVisible():
                positions.append(self.pos())
            super().paintEvent(event)

    widget = ObservedSplash()
    widget.move(7, 11)
    screen = QGuiApplication.screenAt(QCursor.pos()) or widget.screen()
    assert screen is not None
    expected = screen.availableGeometry().center() - widget.rect().center()
    widget.show()
    _wait_until(lambda: bool(positions))
    assert positions[0] == expected
    qt_application.processEvents()
    assert all(position == expected for position in positions)
    widget.finish()


def test_missing_high_resolution_image_falls_back_once_and_repaint_does_not_read_paths(
    qt_application, monkeypatch, tmp_path,
):
    from gui.widgets import startup_splash

    resolved = []

    def resolve(relative):
        resolved.append(relative)
        if relative == "resources/app-icon.png":
            return str(tmp_path / "absent.png")
        return resource_path(relative)

    monkeypatch.setattr(startup_splash, "resource_path", resolve)
    widget = startup_splash.StartupSplash()
    widget.show()
    qt_application.processEvents()
    initial_paths = list(resolved)
    assert initial_paths == ["resources/app-icon.png", "icon.ico"]
    for progress in (0, 50, 100):
        widget.set_progress(progress, animate=False)
        widget.repaint()
        image = widget.grab().toImage()
        assert _pixel(image, 128, 40).alpha() > 0
    assert resolved == initial_paths
    best_icon = QIcon(resource_path("icon.ico")).pixmap(256, 256).toImage()
    assert widget.grab().toImage() == _original_frame(widget.devicePixelRatioF(), best_icon)
    widget.finish()


@pytest.mark.parametrize("scale", ["1", "1.5", "2"])
def test_cold_qt_splash_uses_dpr_without_loading_fluent_or_settings(tmp_path, scale):
    script = """
import json, sys
from PySide6.QtWidgets import QApplication
from gui.widgets.startup_splash import StartupSplash
app = QApplication([])
widget = StartupSplash()
widget.set_progress(100, animate=False)
widget.show()
app.processEvents()
pixmap = widget.grab()
print(json.dumps({
    'logical': [widget.width(), widget.height()],
    'physical': [pixmap.width(), pixmap.height()],
    'dpr': pixmap.devicePixelRatio(),
    'alpha': pixmap.toImage().pixelColor(0, 0).alpha(),
    'forbidden': [name for name in sys.modules if name == 'qfluentwidgets'
                  or name == 'gui.styles' or name == 'core.settings_manager'],
}))
widget.finish()
"""
    environment = dict(
        os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=scale,
        LOCALAPPDATA=str(tmp_path), APPDATA=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path),
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        env=environment, text=True, capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["logical"] == [240, 240]
    assert payload["physical"] == [round(240 * float(scale))] * 2
    assert payload["dpr"] == float(scale)
    assert payload["alpha"] == 0
    assert payload["forbidden"] == []
