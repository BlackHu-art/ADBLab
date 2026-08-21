---
kind: function
---

# test_remote_supervisor_input_thread_start_failure_completes_with_error()

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_supervisor_input_thread_start_failure_completes_with_error

> 输入清理线程无法启动时，必须同步关闭真实持久会话后再收口

## 调用

- [[gui.panels.remote_panel.RemotePanel.register_shutdown_task]]

## 实例化

- [[adblab.application.supervision.TaskSupervisor]]
- [[core.adb_bridge.ADBBridge]]

