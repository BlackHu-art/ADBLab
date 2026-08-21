---
kind: file
---

# adblab.application.supervision

> 维护与业务操作状态相互独立的资源生命周期注册表

- 路径：adblab/application/supervision.py

## 类

- [[adblab.application.supervision.StopDisposition]] — 描述资源停止请求的最终处置结果
- [[adblab.application.supervision.SupervisedTaskSnapshot]] — 提供受监督资源当前运行状态的只读快照
- [[adblab.application.supervision.TaskStopResult]] — 记录单个受监督资源的停止结果，不表示业务成功与否
- [[adblab.application.supervision.TaskSupervisor]] — 注册和停止运行资源，但不推断资源对应的业务结果
- [[adblab.application.supervision.ThreadedShutdownTask]] — 在独立线程中执行一次旧式非 Qt 关闭函数，避免阻塞调用方
- [[adblab.application.supervision._SupervisedTask]] — （无 docstring）

