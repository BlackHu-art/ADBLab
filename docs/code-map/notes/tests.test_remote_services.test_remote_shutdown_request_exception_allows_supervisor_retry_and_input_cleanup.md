---
kind: function
---

# test_remote_shutdown_request_exception_allows_supervisor_retry_and_input_cleanup()

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_shutdown_request_exception_allows_supervisor_retry_and_input_cleanup

> 直接停止异常后 supervisor 可重试，executor 与 ADB 清理仍能完成

## 调用

- [[gui.panels.remote_panel.RemotePanel.register_shutdown_task]]

## 实例化

- [[adblab.application.supervision.TaskSupervisor]]

