"""把逐台遥控侧栏绑定到外部投屏窗口，并管理独立遥控器的视图寿命。"""

import sys
from dataclasses import dataclass
from math import isfinite
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout, QWidget

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role
from gui.widgets.remote_toolbar import RemoteToolbar
from services.remote.window_tracking import create_window_tracker


def dock_geometry(
    window: tuple[int, int, int, int], work: tuple[int, int, int, int],
    size: tuple[int, int], *, gap: int = 8, inset: int = 12,
) -> tuple[int, int, int, int]:
    """物理坐标内优先右侧、再左侧；全屏时退到工作区内侧并约束负坐标屏幕。"""
    x, y, width, _height = window
    left, top, available_width, available_height = work
    tool_width, tool_height = size
    right, bottom = left + available_width, top + available_height
    if x + width + gap + tool_width <= right:
        target_x = x + width + gap
    elif x - gap - tool_width >= left:
        target_x = x - gap - tool_width
    else:
        target_x = right - tool_width - gap
    target_x = max(left, min(target_x, right - tool_width))
    target_y = max(top, min(y + inset, bottom - tool_height))
    return target_x, target_y, tool_width, tool_height


@dataclass
class _DockEntry:
    """窗口和输入共享原会话对象；tracker 为 None 时使用便携浮窗，不查询外部窗口。"""

    session: Any
    tracker: Any
    toolbar: RemoteToolbar
    placement: object = None
    foreground_hwnd: int | None = None
    screen_observed: bool = False


