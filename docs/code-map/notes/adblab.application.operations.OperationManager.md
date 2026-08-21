---
kind: class
---

# OperationManager

- 模块：[[adblab.application.operations]]
- 全名：adblab.application.operations.OperationManager

> 管理业务操作状态，但不拥有线程、进程或 Qt 对象

## 方法

- [[adblab.application.operations.OperationManager.__init__]] — （无 docstring）
- [[adblab.application.operations.OperationManager.begin]] — 创建排队状态的活动操作，并拒绝重复标识和重复单元
- [[adblab.application.operations.OperationManager.get]] — （无 docstring）
- [[adblab.application.operations.OperationManager.active_snapshot]] — （无 docstring）
- [[adblab.application.operations.OperationManager.active_count]] — （无 docstring）
- [[adblab.application.operations.OperationManager.token]] — （无 docstring）
- [[adblab.application.operations.OperationManager.mark_running]] — （无 docstring）
- [[adblab.application.operations.OperationManager.mark_finalizing]] — （无 docstring）
- [[adblab.application.operations.OperationManager.request_cancel]] — 设置协作式取消意图，仅首次有效请求返回 True
- [[adblab.application.operations.OperationManager.cancel_pending_units]] — 原子取消未完成单元、汇总终态并移除活动操作
- [[adblab.application.operations.OperationManager.update_progress]] — （无 docstring）
- [[adblab.application.operations.OperationManager.record_unit_result]] — （无 docstring）
- [[adblab.application.operations.OperationManager.add_artifact]] — （无 docstring）
- [[adblab.application.operations.OperationManager.finish]] — 完成非扇出操作，并从活动注册表中原子移除
- [[adblab.application.operations.OperationManager.finish_from_unit_results]] — 全部单元上报后汇总终态，并原子移除扇出操作
- [[adblab.application.operations.OperationManager._finish_from_unit_results_locked]] — （无 docstring）
- [[adblab.application.operations.OperationManager._move]] — （无 docstring）
- [[adblab.application.operations.OperationManager._matching_entry_locked]] — （无 docstring）
- [[adblab.application.operations.OperationManager._finish_locked]] — （无 docstring）
- [[adblab.application.operations.OperationManager._validate_transition]] — （无 docstring）
- [[adblab.application.operations.OperationManager._non_empty]] — （无 docstring）

