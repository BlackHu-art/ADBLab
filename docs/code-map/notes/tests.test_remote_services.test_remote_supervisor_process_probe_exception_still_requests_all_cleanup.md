---
kind: function
---

# test_remote_supervisor_process_probe_exception_still_requests_all_cleanup()

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_supervisor_process_probe_exception_still_requests_all_cleanup

> 进程探测异常应回传错误，但不能阻止 scrcpy 请求与 ADB 会话清理

## 调用

- [[gui.panels.remote_panel.RemotePanel.register_shutdown_task]]

## 实例化

- [[adblab.application.supervision.TaskSupervisor]]

