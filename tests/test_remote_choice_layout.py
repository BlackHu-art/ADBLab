"""验证紧凑远程页始终使用 FPS 下拉框，尺寸与 FPS 字段保持完整高度和对齐。"""

import pytest
from PySide6.QtTest import QTest

from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from tests import test_remote_layout
from tests.test_responsive_panels import _resize_feature_viewport
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
    for control in (remote.maxsize, remote.fps):
        assert control.height() >= control.minimumSizeHint().height()
        assert control.height() >= control.fontMetrics().height() + 6
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
    if columns == 3:
        assert len({mapped_rect(field, content).top() for field in fields}) == 1
        assert mapped_rect(fields[1], content).right() < mapped_rect(fields[2], content).left()
        assert fields[2].isAncestorOf(remote.bitrate_slider)
        assert_contained(remote.bitrate_slider, fields[2])
    if (font_size, view_width) == (12, 1600):
        assert columns == 3, "普通字号宽窗应在一行展示尺寸、FPS 和码率"
    assert scroll.horizontalScrollBar().maximum() == 0


def test_runtime_font_changes_keep_headers_presets_actions_and_fields_aligned(
    remote_layout, qt_application,
):
    panel, remote, scroll, content, _settings = remote_layout
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
        sections = remote._remote_section_groups
        wait_for_stable_geometry(qt_application, (*sections, remote.maxsize, remote.btn_start))
        headers = [mapped_rect(section.headerView, content) for section in sections]
        assert headers[0].top() == headers[1].top()
        assert headers[0].height() == headers[1].height(), "同排分区应共享标题行高度"
        assert remote.preset_selector.isVisibleTo(content)
        presets = tuple(remote.preset_selector.items.values())
        buttons = (remote.btn_start, remote.btn_stop, *remote._remote_control_buttons, *presets)
        fields = (remote.maxsize, remote.fps, remote.buffer, remote.orientation)
        controls = (*buttons, *fields)
        sizes = [control.height() for control in controls]
        assert max(sizes) - min(sizes) <= 2, "操作、预设和参数应共享同一控件高度"
        for control in controls:
            assert control.font().pointSize() == size
            assert control.height() >= control.minimumSizeHint().height()
        navigation = remote._remote_navigation_binding.widgets()
        assert len({mapped_rect(control, content).top()
                    for control in (*navigation, *presets)}) == 1
        assert mapped_rect(remote.maxsize, content).top() == mapped_rect(remote.fps, content).top()
        heights.append(tuple(sizes))
    assert min(heights[1]) > max(heights[0])
    assert heights[2] == heights[0], "恢复小字号后不得保留大字号固定高度"
