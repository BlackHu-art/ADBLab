"""验证响应式行限宽后仍按实际可用宽度预留换行高度。"""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.panels.base_panel import BasePanel
from gui.widgets.responsive_layout import LayoutContext


@pytest.mark.parametrize("row_width", (120, 180, 240))
def test_responsive_row_height_respects_its_width_cap(qt_application, row_width):
    panel = BasePanel(SimpleNamespace())
    host = QWidget()
    layout = QVBoxLayout(host)
    label = QLabel("The parent has room for a wide row, but this field must wrap.")
    label.setWordWrap(True)
    binding = panel._add_responsive_row(layout, label)
    context = LayoutContext(row_width, 500, False, (), 0)
    binding.apply_responsive_plan(binding.responsive_plan(context))
    row = label.parentWidget()
    assert row is not None
    row_layout = row.layout()
    assert row_layout is not None

    required_height = label.heightForWidth(row.maximumWidth())
    assert required_height > label.heightForWidth(600)
    assert row.heightForWidth(600) >= required_height

    host.resize(600, layout.totalHeightForWidth(600))
    host.show()
    qt_application.processEvents()
    assert label.height() >= label.heightForWidth(label.width())

    # 限宽放宽后重新度量，不能把旧窄行的高度永久固化。
    wider_context = LayoutContext(600, 500, False, (), 0)
    binding.apply_responsive_plan(binding.responsive_plan(wider_context))
    assert row.heightForWidth(600) < required_height
