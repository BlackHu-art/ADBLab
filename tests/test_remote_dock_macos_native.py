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
from PySide6.QtWidgets import QWidget

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
