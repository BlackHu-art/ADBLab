"""验证批准的紧凑镜像表单、折叠项和录制联动。"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from qfluentwidgets import SwitchButton, VerticalSeparator

from tests.test_responsive_panels import _close_feature_panel, _show_feature_panel
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.fixture
def compact_remote(qt_application, monkeypatch, isolated_app_settings):
    panel, remote, scroll, content = _show_feature_panel(
        "remote", 780, 12, qt_application, monkeypatch,
    )
    remote._settings = isolated_app_settings
    try:
        yield remote, scroll, content
    finally:
        _close_feature_panel(panel)


def test_compact_form_keeps_primary_action_above_configuration(compact_remote):
    remote, _scroll, content = compact_remote
    remote.set_target_devices(["synthetic-device"])
    assert mapped_rect(remote.btn_start, content).bottom() < mapped_rect(
        remote.maxsize, content,
    ).top()
    assert remote.fps.isVisibleTo(content)
    for name in ("chk_aot", "chk_fullscreen", "chk_showtouches"):
        assert isinstance(getattr(remote, name), SwitchButton)
    assert remote._mirror_device_label.isVisibleTo(content)


def test_advanced_and_more_options_expand_without_losing_values(
    compact_remote, qt_application,
):
    remote, _scroll, content = compact_remote
    assert not remote.codec.isVisibleTo(content)
    assert not remote.chk_turnscreenoff.isVisibleTo(content)
    for button, container, control in (
        (remote.btn_advanced, remote.advanced_options, remote.codec),
        (remote.btn_more_options, remote.more_options, remote.chk_turnscreenoff),
    ):
        before = remote.buffer.currentData(), remote.codec.text()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        wait_for_stable_geometry(qt_application, (container, button))
        assert container.isVisibleTo(content)
        assert control.isVisibleTo(content)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        wait_for_stable_geometry(qt_application, button)
        assert not container.isVisibleTo(content)
        assert (remote.buffer.currentData(), remote.codec.text()) == before


def test_compact_presets_keep_automatic_encoding_and_legacy_preference(compact_remote):
    remote, _scroll, _content = compact_remote
    assert isinstance(remote.codec, QLabel)
    assert remote.advanced_options.isHidden()
    assert remote.codec.text() == "自动（启动时检测）"
    assert remote.codec.text() in remote._advanced_summary.text()
    remote._settings.set("scrcpy_codec", "h265")
    for preset in ("Quality", "Low Latency", "Balanced"):
        remote.preset_selector.items[preset].click()
        assert remote.codec.text() == "自动（启动时检测）"
        assert remote.codec.text() in remote._advanced_summary.text()
        assert remote.buffer.currentText() in remote._advanced_summary.text()
        assert remote._settings.get("scrcpy_codec") == "h265"


def test_record_only_and_save_recording_stay_consistent(compact_remote):
    remote, _scroll, _content = compact_remote
    remote.set_target_devices(["synthetic-device"])
    remote.chk_noplayback.setChecked(True)
    assert remote.chk_record.isChecked()
    assert remote._mirror_hint.text() == "仅录制，不打开镜像窗口"
    remote.chk_record.setChecked(False)
    assert not remote.chk_noplayback.isChecked()
    assert remote._mirror_hint.text() == "镜像将在独立窗口打开"


def test_record_only_without_target_preserves_device_selection_hint(compact_remote):
    remote, _scroll, _content = compact_remote
    remote.set_target_devices([])
    remote.chk_noplayback.setChecked(True)
    assert remote.chk_record.isChecked()
    assert remote._mirror_hint.text() == "请从右上角选择操作设备"
    remote.set_target_devices(["synthetic-device"])
    assert remote._mirror_hint.text() == "仅录制，不打开镜像窗口"


def test_compact_remote_groups_follow_preview_and_use_short_separators(compact_remote):
    remote, _scroll, content = compact_remote
    by_key = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    by_action = {
        button.property("remoteAction"): button for button in remote._remote_action_buttons
    }
    assert mapped_rect(by_key["MEDIA_PREV"], content).top() < mapped_rect(
        by_action["swipe_up"], content,
    ).top() < mapped_rect(by_key["MENU"], content).top()
    short_lines = [
        line for line in content.findChildren(VerticalSeparator)
        if line.objectName() == "remoteCommandSeparator" and line.isVisibleTo(content)
    ]
    assert len(short_lines) >= 5
    assert all(line.height() == 14 for line in short_lines)
