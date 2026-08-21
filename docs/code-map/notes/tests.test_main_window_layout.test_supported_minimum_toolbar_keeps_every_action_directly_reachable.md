---
kind: function
---

# test_supported_minimum_toolbar_keeps_every_action_directly_reachable(qt_application, monkeypatch, font_size)

- 定义于：[[tests.test_main_window_layout]]
- 全名：tests.test_main_window_layout.test_supported_minimum_toolbar_keeps_every_action_directly_reachable

> 860px 下不得出现空 More，原动作按钮必须完整留在工具栏

## 调用

- [[gui.main_frame.MainFrame._unbind_window_screen]]
- [[tests.test_main_window_layout.assert_non_overlapping]]
- [[tests.test_main_window_layout.build_main_frame]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[tests.test_main_window_layout._FakeScreen]]
- [[tests.test_main_window_layout._FakeScreenAdapter]]

