"""验证远程控制单页的参数投影、两栏重排和共享外观契约。"""

from collections import Counter
from concurrent.futures import Future

import pytest
from qfluentwidgets import (
    Pivot,
    Slider,
    SwitchButton,
    TransparentPushButton,
    TransparentTogglePushButton,
    themeColor,
)

from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _show_feature_panel,
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
        for name in ("maxsize", "fps", "codec", "buffer", "bitrate", "orientation"):
            combo = getattr(remote, name)
            assert combo.currentIndex() >= 0, name
            assert combo.currentData() == combo.itemData(0), name
        assert remote.bitrate_slider.toolTip() == f"{remote.bitrate.currentData()} Mbps"
    finally:
        _close_feature_panel(panel)

_OPTION_NAMES = (
    "chk_record", "chk_fullscreen", "chk_aot", "chk_showtouches", "chk_stayawake",
    "chk_turnscreenoff", "chk_hw_encoder", "chk_noplayback", "chk_noaudio",
)


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


def test_wide_remote_page_shows_mirroring_and_controls_side_by_side(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    mirroring, controls = remote._remote_section_groups
    left, right = mapped_rect(mirroring, content), mapped_rect(controls, content)

    assert left.right() < right.left(), "宽窗口应同时展示左右两栏，不能继续上下堆叠"
    assert abs(left.top() - right.top()) <= 2
    assert isinstance(remote.preset_selector, Pivot)
    assert isinstance(remote.fps_selector, Pivot)
    assert isinstance(remote.bitrate_slider, Slider)
    for selector in (remote.preset_selector, remote.fps_selector):
        for item in selector.items.values():
            assert item.font().pointSize() == 12
            assert item.height() >= item.fontMetrics().height()
            assert item.width() >= item.fontMetrics().horizontalAdvance(item.text())
    for widget in (
        remote.preset_selector, remote.fps_selector, remote.bitrate_slider,
        remote.maxsize, remote.codec, remote.buffer, remote.orientation,
        *(getattr(remote, name) for name in _OPTION_NAMES),
        *remote._remote_control_buttons,
    ):
        assert widget.isVisibleTo(content)
        assert_positive_geometry(widget, content)


def test_remote_middle_separator_tracks_two_columns_and_hides_in_one_column(
    remote_layout, qt_application,
):
    from PySide6.QtWidgets import QWidget

    panel, remote, scroll, content, _settings = remote_layout
    separator = content.findChild(QWidget, "remoteWorkspaceSeparator")
    assert separator is not None
    for width in (780, 420, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        left, right = (mapped_rect(section, content) for section in remote._remote_section_groups)
        if width == 420:
            assert not separator.isVisibleTo(content)
        else:
            line = mapped_rect(separator, content)
            assert separator.isVisibleTo(content)
            assert right.left() - left.right() - 1 >= 56
            assert left.right() < line.left() < line.right() < right.left()
            assert abs(line.top() - min(left.top(), right.top())) <= 1
            assert abs(line.bottom() - max(left.bottom(), right.bottom())) <= 1


def test_parameter_selectors_save_stable_values_and_custom_clears_preset(remote_layout):
    _panel, remote, _scroll, _content, settings = remote_layout
    remote.preset_selector.items["Quality"].click()
    assert remote.preset.currentData() == "Quality"
    assert (remote.maxsize.currentData(), remote.fps.currentData(), remote.codec.currentData()) == (
        "1920", "60", "h265",
    )
    assert remote.fps_selector.currentRouteKey() == "60"
    assert remote.bitrate_slider.value() == 4
    assert settings.get("scrcpy_preset") == "Quality"

    remote.fps_selector.items["120"].click()
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


def test_remote_controls_keep_semantic_pairs_and_media_transport_order(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    groups = (
        (remote._remote_navigation_binding, ("BACK", "HOME", "RECENTS")),
        (remote._remote_key_binding, ("MENU", "ENTER", "DEL", "SETTINGS", "CAMERA", "SEARCH")),
        (remote._remote_volume_binding, ("VOL_DOWN", "VOL_UP")),
        (remote._remote_media_binding, ("MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT")),
    )
    for binding, codes in groups:
        assert tuple(button.property("remoteKey") for button in binding.widgets()) == codes
    actions = remote._remote_action_binding.widgets()
    assert tuple(button.property("remoteAction") for button in actions) == (
        "swipe_up", "swipe_down", "swipe_left", "swipe_right",
        "notif_expand", "notif_collapse", "rotate_portrait", "rotate_landscape",
    )
    assert remote._remote_action_binding.applied_plan.mode.columns == 2
    by_code = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    assert by_code["ENTER"].text() == "回车"
    assert by_code["DEL"].text() == "退格"
    assert by_code["MEDIA_PLAY"].text() == "播放/暂停"
    assert mapped_rect(by_code["POWER"], content).top() > max(
        mapped_rect(button, content).bottom() for button in actions
    )
    assert all(button.iconSize().width() >= 16 for button in remote._remote_control_buttons)


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


@pytest.mark.parametrize("selector_name", ("preset_selector", "fps_selector"))
def test_parameter_focus_and_selection_keep_option_geometry(
    remote_layout, qt_application, selector_name,
):
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtTest import QTest

    _panel, remote, _scroll, content, _settings = remote_layout
    selector = getattr(remote, selector_name)
    items = tuple(selector.items.values())
    for item in items:
        item.clearFocus()
    wait_for_stable_geometry(qt_application, (selector, *items))
    before = tuple((item.geometry(), item.sizeHint()) for item in items)
    watched = (remote.preset_selector, remote.maxsize, remote.fps_selector, remote.btn_start)
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
    for item in (*items, items[1], items[0]):
        item.setFocus(Qt.FocusReason.MouseFocusReason)
        QTest.mouseClick(item, Qt.MouseButton.LeftButton)
        QTest.qWait(selector.slideAni.currentAni.duration() + 60)
        assert tuple((item.geometry(), item.sizeHint()) for item in items) == before
    assert samples
    assert all(sample == positions for sample in samples)


def test_remote_controls_keep_existing_toggle_meanings_and_session_locks(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    for name in ("chk_fullscreen", "chk_aot", "chk_showtouches"):
        assert isinstance(getattr(remote, name), TransparentTogglePushButton)
    for name in set(_OPTION_NAMES) - {"chk_fullscreen", "chk_aot", "chk_showtouches"}:
        assert isinstance(getattr(remote, name), SwitchButton)
    assert remote.chk_noaudio.isChecked()
    assert all(isinstance(button, TransparentPushButton) for button in (
        remote.btn_start, remote.btn_stop, *remote._remote_control_buttons,
    ))
    remote.set_target_devices(["synthetic-device"])
    controls = (
        remote.preset_selector, remote.fps_selector, remote.bitrate_slider,
        remote.maxsize, remote.codec, remote.buffer, remote.orientation,
        *(getattr(remote, name) for name in _OPTION_NAMES),
    )
    for state in (remote._SESSION_STARTING, remote._SESSION_RUNNING, remote._SESSION_STOPPING):
        remote._set_session_state(state)
        assert all(not widget.isEnabled() for widget in controls)
        assert all(button.isEnabled() for button in remote._remote_control_buttons)
        assert all(widget.isVisibleTo(content) for widget in controls)
    remote._set_session_state(remote._SESSION_IDLE)
    assert all(widget.isEnabled() for widget in controls)


def test_remote_wide_narrow_wide_preserves_controls_values_and_check_states(
    remote_layout, qt_application,
):
    panel, remote, scroll, content, _settings = remote_layout
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
    mirroring, controls = remote._remote_section_groups
    for width in (420, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        assert panel._responsive_coordinator.diagnostics.fallback_reason is None
        left, right = mapped_rect(mirroring, content), mapped_rect(controls, content)
        if width == 420:
            assert left.bottom() < right.top()
            assert abs(left.left() - right.left()) <= 2
        else:
            assert left.right() < right.left()
            assert abs(left.top() - right.top()) <= 2
        assert tuple(id(widget) for widget in tracked()) == identities
        assert tuple(getattr(remote, name).isChecked() for name in _OPTION_NAMES) == checks
        assert tuple(combo.currentData() for combo in (
            remote.preset, remote.fps, remote.bitrate,
        )) == ("Quality", "60", "12")
        assert_non_overlapping((mirroring, controls), content)
        for widget in (remote.preset_selector, remote.preset):
            if widget.isVisibleTo(content):
                assert_scroll_target_reachable(scroll, widget)


def test_remote_font_growth_keeps_every_parameter_accessible(remote_layout, qt_application):
    panel, remote, scroll, content, _settings = remote_layout
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family="Arial", ui_size=22,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    _resize_feature_viewport(qt_application, panel, remote, scroll, 292)
    wait_until(qt_application, lambda: panel._responsive_coordinator.diagnostics.stable)
    wait_for_stable_geometry(qt_application, (content, *remote._remote_section_groups))
    for selector, combo in (
        (remote.preset_selector, remote.preset), (remote.fps_selector, remote.fps),
    ):
        shown = [widget for widget in (selector, combo) if widget.isVisibleTo(content)]
        assert len(shown) == 1
        assert_scroll_target_reachable(scroll, shown[0])
    for widget in (
        remote.maxsize, remote.codec, remote.buffer, remote.orientation,
        *(getattr(remote, name) for name in _OPTION_NAMES),
        *remote._remote_control_buttons,
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
    for width in (420, 1280, 292, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
    for button in remote._remote_control_buttons:
        assert button.isVisibleTo(_content)
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
