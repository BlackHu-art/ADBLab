"""验证远程控制单页的统一设置区、响应式重排和共享外观契约。"""

from collections import Counter
from concurrent.futures import Future

import pytest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    Pivot,
    Slider,
    SwitchButton,
    TransparentPushButton,
    themeColor,
)

from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _resize_remote_controller,
    _show_feature_panel,
    _show_remote_controller,
)
from tests.ui_geometry_helpers import (
    assert_non_overlapping,
    assert_positive_geometry,
    assert_scroll_target_reachable,
    mapped_rect,
    wait_for_stable_geometry,
    wait_until,
)

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("theme", ("Dark", "Light"))
@pytest.mark.parametrize("enabled", (True, False))
def test_command_button_text_uses_theme_colors_instead_of_stale_palette(
    remote_layout, qt_application, theme, enabled,
):
    from PySide6.QtGui import QColor, QFont, QPalette

    from gui.panels.remote_panel_controls import RemoteCommandButton

    _panel, remote, _scroll, _content, _settings = remote_layout
    _show_remote_controller(qt_application, remote, 1280)
    button = remote._remote_primary_key_buttons[0]
    assert isinstance(button, RemoteCommandButton)
    button.setText("MMMM")
    try:
        BaseStyles.switch_theme(theme)
        button.setFont(QFont("Arial", 22))
        button.resize(160, 100)
        palette = button.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Disabled):
            palette.setColor(group, QPalette.ColorRole.ButtonText, QColor("magenta"))
        button.setPalette(palette)
        button.setEnabled(enabled)
        button.show()
        qt_application.processEvents()
        painted = button.grab().toImage()
        expected = QColor(BaseStyles.color("TEXT_PRIMARY" if enabled else "TEXT_DISABLED"))
        colors = {painted.pixelColor(x, y).name()
                  for y in range(painted.height() // 2, painted.height())
                  for x in range(painted.width())}
        assert expected.name() in colors
        assert QColor("magenta").name() not in colors
    finally:
        button.setText("返回")


def test_invalid_saved_custom_parameters_keep_legal_control_values(
    qt_application, monkeypatch, isolated_app_settings,
):
    from gui.panels.remote_panel import RemotePanel

    monkeypatch.setattr(
        RemotePanel, "_load", lambda self, key: "Custom" if key == "preset" else "123",
    )
    panel, remote, _scroll, _content = _show_feature_panel(
        "remote", 780, 12, qt_application, monkeypatch,
    )
    try:
        assert remote.preset.currentIndex() == -1
        for name in ("maxsize", "fps", "buffer", "bitrate", "orientation"):
            combo = getattr(remote, name)
            assert combo.currentIndex() >= 0, name
            assert combo.currentData() == combo.itemData(0), name
        assert remote.bitrate_slider.toolTip() == f"{remote.bitrate.currentData()} Mbps"
    finally:
        _close_feature_panel(panel)

_OPTION_NAMES = (
    "chk_record", "chk_fullscreen", "chk_aot", "chk_showtouches", "chk_stayawake",
    "chk_turnscreenoff", "chk_noplayback", "chk_noaudio",
)


def expand_remote_options(remote, content, qt_application):
    """兼容既有测试入口，并验证高级参数和更多选项无需操作即可访问。"""
    for container, controls in (
        (remote.advanced_options,
         (remote.codec, remote.buffer, remote.orientation)),
        (remote.more_options,
         (remote.chk_turnscreenoff, remote.chk_noplayback)),
    ):
        wait_for_stable_geometry(qt_application, (container, *controls))
        assert container.isVisibleTo(content)
        assert all(control.isVisibleTo(content) for control in controls)


@pytest.fixture
def remote_layout(qt_application, monkeypatch, isolated_app_settings):
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family="Arial", ui_size=12,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    panel, remote, scroll, content = _show_feature_panel(
        "remote", 1280, 12, qt_application, monkeypatch,
        patch_font_factory=False,
    )
    remote._settings = isolated_app_settings
    try:
        yield panel, remote, scroll, content, isolated_app_settings
    finally:
        _close_feature_panel(panel)


def test_wide_remote_page_keeps_session_above_settings_and_controls_in_separate_window(
    remote_layout, qt_application,
):
    _panel, remote, _scroll, content, _settings = remote_layout
    _window, _controller_scroll, controller_content = _show_remote_controller(
        qt_application, remote, 1280,
    )
    (mirroring,) = remote._remote_section_groups
    session = content.findChild(QWidget, "remoteMirrorSession")
    session_rect, setting_rect = mapped_rect(session, content), mapped_rect(mirroring, content)

    assert session_rect.bottom() < setting_rect.top(), "紧凑会话操作必须位于统一设置区上方"
    assert not hasattr(remote, "btn_open_controller")
    assert abs(session_rect.left() - setting_rect.left()) <= 2
    assert abs(session_rect.width() - setting_rect.width()) <= 2
    system, recording = remote._remote_bottom_sections
    assert controller_content.isAncestorOf(system)
    assert mirroring.isAncestorOf(recording)
    assert not recording.headerView.isVisibleTo(content), "合并后的开关区不重复显示标题"
    for button in remote._remote_control_buttons:
        assert controller_content.isAncestorOf(button)
        assert not content.isAncestorOf(button)
    assert remote.advanced_options.isVisibleTo(content)
    assert remote.more_options.isVisibleTo(content)
    assert isinstance(remote.preset_selector, Pivot)
    assert remote.fps.isVisibleTo(content)
    assert not remote.fps_selector.isVisibleTo(content)
    assert isinstance(remote.bitrate_slider, Slider)
    for selector in (remote.preset_selector,):
        for item in selector.items.values():
            assert item.font().pointSize() == 12
            assert item.height() >= item.fontMetrics().height()
            assert item.width() >= item.fontMetrics().horizontalAdvance(item.text())
    for widget in (
        remote.preset_selector, remote.fps, remote.bitrate_slider,
        remote.maxsize, remote.codec, remote.buffer, remote.orientation,
        *(getattr(remote, name) for name in _OPTION_NAMES),
    ):
        assert widget.isVisibleTo(content)
        assert_positive_geometry(widget, content)
    for button in remote._remote_control_buttons:
        assert button.isVisibleTo(controller_content)
        assert_positive_geometry(button, controller_content)


def test_session_summary_stays_above_settings_through_resizing(
    remote_layout, qt_application,
):
    panel, remote, scroll, content, _settings = remote_layout
    session = content.findChild(QWidget, "remoteMirrorSession")
    assert session is not None
    for width in (780, 420, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        (settings,) = (mapped_rect(section, content)
                       for section in remote._remote_section_groups)
        top = mapped_rect(session, content)
        assert top.bottom() < settings.top() < settings.bottom()
        assert top.left() <= settings.left()
        assert top.right() >= settings.right()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert abs(top.left() - settings.left()) <= 2
        assert abs(top.width() - settings.width()) <= 2
        for control in (remote.btn_start, remote.btn_stop, remote._mirror_hint):
            assert session.isAncestorOf(control)
            assert_scroll_target_reachable(scroll, control)


def test_unified_settings_keep_options_expanded_and_queue_in_control_header(
    remote_layout, qt_application,
):
    panel, remote, scroll, content, _settings = remote_layout
    _window, _controller_scroll, controller_content = _show_remote_controller(
        qt_application, remote, 1280,
    )
    for width in (1280, 320, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        _resize_remote_controller(qt_application, remote, width)
        (mirroring,) = remote._remote_section_groups
        _system, recording = remote._remote_bottom_sections
        assert mirroring.isAncestorOf(recording)
        assert not recording.headerView.isVisibleTo(content)
        assert recording.separator.isVisibleTo(content)
        separator = mapped_rect(recording.separator, content)
        assert mapped_rect(remote.codec, content).bottom() < separator.top()
        for name in _OPTION_NAMES:
            option = getattr(remote, name)
            assert option.isVisibleTo(content)
            assert separator.bottom() < mapped_rect(option, content).top()
            assert_scroll_target_reachable(scroll, option)
        assert controller_content.headerView.isAncestorOf(remote._remote_queue_label)
        assert remote._remote_queue_label.isVisibleTo(controller_content)
        assert remote._remote_queue_label.width() >= (
            remote._remote_queue_label.fontMetrics().horizontalAdvance(
                remote._remote_queue_label.text(),
            )
        )
        assert controller_content.headerLabel.isHidden()
        assert not hasattr(remote, "btn_open_controller")
        assert scroll.horizontalScrollBar().maximum() == 0


def test_hidden_control_titles_and_queue_survive_runtime_font_changes(
    remote_layout, qt_application,
):
    panel, remote, scroll, content, _settings = remote_layout
    _window, _controller_scroll, controller_content = _show_remote_controller(
        qt_application, remote, 1280,
    )
    current = BaseStyles.current_font_config()
    for size in (12, 22, 12):
        config = FontConfig(
            ui_family="Segoe UI", ui_size=size,
            log_size=current.log_size, mono_family=current.mono_family,
        )
        BaseStyles._sync_legacy_values(config)
        typography_manager.apply(config)
        _resize_feature_viewport(qt_application, panel, remote, scroll, 1280)
        _resize_remote_controller(qt_application, remote, 1280)
        (mirroring,) = remote._remote_section_groups
        assert remote.btn_start.isVisibleTo(content)
        assert remote.btn_start.font().pointSize() == size
        assert not mirroring.headerLabel.isVisibleTo(content)
        assert not controller_content.headerLabel.isVisibleTo(controller_content)
        label = remote._remote_queue_label
        assert label.isVisibleTo(controller_content)
        assert label.font().family() == "Segoe UI"
        assert label.font().pointSize() == size
        assert label.height() >= label.fontMetrics().height()


def test_parameter_selectors_save_stable_values_and_custom_clears_preset(remote_layout):
    _panel, remote, _scroll, _content, settings = remote_layout
    remote.preset_selector.items["Quality"].click()
    assert remote.preset.currentData() == "Quality"
    assert (remote.maxsize.currentData(), remote.fps.currentData()) == (
        "1920", "60",
    )
    assert remote.codec.text()
    assert settings.get("scrcpy_codec") == "h264"
    assert remote.fps_selector.currentRouteKey() == "60"
    assert remote.bitrate_slider.value() == 4
    assert settings.get("scrcpy_preset") == "Quality"

    remote.fps.setCurrentIndex(remote.fps.findData("120"))
    assert remote.fps.currentData() == "120"
    assert settings.get("scrcpy_fps") == "120"
    assert settings.get("scrcpy_preset") == "Custom"
    assert remote.preset.currentIndex() == -1
    assert not any(item.isSelected for item in remote.preset_selector.items.values())
    assert not remote.preset_selector.currentRouteKey()
    assert remote.preset_selector.currentItem() is None

    remote.preset_selector.items["Quality"].click()
    assert remote.preset.currentData() == "Quality"
    assert remote.fps.currentData() == "60"
    assert settings.get("scrcpy_preset") == "Quality"

    remote.preset_selector.items["Smooth"].click()
    assert remote.fps.currentData() == "30"
    assert remote.fps_selector.currentRouteKey() == "30"
    assert remote.bitrate_slider.value() == 1
    assert settings.get("scrcpy_preset") == "Smooth"
    remote.maxsize.setCurrentIndex(remote.maxsize.findData("Default"))
    assert settings.get("scrcpy_preset") == "Custom"
    assert not any(item.isSelected for item in remote.preset_selector.items.values())
    assert remote.preset_selector.currentItem() is None


def test_buffer_and_orientation_labels_preserve_command_and_saved_values(remote_layout):
    _panel, remote, _scroll, _content, settings = remote_layout
    remote.buffer.setCurrentIndex(remote.buffer.findData("100"))
    remote.orientation.setCurrentIndex(remote.orientation.findData("90"))
    assert remote.buffer.currentText() == "100"
    assert remote.orientation.currentText() == "90"
    assert settings.get("scrcpy_buffer") == "100"
    assert settings.get("scrcpy_orientation") == "90"
    remote.orientation.setCurrentIndex(remote.orientation.findData("0"))
    assert remote.orientation.currentText() == "自动"
    assert settings.get("scrcpy_orientation") == "0"
    from PySide6.QtWidgets import QLabel

    units = [label for label in remote.orientation.parentWidget().findChildren(QLabel)
             if label.text() == "°"]
    assert len(units) == 1 and units[0].isHidden()
    remote.orientation.setCurrentIndex(remote.orientation.findData("90"))
    assert not units[0].isHidden()
    remote.maxsize.setCurrentIndex(remote.maxsize.findData("Default"))
    pixel_unit = next(label for label in remote.maxsize.parentWidget().findChildren(QLabel)
                      if label.text() == "px")
    assert pixel_unit.isHidden()


@pytest.mark.parametrize("preset,expected", [
    ("Smooth", ("1024", "30", "4", "50")),
    ("Balanced", ("1280", "30", "8", "20")),
    ("Quality", ("1920", "60", "12", "50")),
    ("Low Latency", ("720p", "24", "2", "0")),
])
def test_each_preset_updates_fields_saved_values_and_launch_arguments(
    remote_layout, monkeypatch, preset, expected,
):
    from services.remote import ScrcpyService
    from services.remote.scrcpy_args import build_scrcpy_args

    _panel, remote, _scroll, _content, settings = remote_layout
    monkeypatch.setattr(ScrcpyService, "require_client", lambda _path: "adb")
    monkeypatch.setattr(remote._input_engine, "window_title", lambda _device: "")
    remote.preset_selector.items["Quality" if preset != "Quality" else "Smooth"].click()
    remote.preset_selector.items[preset].click()
    keys = ("maxsize", "fps", "bitrate", "buffer")
    assert tuple(getattr(remote, key).currentData() for key in keys) == expected
    assert tuple(settings.get(f"scrcpy_{key}") for key in keys) == expected
    assert settings.get("scrcpy_preset") == preset
    config = remote._scrcpy_config("scrcpy", "synthetic-device")
    assert tuple(getattr(config, key) for key in keys) == expected
    args = build_scrcpy_args(config)
    assert args[args.index("-m") + 1] == expected[0].replace("p", "")
    assert args[args.index("--max-fps") + 1] == expected[1]
    assert f"--video-bit-rate={expected[2]}M" in args
    if expected[3] == "0":
        assert not any(arg.startswith("--video-buffer=") for arg in args)
    else:
        assert f"--video-buffer={expected[3]}" in args


def test_remote_controls_keep_semantic_pairs_and_media_transport_order(
    remote_layout, qt_application,
):
    _panel, remote, _scroll, _content, _settings = remote_layout
    _window, _scroll, content = _show_remote_controller(qt_application, remote, 1280)
    groups = (
        (remote._remote_navigation_binding, ("BACK", "HOME", "RECENTS", "POWER")),
        (remote._remote_key_binding, ("MENU", "ENTER", "DEL", "SETTINGS", "CAMERA", "SEARCH")),
        (remote._remote_media_binding, (
            "VOL_DOWN", "MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT", "VOL_UP",
        )),
    )
    for binding, codes in groups:
        from PySide6.QtWidgets import QAbstractButton

        buttons = [button for widget in binding.widgets()
                   for button in (widget, *widget.findChildren(QAbstractButton))
                   if button.property("remoteKey")]
        assert tuple(button.property("remoteKey") for button in buttons) == codes
    actions = remote._remote_action_buttons
    assert tuple(button.property("remoteAction") for button in actions) == (
        "swipe_up", "swipe_down", "swipe_left", "swipe_right",
        "notif_expand", "notif_collapse", "rotate_portrait", "rotate_landscape",
    )
    assert remote._remote_action_binding.applied_plan.mode.columns == 10
    by_code = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    assert by_code["ENTER"].text() == "回车"
    assert by_code["DEL"].text() == "退格"
    assert by_code["MEDIA_PLAY"].accessibleName() == "播放/暂停"
    assert by_code["POWER"] in remote._remote_navigation_binding.widgets()
    assert mapped_rect(by_code["POWER"], content).top() == mapped_rect(
        by_code["BACK"], content,
    ).top()
    screen = tuple(button for button in remote._remote_screen_binding.widgets()
                   if button.property("remoteAction"))
    navigation = tuple(button for button in remote._remote_navigation_binding.widgets()
                       if button.property("remoteKey"))
    assert tuple(button.property("remoteAction") for button in screen) == (
        "rotate_portrait", "rotate_landscape", "notif_expand", "notif_collapse",
    )
    top_rows = [mapped_rect(button, content) for button in (*navigation, *screen)]
    assert max(rect.top() for rect in top_rows) - min(rect.top() for rect in top_rows) <= 2
    assert max(rect.bottom() for rect in top_rows) < min(
        mapped_rect(button, content).top() for button in remote._remote_action_binding.widgets()
    )
    gestures = [mapped_rect(button, content)
                for button in remote._remote_action_binding.widgets()
                if button.property("remoteAction")]
    system = [mapped_rect(button, content) for button in remote._remote_key_binding.widgets()
              if button.property("remoteKey")]
    assert max(rect.right() for rect in gestures) < min(rect.left() for rect in system)
    assert abs(gestures[0].top() - system[0].top()) <= 2
    media = remote._remote_media_binding.widgets()
    assert tuple(button.text() for button in media) == (
        "音量 −", "上一个", "播放/暂停", "下一个", "音量 +",
    )
    assert max(button.width() for button in media) - min(button.width() for button in media) <= 2
    media_rects = [mapped_rect(button, content) for button in media]
    assert media_rects[0].left() == mapped_rect(media[0].parentWidget(), content).left()
    assert all(0 < after.left() - before.right() - 1 <= 8
               for before, after in zip(media_rects, media_rects[1:]))
    assert min(mapped_rect(button, content).top() for button in media) > max(
        rect.bottom() for rect in gestures
    )
    assert all(button.iconSize().width() >= 16 for button in remote._remote_control_buttons)


def test_default_preset_is_selected_before_user_interaction(remote_layout):
    _panel, remote, _scroll, _content, _settings = remote_layout
    assert remote.preset.currentData() == "Smooth"
    assert remote.preset_selector.currentRouteKey() == "Smooth"
    assert remote.preset_selector.items["Smooth"].isSelected
    assert tuple(getattr(remote, key).currentData() for key in (
        "maxsize", "fps", "bitrate", "buffer",
    )) == ("1024", "30", "4", "50")


@pytest.mark.parametrize("width,font_size", ((1280, 12), (292, 22)))
def test_mirror_toolbar_keeps_height_across_selection_and_session_states(
    remote_layout, qt_application, width, font_size,
):
    panel, remote, scroll, content, _settings = remote_layout
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family="Arial", ui_size=font_size,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    _resize_feature_viewport(qt_application, panel, remote, scroll, width)
    toolbar = content.findChild(type(remote._session_list.parentWidget()), "remoteMirrorSession")
    assert toolbar is not None
    wait_for_stable_geometry(qt_application, toolbar)
    height = toolbar.height()
    watched = (remote.btn_start, remote.btn_stop, remote.preset_selector, remote.fps,
               remote.bitrate_slider, remote.more_options)
    geometry = tuple(mapped_rect(widget, content).getRect() for widget in watched)
    from tests.test_remote_first_frame import _VisiblePaintGeometry

    probe = _VisiblePaintGeometry(content, watched)
    for state in (remote._SESSION_IDLE, remote._SESSION_STARTING, remote._SESSION_RUNNING,
                  remote._SESSION_STOPPING, remote._SESSION_IDLE):
        remote._set_session_state(state)
        wait_for_stable_geometry(qt_application, toolbar)
        assert toolbar.height() == height
        assert tuple(mapped_rect(widget, content).getRect() for widget in watched) == geometry
        assert remote._session_list.isHidden()
        assert remote._mirror_device_label.isHidden()
        assert remote.btn_start.text() == "选择设备"
        assert remote.btn_stop.text() == (
            "正在停止…" if state == remote._SESSION_STOPPING else "停止全部"
        )
    assert probe.samples
    assert all(sample == geometry for sample in probe.samples)
    remote._session_state = remote._SESSION_IDLE
    remote._last_mirror_status = "Error"
    remote._refresh_mirror_presentation()
    wait_for_stable_geometry(qt_application, toolbar)
    if width == 1280:
        assert toolbar.height() == height
    else:
        assert toolbar.height() >= height
        assert remote.btn_mirror_diagnostics.isVisibleTo(content)
        assert_scroll_target_reachable(scroll, remote.btn_mirror_diagnostics)
        assert remote._mirror_hint.height() >= remote._mirror_hint.heightForWidth(
            remote._mirror_hint.width(),
        )
        assert_scroll_target_reachable(scroll, remote._mirror_hint)
    assert "重试" in remote._status_label.toolTip()


@pytest.mark.parametrize("theme", ("Dark", "Light"))
def test_preset_selection_fills_button_with_theme_accent(
    remote_layout, qt_application, theme,
):
    from PySide6.QtCore import QAbstractAnimation

    _panel, remote, _scroll, _content, _settings = remote_layout
    BaseStyles.switch_theme(theme)
    pivot = remote.preset_selector
    for preset in ("Balanced", "Quality", "Low Latency", "Smooth"):
        pivot.items[preset].click()
        wait_until(qt_application, lambda: pivot.slideAni.currentAni.state() == (
            QAbstractAnimation.State.Stopped
        ))
        selected = pivot.items[preset]
        selected.setFocus()
        qt_application.processEvents()
        unselected = next(item for item in pivot.items.values() if not item.isSelected)
        selected_image, unselected_image = selected.grab().toImage(), unselected.grab().toImage()
        scale = selected_image.devicePixelRatio()
        sample = (round(8 * scale), round(4 * scale))
        assert selected_image.pixelColor(*sample).name() == themeColor().name()
        assert selected_image.pixelColor(*sample) != unselected_image.pixelColor(*sample)
        assert selected.isSelected
        assert sum(item.isSelected for item in pivot.items.values()) == 1


@pytest.mark.parametrize("theme", ("Light", "Dark"))
@pytest.mark.parametrize("accent,foreground", (("#003366", "#ffffff"), ("#ffee66", "#000000")))
def test_selected_preset_keeps_contrast_through_mouse_states(
    remote_layout, qt_application, theme, accent, foreground,
):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    _panel, remote, _scroll, _content, _settings = remote_layout
    BaseStyles.switch_theme(theme)
    BaseStyles.set_accent_color(accent)
    if theme == "Dark" and accent == "#003366":
        # Fluent 在深色主题提亮强调色，实际底板为亮蓝色，黑字对比度更高。
        foreground = "#000000"
    item = remote.preset_selector.items["Smooth"]
    item.setText("MMMM")
    before = item.geometry()
    QTest.mouseMove(item, QPoint(item.width() // 2, item.height() // 2))
    for pressed in (False, True):
        if pressed:
            QTest.mousePress(item, Qt.MouseButton.LeftButton)
        qt_application.processEvents()
        painted = item.grab().toImage()
        colors = {painted.pixelColor(x, y).name()
                  for y in range(3, painted.height() - 3)
                  for x in range(3, painted.width() - 3)}
        assert foreground in colors
        assert item.geometry() == before
    QTest.mouseRelease(item, Qt.MouseButton.LeftButton)
    item.setEnabled(False)
    qt_application.processEvents()
    painted = item.grab().toImage()
    assert painted.pixelColor(8, 4).name() == BaseStyles.color("BUTTON_BG").lower()


@pytest.mark.parametrize("width,font_size", ((292, 22), (640, 12)))
def test_session_hint_reserves_full_text_height_without_state_jumps(
    qt_application, width, font_size,
):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont

    from gui.panels.remote_panel_controls import RemoteSessionHint

    texts = ("准备", "正在准备服务；可取消启动，已打开的镜像也将停止", "未能建立镜像连接，请重试。")
    hint = RemoteSessionHint(texts[0], texts)
    try:
        hint.setFont(QFont("Microsoft YaHei", font_size))
        hint.resize(width, 36)
        hint.show()
        hint.refresh_height()
        qt_application.processEvents()
        height = hint.height()
        for text in texts:
            hint.setText(text)
            qt_application.processEvents()
            required = hint.fontMetrics().boundingRect(
                0, 0, width, 10000, Qt.TextFlag.TextWordWrap, text,
            ).height()
            assert hint.height() >= required
            assert hint.height() == height
    finally:
        hint.close()
        hint.deleteLater()


def test_preset_focus_tracks_keyboard_without_changing_geometry(remote_layout, qt_application):
    from PySide6.QtCore import Qt

    _panel, remote, _scroll, _content, _settings = remote_layout
    item = remote.preset_selector.items["Smooth"]
    before = item.geometry()
    item.clearFocus()
    item.setFocus(Qt.FocusReason.TabFocusReason)
    qt_application.processEvents()
    assert item.property("adblabKeyboardFocus") is True
    assert item.geometry() == before
    item.clearFocus()
    item.setFocus(Qt.FocusReason.MouseFocusReason)
    qt_application.processEvents()
    assert item.property("adblabKeyboardFocus") is False
    assert item.geometry() == before


def test_parameter_labels_stay_above_controls_and_units_follow_them(remote_layout):
    from PySide6.QtWidgets import QLabel

    _panel, remote, _scroll, content, _settings = remote_layout
    for control, caption, unit in (
        (remote.maxsize, "画面尺寸", "px"), (remote.fps, "帧率", "FPS"),
        (remote.buffer, "视频缓冲", "ms"), (remote.orientation, "画面方向", None),
    ):
        label = next(label for label in remote._parameter_labels if label.text() == caption)
        assert mapped_rect(label, content).bottom() < mapped_rect(control, content).top()
        assert abs(mapped_rect(label, content).left() - mapped_rect(control, content).left()) <= 2
        if unit:
            suffix = next(label for label in label.parentWidget().findChildren(QLabel)
                          if label.text() == unit)
            assert mapped_rect(control, content).right() < mapped_rect(suffix, content).left()


def test_bitrate_and_codec_share_three_to_one_row_below_parameters(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    editor = remote.bitrate_slider.parentWidget()
    editor_rect, codec_rect = mapped_rect(editor, content), mapped_rect(remote.codec, content)
    assert editor_rect.top() > max(mapped_rect(field, content).bottom()
                                   for field in remote.mirroring_binding.widgets())
    assert editor_rect.right() < codec_rect.left()
    assert abs(editor_rect.center().y() - codec_rect.center().y()) <= 2
    assert abs(editor.width() - 3 * remote.codec.width()) <= 4


def test_window_options_form_left_aligned_four_column_grid_with_leading_switches(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    controls = (
        remote.chk_aot, remote.chk_fullscreen, remote.chk_showtouches, remote.chk_stayawake,
        remote.chk_turnscreenoff, remote.chk_noaudio, remote.chk_record, remote.chk_noplayback,
    )
    assert remote.window_options_binding.widgets() == controls
    assert remote.window_options_binding.applied_plan.mode.columns == 4
    rectangles = [mapped_rect(control, content) for control in controls]
    for start in range(0, len(rectangles), 4):
        row = rectangles[start:start + 4]
        assert max(rect.top() for rect in row) - min(rect.top() for rect in row) <= 2
    for first, second in zip(rectangles[:4], rectangles[4:]):
        assert abs(first.left() - second.left()) <= 2
        assert first.bottom() < second.top()
    for control in controls:
        indicator = mapped_rect(control.indicator, content)
        label = mapped_rect(control.label, content)
        assert indicator.right() < label.left()
        assert abs(indicator.left() - mapped_rect(control, content).left()) <= 2


def test_bitrate_slider_and_legacy_combo_keep_each_others_value(remote_layout):
    _panel, remote, _scroll, _content, settings = remote_layout
    remote.bitrate_slider.setValue(5)
    assert remote.bitrate.currentData() == "16"
    assert settings.get("scrcpy_bitrate") == "16"
    assert settings.get("scrcpy_preset") == "Custom"
    remote.bitrate.setCurrentIndex(remote.bitrate.findData("24"))
    assert remote.bitrate_slider.value() == 6
    assert settings.get("scrcpy_bitrate") == "24"

    settings.set("scrcpy_preset", "Custom")
    settings.set("scrcpy_fps", "30")
    settings.set("scrcpy_bitrate", "32")
    assert remote.reload_from_settings()
    assert remote.bitrate_slider.value() == 7
    assert remote.fps_selector.currentRouteKey() == "30"
    assert not any(item.isSelected for item in remote.preset_selector.items.values())


def test_bitrate_preset_moves_handle_with_value_without_resizing(remote_layout, qt_application):
    _panel, remote, _scroll, _content, settings = remote_layout
    slider = remote.bitrate_slider
    track_width = slider.width()
    for preset in ("Balanced", "Quality", "Smooth", "Low Latency"):
        remote.preset_selector.items[preset].click()
        position = slider.handle.x() / slider.grooveLength
        expected = slider.value() / slider.maximum()
        assert abs(position - expected) <= 1 / slider.grooveLength
        assert slider.toolTip() == f"{remote.bitrate.currentData()} Mbps"
        assert settings.get("scrcpy_preset") == preset
        wait_for_stable_geometry(qt_application, slider)
        assert slider.width() == track_width
        painted = slider.grab().toImage()
        scale = painted.devicePixelRatio()
        sample_x = slider.handle.width() / 2 + slider.handle.x() / 2
        sample_y = slider.handle.height() / 2
        assert painted.pixelColor(round(sample_x * scale), round(sample_y * scale)).name() == (
            themeColor().name()
        )
    remote.bitrate.setCurrentIndex(remote.bitrate.count() - 1)
    assert slider.handle.x() == slider.grooveLength


@pytest.mark.parametrize("font_size", (12, 22))
def test_bitrate_readout_keeps_one_line_for_every_value(
    remote_layout, qt_application, font_size,
):
    panel, remote, scroll, content, _settings = remote_layout
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family="Arial", ui_size=font_size,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    _resize_feature_viewport(qt_application, panel, remote, scroll, 1280)
    editor = remote.bitrate_slider.parentWidget()
    label = editor.value_label
    wait_for_stable_geometry(qt_application, (editor, slider := remote.bitrate_slider, label))
    handle_center = slider.mapTo(editor, slider.handle.geometry().center()).y()
    assert abs(handle_center - label.geometry().center().y()) <= 1
    assert abs(handle_center - editor.title_label.geometry().center().y()) <= 1
    remote.bitrate.setCurrentIndex(0)
    wait_for_stable_geometry(qt_application, (editor, label, remote.btn_start))
    single_line_height = label.sizeHint().height()
    positions = (mapped_rect(editor, content), mapped_rect(remote.btn_start, content))
    for index in range(remote.bitrate.count()):
        remote.bitrate.setCurrentIndex(index)
        wait_for_stable_geometry(qt_application, (editor, label, remote.btn_start))
        assert label.text() == f"{remote.bitrate.currentData()} Mbps"
        assert label.sizeHint().height() == single_line_height
        assert label.contentsRect().width() >= label.fontMetrics().horizontalAdvance(label.text())
        assert (mapped_rect(editor, content), mapped_rect(remote.btn_start, content)) == positions


@pytest.mark.parametrize("selector_name", ("preset_selector", "fps"))
def test_parameter_focus_and_selection_keep_option_geometry(
    remote_layout, qt_application, selector_name,
):
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    _panel, remote, _scroll, content, _settings = remote_layout
    selector = getattr(remote, selector_name)
    is_preset = selector_name == "preset_selector"
    items = tuple(selector.items.values()) if is_preset else (selector,)
    for item in items:
        item.clearFocus()
    wait_for_stable_geometry(qt_application, (selector, *items))
    before = tuple((item.geometry(), item.sizeHint()) for item in items)
    watched = (remote.preset_selector, remote.maxsize, remote.fps, remote.btn_start)
    positions = tuple(mapped_rect(widget, content) for widget in watched)
    samples = []

    class PaintProbe(QObject):
        def eventFilter(self, widget, event):
            if event.type() == QEvent.Type.Paint and widget.isVisibleTo(content):
                samples.append(tuple(mapped_rect(target, content) for target in watched))
            return False

    probe = PaintProbe(selector)
    for widget in watched:
        widget.installEventFilter(probe)
    # 连续切换后再返回，覆盖焦点边框与布局防抖在中间帧产生的来回抖动。
    if is_preset:
        for item in (*items, items[1], items[0]):
            item.setFocus(Qt.FocusReason.MouseFocusReason)
            QTest.mouseClick(item, Qt.MouseButton.LeftButton)
            QTest.qWait(selector.slideAni.currentAni.duration() + 60)
            assert tuple((item.geometry(), item.sizeHint()) for item in items) == before
    else:
        assert selector.isVisibleTo(content)
        assert not remote.fps_selector.isVisibleTo(content)
        selector.setFocus(Qt.FocusReason.TabFocusReason)
        assert selector.hasFocus()
        QTest.qWait(100)
        assert tuple((item.geometry(), item.sizeHint()) for item in items) == before
        for index in (*range(selector.count()), 1, 0):
            selector.setCurrentIndex(index)
            QTest.qWait(100)
            assert selector.geometry() == before[0][0]
            assert selector.sizeHint().height() == before[0][1].height()
            assert selector.width() >= selector.sizeHint().width()
            option = QStyleOptionButton()
            selector.initStyleOption(option)
            text_rect = selector.style().subElementRect(
                QStyle.SubElement.SE_PushButtonContents, option, selector,
            )
            text_width = selector.fontMetrics().horizontalAdvance(selector.currentText())
            assert text_rect.width() >= text_width
            # 安装版 Fluent ComboBox 的箭头绘制在右侧 22px 处，文本必须保持间隔。
            assert text_rect.left() + text_width < selector.width() - 22
    assert samples
    assert all(sample == positions for sample in samples)


def test_remote_controls_keep_existing_toggle_meanings_and_session_locks(
    remote_layout, qt_application,
):
    _panel, remote, _scroll, content, _settings = remote_layout
    expand_remote_options(remote, content, qt_application)
    for name in _OPTION_NAMES:
        assert isinstance(getattr(remote, name), SwitchButton)
    assert remote.chk_noaudio.isChecked()
    assert isinstance(remote.btn_start, TransparentPushButton)
    remote.set_target_devices(["synthetic-device"])
    controls = (
        remote.preset_selector, remote.fps, remote.bitrate_slider,
        remote.maxsize, remote.buffer, remote.orientation,
        *(getattr(remote, name) for name in _OPTION_NAMES),
    )
    for state in (remote._SESSION_STARTING, remote._SESSION_RUNNING, remote._SESSION_STOPPING):
        remote._set_session_state(state)
        assert all(not widget.isEnabled() for widget in controls)
        assert remote.codec.isEnabled()
        assert all(button.isEnabled() for button in remote._remote_control_buttons)
        assert all(widget.isVisibleTo(content) for widget in controls)
    remote._set_session_state(remote._SESSION_IDLE)
    assert all(widget.isEnabled() for widget in controls)


def test_remote_wide_narrow_wide_preserves_controls_values_and_check_states(
    remote_layout, qt_application,
):
    panel, remote, scroll, content, _settings = remote_layout
    expand_remote_options(remote, content, qt_application)
    _show_remote_controller(qt_application, remote, 1280)
    remote.preset_selector.items["Quality"].click()
    remote.chk_fullscreen.setChecked(True)
    remote.chk_record.setChecked(True)
    remote.chk_noaudio.setChecked(False)
    def tracked():
        return (
            remote.preset, remote.fps, remote.bitrate,
            remote.preset_selector, remote.fps_selector, remote.bitrate_slider,
            *remote._remote_section_groups,
            *(getattr(remote, name) for name in _OPTION_NAMES),
            *remote._remote_control_buttons,
        )

    identities = tuple(id(widget) for widget in tracked())
    checks = tuple(getattr(remote, name).isChecked() for name in _OPTION_NAMES)
    (mirroring,) = remote._remote_section_groups
    session = content.findChild(QWidget, "remoteMirrorSession")
    for width in (320, 420, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        _resize_remote_controller(qt_application, remote, width)
        assert panel._responsive_coordinator.diagnostics.fallback_reason is None
        session_rect = mapped_rect(session, content)
        settings_rect = mapped_rect(mirroring, content)
        assert session_rect.bottom() < settings_rect.top()
        assert abs(session_rect.left() - settings_rect.left()) <= 2
        assert abs(session_rect.width() - settings_rect.width()) <= 2
        assert scroll.horizontalScrollBar().maximum() == 0
        assert tuple(id(widget) for widget in tracked()) == identities
        assert tuple(getattr(remote, name).isChecked() for name in _OPTION_NAMES) == checks
        assert tuple(combo.currentData() for combo in (
            remote.preset, remote.fps, remote.bitrate,
        )) == ("Quality", "60", "12")
        assert_non_overlapping((session, mirroring), content)
        for widget in (remote.preset_selector, remote.preset):
            if widget.isVisibleTo(content):
                assert_scroll_target_reachable(scroll, widget)


def test_remote_font_growth_keeps_every_parameter_accessible(remote_layout, qt_application):
    panel, remote, scroll, content, _settings = remote_layout
    expand_remote_options(remote, content, qt_application)
    _window, controller_scroll, controller_content = _show_remote_controller(
        qt_application, remote, 292,
    )
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family="Arial", ui_size=22,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    _resize_feature_viewport(qt_application, panel, remote, scroll, 292)
    _resize_remote_controller(qt_application, remote, 292)
    wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
    wait_for_stable_geometry(qt_application, (content, *remote._remote_section_groups))
    for selector, combo in ((remote.preset_selector, remote.preset),):
        shown = [widget for widget in (selector, combo) if widget.isVisibleTo(content)]
        assert len(shown) == 1
        assert_scroll_target_reachable(scroll, shown[0])
    assert remote.fps.isVisibleTo(content)
    assert not remote.fps_selector.isVisibleTo(content)
    for widget in (
        remote.maxsize, remote.fps, remote.codec, remote.buffer, remote.orientation,
        *(getattr(remote, name) for name in _OPTION_NAMES),
    ):
        assert widget.isVisibleTo(content)
        assert widget.font().pointSize() == 22
        assert widget.height() >= widget.minimumSizeHint().height()
        if isinstance(widget, SwitchButton):
            assert widget.label.font().pointSize() == 22
            assert widget.label.height() >= widget.label.fontMetrics().height()
            assert widget.label.width() >= widget.label.fontMetrics().horizontalAdvance(
                widget.label.text(),
            )
        assert_scroll_target_reachable(scroll, widget)
    for button in remote._remote_control_buttons:
        assert button.isVisibleTo(controller_content)
        assert button.font().pointSize() == 22
        assert button.height() >= button.minimumSizeHint().height()
        assert_scroll_target_reachable(controller_scroll, button)
    for theme in ("Dark", "Light"):
        BaseStyles.switch_theme(theme)
        wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
        assert remote.maxsize.font().pointSize() == 22
        assert all(button.font().pointSize() == 22 for button in remote._remote_control_buttons)
        assert all(
            widget.label.font().pointSize() == 22
            for name in _OPTION_NAMES
            if isinstance(widget := getattr(remote, name), SwitchButton)
        )


def test_all_remote_actions_dispatch_once_after_repeated_reflow(remote_layout, qt_application):
    panel, remote, scroll, _content, _settings = remote_layout
    sent = []

    class InputService:
        def send_keyevent(self, device, key, *, cancelled):
            assert not cancelled()
            sent.append((device, "key", key))
            return True

        def perform_action(self, device, action, *, cancelled):
            assert not cancelled()
            sent.append((device, "action", action))
            return True

    class InlineExecutor:
        def submit(self, task):
            future = Future()
            future.set_result(task())
            return future

        def shutdown(self, **_kwargs):
            return None

    remote._remote_executor.shutdown(wait=True)
    remote._remote_executor = InlineExecutor()
    remote._remote_control = InputService()
    remote.set_target_devices(["synthetic-device"])
    _window, _controller_scroll, controller_content = _show_remote_controller(
        qt_application, remote, 420,
    )
    for width in (420, 1280, 292, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        _resize_remote_controller(qt_application, remote, width)
    for button in remote._remote_control_buttons:
        assert button.isVisibleTo(controller_content)
        assert button.isEnabled()
        button.click()
    qt_application.processEvents()
    expected_keys = {
        "HOME", "BACK", "RECENTS", "MENU", "POWER", "SETTINGS", "CAMERA", "SEARCH",
        "ENTER", "DEL", "VOL_DOWN", "VOL_UP", "MEDIA_PLAY", "MEDIA_PREV", "MEDIA_NEXT",
    }
    expected_actions = {
        "swipe_up", "swipe_down", "swipe_left", "swipe_right", "notif_expand",
        "notif_collapse", "rotate_portrait", "rotate_landscape",
    }
    expected = [("synthetic-device", "key", key) for key in expected_keys]
    expected.extend(("synthetic-device", "action", action) for action in expected_actions)
    assert Counter(sent) == Counter(expected)
    assert (
        remote._remote_submitted, remote._remote_completed,
        remote._remote_sent, remote._remote_failed,
    ) == (23, 23, 23, 0)
