---
kind: function
---

# test_device_medium_compact_transition_does_not_collapse_wide_right_panel_rows(qt_application, monkeypatch)

- 定义于：[[tests.test_main_window_layout]]
- 全名：tests.test_main_window_layout.test_device_medium_compact_transition_does_not_collapse_wide_right_panel_rows

> Devices 的高度反馈必须独立收敛，不能让宽右栏在相同宽度变成全单列

## 调用

- [[gui.main_frame.MainFrame._unbind_window_screen]]
- [[gui.panels.side_panel.SidePanel.request_responsive_reflow]]
- [[tests.test_main_window_layout.build_main_frame]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[tests.test_main_window_layout._FakeScreen]]
- [[tests.test_main_window_layout._FakeScreenAdapter]]

