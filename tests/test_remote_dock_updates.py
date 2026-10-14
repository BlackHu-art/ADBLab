"""验证窗口事件合并、跨屏比例收敛和关闭后的通知失效。"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QWidget

from tests.test_remote_dock import Frame, Tracker, session

pytestmark = pytest.mark.ui


class EventTracker(Tracker):
    def __init__(self, pid, title):
        super().__init__(pid, title)
        self.callback = None
        self.reads = 0

    @property
    def event_tracking(self):
        return self.callback is not None

    def set_change_callback(self, callback):
        self.callback = callback

    def snapshot(self):
        self.reads += 1
        return super().snapshot()

    def close(self):
        self.callback = None


def _wait_events(application, condition):
    loop = QEventLoop()
    observer = QTimer()
    observer.setInterval(1)
    observer.timeout.connect(lambda: loop.quit() if condition() else None)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    observer.start()
    deadline.start(500)
    loop.exec()
    observer.stop()
    deadline.stop()
    application.processEvents()
    assert condition()


def test_window_event_burst_updates_latest_geometry_without_polling_other_sessions(qt_application):
    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    frame._device_sessions = {"a": session("a"), "b": session("b", 200)}
    dock = RemotePanelDock(frame, owner, tracker_factory=EventTracker)
    try:
        dock.sync()
        dock.timer.stop()
        first, second = dock.entries["a"], dock.entries["b"]
        before = (first.tracker.reads, second.tracker.reads)
        placements = len(first.tracker.positions)
        assert first.tracker.callback is not None
        for x in range(200, 500, 10):
            first.tracker.current.rect = (x, 180, 420, 620)
            first.tracker.callback()
        # 原生回调只排队；重入的 WinEvent 不能同步访问 Qt 或读取窗口几何。
        assert first.tracker.reads == before[0]
        QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
        assert first.tracker.reads == before[0]
        _wait_events(qt_application, lambda: len(first.tracker.positions) > placements)
        assert first.tracker.positions[-1][:2] == (918, 192)
        assert first.tracker.reads == before[0] + 1
        assert second.tracker.reads == before[1]
        assert not dock.timer.isActive()
    finally:
        dock.close()
        owner.close()


def test_event_sampling_follows_current_screen_and_stops_when_idle(qt_application, monkeypatch):
    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    frame._device_sessions = {"a": session("a")}
    dock = RemotePanelDock(frame, owner, tracker_factory=EventTracker)
    try:
        dock.sync()
        dock.timer.stop()
        entry = dock.entries["a"]
        rate = [165.0]
        monkeypatch.setattr(
            entry.toolbar, "screen", lambda: SimpleNamespace(refreshRate=lambda: rate[0]),
        )
        for refresh, interval in ((165.0, 6), (60.0, 17), (float("nan"), 17)):
            rate[0] = refresh
            entry.tracker.current.rect = (200, 180, 420, 620)
            assert entry.tracker.callback is not None
            entry.tracker.callback()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
            assert dock._motion_timer.interval() == interval
            _wait_events(qt_application, lambda: not dock._motion_timer.isActive())
        assert not dock._pending
    finally:
        dock.close()
        owner.close()


def test_native_move_dpi_change_converges_without_another_owner_event(qt_application, monkeypatch):
    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    frame._device_sessions = {"a": session("a")}
    dock = RemotePanelDock(frame, owner, tracker_factory=EventTracker)
    try:
        dock.sync()
        dock.timer.stop()
        entry = dock.entries["a"]
        ratio = [1.0]
        monkeypatch.setattr(entry.toolbar, "devicePixelRatioF", lambda: ratio[0])
        original_position = entry.tracker.position_tool

        def cross_screen(*args):
            ratio[0] = 1.5
            return original_position(*args)

        monkeypatch.setattr(entry.tracker, "position_tool", cross_screen)
        entry.tracker.current.rect = (-1800, -500, 420, 620)
        entry.tracker.current.work_area = (-2160, -746, 2160, 3840)
        entry.tracker.current.dpi = 144
        entry.tracker.callback()
        _wait_events(qt_application, lambda: entry.tracker.positions[-1][2] == 84)
        assert entry.tracker.positions[-1][0] == -1368
        assert entry.toolbar.isVisible()
    finally:
        dock.close()
        owner.close()


def test_pending_and_late_window_events_cannot_reopen_a_closed_dock(qt_application):
    from gui.panels.remote_panel_dock import RemotePanelDock

    owner, frame = QWidget(), Frame()
    frame._device_sessions = {"a": session("a")}
    dock = RemotePanelDock(frame, owner, tracker_factory=EventTracker)
    try:
        dock.sync()
        entry = dock.entries["a"]
        notify = entry.tracker.callback
        assert notify is not None
        notify()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
        dock.close()
        notify()
        qt_application.processEvents()
        assert not dock.entries
        assert not entry.tracker.event_tracking
        assert not any(timer.isActive() for timer in dock.findChildren(QTimer))
        assert not frame.calls
        assert frame.invalidated == [entry.session]
    finally:
        dock.close()
        owner.close()
