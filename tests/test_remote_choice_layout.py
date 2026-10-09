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
    fields = (remote.maxsize.parentWidget(), editor.parentWidget())
    assert_non_overlapping(fields, content)
    if remote.mirroring_binding.applied_plan.mode.columns == 2:
        assert mapped_rect(remote.maxsize, content).top() == mapped_rect(editor, content).top()
        assert mapped_rect(labels[remote.maxsize], content).top() == mapped_rect(
            labels[editor], content,
        ).top()
    else:
        assert mapped_rect(fields[0], content).bottom() < mapped_rect(fields[1], content).top()
    assert scroll.horizontalScrollBar().maximum() == 0
