"""验证远程控制单页的参数投影、两栏重排和共享外观契约。"""

from collections import Counter
from concurrent.futures import Future

import pytest
from qfluentwidgets import (
    Pivot,
    PrimaryPushButton,
    Slider,
    SwitchButton,
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


def test_wide_remote_page_keeps_sections_contiguous_in_independent_columns(
    remote_layout, qt_application,
):
    _panel, remote, _scroll, content, _settings = remote_layout
    controls, mirroring = remote._remote_section_groups
    left, right = mapped_rect(controls, content), mapped_rect(mirroring, content)

    assert abs(left.top() - right.top()) <= 2, "宽窗操作和参数应在同一行"
    assert left.right() < right.left()
    assert abs(left.width() - right.width()) <= 2
    system, recording = (
        mapped_rect(section, content) for section in remote._remote_bottom_sections
    )
    assert 0 < system.top() - left.bottom() <= 24
    assert 0 < recording.top() - right.bottom() <= 24
    assert abs(system.left() - left.left()) <= 2
    assert abs(recording.left() - right.left()) <= 2
    assert abs(system.width() - recording.width()) <= 2
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
        *remote._remote_control_buttons,
    ):
        assert widget.isVisibleTo(content)
        assert_positive_geometry(widget, content)


def test_session_summary_stays_above_controls_and_settings_through_resizing(
    remote_layout, qt_application,
):
    from PySide6.QtWidgets import QWidget

    panel, remote, scroll, content, _settings = remote_layout
    session = content.findChild(QWidget, "remoteMirrorSession")
    assert session is not None
    for width in (780, 420, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        left, right = (mapped_rect(section, content) for section in remote._remote_section_groups)
        top = mapped_rect(session, content)
        assert top.bottom() < min(left.top(), right.top())
        assert top.left() <= min(left.left(), right.left())
        assert top.right() >= max(left.right(), right.right())
        assert scroll.horizontalScrollBar().maximum() == 0
        if left.top() == right.top():
            assert left.right() < right.left()
            assert abs(left.width() - right.width()) <= 2
        else:
            assert left.bottom() < right.top()
            assert abs(left.left() - right.left()) <= 2
        for control in (remote.btn_start, remote.btn_stop, remote._mirror_hint):
            assert session.isAncestorOf(control)
            assert_scroll_target_reachable(scroll, control)


def test_workspace_dividers_follow_two_column_layout_and_keep_lower_sections_separate(
    remote_layout, qt_application,
):
    from PySide6.QtWidgets import QWidget

    panel, remote, scroll, content, _settings = remote_layout
    divider = content.findChild(QWidget, "remoteWorkspaceDivider")
    assert divider is not None, "双栏工作区应有设计稿中的中央分割线"
    for width in (1280, 320, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        left, right = (mapped_rect(section, content) for section in remote._remote_section_groups)
        if width == 320:
            assert not divider.isVisibleTo(content), "单栏回流后中央分割线应隐藏"
        else:
            assert divider.isVisibleTo(content)
            rect = mapped_rect(divider, content)
            assert left.right() < rect.left() <= rect.right() < right.left()
            gap_center = (left.right() + right.left()) / 2
            assert abs(rect.center().x() - gap_center) <= 2
            assert rect.top() <= min(left.top(), right.top()) + 1
            lower_bottom = max(mapped_rect(section, content).bottom()
                               for section in remote._remote_bottom_sections)
            assert rect.bottom() >= lower_bottom - 1
        for section in remote._remote_bottom_sections:
            assert section.separator.isVisibleTo(content)
            separator = mapped_rect(section.separator, content)
            header = mapped_rect(section.headerView, content)
            assert separator.bottom() < header.top()
            assert abs(separator.width() - section.width()) <= 2
        assert scroll.horizontalScrollBar().maximum() == 0


def test_group_heading_emphasis_survives_runtime_font_changes(remote_layout, qt_application):
    from PySide6.QtWidgets import QLabel

    panel, remote, scroll, content, _settings = remote_layout
    heading_texts = ("滑动手势", "音量与媒体", "高级参数", "窗口", "设备屏幕", "音频与录制")
    headings = {label.text(): label for label in content.findChildren(QLabel)
                if label.text() in heading_texts}
    assert set(headings) == {"滑动手势", "音量与媒体"}
    current = BaseStyles.current_font_config()
    for size in (12, 22, 12):
        config = FontConfig(
            ui_family="Segoe UI", ui_size=size,
            log_size=current.log_size, mono_family=current.mono_family,
        )
        BaseStyles._sync_legacy_values(config)
        typography_manager.apply(config)
        _resize_feature_viewport(qt_application, panel, remote, scroll, 1280)
        for label in headings.values():
            assert label.font().family() == "Segoe UI"
            assert label.font().pointSize() == size
            assert label.font().bold(), f"{label.text()} 不应在改变字体后丢失标题字重"
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


def test_remote_controls_keep_semantic_pairs_and_media_transport_order(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    groups = (
        (remote._remote_navigation_binding, ("BACK", "HOME", "RECENTS", "POWER")),
        (remote._remote_key_binding, ("MENU", "ENTER", "DEL", "SETTINGS", "CAMERA", "SEARCH")),
        (remote._remote_volume_binding, ("VOL_DOWN", "VOL_UP")),
        (remote._remote_media_binding, ("MEDIA_PREV", "MEDIA_PLAY", "MEDIA_NEXT")),
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
    assert remote._remote_action_binding.applied_plan.mode.columns == 3
    by_code = {button.property("remoteKey"): button for button in remote._remote_key_buttons}
    assert by_code["ENTER"].text() == "回车"
    assert by_code["DEL"].text() == "退格"
    assert by_code["MEDIA_PLAY"].accessibleName() == "播放/暂停"
    assert by_code["POWER"] in remote._remote_navigation_binding.widgets()
    assert mapped_rect(by_code["POWER"], content).bottom() < min(
        mapped_rect(button, content).top() for button in actions
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


@pytest.mark.parametrize("theme", ("Dark", "Light"))
def test_preset_selection_uses_bottom_indicator_without_button_highlight(
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
        assert selected_image.pixelColor(round(8 * scale), round(4 * scale)) == (
            unselected_image.pixelColor(round(8 * scale), round(4 * scale))
        )
        assert selected_image.pixelColor(round(8 * scale), 0) == (
            unselected_image.pixelColor(round(8 * scale), 0)
        )
        painted = pivot.grab().toImage()
        center = selected.geometry().center().x()
        indicator_color = painted.pixelColor(
            round(center * scale), round((pivot.height() - 2) * scale),
        )
        assert indicator_color.name() == themeColor().name()
        assert selected.isSelected
        assert sum(item.isSelected for item in pivot.items.values()) == 1


def test_parameter_labels_precede_controls_and_units_follow_them(remote_layout):
    from PySide6.QtWidgets import QLabel

    _panel, remote, _scroll, content, _settings = remote_layout
    for control, caption, unit in (
        (remote.maxsize, "画面尺寸", "px"), (remote.fps, "帧率", "FPS"),
        (remote.buffer, "视频缓冲", "ms"), (remote.orientation, "画面方向", None),
    ):
        label = next(label for label in remote._parameter_labels if label.text() == caption)
        assert mapped_rect(label, content).right() < mapped_rect(control, content).left()
        assert abs(mapped_rect(label, content).center().y()
                   - mapped_rect(control, content).center().y()) <= 2
        if unit:
            suffix = next(label for label in label.parentWidget().findChildren(QLabel)
                          if label.text() == unit)
            assert mapped_rect(control, content).right() < mapped_rect(suffix, content).left()


def test_bitrate_gets_full_width_row_below_size_and_frame_rate(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    editor = remote.bitrate_slider.parentWidget()
    assert mapped_rect(editor, content).top() > mapped_rect(remote.fps, content).bottom()
    assert abs(editor.width() - remote.mirror_settings.width()) <= 2


def test_window_options_form_one_continuous_three_column_grid(remote_layout):
    _panel, remote, _scroll, content, _settings = remote_layout
    controls = (
        remote.chk_aot, remote.chk_fullscreen, remote.chk_showtouches, remote.chk_stayawake,
        remote.chk_turnscreenoff, remote.chk_noaudio, remote.chk_record, remote.chk_noplayback,
    )
    assert remote.window_options_binding.widgets() == controls
    assert remote.window_options_binding.applied_plan.mode.columns == 3
    rectangles = [mapped_rect(control, content) for control in controls]
    for start in range(0, len(rectangles), 3):
        row = rectangles[start:start + 3]
        assert max(rect.top() for rect in row) - min(rect.top() for rect in row) <= 2
    gaps = [after.top() - before.bottom() - 1
            for before, after in zip(rectangles[::3], rectangles[3::3])]
    assert max(gaps) - min(gaps) <= 2


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
    assert isinstance(remote.btn_start, PrimaryPushButton)
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
    controls, mirroring = remote._remote_section_groups
    for width in (320, 420, 1280):
        _resize_feature_viewport(qt_application, panel, remote, scroll, width)
        assert panel._responsive_coordinator.diagnostics.fallback_reason is None
        left, right = mapped_rect(controls, content), mapped_rect(mirroring, content)
        if width <= 420:
            assert left.bottom() < right.top()
            assert abs(left.left() - right.left()) <= 2
        else:
            assert abs(left.top() - right.top()) <= 2
            assert left.right() < right.left()
            assert abs(left.width() - right.width()) <= 2
        assert scroll.horizontalScrollBar().maximum() == 0
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
    expand_remote_options(remote, content, qt_application)
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
    for selector, combo in ((remote.preset_selector, remote.preset),):
        shown = [widget for widget in (selector, combo) if widget.isVisibleTo(content)]
        assert len(shown) == 1
        assert_scroll_target_reachable(scroll, shown[0])
    assert remote.fps.isVisibleTo(content)
    assert not remote.fps_selector.isVisibleTo(content)
    for widget in (
        remote.maxsize, remote.fps, remote.codec, remote.buffer, remote.orientation,
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
