---
kind: class
---

# TaskSupervisor

- 模块：[[adblab.application.supervision]]
- 全名：adblab.application.supervision.TaskSupervisor

> 注册和停止运行资源，但不推断资源对应的业务结果

## 方法

- [[adblab.application.supervision.TaskSupervisor.__init__]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor.register]] — 注册资源停止回调，并拒绝无效回调和重复任务标识
- [[adblab.application.supervision.TaskSupervisor.unregister]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor.active_snapshot]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor.active_count]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor.stop]] — 在优雅停止和强制停止各自的预算内停止一个资源
- [[adblab.application.supervision.TaskSupervisor.stop_owner]] — 在共享截止预算内停止指定 owner 的全部未认领资源
- [[adblab.application.supervision.TaskSupervisor.stop_all]] — 在同一绝对截止时间内向所有未认领任务广播停止请求
- [[adblab.application.supervision.TaskSupervisor._stop_selected]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._wait]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._claim]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._release_claim]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._running]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._request]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._force]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._completion_error]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._result]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._remove_if_same]] — （无 docstring）
- [[adblab.application.supervision.TaskSupervisor._non_empty]] — （无 docstring）

