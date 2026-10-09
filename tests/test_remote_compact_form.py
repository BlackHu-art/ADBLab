"""验证紧凑遥控桌面的常显参数、统一按钮规格和录制联动。"""

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QWidget
from qfluentwidgets import SwitchButton

from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _show_feature_panel,
)
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


def test_session_actions_span_both_settings_and_remote_controls(compact_remote):
    remote, scroll, content = compact_remote
    remote.set_target_devices(["synthetic-device"])
    session = content.findChild(QWidget, "remoteMirrorSession")
    assert session is not None, "镜像会话应独立展示，不能混入参数栏"
    assert session.isVisibleTo(content)
    session_rect = mapped_rect(session, content)
    settings_rect, controls_rect = (
        mapped_rect(section, content) for section in remote._remote_section_groups
    )
    assert session_rect.bottom() < min(settings_rect.top(), controls_rect.top())
    assert session_rect.left() <= settings_rect.left()
    assert session_rect.right() >= controls_rect.right()
    assert session.isAncestorOf(remote.btn_start)
    assert session.isAncestorOf(remote.btn_stop)
    assert session.isAncestorOf(remote._status_label)
    assert session.isAncestorOf(remote._mirror_hint)
    assert scroll.horizontalScrollBar().maximum() == 0


def test_session_and_workspace_share_outer_edges(compact_remote):
    remote, _scroll, content = compact_remote
    session = content.findChild(QWidget, "remoteMirrorSession")
    workspace = remote._remote_section_groups[0].parentWidget()
    assert mapped_rect(session, content).left() == mapped_rect(workspace, content).left()
    assert mapped_rect(session, content).right() == mapped_rect(workspace, content).right()


@pytest.mark.parametrize("width", (780, 320))
def test_session_copy_is_not_compressed_below_text_height(
    compact_remote, qt_application, width,
):
    remote, scroll, content = compact_remote
    remote.set_target_devices(["synthetic-device"])
    _resize_feature_viewport(qt_application, remote.panel, remote, scroll, width)
    for label in (remote._mirror_hint, remote._mirror_device_label, remote._status_label):
        wait_for_stable_geometry(qt_application, label)
        assert label.height() >= max(
            label.fontMetrics().height(), label.heightForWidth(label.width()),
        ), f"会话文案不应被相邻按钮压缩：{label.text()}"


def test_remote_key_tooltips_describe_actions_without_protocol_identifiers(compact_remote):
    remote, _scroll, _content = compact_remote
    for button in remote._remote_key_buttons:
        tooltip = button.toolTip()
        assert tooltip
        assert str(button.property("remoteKey")) not in tooltip
        assert button.accessibleDescription() == tooltip


def test_media_and_volume_buttons_share_outer_edges(compact_remote):
    remote, _scroll, content = compact_remote
    buttons = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    assert mapped_rect(buttons["VOL_DOWN"], content).left() == mapped_rect(
        buttons["MEDIA_PREV"], content,
    ).left()
    assert mapped_rect(buttons["VOL_UP"], content).right() == mapped_rect(
        buttons["MEDIA_NEXT"], content,
    ).right()


def test_automatic_encoding_description_remains_fully_readable(
    compact_remote, qt_application,
):
    remote, _scroll, content = compact_remote
    remote.buffer.setCurrentIndex(remote.buffer.findData("200"))
    label = remote.codec
    wait_for_stable_geometry(qt_application, label)
    needed = label.fontMetrics().boundingRect(
        QRect(0, 0, label.contentsRect().width(), 1000),
        int(Qt.TextFlag.TextWordWrap), label.text(),
    )
    assert label.isVisibleTo(content)
    assert label.contentsRect().height() >= needed.height(), "编码信息不能被裁切"


def test_common_parameters_start_visible_and_preserve_values_when_reflowed(
    compact_remote, qt_application,
):
    remote, scroll, content = compact_remote
    assert remote.maxsize.isVisibleTo(content), "参数和常用遥控应同时展示"
    assert all(button.isVisibleTo(content) for button in remote._remote_control_buttons)
    remote.fps.setCurrentIndex(remote.fps.findData("60"))
    remote.chk_fullscreen.setChecked(True)
    identities = id(remote.fps), id(remote.chk_fullscreen)
    for width in (320, 1280, 780):
        _resize_feature_viewport(qt_application, remote.panel, remote, scroll, width)
        assert remote.maxsize.isVisibleTo(content)
        assert remote.fps.currentData() == "60"
        assert scroll.horizontalScrollBar().maximum() == 0
    assert (id(remote.fps), id(remote.chk_fullscreen)) == identities
    assert remote.chk_fullscreen.isChecked()


def test_swipe_pad_has_spatial_directions_below_primary_navigation(compact_remote):
    remote, _scroll, content = compact_remote
    actions = {button.property("remoteAction"): button for button in remote._remote_action_buttons}
    up, down, left, right = (
        mapped_rect(actions[action], content)
        for action in ("swipe_up", "swipe_down", "swipe_left", "swipe_right")
    )
    assert up.bottom() < left.top() == right.top() < down.top()
    assert left.right() < up.center().x() < right.left()
    assert abs(up.center().x() - down.center().x()) <= 1
    navigation = [button for button in remote._remote_key_buttons
                  if button.property("remoteKey") in {"BACK", "HOME", "RECENTS"}]
    assert all(mapped_rect(button, content).bottom() < up.top() for button in navigation)
    assert all(button.accessibleName() for button in actions.values())
    assert all(button.toolTip() for button in actions.values())


