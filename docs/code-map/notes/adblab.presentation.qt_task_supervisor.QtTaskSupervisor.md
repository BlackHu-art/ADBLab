---
kind: class
---

# QtTaskSupervisor

- 模块：[[adblab.presentation.qt_task_supervisor]]
- 全名：adblab.presentation.qt_task_supervisor.QtTaskSupervisor

> 在 GUI 线程之外执行有时限的资源停止和等待

## 方法

- [[adblab.presentation.qt_task_supervisor.QtTaskSupervisor.__init__]] — （无 docstring）
- [[adblab.presentation.qt_task_supervisor.QtTaskSupervisor.shared]] — （无 docstring）
- [[adblab.presentation.qt_task_supervisor.QtTaskSupervisor.stop_async]] — 在线程池中停止单个资源，并通过 Qt 信号返回结果
- [[adblab.presentation.qt_task_supervisor.QtTaskSupervisor.stop_owner_async]] — 异步停止指定 owner 的资源；应用关闭开始后拒绝新请求
- [[adblab.presentation.qt_task_supervisor.QtTaskSupervisor.begin_application_shutdown]] — 原子标记应用关闭开始，仅首次调用返回 True
- [[adblab.presentation.qt_task_supervisor.QtTaskSupervisor.stop_all_async]] — 停止全部已注册任务一次，并发送结果和残留资源快照
- [[adblab.presentation.qt_task_supervisor.QtTaskSupervisor.stop_finalizer_async]] — 在独立且有时限的执行通道中停止资源清理后的唯一收尾任务

