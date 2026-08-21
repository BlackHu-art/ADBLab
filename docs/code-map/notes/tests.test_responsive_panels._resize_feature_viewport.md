---
kind: function
---

# _resize_feature_viewport(qt_application, panel, feature_panel, scroll, width)

- 定义于：[[tests.test_responsive_panels]]
- 全名：tests.test_responsive_panels._resize_feature_viewport

> 只经宿主尺寸变化调整真实 viewport，并等待页面计划覆盖最终 Qt 几何

## 调用

- [[gui.panels.base_panel.BasePanel.responsive_geometry_is_applied]]
- [[tests.test_responsive_panels._set_scroll_viewport_width]]
- [[tests.ui_geometry_helpers.wait_for_stable_geometry]]
- [[tests.ui_geometry_helpers.wait_until]]

