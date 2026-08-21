---
kind: function
---

# test_coordinator_fallback_only_conservatizes_targets_that_are_still_changing(qt_application)

- 定义于：[[tests.test_responsive_layout_controller]]
- 全名：tests.test_responsive_layout_controller.test_coordinator_fallback_only_conservatizes_targets_that_are_still_changing

> 一个目标达到轮次上限时，不得把同批稳定目标一起降到最保守模式

## 调用

- [[gui.widgets.responsive_coordinator.ResponsiveCoordinator.request_reflow]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[tests.test_responsive_layout_controller.FakeTarget]]

