---
kind: function
---

# test_remote_supervisor_input_fallback_error_survives_process_timeout()

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_supervisor_input_fallback_error_survives_process_timeout

> 进程同时超时时，输入同步兜底的实际异常仍应作为残余原因上报

## 调用

- [[gui.panels.remote_panel.RemotePanel.register_shutdown_task]]

## 实例化

- [[adblab.application.supervision.TaskSupervisor]]
- [[core.adb_bridge.ADBBridge]]

