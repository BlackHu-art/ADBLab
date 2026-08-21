---
kind: function
---

# test_remote_supervisor_async_input_error_survives_process_timeout()

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_supervisor_async_input_error_survives_process_timeout

> 正常启动的输入清理线程失败时，进程残余结果必须保留关闭异常

## 调用

- [[gui.panels.remote_panel.RemotePanel.register_shutdown_task]]

## 实例化

- [[adblab.application.supervision.TaskSupervisor]]

