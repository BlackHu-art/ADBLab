"""验证统一设置区的四项参数保持完整标签、字段高度和响应式对齐。"""

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from tests import test_remote_layout
from tests.test_responsive_panels import (
    _resize_feature_viewport,
    _resize_remote_controller,
    _show_remote_controller,
)
from tests.ui_geometry_helpers import (
    assert_contained,
    assert_non_overlapping,
    mapped_rect,
    wait_for_stable_geometry,
)

pytestmark = pytest.mark.ui
remote_layout = test_remote_layout.remote_layout


@pytest.mark.parametrize(
    "font_size,view_width", ((12, 780), (12, 1600), (22, 420), (22, 2600)),
)
def test_remote_parameter_dropdowns_keep_labels_and_control_heights_aligned(
    remote_layout, qt_application, font_size, view_width,
):
    panel, remote, scroll, content, _settings = remote_layout
    current = BaseStyles.current_font_config()
    config = FontConfig(
        ui_family="Arial", ui_size=font_size,
        log_size=current.log_size, mono_family=current.mono_family,
    )
    BaseStyles._sync_legacy_values(config)
    typography_manager.apply(config)
    _resize_feature_viewport(qt_application, panel, remote, scroll, view_width)
    QTest.qWait(160)
    editor = remote.fps.parentWidget()
    labels = {
        control: label for _container, label, control in remote._form_controller._fields
    }
    wait_for_stable_geometry(qt_application, (remote.maxsize, editor))
    assert not editor.pivot.isVisibleTo(content)
    assert remote.fps.isVisibleTo(content)
    expected_height = remote.maxsize.height()
    assert editor.height() == remote.fps.height() == expected_height
    for control in (remote.maxsize, remote.fps, remote.buffer, remote.orientation):
        assert control.height() >= control.minimumSizeHint().height()
        assert control.height() >= control.fontMetrics().height() + 6
    for control in (remote.maxsize, editor, remote.buffer, remote.orientation):
        assert mapped_rect(labels[control], content).bottom() < mapped_rect(control, content).top()
    assert_contained(remote.fps, editor)
    fields = tuple(remote.mirroring_binding.widgets())
    assert_non_overlapping(fields, content)
    columns = remote.mirroring_binding.applied_plan.mode.columns
    if columns >= 2:
        assert mapped_rect(remote.maxsize, content).top() == mapped_rect(editor, content).top()
        assert mapped_rect(labels[remote.maxsize], content).top() == mapped_rect(
            labels[editor], content,
        ).top()
    else:
        assert mapped_rect(fields[0], content).bottom() < mapped_rect(fields[1], content).top()
    assert len(fields) == 4
    bitrate_editor = remote.bitrate_slider.parentWidget()
    bitrate_rect = mapped_rect(bitrate_editor, content)
    assert bitrate_rect.top() > max(mapped_rect(field, content).bottom() for field in fields)
    assert_contained(remote.bitrate_slider, bitrate_editor)
    assert_non_overlapping((*fields, bitrate_editor), content)
    if (font_size, view_width) == (12, 1600):
        assert columns == 4, "普通字号宽窗应并排显示尺寸、FPS、缓冲和方向"
        assert len({mapped_rect(field, content).top() for field in fields}) == 1
        assert abs(bitrate_editor.width() - 3 * remote.codec.width()) <= 4
    assert scroll.horizontalScrollBar().maximum() == 0


def test_runtime_font_changes_keep_headers_presets_actions_and_fields_aligned(
    remote_layout, qt_application,
):
    panel, remote, scroll, content, _settings = remote_layout
    _window, _controller_scroll, controller_content = _show_remote_controller(
        qt_application, remote, 2600,
    )
    current = BaseStyles.current_font_config()
    heights = []
    for size in (12, 22, 12):
        config = FontConfig(
            ui_family="Segoe UI", ui_size=size,
            log_size=current.log_size, mono_family=current.mono_family,
        )
        BaseStyles._sync_legacy_values(config)
        typography_manager.apply(config)
        _resize_feature_viewport(qt_application, panel, remote, scroll, 2600)
        _resize_remote_controller(qt_application, remote, 2600)
        sections = remote._remote_section_groups
        wait_for_stable_geometry(qt_application, (*sections, remote.maxsize, remote.btn_start))
        (settings,) = sections
        session = content.findChild(QWidget, "remoteMirrorSession")
        assert session.isAncestorOf(remote.btn_start)
        assert session.isAncestorOf(remote.btn_stop)
        assert mapped_rect(session, content).bottom() < mapped_rect(settings, content).top()
        assert_non_overlapping((session, settings), content)
        assert remote.preset_selector.isVisibleTo(content)
        presets = tuple(remote.preset_selector.items.values())
        buttons = (remote.btn_start, remote.btn_stop, *remote._remote_control_buttons, *presets)
        fields = (remote.maxsize, remote.fps, remote.buffer, remote.orientation)
        controls = (*buttons, *fields)
        sizes = [control.height() for control in controls]
        groups = (
            (remote.btn_start, remote.btn_stop), presets, fields,
            remote._remote_navigation_binding.widgets(),
            remote._remote_screen_binding.widgets(),
            remote._remote_action_binding.widgets(),
            remote._remote_media_binding.widgets(),
            remote._remote_key_binding.widgets(),
        )
        for group in groups:
            group_heights = [control.height() for control in group]
            assert max(group_heights) - min(group_heights) <= 2, "每组控件应等高"
        for control in controls:
            assert control.font().pointSize() == size
            assert control.height() >= control.minimumSizeHint().height()
        navigation = remote._remote_navigation_binding.widgets()
        assert len({mapped_rect(control, controller_content).top() for control in navigation}) == 1
        assert len({mapped_rect(control, content).top() for control in presets}) == 1
        assert max(mapped_rect(control, content).bottom() for control in presets) < min(
            mapped_rect(control, content).top() for control in fields
        )
        assert all(button.isVisibleTo(controller_content)
                   for button in remote._remote_control_buttons)
        assert_non_overlapping(remote._remote_control_buttons, controller_content)
        assert mapped_rect(remote.maxsize, content).top() == mapped_rect(remote.fps, content).top()
        heights.append(tuple(sizes))
    assert all(large > small for small, large in zip(heights[0], heights[1]))
    assert heights[2] == heights[0], "恢复小字号后不得保留大字号固定高度"
