"""验证统一遥控桌面的常显参数、分组按钮规格、键盘顺序和录制联动。"""

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QWidget
from qfluentwidgets import SwitchButton, TransparentPushButton

from gui.styles import BaseStyles
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _resize_remote_controller,
    _show_feature_panel,
    _show_remote_controller,
)
from tests.ui_geometry_helpers import assert_non_overlapping, mapped_rect, wait_for_stable_geometry

pytestmark = pytest.mark.ui


@pytest.fixture
def compact_remote(qt_application, monkeypatch, isolated_app_settings):
    panel, remote, scroll, content = _show_feature_panel(
        "remote", 780, 12, qt_application, monkeypatch,
    )
    remote._settings = isolated_app_settings
    # 构建阶段用固定 12 号字体量取几何；恢复真实角色解析后，测试才能验证
    # 运行时 12→22 字号切换确实重新应用到复合控件。
    monkeypatch.delattr(BaseStyles, "font_for_role", raising=False)
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
    assert remote._status_label.isVisibleTo(content)
    assert "待启动 1 台" == remote._status_label.text()


def test_session_actions_span_settings_without_controller_entry(compact_remote):
    remote, scroll, content = compact_remote
    remote.set_target_devices(["synthetic-device"])
    session = content.findChild(QWidget, "remoteMirrorSession")
    assert session is not None, "镜像会话应独立展示，不能混入参数栏"
    assert session.isVisibleTo(content)
    session_rect = mapped_rect(session, content)
    (settings_rect,) = (
        mapped_rect(section, content) for section in remote._remote_section_groups
    )
    assert session_rect.bottom() < settings_rect.top()
    assert session_rect.left() <= settings_rect.left()
    assert session_rect.right() >= settings_rect.right()
    assert session.isAncestorOf(remote.btn_start)
    assert session.isAncestorOf(remote.btn_stop)
    assert not hasattr(remote, "btn_open_controller")
    assert session.isAncestorOf(remote._status_label)
    assert session.isAncestorOf(remote._mirror_hint)
    assert scroll.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("font_size", (12, 22))
def test_mirror_actions_reflow_without_controller_entry_or_bottom_section(
    compact_remote, qt_application, font_size,
):
    """主窗口仅保留启动和停止动作，不出现遥控入口或旧说明区。"""
    from gui.styles.typography import FontConfig, typography_manager
    from tests.ui_geometry_helpers import assert_scroll_target_reachable

    remote, scroll, content = compact_remote
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family="Arial", ui_size=font_size,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    session = content.findChild(QWidget, "remoteMirrorSession")
    assert not hasattr(remote, "btn_open_controller")
    assert content.findChild(QWidget, "remoteControllerEntry") is None
    assert all(label.text() != "投屏操控" for label in content.findChildren(QLabel))
    assert all(button.text() not in ("打开独立遥控器", "独立遥控器")
               for button in content.findChildren(TransparentPushButton))
    assert len(remote._remote_section_groups) == 1
    assert remote._remote_workspace_binding.widgets() == tuple(remote._remote_section_groups)
    for width in (292, 420, 780, 1280, 780):
        _resize_feature_viewport(qt_application, remote.panel, remote, scroll, width)
        assert {button for button in session.findChildren(TransparentPushButton)
                if button.isVisibleTo(session)} == {remote.btn_start, remote.btn_stop}
        for button in (remote.btn_start, remote.btn_stop):
            assert button.isVisibleTo(content)
            assert button.font().pointSize() == font_size
            assert button.height() >= button.minimumSizeHint().height()
            assert button.width() >= button.minimumSizeHint().width()
            assert mapped_rect(button, content).bottom() < mapped_rect(
                remote.maxsize, content,
            ).top()
            assert_scroll_target_reachable(scroll, button)
        assert_non_overlapping((remote.btn_start, remote.btn_stop), content)
        assert scroll.horizontalScrollBar().maximum() == 0
        if width == 1280:
            assert remote.btn_start.y() == remote.btn_stop.y()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("scope", ["launch", "media"])
