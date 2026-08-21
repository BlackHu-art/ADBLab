---
kind: function
---

# test_height_only_settling_snapshot_does_not_consume_an_apply_round(qt_application)

- 定义于：[[tests.test_responsive_layout_controller]]
- 全名：tests.test_responsive_layout_controller.test_height_only_settling_snapshot_does_not_consume_an_apply_round

> 行高反馈只同步只读快照，后续真实宽度变化仍可在本代正常应用

## 调用

- [[gui.widgets.responsive_coordinator.ResponsiveCoordinator.request_reflow]]
- [[gui.widgets.responsive_layout.row_major_mode]]
- [[gui.widgets.responsive_layout.span_tail_mode]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[gui.widgets.responsive_layout.LayoutContext]]
- [[tests.test_responsive_layout_controller.MetricWidget]]
- [[tests.test_responsive_layout_controller.RecordingBinding]]