@pytest.mark.parametrize("width", (320, 780))
def test_tab_from_mirror_start_enters_navigation_before_settings(
    compact_remote, qt_application, width,
):
    remote, scroll, _content = compact_remote
    _resize_feature_viewport(qt_application, remote.panel, remote, scroll, width)
    remote.set_target_devices(["synthetic-device"])
    back = next(button for button in remote._remote_key_buttons
                if button.property("remoteKey") == "BACK")
    remote.btn_start.setFocus(Qt.FocusReason.TabFocusReason)
    assert remote.btn_start.hasFocus()
    for _ in range(6):
        focused = qt_application.focusWidget()
        assert focused is not None
        QTest.keyClick(focused, Qt.Key.Key_Tab)
        assert not remote.maxsize.hasFocus(), "键盘顺序应先进入遥控操作再进入参数"
        if back.hasFocus():
            break
    assert back.hasFocus()


def test_swipe_pad_keyboard_order_follows_its_visible_rows(compact_remote):
    remote, _scroll, _content = compact_remote
    remote.set_target_devices(["synthetic-device"])
    actions = {button.property("remoteAction"): button for button in remote._remote_action_buttons}
    up = actions["swipe_up"]
    up.setFocus(Qt.FocusReason.TabFocusReason)
    assert up.hasFocus()
    QTest.keyClick(up, Qt.Key.Key_Tab)
    assert actions["swipe_left"].hasFocus()


def test_advanced_and_more_options_stay_visible_without_losing_values(
    compact_remote, qt_application,
):
    remote, scroll, content = compact_remote
    widgets = (remote.advanced_options, remote.more_options, remote.codec,
               remote.buffer, remote.orientation, remote.chk_turnscreenoff, remote.chk_noplayback)
    assert all(widget.isVisibleTo(content) for widget in widgets)
    remote.buffer.setCurrentIndex(remote.buffer.findData("200"))
    remote.orientation.setCurrentIndex(remote.orientation.findData("90"))
    remote.chk_turnscreenoff.setChecked(True)
    remote.chk_noplayback.setChecked(True)
    identities = tuple(id(widget) for widget in widgets)
    for width in (320, 1280, 780):
        _resize_feature_viewport(qt_application, remote.panel, remote, scroll, width)
        assert all(widget.isVisibleTo(content) for widget in widgets)
        assert remote.buffer.currentData() == "200"
        assert remote.orientation.currentData() == "90"
        assert remote.chk_turnscreenoff.isChecked()
        assert remote.chk_noplayback.isChecked() and remote.chk_record.isChecked()
    assert tuple(id(widget) for widget in widgets) == identities


def test_compact_presets_keep_automatic_encoding_and_legacy_preference(compact_remote):
    remote, _scroll, _content = compact_remote
    assert isinstance(remote.codec, QLabel)
    assert not remote.advanced_options.isHidden()
    assert remote.codec.text() == "自动"
    assert "启动时" in remote.codec.accessibleDescription()
    remote._settings.set("scrcpy_codec", "h265")
    for preset in ("Quality", "Low Latency", "Balanced"):
        remote.preset_selector.items[preset].click()
        assert remote.codec.text() == "自动"
        assert remote._settings.get("scrcpy_codec") == "h265"


def test_remote_actions_share_compact_height_and_icon_targets_are_square(compact_remote):
    remote, _scroll, _content = compact_remote
    buttons = (remote.btn_start, remote.btn_stop, *remote._remote_control_buttons)
    heights = [button.height() for button in buttons]
    assert min(heights) >= 36
    assert max(heights) - min(heights) <= 2, "常用操作应保持一致的按钮高度"
    for button in buttons:
        if not button.text():
            assert abs(button.width() - button.height()) <= 2
            assert button.accessibleName()
            assert button.toolTip()


@pytest.mark.parametrize("width", (780, 1280))
def test_parameters_and_switches_use_three_columns_without_hiding_options(
    compact_remote, qt_application, width,
):
    remote, scroll, content = compact_remote
    _resize_feature_viewport(qt_application, remote.panel, remote, scroll, width)
    assert remote.mirroring_binding.applied_plan.mode.columns == 3
    assert remote.window_options_binding.applied_plan.mode.columns == 3
    advanced = tuple(control.parentWidget() for control in (
        remote.codec, remote.buffer, remote.orientation,
    ))
    rectangles = [mapped_rect(field, content) for field in advanced]
    assert len({rect.top() for rect in rectangles}) == 1
    assert max(rect.width() for rect in rectangles) - min(rect.width() for rect in rectangles) <= 2
    assert all(left.right() < right.left() for left, right in zip(rectangles, rectangles[1:]))
    bitrate_editor = remote.mirroring_binding.widgets()[2]
    bitrate_title = bitrate_editor.title_label
    assert isinstance(bitrate_title, QLabel) and bitrate_title.text()
    assert bitrate_title.width() >= bitrate_title.fontMetrics().horizontalAdvance(
        bitrate_title.text(),
    )
    assert bitrate_title.height() <= bitrate_title.fontMetrics().height() + 4
    switches = remote.window_options_binding.widgets()
    assert len(switches) == 8
    assert all(switch.isVisibleTo(content) for switch in switches)
    for start in (0, 3):
        row = switches[start:start + 3]
        assert len({mapped_rect(switch, content).top() for switch in row}) == 1


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


def test_compact_remote_groups_keep_semantic_order_and_separate_click_targets(compact_remote):
    remote, _scroll, content = compact_remote
    by_key = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    by_action = {
        button.property("remoteAction"): button for button in remote._remote_action_buttons
    }
    assert max(mapped_rect(button, content).bottom() for button in by_action.values()) < (
        mapped_rect(by_key["MENU"], content).top()
    )
    previous, play, following = (
        mapped_rect(by_key[code], content) for code in ("MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT")
    )
    assert previous.right() < play.left() < play.right() < following.left()
    for button in (*by_key.values(), *by_action.values()):
        assert button.height() >= button.minimumSizeHint().height()
