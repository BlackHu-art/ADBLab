"""使用独立合成窗口验证 Windows 侧栏集成，不访问设备或用户配置。"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QWidget
from shiboken6 import isValid

from services.remote.window_tracking import _Win32WindowApi

pytestmark = [
    pytest.mark.ui,
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM") != "windows",
        reason="原生桌面验证需显式 QT_QPA_PLATFORM=windows；默认离屏运行不显示窗口",
    ),
]

_OWNER_SCRIPT = """
import ctypes
import json
import os
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
app = QApplication([])
window = QWidget()
window.setWindowTitle(sys.argv[1])
window.resize(340, 560)
window.move(120, 100)
window.setStyleSheet('background:#172329; color:#d7ede9; font:18px Segoe UI;')
layout = QVBoxLayout(window)
label = QLabel('SYNTHETIC MIRROR\\n\\nNative dock validation\\nNo device connection')
layout.addWidget(label)
window.show()
other = QWidget()
other.setWindowTitle(sys.argv[1] + '-other')
other.resize(260, 180)
other.move(850, 120)
app.processEvents()
user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
user32.AllowSetForegroundWindow.restype = ctypes.c_int
allowed = bool(user32.AllowSetForegroundWindow(int(sys.argv[2])))
print(json.dumps({
    'hwnd': int(window.winId()), 'other_hwnd': int(other.winId()), 'pid': os.getpid(),
    'allowed_parent': allowed,
}), flush=True)
QTimer.singleShot(45000, app.quit)
app.exec()
"""


def _wait(application, predicate, explanation, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), explanation


class _Frame:
    _closing = False
    _remote_input_closing = False
    _connected_remote_devices = frozenset({"synthetic"})

    def __init__(self, session):
        self._device_sessions = {"synthetic": session}
        self.invalidated = []
        self.calls = []
        self._input_controller = SimpleNamespace(
            _invalidate_session_input=self.invalidated.append,
            _send_session_keyevent=lambda *args: self.calls.append(args),
            _send_session_action=lambda *args: self.calls.append(args),
        )

    def _mirror_device_name(self, device):
        return "合成投屏验证"


@pytest.fixture
def external_window():
    title = "ADBLab-native-dock-" + uuid.uuid4().hex
    environment = dict(os.environ, QT_QPA_PLATFORM="windows", QT_SCALE_FACTOR="1")
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", _OWNER_SCRIPT, title, str(os.getpid())],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    results = queue.Queue()
    reader = threading.Thread(target=lambda: results.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        line = results.get(timeout=12)
        assert line, "合成外部窗口未报告就绪"
        info = json.loads(line)
        yield process, info, title
    finally:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]
        user.PostMessageW.restype = wintypes.BOOL
        if process.poll() is None and "info" in locals():
            user.PostMessageW(info["other_hwnd"], 0x0010, 0, 0)
            user.PostMessageW(info["hwnd"], 0x0010, 0, 0)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=2)
        assert not reader.is_alive()
        process.stdout.close()
        process.stderr.close()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_native_mica_blank_surfaces_keep_full_pointer_hit_targets(qt_application, theme):
    """仅查询合成窗口的原生命中；Qt 直接分发点击不能证明窗口没有穿透。"""
    from gui.styles import BaseStyles
    from gui.widgets.remote_toolbar import RemoteToolbar
    from gui.window_effects import is_mica_supported

    if not is_mica_supported():
        pytest.skip("原生 Mica 命中回归需要 Windows 11 支持；实色和绘制回归独立覆盖")

    class Host(QWidget):
        enabled = False

        def isMicaEffectEnabled(self):
            return self.enabled

    api = _Win32WindowApi()
    user = api._user32
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.ClientToScreen.restype = wintypes.BOOL
    BaseStyles.switch_theme(theme)
    host = Host()
    host.setWindowFlags(
        Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowStaysOnTopHint,
    )
    host.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    host.setGeometry(80, 80, 700, 760)
    host.setStyleSheet("background: #883399;")
    toolbar = RemoteToolbar(host)
    toolbar.set_available(True)
    toolbar.move(120, 120)
    popup = toolbar.popup_window
    foreground = int(user.GetForegroundWindow() or 0)
    try:
        host.show()
        toolbar.show()
        toolbar._more_button.click()
        _wait(qt_application, popup.isVisible, "合成更多面板未展开")
        handles = (int(toolbar.winId()), int(popup.winId()))
        geometries = (toolbar.geometry(), popup.geometry())
        for mica_enabled in (False, True, False):
            host.enabled = mica_enabled
            toolbar._material.refresh(force=True)
            qt_application.processEvents()
            assert toolbar.isMicaEffectEnabled() is mica_enabled
            assert popup.isMicaEffectEnabled() is mica_enabled
            for surface, button in (
                (toolbar, toolbar._common_buttons[0]),
                (popup, toolbar._commands["rotate_portrait"][1]),
            ):
                surface.repaint()
                hwnd = int(surface.winId())
                assert user.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0013)
                ratio = surface.devicePixelRatioF()
                image = surface.grab().toImage()
                alpha = image.pixelColor(round(20 * ratio), round(4 * ratio)).alpha()
                assert 0 < alpha < 20 if mica_enabled else alpha == 255
                for point in (
                    QPoint(20, 4),
                    button.mapTo(surface, QPoint(4, button.height() // 2)),
                    button.mapTo(surface, QPoint(button.width() - 5, button.height() // 2)),
                ):
                    with api._physical_coordinates():
                        origin = wintypes.POINT(0, 0)
                        assert user.ClientToScreen(hwnd, ctypes.byref(origin))
                        position = wintypes.POINT(
                            origin.x + round(point.x() * ratio),
                            origin.y + round(point.y() * ratio),
                        )

                        def hits_surface():
                            return user.GetAncestor(user.WindowFromPoint(position), 2) == hwnd

                        _wait(
                            qt_application, hits_surface,
                            f"{surface.objectName()} {point} 在 {theme}/Mica={mica_enabled} 穿透",
                        )
            assert (int(toolbar.winId()), int(popup.winId())) == handles
            assert (toolbar.geometry(), popup.geometry()) == geometries
            assert int(user.GetForegroundWindow() or 0) == foreground
    finally:
        toolbar.dispose()
        host.close()


def test_native_dark_more_icons_and_mouse_feedback_stay_legible(
    qt_application, external_window,
):
    from gui.panels.remote_panel_dock import RemotePanelDock
    from gui.styles import BaseStyles

    BaseStyles.switch_theme("Dark")
    process, info, title = external_window
    session = SimpleNamespace(
        config=SimpleNamespace(device="synthetic", no_window=False, window_title=title),
        process=process, state="ready", resource_owned=True, cancel_event=threading.Event(),
    )
    frame = _Frame(session)
    parent = QWidget()
    dock = RemotePanelDock(frame, parent)
    api = _Win32WindowApi()
    measurements = []
    entry = None
    more = None
    artifacts = os.environ.get("ADBLAB_NATIVE_DOCK_ARTIFACT_DIR")
    directory = Path(artifacts) if artifacts else None
    scale = os.environ.get("QT_SCALE_FACTOR", "default")
    if directory:
        directory.mkdir(parents=True, exist_ok=True)

    def record(button, stage):
        surface = entry.toolbar.grab().toImage()
        ratio = surface.devicePixelRatio()
        image = surface.copy(
            round(button.x() * ratio), round(button.y() * ratio),
            round(button.width() * ratio), round(button.height() * ratio),
        )
        icon_width = round(button.iconSize().width() * ratio)
        icon_height = round(button.iconSize().height() * ratio)
        left = (image.width() - icon_width) // 2
        top = (image.height() - icon_height) // 2
        background = image.pixelColor(image.width() // 2, round(3 * ratio)).lightness()
        icon_lightness = [
            image.pixelColor(x, y).lightness()
            for x in range(left, left + icon_width)
            for y in range(top, top + icon_height)
        ]
        accent = QColor(BaseStyles.color("BORDER_FOCUS"))
        edge_colors = [
            image.pixelColor(x, y)
            for offset in range(int(ratio) + 1)
            for x, y in (
                (image.width() // 2, offset),
                (image.width() // 2, image.height() - 1 - offset),
                (offset, image.height() // 2),
                (image.width() - 1 - offset, image.height() // 2),
            )
        ]
        measurement = {
            "stage": stage,
            "foreground_hwnd": int(api._user32.GetForegroundWindow() or 0),
            "qt_dpr": ratio,
            "enabled": button.isEnabled(),
            "checked": button.isChecked(),
            "down": button.isDown(),
            "background_lightness": background,
            "icon_max_lightness": max(icon_lightness),
            "bright_icon_pixels": sum(value >= background + 45 for value in icon_lightness),
            "edge_colors": [color.name() for color in edge_colors],
        }
        measurements.append(measurement)
        if directory:
            assert image.save(str(directory / f"native-dark-button-scale-{scale}-{stage}.png"))
            if stage == "more-normal-off":
                assert surface.save(str(directory / f"native-dark-toolbar-normal-{scale}.png"))
        assert measurement["bright_icon_pixels"] >= 3, measurements
        assert accent not in edge_colors, "鼠标反馈不可留下键盘导航的强调边框"

    try:
        dock.sync()
        entry = dock.entries["synthetic"]
        _wait(qt_application, entry.toolbar.isVisible, "侧栏未显示")
        dock.tick()
        more = entry.toolbar._more_button
        collapse = entry.toolbar._collapse_button
        record(more, "more-normal-off")
        record(collapse, "collapse-expanded")
        QTest.mousePress(more, Qt.MouseButton.LeftButton)
        assert more.isDown()
        record(more, "more-pressed-off")
        dock.tick()
        QTest.mouseRelease(more, Qt.MouseButton.LeftButton)
        assert entry.toolbar.popup_window.isVisible() and more.isChecked()
        record(more, "more-opened-on")
        if directory:
            assert entry.toolbar.grab().save(str(directory / f"native-dark-toolbar-{scale}.png"))
            assert entry.toolbar.popup_window.grab().save(
                str(directory / f"native-dark-popup-{scale}.png"),
            )
        QTest.mouseClick(more, Qt.MouseButton.LeftButton)
        assert not entry.toolbar.popup_window.isVisible()
        record(more, "more-closed-off")
        QTest.mouseClick(collapse, Qt.MouseButton.LeftButton)
        assert entry.toolbar.collapsed
        record(collapse, "collapse-collapsed")
        QTest.mouseClick(collapse, Qt.MouseButton.LeftButton)
        assert not entry.toolbar.collapsed
        frame._connected_remote_devices = frozenset()
        dock.tick()
        assert not more.isEnabled()
        record(more, "more-disabled-off")
        assert not frame.calls
        assert len({item["foreground_hwnd"] for item in measurements}) == 1, measurements
    finally:
        if more is not None and isValid(more) and more.isDown():
            QTest.mouseRelease(more, Qt.MouseButton.LeftButton)
        if directory:
            (directory / f"native-dark-buttons-scale-{scale}.json").write_text(
                json.dumps(measurements, indent=2), encoding="utf-8",
            )
        dock.close()
        parent.close()


def test_native_theme_and_accent_changes_update_open_and_collapsed_surfaces(
    qt_application, external_window,
):
    from gui.panels.remote_panel_dock import RemotePanelDock
    from gui.styles import BaseStyles

    original_accent = BaseStyles.accent_color()
    BaseStyles.switch_theme("Dark")
    process, info, title = external_window
    session = SimpleNamespace(
        config=SimpleNamespace(device="synthetic", no_window=False, window_title=title),
        process=process, state="ready", resource_owned=True, cancel_event=threading.Event(),
    )
    frame = _Frame(session)
    parent = QWidget()
    dock = RemotePanelDock(frame, parent)
    api = _Win32WindowApi()
    measurements = []
    selected_colors = {"Light": {}, "Dark": {}}
    artifacts = os.environ.get("ADBLAB_NATIVE_DOCK_ARTIFACT_DIR")
    directory = Path(artifacts) if artifacts else None
    scale = os.environ.get("QT_SCALE_FACTOR", "default")
    if directory:
        directory.mkdir(parents=True, exist_ok=True)

    def widget_image(surface, widget):
        ratio = surface.devicePixelRatio()
        return surface.copy(
            round(widget.x() * ratio), round(widget.y() * ratio),
            round(widget.width() * ratio), round(widget.height() * ratio),
        )

    try:
        dock.sync()
        toolbar = dock.entries["synthetic"].toolbar
        _wait(qt_application, toolbar.isVisible, "侧栏未显示")
        toolbar_hwnd = int(toolbar.winId())
        popup_hwnd = int(toolbar.popup_window.winId())
        foreground = int(api._user32.GetForegroundWindow() or 0)
        for presentation in ("open", "collapsed"):
            if presentation == "open":
                QTest.mouseClick(toolbar._more_button, Qt.MouseButton.LeftButton)
            else:
                QTest.mouseClick(toolbar._collapse_button, Qt.MouseButton.LeftButton)
            for accent in ("#D04080", "#159B85"):
                for index, theme in enumerate(("Dark", "Light", "Dark")):
                    BaseStyles.switch_theme(theme)
                    BaseStyles.set_accent_color(accent)
                    qt_application.processEvents()
                    dock.tick()
                    assert toolbar.collapsed is (presentation == "collapsed")
                    assert toolbar.popup_window.isVisible() is (presentation == "open")
                    assert int(toolbar.winId()) == toolbar_hwnd
                    assert int(toolbar.popup_window.winId()) == popup_hwnd
                    assert api._get_window_long(toolbar_hwnd, -8) == info["hwnd"]
                    assert api._get_window_long(popup_hwnd, -8) == toolbar_hwnd
                    assert int(api._user32.GetForegroundWindow() or 0) == foreground
                    stage = f"{presentation}-{accent[1:]}-{index}-{theme.lower()}"
                    background = QColor(BaseStyles.color("TOOLBAR_BG"))
                    surfaces = [("toolbar", toolbar)]
                    if presentation == "open":
                        surfaces.append(("popup", toolbar.popup_window))
                    for name, widget in surfaces:
                        image = widget.grab().toImage()
                        ratio = image.devicePixelRatio()
                        sampled = image.pixelColor(image.width() // 2, round(4 * ratio))
                        assert sampled == background, (stage, name, sampled, background)
                        corners = ((0, 0), (image.width() - 1, 0),
                                   (0, image.height() - 1),
                                   (image.width() - 1, image.height() - 1))
                        assert all(image.pixelColor(x, y).alpha() == 0 for x, y in corners)
                        if directory:
                            assert image.save(str(
                                directory / f"native-theme-{scale}-{stage}-{name}.png",
                            ))
                    toolbar_image = toolbar.grab().toImage()
                    button = (toolbar._more_button if presentation == "open"
                              else toolbar._collapse_button)
                    button_image = widget_image(toolbar_image, button)
                    ratio = button_image.devicePixelRatio()
                    width = round(button.iconSize().width() * ratio)
                    height = round(button.iconSize().height() * ratio)
                    left = (button_image.width() - width) // 2
                    top = (button_image.height() - height) // 2
                    lightness = [button_image.pixelColor(x, y).lightness()
                                 for x in range(left, left + width)
                                 for y in range(top, top + height)]
                    if theme == "Dark":
                        assert max(lightness) > background.lightness() + 80, stage
                    else:
                        assert min(lightness) < background.lightness() - 80, stage
                    if presentation == "open":
                        selected = button_image.pixelColor(
                            button_image.width() // 2, round(3 * ratio),
                        )
                        selected_colors[theme][accent] = selected.name()
                        if accent == "#D04080":
                            assert selected.red() > selected.green(), (stage, selected)
                        else:
                            assert selected.green() > selected.red(), (stage, selected)
                        indicator = widget_image(toolbar_image, toolbar._indicator)
                        expected_accent = QColor(accent)
                        edges = [
                            button_image.pixelColor(x, y)
                            for offset in range(int(ratio) + 1)
                            for x, y in (
                                (button_image.width() // 2, offset),
                                (button_image.width() // 2, button_image.height() - 1 - offset),
                                (offset, button_image.height() // 2),
                                (button_image.width() - 1 - offset, button_image.height() // 2),
                            )
                        ]
                        assert expected_accent not in edges, (stage, "鼠标展开出现强调色边框")
                        assert any(
                            indicator.pixelColor(x, y) == expected_accent
                            for x in range(indicator.width()) for y in range(indicator.height())
                        ), (stage, "指示点未更新强调色")
                    measurements.append({
                        "stage": stage,
                        "qt_dpr": ratio,
                        "background": background.name(),
                        "accent": accent,
                        "icon_min_lightness": min(lightness),
                        "icon_max_lightness": max(lightness),
                        "more_selected_fill": selected.name() if presentation == "open" else None,
                        "toolbar_hwnd": toolbar_hwnd,
                        "popup_hwnd": popup_hwnd,
                        "foreground_hwnd": foreground,
                    })
        assert all(len(set(colors.values())) == 2 for colors in selected_colors.values())
        assert not frame.calls
    finally:
        if directory:
            (directory / f"native-theme-changes-scale-{scale}.json").write_text(
                json.dumps(measurements, indent=2), encoding="utf-8",
            )
        dock.close()
        parent.close()
        BaseStyles.set_accent_color(original_accent)


def test_native_more_mouse_press_survives_dock_poll_and_dispatches_on_release(
    qt_application, external_window,
):
    from gui.panels.remote_panel_dock import RemotePanelDock

    process, info, title = external_window
    session = SimpleNamespace(
        config=SimpleNamespace(device="synthetic", no_window=False, window_title=title),
        process=process, state="ready", resource_owned=True, cancel_event=threading.Event(),
    )
    frame = _Frame(session)
    parent = QWidget()
    dock = RemotePanelDock(frame, parent)
    api = _Win32WindowApi()
    events = []
    button = None
    entry = None
    try:
        dock.sync()
        entry = dock.entries["synthetic"]
        _wait(qt_application, entry.toolbar.isVisible, "侧栏未显示")
        dock.tick()
        QTest.mouseClick(entry.toolbar._more_button, Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        popup = entry.toolbar.popup_window
        assert popup.isVisible()
        button = popup.findChild(QPushButton, "remoteToolbarCommand_rotate_portrait")
        assert button is not None and button.isVisible() and button.isEnabled()
        artifacts = os.environ.get("ADBLAB_NATIVE_DOCK_ARTIFACT_DIR")
        if artifacts:
            directory = Path(artifacts)
            directory.mkdir(parents=True, exist_ok=True)
            scale = os.environ.get("QT_SCALE_FACTOR", "default")
            popup.grab().save(str(directory / f"native-more-popup-scale-{scale}.png"))

        def record(stage):
            events.append({
                "stage": stage,
                "foreground_hwnd": int(api._user32.GetForegroundWindow() or 0),
                "cached_foreground": entry.foreground_hwnd,
                "popup_visible": popup.isVisible(),
                "button_down": button.isDown(),
                "toolbar_is_ancestor": entry.toolbar.isAncestorOf(button),
                "popup_is_ancestor": popup.isAncestorOf(button),
                "sent_count": len(frame.calls),
            })

        record("before-press")
        QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
        record("after-press")
        assert popup.isVisible(), events
        assert button.isDown(), events
        dock.tick()
        record("after-dock-poll")
        assert popup.isVisible(), events
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
        record("after-release")
        assert frame.calls == [(session, "rotate_portrait")], events
        assert popup.isVisible(), events

        button = popup.findChild(QPushButton, "remoteToolbarCommand_rotate_landscape")
        assert button is not None and button.isVisible() and button.isEnabled()
        QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
        dock.tick()
        record("second-press-after-dock-poll")
        assert popup.isVisible() and button.isDown(), events
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
        record("after-second-release")
        assert frame.calls == [
            (session, "rotate_portrait"), (session, "rotate_landscape"),
        ], events
        assert popup.isVisible(), events
        if artifacts:
            popup.grab().save(str(directory / f"native-more-popup-scale-{scale}.png"))

        QTest.mouseClick(entry.toolbar._more_button, Qt.MouseButton.LeftButton)
        record("explicit-more-hide")
        assert not popup.isVisible(), events
        QTest.mouseClick(entry.toolbar._more_button, Qt.MouseButton.LeftButton)
        record("explicit-more-reopen")
        assert popup.isVisible(), events
        assert len(frame.calls) == 2, events
        assert events[0]["foreground_hwnd"] == events[-1]["foreground_hwnd"], events
    finally:
        if button is not None and isValid(button) and button.isDown():
            QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
        artifacts = os.environ.get("ADBLAB_NATIVE_DOCK_ARTIFACT_DIR")
        if artifacts:
            directory = Path(artifacts)
            directory.mkdir(parents=True, exist_ok=True)
            scale = os.environ.get("QT_SCALE_FACTOR", "default")
            (directory / f"native-more-mouse-scale-{scale}.json").write_text(
                json.dumps(events, indent=2), encoding="utf-8",
            )
            if entry is not None and isValid(entry.toolbar):
                entry.toolbar.grab().save(
                    str(directory / f"native-more-toolbar-scale-{scale}.png"),
                )
        dock.close()
        parent.close()


@pytest.mark.parametrize("focus_probe", [False, True], ids=["lifecycle", "foreground"])
def test_native_dock_tracks_external_window_without_focus_or_geometry_drift(
    qt_application, external_window, focus_probe,
):
    from gui.panels.remote_panel_dock import RemotePanelDock

    process, info, title = external_window
    api = _Win32WindowApi()
    user = api._user32
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.ShowWindow.restype = wintypes.BOOL
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW.restype = wintypes.BOOL
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.SetForegroundWindow.restype = wintypes.BOOL
    session = SimpleNamespace(
        config=SimpleNamespace(device="synthetic", no_window=False, window_title=title),
        process=process, state="ready", resource_owned=True, cancel_event=threading.Event(),
    )
    frame = _Frame(session)
    parent = QWidget()
    parent.setWindowTitle("ADBLab synthetic focus witness")
    parent.setGeometry(20, 20, 230, 80)
    parent.show()
    parent.activateWindow()
    user.SetForegroundWindow(int(parent.winId()))
    dock = RemotePanelDock(frame, parent)
    measurements = []

    def record(stage):
        native_owner = api.snapshot(info["hwnd"])
        native_tool = api.snapshot(int(entry.toolbar.winId()))
        measurements.append({
            "stage": stage,
            "owner_rect": native_owner.rect if native_owner else None,
            "owner_dpi": native_owner.dpi if native_owner else None,
            "tool_rect": native_tool.rect if native_tool else None,
            "tool_qt_geometry": entry.toolbar.geometry().getRect(),
            "tool_qt_dpr": entry.toolbar.devicePixelRatioF(),
            "tool_size_hint": entry.toolbar.sizeHint().toTuple(),
        })
        artifacts = os.environ.get("ADBLAB_NATIVE_DOCK_ARTIFACT_DIR")
        if artifacts:
            directory = Path(artifacts)
            directory.mkdir(parents=True, exist_ok=True)
            scale = os.environ.get("QT_SCALE_FACTOR", "default")
            entry.toolbar.grab().save(
                str(directory / f"native-toolbar-scale-{scale}-{stage}.png"),
            )
        return native_owner, native_tool

    def assert_position(stage):
        native_owner, native_tool = record(stage)
        assert native_owner is not None and native_tool is not None
        assert native_tool.visible and not native_tool.minimized
        assert api._get_window_long(native_tool.hwnd, -8) == native_owner.hwnd
        preferred = entry.toolbar.sizeHint()
        ratio = entry.toolbar.devicePixelRatioF()
        logical_width = max(preferred.width(), entry.toolbar.minimumWidth())
        assert abs(native_tool.rect[2] - round(logical_width * ratio)) <= 1, measurements
        assert abs(native_tool.rect[3] - round(preferred.height() * ratio)) <= 1, measurements
        assert native_tool.rect[0] >= native_owner.rect[0] + native_owner.rect[2]

    try:
        qt_application.processEvents()
        if focus_probe and user.GetForegroundWindow() != int(parent.winId()):
            pytest.skip(
                "Windows 未授权测试进程切换前台；仅跳过前台专项，生命周期用例独立执行",
            )
        foreground = user.GetForegroundWindow()
        dock.sync()
        _wait(qt_application, lambda: bool(dock.entries), "未创建外部窗口侧栏")
        entry = dock.entries["synthetic"]
        _wait(qt_application, entry.toolbar.isVisible, "侧栏未显示")
        assert user.GetForegroundWindow() == foreground
        assert_position("initial")

        assert user.SetWindowPos(info["hwnd"], 0, 240, 140, 390, 580, 0x0014)
        _wait(qt_application, lambda: api.snapshot(info["hwnd"]).rect == (240, 140, 390, 580),
              "合成外部窗口未移动")
        _wait(qt_application, lambda: api.snapshot(int(entry.toolbar.winId())).rect[0] > 630,
              "侧栏未跟随外部窗口")
        assert user.GetForegroundWindow() == foreground
        assert_position("moved-and-resized")

        parent.hide()
        qt_application.processEvents()
        dock.tick()
        assert not parent.isVisible()
        assert api.snapshot(info["hwnd"]).visible
        assert_position("main-hidden")
        parent.showMinimized()
        qt_application.processEvents()
        dock.tick()
        assert parent.isMinimized()
        assert not api.snapshot(info["hwnd"]).minimized
        assert_position("main-minimized")
        parent.showNormal()
        user.SetForegroundWindow(int(parent.winId()))
        qt_application.processEvents()
        foreground = user.GetForegroundWindow()
        dock.tick()

        entry.toolbar._more_button.click()
        qt_application.processEvents()
        assert entry.toolbar.popup_window.isVisible()
        popup_hwnd = int(entry.toolbar.popup_window.winId())
        assert api._get_window_long(popup_hwnd, -8) == int(entry.toolbar.winId())
        assert user.GetForegroundWindow() == foreground

        if focus_probe:
            entry.toolbar.dismiss_popup()
            granted = user.SetForegroundWindow(info["hwnd"])
            if not granted and user.GetForegroundWindow() != info["hwnd"]:
                pytest.skip("Windows 拒绝前台专项的合成投屏切换；未修改系统前台限制")
            _wait(qt_application, lambda: user.GetForegroundWindow() == info["hwnd"]
                  and qt_application.applicationState() == Qt.ApplicationState.ApplicationInactive,
                  "无法建立 ADBLab 已在后台的投屏前台场景")
            dock.tick()
            entry.toolbar._more_button.click()
            qt_application.processEvents()
            assert entry.toolbar.popup_window.isVisible()
            assert qt_application.applicationState() == Qt.ApplicationState.ApplicationInactive
            user.ShowWindow(info["other_hwnd"], 5)
            granted = user.SetForegroundWindow(info["other_hwnd"])
            if not granted and user.GetForegroundWindow() != info["other_hwnd"]:
                pytest.skip("Windows 拒绝前台专项的第二窗口切换；未修改系统前台限制")
            _wait(qt_application, lambda: user.GetForegroundWindow() == info["other_hwnd"],
                  "未切换到另一合成外部窗口")
            _wait(qt_application, lambda: not entry.toolbar.popup_window.isVisible(),
                  "ADBLab 已在后台时，切换外部前台窗口仍必须收起更多面板")
            measurements.append({
                "stage": "foreign-focus-switch",
                "application_inactive": (
                    qt_application.applicationState() == Qt.ApplicationState.ApplicationInactive
                ),
                "popup_visible": entry.toolbar.popup_window.isVisible(),
            })
            user.PostMessageW(info["other_hwnd"], 0x0010, 0, 0)
            dock.tick()
            entry.toolbar._more_button.click()
            assert entry.toolbar.popup_window.isVisible()

        user.ShowWindow(info["hwnd"], 6)
        _wait(qt_application, lambda: not entry.toolbar.isVisible(), "最小化未隐藏侧栏")
        assert not entry.toolbar.popup_window.isVisible()
        user.ShowWindow(info["hwnd"], 9)
        _wait(qt_application, entry.toolbar.isVisible, "恢复后侧栏未恢复")
        assert_position("restored")

        assert user.SetWindowPos(info["hwnd"], -1, 0, 0, 0, 0, 0x0013)
        _wait(qt_application, lambda: api.snapshot(int(entry.toolbar.winId())).topmost,
              "侧栏未跟随 owner 置顶")
        assert user.SetWindowPos(info["hwnd"], -2, 0, 0, 0, 0, 0x0013)
        _wait(qt_application, lambda: not api.snapshot(int(entry.toolbar.winId())).topmost,
              "侧栏未跟随 owner 取消置顶")

        entry.toolbar.key_requested.emit("HOME")
        assert frame.calls == [(session, "HOME")]
        user.PostMessageW(info["hwnd"], 0x0010, 0, 0)
        _wait(qt_application, lambda: not dock.entries, "外部窗口关闭后侧栏未释放")
        assert frame.invalidated == [session]
        assert not dock.timer.isActive()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not user.IsWindow(popup_hwnd)
    finally:
        artifacts = os.environ.get("ADBLAB_NATIVE_DOCK_ARTIFACT_DIR")
        if artifacts:
            directory = Path(artifacts)
            directory.mkdir(parents=True, exist_ok=True)
            scale = os.environ.get("QT_SCALE_FACTOR", "default")
            suffix = "-foreground" if focus_probe else ""
            (directory / f"native-dock-scale-{scale}{suffix}.json").write_text(
                json.dumps(measurements, indent=2), encoding="utf-8",
            )
            if "entry" in locals() and isValid(entry.toolbar) and entry.toolbar.isVisible():
                entry.toolbar.grab().save(str(directory / f"native-toolbar-scale-{scale}.png"))
        dock.close()
        parent.close()
