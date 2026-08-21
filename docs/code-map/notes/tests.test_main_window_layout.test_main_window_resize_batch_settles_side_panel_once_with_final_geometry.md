---
kind: function
---

# test_main_window_resize_batch_settles_side_panel_once_with_final_geometry(qt_application)

- 定义于：[[tests.test_main_window_layout]]
- 全名：tests.test_main_window_layout.test_main_window_resize_batch_settles_side_panel_once_with_final_geometry

> 一次真实主窗口 resize 只能提交一代，并应用最终 viewport 几何

## 调用

- [[gui.main_frame.MainFrame._unbind_window_screen]]
- [[gui.panels.base_panel.BasePanel.responsive_geometry_is_applied]]
- [[tests.test_main_window_layout.build_main_frame]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[tests.test_main_window_layout._FakeScreen]]
- [[tests.test_main_window_layout._FakeScreenAdapter]]

