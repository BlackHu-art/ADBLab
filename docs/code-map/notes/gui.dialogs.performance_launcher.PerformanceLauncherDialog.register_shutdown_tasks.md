---
kind: method
---

# register_shutdown_tasks(self, supervisor, *, owner_id, task_prefix)

- 定义于：[[gui.dialogs.performance_launcher.PerformanceLauncherDialog]]
- 全名：gui.dialogs.performance_launcher.PerformanceLauncherDialog.register_shutdown_tasks

> 分别注册包名查询线程和 MobilePerf 进程的有限时关闭任务

## 实例化

- [[adblab.application.supervision.ThreadedShutdownTask]]
- [[gui.dialogs.lifecycle.QThreadGroupShutdownTask]]

