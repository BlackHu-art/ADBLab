"""显式原生桌面回归：合成镜像的事件跟随、混合 DPI 和资源释放。"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from services.remote.window_tracking import _Win32WindowApi
from tests.test_remote_dock_native import _Frame, _wait
from tests.test_remote_dock_native import external_window as external_window

pytestmark = [
    pytest.mark.ui,
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform != "win32" or os.environ.get("QT_QPA_PLATFORM") != "windows",
        reason="原生运动验证需显式 QT_QPA_PLATFORM=windows；默认离屏不显示窗口",
    ),
]


class _MaterialHost(QWidget):
    def __init__(self, mica_enabled):
        super().__init__()
        self._mica_enabled = mica_enabled

    def isMicaEffectEnabled(self):
        return self._mica_enabled


@pytest.fixture
def native_motion(qt_application, external_window, request):
    from gui.panels.remote_panel_dock import RemotePanelDock
    from gui.window_effects import is_mica_supported
    from services.remote.window_events import _RETAINED_SUBSCRIPTIONS

    process, info, title = external_window
    session = SimpleNamespace(
        config=SimpleNamespace(device="synthetic", no_window=False, window_title=title),
        process=process, state="ready", resource_owned=True, cancel_event=threading.Event(),
    )
    frame = _Frame(session)
    requested_mica = getattr(request, "param", False)
    parent = _MaterialHost(requested_mica)
    dock = RemotePanelDock(frame, parent)
    probe = SimpleNamespace(
        app=qt_application, dock=dock, frame=frame, session=session,
        api=_Win32WindowApi(), owner_hwnd=info["hwnd"], samples=[],
        retained_subscriptions=set(_RETAINED_SUBSCRIPTIONS),
        expected_mica=requested_mica and is_mica_supported(),
    )
    try:
        dock.sync()
        _wait(qt_application, lambda: bool(dock.entries), "未创建合成镜像侧栏")
        probe.entry = dock.entries["synthetic"]
        probe.toolbar = probe.entry.toolbar
        probe.popup = probe.toolbar.popup_window
        _wait(qt_application, probe.toolbar.isVisible, "合成镜像侧栏未显示")
        probe.toolbar._more_button.click()
        _wait(qt_application, probe.popup.isVisible, "更多面板未展开")
        _wait(qt_application, lambda: _adjacent(probe), "初始侧栏或更多面板未正确相邻")
        probe.foreground = int(probe.api._user32.GetForegroundWindow() or 0)
        yield probe
    finally:
        dock.close()
        parent.close()
        report = {
            "test": request.node.name,
            "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", "default"),
            "host_mica_requested": requested_mica,
            "expected_mica": probe.expected_mica,
            "screens": [
                {"index": index, "dpr": screen.devicePixelRatio(),
                 "refresh_hz": screen.refreshRate(),
                 "geometry": screen.geometry().getRect()}
                for index, screen in enumerate(qt_application.screens())
            ],
            "samples": probe.samples,
        }
        print("native-dock-motion " + json.dumps(report, ensure_ascii=False))
        artifacts = os.environ.get("ADBLAB_NATIVE_DOCK_ARTIFACT_DIR")
        if artifacts:
            directory = Path(artifacts)
            directory.mkdir(parents=True, exist_ok=True)
            scale = os.environ.get("QT_SCALE_FACTOR", "default")
            (directory / f"{request.node.name}-scale-{scale}.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
            )


def _move_owner(probe, x, y, width=340, height=560):
    with probe.api._physical_coordinates():
        assert probe.api._user32.SetWindowPos(
            probe.owner_hwnd, 0, x, y, width, height, 0x0014,
        ), "合成镜像移动失败"


def _adjacent(probe):
    owner = probe.api.snapshot(probe.owner_hwnd)
    tool = probe.api.snapshot(int(probe.toolbar.winId()))
    popup = probe.api.snapshot(int(probe.popup.winId()))
    if owner is None or tool is None or popup is None:
        return False
    ratio = probe.toolbar.devicePixelRatioF()
    gap = round(8 * ratio)
    if not (tool.visible and popup.visible and probe.popup.isVisible()):
        return False
    # 合成镜像在工作区左侧，侧栏和面板具有充分右侧空间。
    if abs(tool.rect[0] - (owner.rect[0] + owner.rect[2] + gap)) > 2:
        return False
    if abs(tool.rect[1] - (owner.rect[1] + round(12 * ratio))) > 2:
        return False
    return _popup_adjacent(tool, popup, ratio)


def _popup_adjacent(tool, popup, ratio):
    gap = round(8 * ratio)
    popup_gap = min(
        abs(popup.rect[0] - (tool.rect[0] + tool.rect[2]) - gap),
        abs(tool.rect[0] - (popup.rect[0] + popup.rect[2]) - gap),
    )
    left, top, width, height = popup.work_area
    expected_y = max(top, min(tool.rect[1], top + height - popup.rect[3]))
    return (
        popup_gap <= 2 and abs(popup.rect[1] - expected_y) <= 2
        and popup.rect[0] >= left - 2
        and popup.rect[0] + popup.rect[2] <= left + width + 2
    )


def _sizes_settled(probe, expected_dpr):
    for widget in (probe.toolbar, probe.popup):
        if abs(widget.devicePixelRatioF() - expected_dpr) > 0.001:
            return False
        native = probe.api.snapshot(int(widget.winId()))
        if native is None:
            return False
        if abs(native.rect[2] - round(widget.width() * expected_dpr)) > 2:
            return False
        if abs(native.rect[3] - round(widget.height() * expected_dpr)) > 2:
            return False
    preferred = probe.toolbar.sizeHint().expandedTo(probe.toolbar.minimumSize())
    return (
        abs(probe.toolbar.width() - preferred.width()) <= 1
        and abs(probe.toolbar.height() - preferred.height()) <= 1
    )


def _native_backdrop(hwnd):
    query = ctypes.WinDLL("dwmapi").DwmGetWindowAttribute
    query.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.POINTER(ctypes.c_int), wintypes.DWORD]
    query.restype = ctypes.c_long
    backdrop = ctypes.c_int()
    assert query(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop)) == 0
    return backdrop.value


def _record(probe, stage, elapsed_ms=None):
    sample = {"stage": stage, "settle_ms": elapsed_ms}
    for name, widget, hwnd in (
        ("owner", None, probe.owner_hwnd),
        ("toolbar", probe.toolbar, int(probe.toolbar.winId())),
        ("popup", probe.popup, int(probe.popup.winId())),
    ):
        native = probe.api.snapshot(hwnd)
        assert native is not None, (stage, name, "原生窗口已消失")
        sample[name] = {"rect": native.rect, "dpi": native.dpi}
        if widget is not None:
            ratio = widget.devicePixelRatioF()
            sample[name].update(
                dpr=ratio, logical_size=widget.size().toTuple(),
                mica=widget.isMicaEffectEnabled(),
            )
            assert widget.isMicaEffectEnabled() is probe.expected_mica, sample
            if sys.getwindowsversion().build >= 22523:
                sample[name]["native_backdrop"] = _native_backdrop(hwnd)
                assert sample[name]["native_backdrop"] == (2 if probe.expected_mica else 1), sample
            assert abs(native.rect[2] - round(widget.width() * ratio)) <= 2, sample
            assert abs(native.rect[3] - round(widget.height() * ratio)) <= 2, sample
    preferred = probe.toolbar.sizeHint().expandedTo(probe.toolbar.minimumSize())
    assert abs(sample["toolbar"]["rect"][2] - round(
        preferred.width() * probe.toolbar.devicePixelRatioF(),
    )) <= 2, sample
    assert abs(sample["toolbar"]["rect"][3] - round(
        preferred.height() * probe.toolbar.devicePixelRatioF(),
    )) <= 2, sample
    assert int(probe.api._user32.GetForegroundWindow() or 0) == probe.foreground, sample
    assert probe.popup.isVisible() and probe.toolbar._more_button.isChecked(), sample
    assert not probe.frame.calls
    probe.samples.append(sample)
    return sample


@pytest.mark.parametrize("native_motion", [False, True], indirect=True, ids=["solid", "mica"])
def test_native_location_events_follow_with_polling_stopped(native_motion):
    probe = native_motion
    baseline = _record(probe, "before-motion")
    probe.dock.timer.stop()
    owner = probe.api.snapshot(probe.owner_hwnd)
    assert owner is not None
    for index in range(8):
        started = time.perf_counter()
        _move_owner(probe, owner.rect[0] + 80 + index * 14, owner.rect[1] + 30 + index * 5)
        _wait(probe.app, lambda: _adjacent(probe),
              "停止轮询后，原生位置事件未让侧栏与展开面板跟随镜像")
        sample = _record(probe, f"motion-{index}", (time.perf_counter() - started) * 1000)
        assert sample["popup"]["rect"][2:] == baseline["popup"]["rect"][2:], probe.samples
        assert not probe.dock.timer.isActive(), "移动跟随不得重新依赖周期轮询"

    moving_positions = set()
    for index in range(24):
        _move_owner(probe, owner.rect[0] + 200 + index * 5, owner.rect[1] + 70)
        # 连续输入期间只处理 Qt 消息，不等待侧栏追平每一个目标位置。
        QTest.qWait(12)
        sample = _record(probe, f"continuous-{index}")
        tool = probe.api.snapshot(int(probe.toolbar.winId()))
        popup = probe.api.snapshot(int(probe.popup.winId()))
        assert tool is not None and popup is not None
        assert _popup_adjacent(tool, popup, probe.toolbar.devicePixelRatioF()), sample
        assert sample["popup"]["rect"][2:] == baseline["popup"]["rect"][2:], sample
        moving_positions.add(tool.rect[:2])
    assert len(moving_positions) > 1, "连续运动期间侧栏始终停留在原位"
    _wait(probe.app, lambda: _adjacent(probe), "连续运动结束后侧栏未收敛到最终位置")
    _record(probe, "continuous-settled")


def test_native_mixed_dpi_round_trips_preserve_popup_and_application_scale(native_motion):
    probe = native_motion
    screens = sorted(probe.app.screens(), key=lambda screen: screen.devicePixelRatio())
    if (len(screens) < 2
            or abs(screens[0].devicePixelRatio() - screens[-1].devicePixelRatio()) < 0.1):
        pytest.skip("混合 DPI 专项需要两个具有不同系统缩放比例的真实显示器")
    targets = (screens[0], screens[-1])
    baselines = {}
    probe.dock.timer.stop()
    for turn in range(3):
        for index, screen in enumerate(targets):
            # Windows 的 QScreen 原点保留原生桌面位置，仅尺寸为逻辑像素。
            # 只借用原点选中显示器，物理尺寸及工作区均由 Win32 快照独立核验。
            origin = screen.geometry().topLeft()
            started = time.perf_counter()
            _move_owner(probe, origin.x() + 100, origin.y() + 100)
            expected_dpr = screen.devicePixelRatio()
            _wait(
                probe.app,
                lambda: _adjacent(probe) and _sizes_settled(probe, expected_dpr),
                f"第 {turn + 1} 次跨屏后侧栏或更多面板的 DPR、物理尺寸、相邻位置未收敛",
                timeout=6.0,
            )
            sample = _record(
                probe, f"screen-{index}-round-{turn}",
                (time.perf_counter() - started) * 1000,
            )
            owner_ratio = sample["owner"]["dpi"] / 96
            user_scale = float(os.environ.get("QT_SCALE_FACTOR", "1"))
            assert abs(sample["toolbar"]["dpr"] - owner_ratio * user_scale) < 0.001, sample
            assert abs(sample["popup"]["dpr"] - expected_dpr) < 0.001, sample
            assert not probe.dock.timer.isActive()
            if index not in baselines:
                baselines[index] = sample
            else:
                for name in ("toolbar", "popup"):
                    assert sample[name]["dpr"] == baselines[index][name]["dpr"], probe.samples
                    assert sample[name]["logical_size"] == baselines[index][name]["logical_size"], (
                        probe.samples
                    )
                    assert sample[name]["rect"][2:] == baselines[index][name]["rect"][2:], (
                        probe.samples
                    )


def test_native_close_releases_hooks_timers_and_ignores_late_motion(native_motion):
    from services.remote.window_events import _RETAINED_SUBSCRIPTIONS

    probe = native_motion
    tracker = probe.entry.tracker
    assert tracker.event_tracking, "真实 Windows 跟踪必须已安装原生事件订阅"
    toolbar_hwnd = int(probe.toolbar.winId())
    popup_hwnd = int(probe.popup.winId())
    timers = [*probe.dock.findChildren(QTimer), *probe.toolbar.findChildren(QTimer)]
    _move_owner(probe, 260, 180)
    probe.dock.close()
    assert not tracker.event_tracking
    assert _RETAINED_SUBSCRIPTIONS == probe.retained_subscriptions
    assert not probe.dock.entries
    assert probe.frame.invalidated == [probe.session]
    assert all(not timer.isActive() for timer in timers if isValid(timer))
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not probe.api._user32.IsWindow(toolbar_hwnd)
    assert not probe.api._user32.IsWindow(popup_hwnd)
    _move_owner(probe, 280, 200)
    QTest.qWait(100)
    assert not probe.dock.entries, "关闭后晚到原生事件不能重建侧栏"
    assert not tracker.event_tracking
    assert all(not timer.isActive() for timer in timers if isValid(timer))
    assert probe.frame.invalidated == [probe.session]
    assert int(probe.api._user32.GetForegroundWindow() or 0) == probe.foreground
    assert not probe.frame.calls
    probe.samples.append({
        "stage": "closed", "hooks_active": tracker.event_tracking,
        "active_timers": sum(timer.isActive() for timer in timers if isValid(timer)),
    })
