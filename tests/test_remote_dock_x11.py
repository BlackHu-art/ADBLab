"""在真实 X11/XWayland 上移动独立合成窗口，不连接设备或读取用户设置。"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QProcess, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QToolButton, QWidget

from tests import test_global_device_context
from tests.test_remote_dock import Frame, session

main_frame = test_global_device_context.frame

pytestmark = [
    pytest.mark.ui,
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform != "linux" or os.environ.get("QT_QPA_PLATFORM") != "xcb",
        reason="原生跟随验证需显式 QT_QPA_PLATFORM=xcb；默认离屏测试不显示窗口",
    ),
]

_MIRROR = r'''
import json, os, sys
from PySide6.QtCore import QSocketNotifier, QTimer
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
window = QWidget()
window.setWindowTitle(sys.argv[1])
window.resize(320, 480)
window.move(100, 100)
window.show()
app.processEvents()
print(json.dumps({'pid': os.getpid(), 'hwnd': int(window.winId())}), flush=True)
notifier = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read)
def command(*_):
    line = sys.stdin.readline()
    if not line:
        app.quit()
        return
    data = json.loads(line)
    if data[0] == 'move': window.move(*data[1:])
    elif data[0] == 'resize': window.resize(*data[1:])
    elif data[0] == 'minimize': window.showMinimized()
    elif data[0] == 'restore':
        window.showNormal()
        window.raise_()
        window.activateWindow()
    elif data[0] == 'quit': app.quit()
notifier.activated.connect(command)
QTimer.singleShot(30000, app.quit)
app.exec()
'''


def _wait(app, predicate, *, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    assert predicate(), "窗口状态未在限定时间内同步"


@pytest.fixture
def mirror_process(qt_application, monkeypatch):
    # 测试平台由调用命令显式指定，不继承用户对 scrcpy 的后端偏好。
    monkeypatch.delenv("SDL_VIDEO_DRIVER", raising=False)
    monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    process = QProcess()
    title = "ADBLab X11 validation " + uuid.uuid4().hex
    process.start(sys.executable, ["-c", _MIRROR, title])
    try:
        assert process.waitForStarted(3000)
        _wait(qt_application, process.canReadLine)
        identity = json.loads(bytes(process.readLine()))
        yield process, title, identity
    finally:
        if process.state() != QProcess.ProcessState.NotRunning:
            process.write(b'["quit"]\n')
            if not process.waitForFinished(3000):
                process.kill()
                assert process.waitForFinished(3000)
        process.close()


def _send(process, *command):
    process.write((json.dumps(command) + "\n").encode())
    assert process.waitForBytesWritten(1000)


def _dock_for_process(process, title, identity):
    from gui.panels.remote_panel_dock import RemotePanelDock

    parent, frame = QWidget(), Frame()
    parent.show()
    target = session("a", identity["pid"])
    target.config.window_title = title
    target.process.poll = lambda: (
        None if process.state() != QProcess.ProcessState.NotRunning else process.exitCode()
    )
    frame._device_sessions = {"a": target}
    dock = RemotePanelDock(frame, parent)
    dock.sync()
    return parent, frame, target, dock


def test_x11_sidebar_preserves_main_navigation_window_hierarchy(
    qt_application, mirror_process, main_frame,
):
    """可见远程页创建侧栏不能将主导航原生化，否则逻辑已切页而实屏仍冻结。"""
    from qfluentwidgets import NavigationDisplayMode

    from gui.panels.remote_panel_scrcpy import RemoteDeviceSession
    from services.remote import ScrcpyConfig

    process, title, identity = mirror_process
    main_frame.show()
    main_frame.resize(900, 750)
    main_frame._on_devices_updated(["a"])
    main_frame._open_workspace_feature("devices", "remote")
    navigation = main_frame.navigationInterface
    panel = navigation.panel
    _wait(qt_application, lambda: panel.currentItem().isSelected)
    surfaces = (navigation, main_frame._content_surface)
    assert all(not widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
               for widget in surfaces)
    remote = main_frame.left_panel.remote_panel
    config = ScrcpyConfig("", "", "a", "720", "24", "2M", "auto", "0", "",
                          window_title=title)
    target = RemoteDeviceSession(
        config, state="ready", resource_owned=True,
        process=SimpleNamespace(pid=identity["pid"], poll=lambda: (
            None if process.state() != QProcess.ProcessState.NotRunning else process.exitCode()
        )),
    )
    remote._device_sessions = {"a": target}
    dock = remote._dock_controller
    try:
        dock.sync()
        entry = dock.entries["a"]
        assert entry.tracker is not None
        _wait(qt_application, entry.toolbar.isVisible)
        # 只检查逻辑选中项或 QWidget.grab 会漏掉原生窗口合成的显示停滞。
        assert all(not widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
                   for widget in surfaces), "镜像侧栏不能改变主导航和内容层的原生窗口归属"
        QTest.mouseClick(navigation.widget("appsPage").itemWidget, Qt.MouseButton.LeftButton)
        _wait(qt_application, lambda: panel.currentItem().isSelected)
        assert main_frame.stackedWidget.currentWidget() is main_frame._workspace_pages["apps"]
        assert panel.currentItem().property("routeKey") == "appsPage"
        QTest.mouseClick(panel.menuButton, Qt.MouseButton.LeftButton)
        _wait(qt_application, lambda: panel.displayMode == NavigationDisplayMode.MENU)
        assert entry.toolbar.isVisible()
    finally:
        dock.close()
        remote._device_sessions.clear()


def test_x11_sidebar_follows_external_move_resize_and_keeps_session_target(
    qt_application, mirror_process,
):
    process, title, identity = mirror_process
    parent, frame, target, dock = _dock_for_process(process, title, identity)
    try:
        entry = dock.entries["a"]
        assert entry.tracker is not None, "xcb 镜像必须接入原生跟随，不能退回独立浮窗"
        _wait(qt_application, lambda: entry.toolbar.isVisible())
        api = entry.tracker._api
        scale = entry.toolbar.devicePixelRatioF()

        def attached():
            owner, tool = api.snapshot(identity["hwnd"]), api.snapshot(int(entry.toolbar.winId()))
            return owner is not None and tool is not None and (
                tool.rect[0] == owner.rect[0] + owner.rect[2] + round(8 * scale)
                and tool.rect[1] == owner.rect[1] + round(12 * scale)
            )

        _wait(qt_application, attached)
        original = api.snapshot(int(entry.toolbar.winId())).rect
        _send(process, "move", 220, 160)
        _wait(qt_application, lambda: attached() and (
            api.snapshot(int(entry.toolbar.winId())).rect[0] == original[0] + round(120 * scale)
        ))
        _send(process, "resize", 420, 520)
        _wait(qt_application, lambda: attached() and (
            api.snapshot(int(entry.toolbar.winId())).rect[0] == original[0] + round(220 * scale)
        ))
        frame.selected_devices = ["b"]
        button = entry.toolbar.findChild(QAbstractButton, "remoteToolbarCommand_HOME")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert frame.calls == [(target, "HOME")]
        more = entry.toolbar.findChild(QToolButton, "remoteToolbarMore")
        QTest.mouseClick(more, Qt.MouseButton.LeftButton)
        _wait(qt_application, entry.toolbar.popup_window.isVisible)
        assert entry.toolbar.popup_window.window() is not entry.toolbar
    finally:
        dock.close()
        parent.close()


def test_x11_sidebar_hides_on_minimize_returns_on_restore_and_retires_on_exit(
    qt_application, mirror_process,
):
    process, title, identity = mirror_process
    parent, frame, target, dock = _dock_for_process(process, title, identity)
    try:
        entry = dock.entries["a"]
        assert entry.tracker is not None
        _wait(qt_application, entry.toolbar.isVisible)
        _send(process, "minimize")
        _wait(qt_application, lambda: not entry.toolbar.isVisible())
        entry.toolbar.key_requested.emit("HOME")
        assert frame.calls == []
        _send(process, "restore")
        _wait(qt_application, lambda: (
            (snapshot := entry.tracker.snapshot()) is not None and snapshot.visible
        ))
        _wait(qt_application, entry.toolbar.isVisible)
        _send(process, "quit")
        _wait(qt_application, lambda: not dock.entries)
        assert not dock.timer.isActive()
        assert entry.tracker.lost and not entry.tracker.supported
        assert frame.invalidated == [target]
    finally:
        dock.close()
        parent.close()
