---
kind: method
---

# register_shutdown_task(self, supervisor, *, owner_id, task_id)

- 定义于：[[gui.panels.remote_panel.RemotePanel]]
- 全名：gui.panels.remote_panel.RemotePanel.register_shutdown_task

> 在界面断开引用前注册 scrcpy、启动 worker 和输入会话清理任务

## 调用

- [[gui.panels.remote_panel.RemotePanel._request_launch_worker_interruption_once]]
- [[gui.panels.remote_panel.RemotePanel._request_scrcpy_stop_once]]

