"""验证远程参数的展开项和下拉框共享完整高度，同排字段保持对齐。"""

import pytest
from PySide6.QtTest import QTest

from gui.styles import BaseStyles
from gui.styles.typography import FontConfig, typography_manager
from tests import test_remote_layout
from tests.test_responsive_panels import _resize_feature_viewport
from tests.ui_geometry_helpers import mapped_rect, wait_for_stable_geometry

pytestmark = pytest.mark.ui
remote_layout = test_remote_layout.remote_layout


@pytest.mark.parametrize(
    "font_size,view_width,expanded", ((12, 780, False), (12, 1600, True),
                                     (22, 420, False), (22, 2600, True)),
)
def test_remote_parameter_modes_keep_labels_and_control_heights_aligned(
    remote_layout, qt_application, font_size, view_width, expanded,
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
    assert editor.pivot.isVisibleTo(content) is expanded, (
        editor.width(), editor.pivot.minimumSizeHint().width(),
        remote.mirroring_binding.applied_plan.mode, remote.maxsize.minimumWidth(),
    )
    current_control = editor.pivot if expanded else remote.fps
    expected_height = remote.maxsize.height()
    assert editor.height() == current_control.height() == expected_height
    assert mapped_rect(remote.maxsize, content).top() == mapped_rect(editor, content).top()
    assert mapped_rect(labels[remote.maxsize], content).top() == mapped_rect(
        labels[editor], content,
    ).top()
    if expanded:
        assert editor.rect().contains(editor.pivot.geometry())
        for item in editor.pivot.items.values():
            assert editor.pivot.rect().contains(item.geometry())
            assert item.height() >= item.fontMetrics().height() + 6
        assert editor.pivot.rect().contains(editor.pivot.currentIndicatorGeometry().toRect())
