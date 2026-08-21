---
kind: function
---

# test_lazy_feature_rows_share_one_coordinator_and_register_once(qt_application, monkeypatch, panel_name)

- 定义于：[[tests.test_responsive_panels]]
- 全名：tests.test_responsive_panels.test_lazy_feature_rows_share_one_coordinator_and_register_once

> 懒加载页的每行只注册一次，并统一消费 SidePanel coordinator

## 调用

- [[gui.panels.side_panel.SidePanel._ensure_tab_loaded]]
- [[tests.test_responsive_panels._close_feature_panel]]
- [[tests.test_responsive_panels._show_feature_panel]]
- [[tests.ui_geometry_helpers.wait_until]]

