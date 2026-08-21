---
kind: function
---

# test_side_panel_supervised_remote_close_cleans_active_resources_once(qt_application, monkeypatch)

- 定义于：[[tests.test_responsive_panels]]
- 全名：tests.test_responsive_panels.test_side_panel_supervised_remote_close_cleans_active_resources_once

> 排队重排中经 SidePanel 与 supervisor 关闭 Remote，每类资源只清理一次

## 调用

- [[gui.panels.side_panel.SidePanel.request_responsive_reflow]]
- [[gui.widgets.responsive_binding.ResponsiveGridBinding.widgets]]
- [[tests.test_responsive_panels._close_feature_panel]]
- [[tests.test_responsive_panels._show_feature_panel]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[adblab.application.supervision.TaskSupervisor]]

