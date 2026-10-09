"""验证远程页首次进入及再次切入时，每次可见绘制都使用稳定的字段几何。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, QObject, QSize
from PySide6.QtTest import QTest

from gui.styles import BaseStyles
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame
from tests.ui_geometry_helpers import mapped_rect, wait_until

pytestmark = pytest.mark.ui


class _VisiblePaintGeometry(QObject):
    """记录实际可见 Paint 的字段坐标，不能以最终稳定快照掩盖中间跳动。"""

    def __init__(self, root, widgets):
        super().__init__(root)
        self.root = root
        self.widgets = widgets
        self.samples = []
        for widget in widgets:
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint and watched.isVisible():
            self.samples.append(tuple(
                mapped_rect(widget, self.root).getRect() for widget in self.widgets
            ))
        return False


@pytest.mark.parametrize("width,font_size", ((1120, 12), (760, 12), (1600, 22)))
def test_remote_entry_keeps_parameter_geometry_from_first_visible_paint(
    qt_application, monkeypatch, isolated_app_settings, width, font_size,
):
    isolated_app_settings.set_many({
        "window_width": width,
        "window_height": 820,
        "ui_font_size": font_size,
        "mica_enabled": False,
        "continuous_device_scan": False,
    })
    monkeypatch.setattr("models.device_store.DeviceStore.get_basic_devices_info", lambda: [])
    monkeypatch.setattr("models.device_store.DeviceStore.get_full_devices_info", lambda _ids: [])
    monkeypatch.setattr(
        "gui.widgets.adb_client_card.AdbClientSettingCard.start_detection", lambda _self: None,
    )
    monkeypatch.setattr(
        "gui.panels.remote_panel.ADBBridge", lambda: SimpleNamespace(path="synthetic-adb"),
    )
    monkeypatch.setattr("gui.panels.remote_panel.ScrcpyService", lambda: Mock(
        encoder_probes_running=Mock(return_value=False),
        wait_encoder_probes=Mock(return_value=True),
    ))
    for name in ("RemoteControlService", "RemoteInputEngine"):
        monkeypatch.setattr(f"gui.panels.remote_panel.{name}", Mock())
    BaseStyles.reload_from_settings()
    frame = build_main_frame(
        settings=isolated_app_settings,
        screen_adapter=_FakeScreenAdapter(_FakeScreen("remote-entry", QSize(width, 1080))),
    )
    try:
        remote = frame.left_panel.remote_panel
        content = frame.left_panel._tab_scroll_areas[2].widget()
        tracked = (
            remote.preset.parentWidget(), remote.fps.parentWidget(),
            remote.maxsize, remote.bitrate_slider, remote.btn_start,
        )
        probe = _VisiblePaintGeometry(content, tracked)
        frame.show()
        wait_until(
            qt_application, lambda: frame.left_panel._responsive_coordinator.diagnostics.stable,
        )
        QTest.qWait(160)
        phases = []
        for previous in (None, ("system", "overview"), ("devices", "overview")):
            if previous is not None:
                assert frame._open_workspace_feature(*previous)
                QTest.qWait(240)
            probe.samples.clear()
            assert frame._open_workspace_feature("devices", "remote")
            # 覆盖原生切页动画与布局防抖；每次 Paint 都已在过滤器中记录。
            QTest.qWait(350)
            assert remote.fps.isVisibleTo(content)
            assert not remote.fps_selector.isVisibleTo(content)
            assert not remote.advanced_options.isVisibleTo(content)
            assert not remote.more_options.isVisibleTo(content)
            assert probe.samples, "远程参数必须实际绘制，不能只检查隐藏控件的几何"
            phases.append(tuple(probe.samples))
        for samples in phases:
            assert all(sample == samples[0] for sample in samples), samples
    finally:
        frame.left_panel.shutdown()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
