---
kind: function
---

# test_remote_supervisor_input_fallback_failure_stays_visible_and_not_graceful()

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_supervisor_input_fallback_failure_stays_visible_and_not_graceful

> 同步输入兜底也失败时，监督结果必须保留失败和残余证据

## 调用

- [[gui.panels.remote_panel.RemotePanel.register_shutdown_task]]

## 实例化

- [[adblab.application.supervision.TaskSupervisor]]
- [[core.adb_bridge.ADBBridge]]

