"""把逐台遥控侧栏绑定到外部投屏窗口，并管理独立遥控器的视图寿命。"""

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout, QWidget

from gui.i18n import tr
from gui.styles import BaseStyles, FontRole
from gui.styles.fluent import apply_label_role
from gui.widgets.remote_toolbar import RemoteToolbar
from services.remote.window_tracking import WindowsWindowTracker


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
    """窗口和输入共享原会话对象，旧窗口回调永远不能取得新会话。"""

    session: Any
    tracker: Any
    toolbar: RemoteToolbar
    placement: object = None
    foreground_hwnd: int | None = None


class RemotePanelDock(QObject):
    """GUI 线程拥有侧栏及轮询器；只查询本机窗口，不等待进程或调用设备。"""

    def __init__(self, frame, parent: QWidget, *, tracker_factory=WindowsWindowTracker):
        super().__init__(parent)
        self._frame = frame
        self._owner = parent
        self._tracker_factory = tracker_factory
        self.entries: dict[str, _DockEntry] = {}
        self._retired: dict[str, object] = {}
        self._closed = False
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
            if not tracker.supported:
                continue
            toolbar = RemoteToolbar(self._owner)
            toolbar.set_target_label(self._frame._mirror_device_name(device))
            entry = _DockEntry(session, tracker, toolbar)
            self.entries[device] = entry
            toolbar.key_requested.connect(
                lambda code, current=entry: self._dispatch(current, code, action=False),
            )
            toolbar.action_requested.connect(
                lambda code, current=entry: self._dispatch(current, code, action=True),
            )
            toolbar.layout_changed.connect(self.tick)
        self.tick()
        if self.entries:
            self.timer.start()
        else:
            self.timer.stop()

    def _dispatch(self, entry: _DockEntry, code: str, *, action: bool) -> None:
        device = entry.session.config.device
        if self.entries.get(device) is not entry or not self._active(entry.session):
            return
        # 每次点击重新确认句柄，避免关闭窗口到下一轮轮询之间仍接纳输入。
        snapshot = entry.tracker.snapshot()
        if snapshot is None or snapshot.minimized or not snapshot.visible:
            return
        controller = self._frame._input_controller
        callback = controller._send_session_action if action else controller._send_session_keyevent
        callback(entry.session, code)

    def tick(self) -> None:
        """仅在几何或置顶状态变化时定位，避免反复抢占其他应用的堆叠顺序。"""
        for device, entry in tuple(self.entries.items()):
            if not self._active(entry.session):
                self._remove(device)
                continue
            snapshot = entry.tracker.snapshot()
            if entry.tracker.lost:
                self._remove(device)
                continue
            toolbar = entry.toolbar
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
            connected = getattr(self._frame, "_connected_remote_devices", None)
            toolbar.set_available(connected is None or device in connected)
            # Qt 的有效比例还包含用户设置的 QT_SCALE_FACTOR；仅使用目标窗口 DPI
            # 会把工具窗压缩为系统比例。跨屏后的 Qt DPI 通知会在下一轮重新定位。
            scale = toolbar.devicePixelRatioF()
            preferred = toolbar.sizeHint().expandedTo(toolbar.minimumSize())
            size = (round(preferred.width() * scale), round(preferred.height() * scale))
            rect = dock_geometry(snapshot.rect, snapshot.work_area, size,
                                 gap=round(8 * scale), inset=round(12 * scale))
            placement = (rect, snapshot.hwnd, snapshot.topmost, snapshot.dpi)
            if placement != entry.placement or not toolbar.isVisible():
                # 原生物理坐标避免混合 DPI 桌面绝对坐标除以一个全局缩放比例。
                if not entry.tracker.position_tool(int(toolbar.winId()), snapshot, rect):
                    toolbar.hide()
                    toolbar.dismiss_popup()
                    entry.placement = None
                    continue
                if not toolbar.isVisible():
                    toolbar.show()
                    entry.tracker.position_tool(int(toolbar.winId()), snapshot, rect)
                entry.placement = placement
        if not self.entries:
            self.timer.stop()

    def _remove(self, device: str) -> None:
        entry = self.entries.pop(device)
        self._retired[device] = entry.session
        self._frame._input_controller._invalidate_session_input(entry.session)
        entry.toolbar.dispose()
        entry.toolbar.deleteLater()

    def close(self) -> None:
        """关闭先撤销输入并停计时器，再释放工具窗；重复关闭无副作用。"""
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
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
