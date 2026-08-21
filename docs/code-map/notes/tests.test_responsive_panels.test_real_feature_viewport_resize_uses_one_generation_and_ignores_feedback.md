---
kind: function
---

# test_real_feature_viewport_resize_uses_one_generation_and_ignores_feedback(qt_application, monkeypatch, panel_name)

- 定义于：[[tests.test_responsive_panels]]
- 全名：tests.test_responsive_panels.test_real_feature_viewport_resize_uses_one_generation_and_ignores_feedback

> 真实顶层缩放只开启一代，内部 viewport 反馈不得排队形成额外代次

## 调用

- [[gui.panels.base_panel.BasePanel.responsive_geometry_is_applied]]
- [[tests.test_responsive_panels._assert_feature_binding_geometry]]
- [[tests.test_responsive_panels._close_feature_panel]]
- [[tests.test_responsive_panels._resize_feature_viewport]]
- [[tests.test_responsive_panels._show_feature_panel]]
- [[tests.ui_geometry_helpers.wait_for_stable_geometry]]
- [[tests.ui_geometry_helpers.wait_until]]

