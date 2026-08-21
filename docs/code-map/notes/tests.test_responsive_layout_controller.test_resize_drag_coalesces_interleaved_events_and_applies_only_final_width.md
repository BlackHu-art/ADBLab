---
kind: function
---

# test_resize_drag_coalesces_interleaved_events_and_applies_only_final_width(qt_application)

- 定义于：[[tests.test_responsive_layout_controller]]
- 全名：tests.test_responsive_layout_controller.test_resize_drag_coalesces_interleaved_events_and_applies_only_final_width

> 真实拖动会在 resize 之间处理事件，仍只能在尾沿提交一次最终布局

## 调用

- [[gui.widgets.responsive_coordinator.ResponsiveCoordinator.request_reflow]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[tests.test_responsive_layout_controller.ResizeEchoTarget]]

