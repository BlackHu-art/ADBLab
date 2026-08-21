---
kind: method
---

# _schedule_launch_worker_delete(cls, worker, *, restart_exhausted)

- 定义于：[[gui.panels.remote_panel.RemotePanel]]
- 全名：gui.panels.remote_panel.RemotePanel._schedule_launch_worker_delete

> 幂等安排一次删除尝试；真实 QObject 始终回到自身 GUI 线程执行

## 调用

- [[core.settings_manager.AppSettings.instance]]
- [[gui.panels.remote_panel.RemotePanel._release_stopped_launch_worker]]
- [[gui.panels.remote_panel.RemotePanel._retry_launch_worker_delete]]