def test_remote_transparent_buttons_only_outline_for_keyboard(
    compact_remote, qt_application, monkeypatch, theme, scope,
):
    remote, _scroll, content = compact_remote
    BaseStyles.switch_theme(theme)
    remote.set_target_devices([] if scope == "launch" else ["synthetic-device"])
    monkeypatch.setattr(remote, "_send_keyevent", lambda _code: None)
    session = content.findChild(QWidget, "remoteMirrorSession")
    assert not session.property("remoteSectionSurface")
    for button in (remote.btn_start, remote.btn_stop, remote.btn_mirror_diagnostics,
                   *remote._remote_control_buttons):
        assert isinstance(button, TransparentPushButton)
        assert button.property("adblabKeyboardFocusOnly")
    button = remote.btn_start if scope == "launch" else remote._remote_media_buttons[2]
    if scope == "media":
        _show_remote_controller(qt_application, remote, 780)
    button.window().activateWindow()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    qt_application.processEvents()
    size = button.size()

    def border_color():
        image = button.grab().toImage()
        return image.pixelColor(image.width() // 2, round(image.devicePixelRatio()))

    accent = QColor(BaseStyles.color("BORDER_FOCUS"))
    assert border_color() != accent
    button.clearFocus()
    button.setFocus(Qt.FocusReason.TabFocusReason)
    qt_application.processEvents()
    assert button.hasFocus()
    assert border_color() == accent
    assert button.size() == size


@pytest.mark.parametrize("width", [780, 320, 180])
def test_toolbar_separators_follow_visible_rows_without_blocking_buttons(
    compact_remote, qt_application, width,
):
    """竖线仅出现在同行点击面之间，回流成单列时消失且不截获输入。"""
    from gui.panels.remote_panel_controls import RemoteToolbarSeparators

    remote, _scroll, _content = compact_remote
    _show_remote_controller(qt_application, remote, width)
    expected_color = QColor(BaseStyles.color("BORDER_COLOR"))
    for binding in remote.remote_control_bindings:
        buttons = binding.widgets()
        row = buttons[0].parentWidget()
        separators = row.findChild(RemoteToolbarSeparators)
        assert separators is not None
        assert separators.geometry() == row.rect()
        lines = separators.separator_lines()
        occupied_rows = len({button.y() for button in buttons})
        assert len(lines) == len(buttons) - occupied_rows
        image = row.grab().toImage()
        scale = image.devicePixelRatio()
        for line in lines:
            x = round(line.x1() * scale)
            y = round((line.y1() + line.y2()) / 2 * scale)
            assert expected_color in [image.pixelColor(x + offset, y) for offset in (-1, 0, 1)]
            assert not any(button.geometry().contains(line.center().toPoint())
                           for button in buttons)
        for button in buttons:
            assert row.childAt(button.geometry().center()) is button


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
    for label in (remote._mirror_hint, remote._status_label):
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


def test_media_and_volume_buttons_form_one_ordered_toolbar(compact_remote, qt_application):
    remote, _scroll, _content = compact_remote
    _window, _scroll, content = _show_remote_controller(qt_application, remote, 780)
    buttons = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    rectangles = [mapped_rect(buttons[code], content) for code in (
        "VOL_DOWN", "MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT", "VOL_UP",
    )]
    assert len({rect.top() for rect in rectangles}) == 1
    assert all(left.right() < right.left() for left, right in zip(rectangles, rectangles[1:]))


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
    assert remote.maxsize.isVisibleTo(content), "参数在主窗口保持常显"
    _window, _control_scroll, control_content = _show_remote_controller(qt_application, remote, 780)
    assert all(button.isVisibleTo(control_content) for button in remote._remote_control_buttons)
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


def test_swipe_toolbar_pairs_directions_below_primary_navigation(compact_remote, qt_application):
    remote, _scroll, _content = compact_remote
    _window, _scroll, content = _show_remote_controller(qt_application, remote, 780)
    actions = {button.property("remoteAction"): button for button in remote._remote_action_buttons}
    up, down, left, right = (
        mapped_rect(actions[action], content)
        for action in ("swipe_up", "swipe_down", "swipe_left", "swipe_right")
    )
    assert up.top() == down.top() == left.top() == right.top()
    assert up.right() < down.left() < left.left() < right.left()
    navigation = [button for button in remote._remote_key_buttons
                  if button.property("remoteKey") in {"BACK", "HOME", "RECENTS"}]
    assert all(mapped_rect(button, content).bottom() < up.top() for button in navigation)
    assert all(button.accessibleName() for button in actions.values())
    assert all(button.toolTip() for button in actions.values())


@pytest.mark.parametrize("width", (320, 780))
def test_tab_from_mirror_start_visits_settings_without_controller_entry(
    compact_remote, qt_application, width,
):
    remote, scroll, _content = compact_remote
    _resize_feature_viewport(qt_application, remote.panel, remote, scroll, width)
    remote.set_target_devices(["synthetic-device"])
    assert not hasattr(remote, "btn_open_controller")
    remote.btn_start.setFocus(Qt.FocusReason.TabFocusReason)
    assert remote.btn_start.hasFocus()
    visited = []
    for _ in range(48):
        focused = qt_application.focusWidget()
        assert focused is not None
        QTest.keyClick(focused, Qt.Key.Key_Tab)
        if remote.btn_start.hasFocus():
            break
        visited.append(qt_application.focusWidget())
    assert remote.btn_start.hasFocus()
    for control in (remote.maxsize, remote.fps, remote.buffer, remote.orientation,
                    remote.bitrate_slider):
        assert control in visited, "启动和停止之后应继续访问完整设置"
    for switch in remote.window_options_binding.widgets():
        assert switch.indicator in visited


def test_remote_keyboard_order_follows_navigation_controls_and_system_keys(
    compact_remote, qt_application,
):
    remote, _scroll, _content = compact_remote
    remote.set_target_devices(["synthetic-device"])
    _show_remote_controller(qt_application, remote, 780)
    actions = {button.property("remoteAction"): button for button in remote._remote_action_buttons}
    keys = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    order = (
        keys["BACK"], keys["HOME"], keys["RECENTS"], keys["POWER"],
        *(actions[action] for action in (
            "rotate_portrait", "rotate_landscape", "notif_expand", "notif_collapse",
        )),
        *(actions[action] for action in ("swipe_up", "swipe_down", "swipe_left", "swipe_right")),
        *(keys[code] for code in ("MENU", "ENTER", "DEL", "SETTINGS", "CAMERA", "SEARCH")),
        *(keys[code] for code in ("VOL_DOWN", "MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT", "VOL_UP")),
    )
    order[0].setFocus(Qt.FocusReason.TabFocusReason)
    assert order[0].hasFocus()
    for before, after in zip(order, order[1:]):
        QTest.keyClick(before, Qt.Key.Key_Tab)
        assert after.hasFocus(), after.accessibleName()


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
    assert remote.codec.text() == "自动视频编码"
    assert "启动时" in remote.codec.accessibleDescription()
    remote._settings.set("scrcpy_codec", "h265")
    for preset in ("Quality", "Low Latency", "Balanced"):
        remote.preset_selector.items[preset].click()
        assert remote.codec.text() == "自动视频编码"
        assert remote._settings.get("scrcpy_codec") == "h265"


def test_remote_action_groups_keep_equal_heights_and_visible_labels(compact_remote, qt_application):
    remote, _scroll, _content = compact_remote
    _show_remote_controller(qt_application, remote, 780)
    buttons = (remote.btn_start, remote.btn_stop, *remote._remote_control_buttons)
    groups = (
        (remote.btn_start, remote.btn_stop),
        remote._remote_navigation_binding.widgets(),
        remote._remote_screen_binding.widgets(),
        remote._remote_action_binding.widgets(),
        remote._remote_media_binding.widgets(),
        remote._remote_key_binding.widgets(),
    )
    for group in groups:
        heights = [button.height() for button in group]
        assert min(heights) >= 36
        assert max(heights) - min(heights) <= 2, "同组操作应保持一致的按钮高度"
    for button in buttons:
        assert button.text()
        assert button.accessibleName()
        assert button.toolTip()


@pytest.mark.parametrize("width", (780, 1280))
def test_parameters_and_switches_use_four_columns_without_hiding_options(
    compact_remote, qt_application, width,
):
    remote, scroll, content = compact_remote
    _resize_feature_viewport(qt_application, remote.panel, remote, scroll, width)
    assert remote.mirroring_binding.applied_plan.mode.columns == 4
    assert remote.window_options_binding.applied_plan.mode.columns == 4
    fields = remote.mirroring_binding.widgets()
    assert len(fields) == 4
    assert all(field.isVisibleTo(content) for field in fields)
    rectangles = [mapped_rect(field, content) for field in fields]
    assert len({rect.top() for rect in rectangles}) == 1
    assert max(rect.width() for rect in rectangles) - min(rect.width() for rect in rectangles) <= 2
    assert all(left.right() < right.left() for left, right in zip(rectangles, rectangles[1:]))
    bitrate_editor = remote.bitrate_slider.parentWidget()
    bitrate_title = bitrate_editor.title_label
    assert isinstance(bitrate_title, QLabel) and bitrate_title.text()
    assert bitrate_title.width() >= bitrate_title.fontMetrics().horizontalAdvance(
        bitrate_title.text(),
    )
    assert not bitrate_title.wordWrap()
    assert bitrate_title.contentsRect().height() >= bitrate_title.fontMetrics().height()
    assert abs(mapped_rect(bitrate_title, content).center().y()
               - mapped_rect(bitrate_editor.value_label, content).center().y()) <= 1
    switches = remote.window_options_binding.widgets()
    assert len(switches) == 8
    assert all(switch.isVisibleTo(content) for switch in switches)
    for start in (0, 4):
        row = switches[start:start + 4]
        assert len({mapped_rect(switch, content).top() for switch in row}) == 1


def test_record_only_and_save_recording_stay_consistent(compact_remote):
    remote, _scroll, _content = compact_remote
    remote.set_target_devices(["synthetic-device"])
    remote.chk_noplayback.setChecked(True)
    assert remote.chk_record.isChecked()
    assert remote._mirror_hint.text() == "仅录制，不打开镜像窗口"
    remote.chk_record.setChecked(False)
    assert not remote.chk_noplayback.isChecked()
    assert remote._mirror_hint.text() == "每台设备将在独立窗口打开镜像"


def test_record_only_without_target_preserves_device_selection_hint(compact_remote):
    remote, _scroll, _content = compact_remote
    remote.set_target_devices([])
    remote.chk_noplayback.setChecked(True)
    assert remote.chk_record.isChecked()
    assert remote._mirror_hint.text() == "请选择操作设备，可同时启动多台"
    remote.set_target_devices(["synthetic-device"])
    assert remote._mirror_hint.text() == "仅录制，不打开镜像窗口"


def test_compact_remote_groups_keep_semantic_order_and_separate_click_targets(
    compact_remote, qt_application,
):
    remote, _scroll, _content = compact_remote
    _window, _scroll, content = _show_remote_controller(qt_application, remote, 780)
    by_key = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    by_action = {
        button.property("remoteAction"): button for button in remote._remote_action_buttons
    }
    gesture_rects = [mapped_rect(by_action[action], content) for action in (
        "swipe_up", "swipe_down", "swipe_left", "swipe_right",
    )]
    system_rects = [mapped_rect(by_key[key], content) for key in (
        "MENU", "ENTER", "DEL", "SETTINGS", "CAMERA", "SEARCH",
    )]
    # 合并工具栏按阅读顺序排列，回流后系统按键可接在手势末尾或下一行。
    command_rects = (*gesture_rects, *system_rects)
    positions = [(rect.top(), rect.left()) for rect in command_rects]
    assert positions == sorted(positions)
    assert len({rect.top() for rect in gesture_rects}) == 1
    assert_non_overlapping(tuple(by_action[action] for action in (
        "swipe_up", "swipe_down", "swipe_left", "swipe_right",
    )) + tuple(by_key[key] for key in (
        "MENU", "ENTER", "DEL", "SETTINGS", "CAMERA", "SEARCH",
    )), content)
    previous, play, following = (
        mapped_rect(by_key[code], content) for code in ("MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT")
    )
    assert previous.right() < play.left() < play.right() < following.left()
    for button in (*by_key.values(), *by_action.values()):
        assert button.height() >= button.minimumSizeHint().height()


@pytest.mark.parametrize("font_size", (12, 22))
def test_remote_scroll_ends_at_media_and_tall_viewport_preserves_content_height(
    qt_application, monkeypatch, isolated_app_settings, font_size,
):
    panel, remote, scroll, content = _show_feature_panel(
        "remote", 780, font_size, qt_application, monkeypatch,
    )
    remote._settings = isolated_app_settings
    try:
        _window, scroll, content = _show_remote_controller(qt_application, remote, 780)
        snapshots = {}
        sections = (content.headerView, remote._remote_bottom_sections[0],
                    remote._form_controller._media_section)
        buttons = tuple(remote._remote_control_buttons)

        def resize_viewport(width, height):
            _resize_remote_controller(qt_application, remote, width, height=height)
            wait_for_stable_geometry(qt_application, (scroll, content, *sections, *buttons))
            assert scroll.viewport().height() == height

        for width in (780, 320, 1280, 780):
            # 工具窗仅保留操作区，使用更短视口继续实际覆盖滚动末端。
            resize_viewport(width, 150)
            bar = scroll.verticalScrollBar()
            assert bar.maximum() > 0, "短视口必须实际验证纵向滚动末端"
            assert all(button.isVisibleTo(content) for button in buttons)
            last_bottom = max(mapped_rect(button, content).bottom() for button in buttons)
            media_bottom = max(
                mapped_rect(button, content).bottom() for button in remote._remote_media_buttons
            )
            assert last_bottom == media_bottom, "音量与媒体应当是最后一组操作"
            # 末端仅允许正常分区边距，不能额外滚入空白区域。
            trailing_margin = bar.maximum() + scroll.viewport().height() - last_bottom - 1
            assert 0 <= trailing_margin <= 24, (width, font_size, trailing_margin)
            bar.setValue(bar.maximum())
            qt_application.processEvents()
            geometry = tuple(mapped_rect(widget, content).getRect()
                             for widget in (*sections, *buttons))
            if width in snapshots:
                assert geometry == snapshots[width], "宽窄往返不能保留旧高度占位"
            snapshots[width] = geometry

            resize_viewport(width, max(2000, content.height() + 400))
            assert bar.maximum() == 0, "高视口应完整容纳当前内容"
            assert tuple(mapped_rect(widget, content).getRect()
                         for widget in (*sections, *buttons)) == geometry, (
                "视口富余高度不能拉高分区或下推最后操作按钮"
            )
            assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        _close_feature_panel(panel)
