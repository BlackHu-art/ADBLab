---
kind: function
---

# test_device_list_minimum_keeps_a_long_row_visible_after_content_changes(qt_application, monkeypatch, font_size, populate_after_shrink)

- 定义于：[[tests.test_responsive_panels]]
- 全名：tests.test_responsive_panels.test_device_list_minimum_keeps_a_long_row_visible_after_content_changes

> 设备项无论先于还是晚于收缩出现，最小高度都必须容纳行和横向滚动条

## 调用

- [[tests.test_responsive_panels._close_device_test_ui]]
- [[tests.ui_geometry_helpers.wait_for_stable_geometry]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[gui.panels.side_panel.SidePanel]]

