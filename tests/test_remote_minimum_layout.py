"""验证正常最小主窗口保留会话区与远程双栏，字体增长由重排和纵向滚动承接。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QWidget

from gui.styles import BaseStyles
from tests.test_main_window_layout import _FakeScreen, _FakeScreenAdapter, build_main_frame
from tests.test_remote_layout import expand_remote_options
from tests.ui_geometry_helpers import (
    assert_non_overlapping,
    assert_positive_geometry,
    assert_scroll_target_reachable,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("font_size", (12, 16, 22))
def test_remote_normal_minimum_window_keeps_session_and_columns_without_horizontal_scroll(
    qt_application, monkeypatch, isolated_app_settings, font_size,
):
    isolated_app_settings.set_many({
        "window_width": 860,
        "window_height": 500,
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
        screen_adapter=_FakeScreenAdapter(_FakeScreen("normal", QSize(1920, 1080))),
    )
    try:
        frame.show()
        frame.resize(frame.minimumSize())
        assert frame._open_workspace_feature("devices", "remote")
        remote = frame.left_panel.remote_panel
        scroll = frame.left_panel._tab_scroll_areas[2]
        content = scroll.widget()
        wait_until(
            qt_application, lambda: frame.left_panel._responsive_coordinator.diagnostics.stable,
        )
        wait_for_stable_geometry(qt_application, (frame, content, *remote._remote_section_groups))
        expand_remote_options(remote, content, qt_application)
        wait_until(
            qt_application, lambda: frame.left_panel._responsive_coordinator.diagnostics.stable,
        )
        wait_for_stable_geometry(qt_application, (frame, content, *remote._remote_section_groups))
        assert frame.size() == QSize(860, 500)
        left, right = (mapped_rect(section, content) for section in remote._remote_section_groups)
        if font_size == 12:
            assert abs(left.top() - right.top()) <= 2
            assert left.right() < right.left()
            assert abs(left.width() - right.width()) <= 2
            system, recording = (mapped_rect(section, content)
                                 for section in remote._remote_bottom_sections)
            assert abs(system.top() - recording.top()) <= 2
        elif left.top() != right.top():
            assert left.bottom() < right.top()
            assert left.left() == right.left()
        assert_non_overlapping(remote._remote_section_groups, content)
        session = content.findChild(QWidget, "remoteMirrorSession")
        assert session is not None and session.isVisibleTo(content)
        top = mapped_rect(session, content)
        assert top.bottom() < min(left.top(), right.top())
        assert top.left() <= left.left() and top.right() >= right.right()
        assert scroll.horizontalScrollBar().maximum() == 0
        if font_size == 12:
            assert remote.window_options_binding.applied_plan.mode.columns == 3, (
                "默认字体下，常用开关也应保持每行三个"
            )
            media = remote._remote_media_binding.widgets()
            assert remote._remote_media_binding.applied_plan.mode.columns == 3
            assert len({mapped_rect(button, content).top() for button in media}) == 1
        parameters = (
            remote.preset.parentWidget(), remote.maxsize, remote.fps.parentWidget(),
            remote.bitrate_slider, remote.codec, remote.buffer, remote.orientation,
        )
        assert remote.fps.isVisibleTo(content)
        assert not remote.fps_selector.isVisibleTo(content)
        options = tuple(getattr(remote, name) for name in (
            "chk_record", "chk_fullscreen", "chk_aot", "chk_showtouches", "chk_stayawake",
            "chk_turnscreenoff", "chk_noplayback", "chk_noaudio",
        ))
        for widget in (*parameters, *options, remote.btn_start, *remote._remote_control_buttons):
            assert widget.isVisibleTo(content)
            assert_positive_geometry(widget, content)
            assert_scroll_target_reachable(scroll, widget)
        assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        frame.left_panel.shutdown()
        frame._unbind_window_screen()
        frame._close_ready = True
        frame.close()
