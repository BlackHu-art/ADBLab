"""显式 cocoa 下用独立合成窗口验证 macOS 跟随，不连接设备或读取用户数据。"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu, QPushButton, QToolButton, QWidget

from tests.ui_geometry_helpers import wait_until

pytestmark = [
    pytest.mark.ui,
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform != "darwin" or os.environ.get("QT_QPA_PLATFORM") != "cocoa",
        reason="原生 macOS 集成需显式 QT_QPA_PLATFORM=cocoa；其它平台运行接口替身测试",
    ),
]

_MIRROR = """
import json, queue, sys, threading, time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
window = QWidget()
window.setWindowTitle(sys.argv[1])
window.resize(340, 500)
window.move(120, 100)
window.show()
commands = queue.Queue()
def read():
    for line in sys.stdin:
        commands.put(json.loads(line))
threading.Thread(target=read, daemon=True).start()
def tick():
    while not commands.empty():
        command = commands.get_nowait()
        kind = command[0]
        if kind == 'move': window.move(*command[1:])
        elif kind == 'resize': window.resize(*command[1:])
        elif kind == 'minimize': window.showMinimized()
        elif kind == 'restore':
            import AppKit
            AppKit.NSApplication.sharedApplication().unhideWithoutActivation()
            window.showNormal()
        elif kind == 'activate':
            import AppKit
            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            window.raise_()
            window.activateWindow()
        elif kind == 'hide':
            import AppKit
            AppKit.NSApplication.sharedApplication().hide_(None)
        elif kind == 'close': window.close()
        elif kind == 'quit': app.quit()
        elif kind == 'stall':
            print(json.dumps({'done':kind}), flush=True)
            time.sleep(1)
            continue
        app.processEvents()
        print(json.dumps({'done':kind}), flush=True)
timer = QTimer()
timer.timeout.connect(tick)
timer.start(10)
app.processEvents()
import AppKit
number = next(w.windowNumber() for w in AppKit.NSApplication.sharedApplication().windows()
              if w.title() == sys.argv[1])