class RemotePanelDock(QObject):
    """GUI 线程拥有会话工具栏；支持时跟随原生窗口，否则显示可拖动的便携浮窗。"""

    _window_changed = Signal(object)

    def __init__(self, frame, parent: QWidget, *, tracker_factory=None):
        super().__init__(parent)
        self._frame = frame
        self._owner = parent
        self._tracker_factory = tracker_factory or (
            lambda pid, title: create_window_tracker(
                pid, title, platform_name=QGuiApplication.platformName(),
            )
        )
        self.entries: dict[str, _DockEntry] = {}
        self._retired: dict[str, object] = {}
        self._closed = False
        self._updating = False
        self._pending: dict[str, _DockEntry] = {}
        self._motion_timer = QTimer(self)
        self._motion_timer.setSingleShot(True)
        self._motion_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._motion_timer.timeout.connect(self._flush_updates)
        # WinEvent 允许重入；通知必须先离开原生回调，再由 GUI 合并处理。
        self._window_changed.connect(self._queue_update, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.tick)
        parent.destroyed.connect(self.close)

    def _active(self, session) -> bool:
        return (
            not self._closed
            and not getattr(self._frame, "_closing", False)
            and not getattr(self._frame, "_remote_input_closing", False)
            and self._frame._device_sessions.get(session.config.device) is session
            and session.resource_owned
            and session.process is not None and session.process.poll() is None
            and session.state in {"connecting", "ready"}
            and not session.cancel_event.is_set()
        )

    def sync(self) -> None:
        """会话变更立即撤销旧侧栏；设备取消选择不改变已运行窗口的归属。"""
        sessions = getattr(self._frame, "_device_sessions", {})
        for device, entry in tuple(self.entries.items()):
            if not self._active(entry.session):
                self._remove(device)
        if self._closed:
            return
        for device, session in sessions.items():
            if (device in self.entries or self._retired.get(device) is session
                    or not self._active(session) or session.config.no_window):
                continue
            pid = getattr(session.process, "pid", None)
            if not isinstance(pid, int) or pid <= 0:
                continue
            tracker = self._tracker_factory(pid, session.config.window_title)
            native_tracker = tracker if tracker.supported else None
            independent = (
                sys.platform == "linux" and QGuiApplication.platformName() == "xcb"
                and native_tracker is not None
            )
            # X11 下有父控件的 winId() 会连带将主导航原生化，造成实际画面停止刷新。
            # 独立工具窗由 entries 持有并经 _remove 释放，原生瞬态归属仍绑定镜像窗口。
            toolbar = RemoteToolbar(
                None if independent else self._owner, portable=native_tracker is None,
            )
            toolbar.set_target_label(self._frame._mirror_device_name(device))
            entry = _DockEntry(session, native_tracker, toolbar)
            self.entries[device] = entry
            toolbar.key_requested.connect(
                lambda code, current=entry: self._dispatch(current, code, action=False),
            )
            toolbar.action_requested.connect(
                lambda code, current=entry: self._dispatch(current, code, action=True),
            )
            toolbar.layout_changed.connect(lambda current=entry: self._queue_update(current))
            subscribe = getattr(native_tracker, "set_change_callback", None)
            if callable(subscribe):
                subscribe(lambda current=entry: self._notify_change(current))
            if native_tracker is None:
                # Wayland 由合成器安排初始位置；操作仅绑定此会话，不能退回主窗口广播。
                toolbar.show()
        self.tick()
        if self.entries:
            self.timer.start()
        else:
            self.timer.stop()

    def _dispatch(self, entry: _DockEntry, code: str, *, action: bool) -> None:
        device = entry.session.config.device
        if self.entries.get(device) is not entry or not self._active(entry.session):
            return
        connected = getattr(self._frame, "_connected_remote_devices", None)
        if connected is not None and device not in connected:
            return
        if entry.tracker is not None:
            # 每次点击重新确认句柄，避免关闭窗口到下一轮轮询之间仍接纳输入。
            snapshot = entry.tracker.snapshot()
            if snapshot is None or snapshot.minimized or not snapshot.visible:
                return
        controller = self._frame._input_controller
        callback = controller._send_session_action if action else controller._send_session_keyevent
        callback(entry.session, code)

    def _notify_change(self, entry: _DockEntry) -> None:
        """原生回调只传递会话身份；关闭后的晚到通知不再访问 Qt 对象。"""
        if not self._closed:
            self._window_changed.emit(entry)

    def _queue_update(self, entry: _DockEntry) -> None:
        """密集通知只保留每台会话一次更新，不因后续事件延长已安排的截止时间。"""
        if self._closed or self.entries.get(entry.session.config.device) is not entry:
            return
        self._pending[entry.session.config.device] = entry
        screen = entry.toolbar.screen()
        rate = screen.refreshRate() if screen is not None else 60.0
        if not isfinite(rate) or rate < 24:
            rate = 60.0
        interval = max(1, round(1000 / min(360.0, rate)))
        if not self._motion_timer.isActive() or self._motion_timer.remainingTime() > interval:
            self._motion_timer.start(interval)

    def _flush_updates(self) -> None:
        entries = tuple(self._pending.values())
        self._pending.clear()
        self._update_entries(entries)

    def tick(self) -> None:
        """低频检查生命周期及漏报事件；无原生订阅的平台保留原轮询兼容路径。"""
        self._update_entries(tuple(self.entries.values()))

    def _update_entries(self, entries: tuple[_DockEntry, ...]) -> None:
        if self._closed:
            return
        if self._updating:
            for entry in entries:
                self._queue_update(entry)
            return
        self._updating = True
        try:
            self._place_entries(entries)
        finally:
            self._updating = False
        if not self.entries:
            self.timer.stop()
            self._motion_timer.stop()
        else:
            interval = 60 if any(
                entry.tracker is not None and not getattr(entry.tracker, "event_tracking", False)
                for entry in self.entries.values()
            ) else 250
            if self.timer.interval() != interval:
                self.timer.setInterval(interval)

    def _place_entries(self, entries: tuple[_DockEntry, ...]) -> None:
        """仅读取发生变化的会话；几何或置顶状态未变时不重复原生定位。"""
        for entry in entries:
            device = entry.session.config.device
            if self.entries.get(device) is not entry:
                continue
            if not self._active(entry.session):
                self._remove(device)
                continue
            toolbar = entry.toolbar
            connected = getattr(self._frame, "_connected_remote_devices", None)
            toolbar.set_available(connected is None or device in connected)
            if entry.tracker is None:
                # 便携浮窗只跟随进程和会话寿命；不伪造外部窗口的几何、焦点或最小化状态。
                continue
            snapshot = entry.tracker.snapshot()
            if entry.tracker.lost:
                self._remove(device)
                continue
            if snapshot is None or snapshot.minimized or not snapshot.visible:
                toolbar.hide()
                toolbar.dismiss_popup()
                entry.placement = None
                continue
            # Qt 已失焦时，外部应用之间切换不会再触发 ApplicationDeactivate。
            # 比较原生前台身份，既能收起残留弹层，也允许从后台投屏直接打开更多。
            foreground = snapshot.foreground_hwnd
            if entry.foreground_hwnd is not None and entry.foreground_hwnd != foreground:
                toolbar.dismiss_popup()
            entry.foreground_hwnd = foreground
            # Qt 的有效比例还包含用户设置的 QT_SCALE_FACTOR；仅使用目标窗口 DPI
            # 会把工具窗压缩为系统比例。跨屏后的 Qt DPI 通知会在下一轮重新定位。
            scale = toolbar.devicePixelRatioF()
            preferred = toolbar.sizeHint().expandedTo(toolbar.minimumSize())
            size = (round(preferred.width() * scale), round(preferred.height() * scale))
            rect = dock_geometry(snapshot.rect, snapshot.work_area, size,
                                 gap=round(8 * scale), inset=round(12 * scale))
            placement = (rect, snapshot.hwnd, snapshot.topmost, snapshot.dpi)
            if placement != entry.placement or not toolbar.isVisible():
                tool_hwnd = int(toolbar.winId())
                if not entry.screen_observed:
                    handle = toolbar.windowHandle()
                    if handle is not None:
                        handle.screenChanged.connect(
                            lambda _screen, current=entry: self._queue_update(current),
                        )
                        entry.screen_observed = True
                # 原生物理坐标避免混合 DPI 桌面绝对坐标除以一个全局缩放比例。
                if not entry.tracker.position_tool(tool_hwnd, snapshot, rect):
                    toolbar.hide()
                    toolbar.dismiss_popup()
                    entry.placement = None
                    continue
                if not toolbar.isVisible():
                    toolbar.show()
                    entry.tracker.position_tool(int(toolbar.winId()), snapshot, rect)
                entry.placement = placement
                # 原生移动可能同步改变 Qt 的屏幕比例；即使镜像停下，也须补一帧新尺寸。
                if toolbar.devicePixelRatioF() != scale:
                    self._queue_update(entry)

    def _remove(self, device: str) -> None:
        entry = self.entries.pop(device)
        self._pending.pop(device, None)
        self._retired[device] = entry.session
        self._frame._input_controller._invalidate_session_input(entry.session)
        close = getattr(entry.tracker, "close", None)
        if callable(close):
            close()
        entry.toolbar.dispose()
        entry.toolbar.deleteLater()

    def close(self) -> None:
        """关闭先撤销输入并停计时器，再释放工具窗；重复关闭无副作用。"""
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self._motion_timer.stop()
        self._pending.clear()
        for device in tuple(self.entries):
            self._remove(device)
        self._retired.clear()


class RemoteControllerWindow(QDialog):
    """独立遥控器复用原按键区；关闭只隐藏视图，不停止任何投屏。"""

    def __init__(self, content: QWidget, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Tool)
        self.setObjectName("remoteControllerWindow")
        self.setWindowTitle(tr("独立遥控器"))
        self.setMinimumSize(200, 200)
        self.resize(760, 410)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.target_label = apply_label_role(QLabel(), FontRole.UI, color_key="TEXT_PRIMARY")
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.control_content = content
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        body_layout.addWidget(content, 0, Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self._refresh_style()
        BaseStyles.theme_changed.connect(self._refresh_style)

    def _refresh_style(self, *_args) -> None:
        self.setStyleSheet(
            f"QDialog#remoteControllerWindow {{ background: {BaseStyles.color('PANEL_BG')}; }}",
        )

    def set_target_count(self, count: int) -> None:
        """操作范围明确展示当前在线选择，允许未投屏时独立使用。"""
        self.target_label.setText(
            tr("操作当前已选的 {count} 台在线设备 · 与投屏侧栏的单台控制独立").format(count=count)
            if count else tr("请在主窗口选择在线设备；无需先启动投屏。"),
        )
