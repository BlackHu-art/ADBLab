---
kind: function
---

# test_queued_remote_reflow_unregisters_bindings_and_keeps_shutdown_once(qt_application, monkeypatch)

- 定义于：[[tests.test_responsive_panels]]
- 全名：tests.test_responsive_panels.test_queued_remote_reflow_unregisters_bindings_and_keeps_shutdown_once

> 排队重排中关闭 Remote 时，binding 注销且 worker/executor 只清理一次

## 调用

- [[gui.panels.side_panel.SidePanel.request_responsive_reflow]]
- [[gui.widgets.responsive_binding.ResponsiveGridBinding.widgets]]
- [[tests.test_responsive_panels._close_feature_panel]]
- [[tests.test_responsive_panels._show_feature_panel]]
- [[tests.ui_geometry_helpers.wait_until]]