print(json.dumps({'ready':True,'number':number}), flush=True)
QTimer.singleShot(60000, app.quit)
app.exec()
"""


@contextmanager
def _mirror_process(qt_application):
    import ApplicationServices

    if not ApplicationServices.AXIsProcessTrusted():
        pytest.skip("真实窗口跟随需已有辅助功能授权；未授权降级由接口测试覆盖")
    title = "ADBLab-macos-dock-" + uuid.uuid4().hex
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", _MIRROR, title],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, env=dict(os.environ, QT_QPA_PLATFORM="cocoa"),
    )
    messages = queue.Queue()

    def read():
        for line in process.stdout:
            messages.put(json.loads(line))

    reader = threading.Thread(target=read, name="macos-test-mirror-output")
    reader.start()

    def send(*command):
        process.stdin.write(json.dumps(command) + "\n")
        process.stdin.flush()
        wait_until(qt_application, lambda: not messages.empty())
        assert messages.get_nowait() == {"done": command[0]}

    try:
        wait_until(qt_application, lambda: not messages.empty())
        ready = messages.get_nowait()
        assert ready["ready"]
        yield SimpleNamespace(process=process, title=title, send=send, number=ready["number"])
    finally:
        if process.poll() is None:
            process.stdin.write('["quit"]\n')
            process.stdin.flush()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        reader.join(timeout=3)
        process.stdin.close()
        process.stdout.close()
        assert not reader.is_alive()


@pytest.fixture
def mirror(qt_application):
    with _mirror_process(qt_application) as current:
        yield current


@pytest.fixture
def macos_dock(qt_application, mirror):
    from gui.panels.remote_panel_dock import RemotePanelDock

    current = SimpleNamespace(
        config=SimpleNamespace(device="synthetic", no_window=False, window_title=mirror.title),
        process=mirror.process, state="ready", resource_owned=True, cancel_event=threading.Event(),
    )
    invalidated = []
    frame = SimpleNamespace(
        _device_sessions={"synthetic": current}, _connected_remote_devices={"synthetic"},
        _closing=False, _remote_input_closing=False,
        _mirror_device_name=lambda _: "合成镜像",
        _input_controller=SimpleNamespace(_invalidate_session_input=invalidated.append),
    )
    owner = QWidget()
    dock = RemotePanelDock(frame, owner)
    try:
        dock.sync()
        entry = dock.entries["synthetic"]
        assert entry.tracker is not None and entry.tracker.supported
        wait_until(qt_application, entry.toolbar.isVisible)
        yield dock, entry, invalidated
    finally:
        dock.close()
        owner.close()


def _snapshot_matches(tracker, predicate):
    snapshot = tracker.snapshot()
    return snapshot is not None and predicate(snapshot)


def test_macos_native_motion_places_toolbar_flush_without_full_state_polling(
    qt_application, mirror, macos_dock, monkeypatch,
):
    dock, entry, _ = macos_dock
    assert entry.tracker.event_tracking
    changes = []
    notify = dock._notify_change

    def changed(current):
        changes.append(True)
        notify(current)

    monkeypatch.setattr(dock, "_notify_change", changed)
    # 禁用完整状态轮询，确保 AX 通知与轻量几何采样能独立驱动 GUI 更新。
    dock.timer.stop()
    mirror.send("activate")
    for x, y, width in ((220, 160, 340), (270, 180, 380), (310, 200, 420)):
        mirror.send("move", x, y)
        mirror.send("resize", width, 400)

        def flush():
            snapshot = entry.tracker.snapshot()
            if snapshot is None:
                return False
            scale = snapshot.dpi / 96
            geometry = entry.toolbar.frameGeometry()
            return (
                round(geometry.x() * scale) == snapshot.rect[0] + snapshot.rect[2]
                and round(geometry.y() * scale) == snapshot.rect[1]
            )

        wait_until(qt_application, flush)
    wait_until(qt_application, lambda: bool(changes))


def test_macos_native_toolbar_follows_move_resize_minimize_and_restore(
    qt_application, mirror, macos_dock,
):
    import AppKit

    dock, entry, _ = macos_dock
    tracker, toolbar = entry.tracker, entry.toolbar
    first = tracker.snapshot()
    first_position = toolbar.frameGeometry().topLeft()
    # 明确模拟用户正在操作外部镜像，排除 Qt 首个工具窗初显时尚未完成的激活请求。
    mirror.send("activate")
    wait_until(qt_application, lambda: _snapshot_matches(tracker, lambda s: s.foreground))
    front_pid = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()
    mirror.send("move", 290, 180)

    def moved():
        dock.tick()
        snapshot = tracker.snapshot()
        return snapshot is not None and snapshot.rect[:2] != first.rect[:2] and (
            toolbar.frameGeometry().topLeft() != first_position
        )

    wait_until(qt_application, moved)
    moved_snapshot = tracker.snapshot()
    before = toolbar.frameGeometry().topLeft()
    mirror.send("resize", 470, 380)

    def resized():
        dock.tick()
        snapshot = tracker.snapshot()
        return snapshot is not None and snapshot.rect[2:] != moved_snapshot.rect[2:] and (
            toolbar.frameGeometry().topLeft() != before
        )

    wait_until(qt_application, resized)
    front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    assert front.processIdentifier() == front_pid
    toolbar._more_button.click()
    wait_until(qt_application, toolbar.popup_window.isVisible)
    mirror.send("minimize")
    wait_until(qt_application, lambda: _snapshot_matches(tracker, lambda s: s.minimized))
    dock.tick()
    assert not toolbar.isVisible()
    assert not toolbar.popup_window.isVisible()
    mirror.send("restore")
    wait_until(qt_application, lambda: _snapshot_matches(tracker, lambda s: not s.minimized))
    wait_until(qt_application, lambda: (dock.tick(), toolbar.isVisible())[1])
    assert tracker.snapshot().hwnd == first.hwnd


def test_macos_native_closing_mirror_retires_side_toolbar_without_process_exit(
    qt_application, mirror, macos_dock,
):
    dock, entry, invalidated = macos_dock
    mirror.send("close")
    wait_until(qt_application, lambda: (dock.tick(), not dock.entries)[1])
    assert mirror.process.poll() is None
    assert invalidated == [entry.session]
    assert not dock.timer.isActive()
    assert not entry.toolbar.isVisible()


def test_macos_native_hidden_application_hides_toolbar_and_restores_same_binding(
    qt_application, mirror, macos_dock,
):
    dock, entry, _ = macos_dock
    first = entry.tracker.snapshot()
    mirror.send("hide")
    wait_until(qt_application, lambda: (dock.tick(), not entry.toolbar.isVisible())[1])
    assert not entry.tracker.lost
    mirror.send("restore")
    wait_until(qt_application, lambda: (dock.tick(), entry.toolbar.isVisible())[1])
    assert entry.tracker.snapshot().hwnd == first.hwnd


def test_macos_native_unresponsive_mirror_does_not_block_gui_or_lose_binding(
    qt_application, mirror, macos_dock,
):
    _, entry, _ = macos_dock
    first = entry.tracker.snapshot()
    mirror.send("stall")
    started = time.monotonic()
    snapshot = entry.tracker.snapshot()
    elapsed = time.monotonic() - started
    assert elapsed < 0.35
    assert snapshot is None and not entry.tracker.lost
    wait_until(qt_application, lambda: entry.tracker.snapshot() is not None)
    assert entry.tracker.snapshot().hwnd == first.hwnd


def test_macos_native_reactivating_stationary_mirror_restores_toolbar_stacking(
    qt_application, mirror, macos_dock,
):
    import AppKit
    import objc
    import Quartz

    dock, entry, _ = macos_dock
    toolbar_number = next(
        window.windowNumber() for window in AppKit.NSApplication.sharedApplication().windows()
        if window.contentView() is not None
        and objc.pyobjc_id(window.contentView()) == int(entry.toolbar.winId())
    )
    with _mirror_process(qt_application) as cover:
        cover.send("move", 80, 80)
        cover.send("resize", 800, 700)
        cover.send("activate")
        wait_until(qt_application, lambda: _snapshot_matches(
            entry.tracker, lambda s: not s.foreground,
        ))
        dock.tick()
        original_rect = entry.tracker.snapshot().rect
        mirror.send("activate")
        wait_until(qt_application, lambda: _snapshot_matches(entry.tracker, lambda s: s.foreground))

        def toolbar_above_mirror():
            dock.tick()
            numbers = [int(info["kCGWindowNumber"]) for info in (
                Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, 0) or ()
            )]
            return toolbar_number in numbers and mirror.number in numbers and (
                numbers.index(toolbar_number) < numbers.index(mirror.number)
            )

        wait_until(qt_application, toolbar_above_mirror)
        assert entry.tracker.snapshot().rect == original_rect


@pytest.mark.parametrize("target", ["HOME", "MORE", "COLLAPSE", "MENU", "CLOSE", "SCROLL"])
def test_macos_attached_mouse_actions_keep_owner_focus_without_activation_warning(
    qt_application, target,
):
    """主窗口在前台时，操作不接收焦点的侧栏不能触发 Qt 的窗口激活请求。"""
    from gui.widgets.remote_toolbar import RemoteToolbar

    owner = QWidget()
    owner.resize(200, 100)
    reference = QPushButton("主窗口焦点", owner)
    toolbar = RemoteToolbar(owner)
    messages, keys = [], []
    previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    try:
        owner.show()
        toolbar.set_available(True)
        toolbar.show()
        if target in {"MENU", "CLOSE", "SCROLL"}:
            toolbar._more_button.click()
            qt_application.processEvents()
            assert toolbar.popup_window.isVisible()
        owner.activateWindow()
        assert QTest.qWaitForWindowActive(owner)
        reference.setFocus()
        assert reference.hasFocus()
        toolbar.key_requested.connect(keys.append)
        button = {
            "HOME": toolbar.findChild(QToolButton, "remoteToolbarCommand_HOME"),
            "MORE": toolbar._more_button,
            "COLLAPSE": toolbar._collapse_button,
            "MENU": toolbar.findChild(QPushButton, "remoteToolbarCommand_MENU"),
            "CLOSE": toolbar.popup_window.findChild(QToolButton),
            "SCROLL": toolbar._popup_scroll.viewport(),
        }[target]
        assert button is not None and button.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(1, 1)
                         if target == "SCROLL" else button.rect().center())
        qt_application.processEvents()
        assert keys == ([target] if target in {"HOME", "MENU"} else [])
        assert reference.hasFocus(), "鼠标操作侧栏不能把主窗口输入焦点转移到工具窗"
        assert toolbar.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
        toolbar.set_available(False)
        toolbar.dispose()
        assert not [message for message in messages if "WindowDoesNotAcceptFocus" in message]
    finally:
        toolbar.dispose()
        owner.close()
        qInstallMessageHandler(previous)


@pytest.mark.parametrize("dismiss", ["escape", "outside-click"])
def test_macos_dropdown_close_and_application_return_do_not_activate_attached_toolbar(
    qt_application, mirror, macos_dock, dismiss,
):
    """菜单关闭和应用切回不能恢复到不接收焦点的侧栏，也不能重复发送设备操作。"""
    import AppKit

    dock, entry, _ = macos_dock
    owner, toolbar = dock._owner, entry.toolbar
    reference = QPushButton("主窗口焦点", owner)
    menu = QMenu(owner)
    menu.addAction("合成菜单项")
    keys, messages = [], []
    dock._frame._input_controller._send_session_keyevent = lambda _session, key: keys.append(key)
    previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    try:
        owner.resize(200, 100)
        owner.show()
        owner.activateWindow()
        assert QTest.qWaitForWindowActive(owner)
        reference.setFocus()
        assert reference.hasFocus()
        home = toolbar.findChild(QToolButton, "remoteToolbarCommand_HOME")
        QTest.mouseClick(home, Qt.MouseButton.LeftButton)
        assert keys == ["HOME"]
        menu.popup(owner.mapToGlobal(owner.rect().center()))
        wait_until(qt_application, menu.isVisible)
        if dismiss == "escape":
            QTest.keyClick(menu, Qt.Key.Key_Escape)
        else:
            # 走 QWindow 的真实菜单事件回放入口，而非直接调用按钮 clicked。
            QTest.mouseClick(toolbar.windowHandle(), Qt.MouseButton.LeftButton,
                             pos=home.mapTo(toolbar, home.rect().center()))
        wait_until(qt_application, lambda: not menu.isVisible())
        assert keys in (["HOME"], ["HOME", "HOME"])
        before_switch = list(keys)
        mirror.send("activate")
        wait_until(qt_application, lambda: _snapshot_matches(entry.tracker, lambda s: s.foreground))
        # 模拟用户切回应用；QWidget.activateWindow 本身不负责激活后台 macOS 应用。
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        owner.raise_()
        owner.activateWindow()
        assert QTest.qWaitForWindowActive(owner)
        qt_application.processEvents()
        assert reference.hasFocus()
        assert keys == before_switch, "应用切换不能重放设备操作"
        dock.close()
        assert not [message for message in messages if "WindowDoesNotAcceptFocus" in message]
    finally:
        menu.close()
        qInstallMessageHandler(previous)
