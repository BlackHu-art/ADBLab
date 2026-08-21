---
kind: method
---

# cancel_pending_units(self, operation_id, *, unit_message='Operation cancelled', message='', expected_kind=None, expected_generation=None)

- 定义于：[[adblab.application.operations.OperationManager]]
- 全名：adblab.application.operations.OperationManager.cancel_pending_units

> 原子取消未完成单元、汇总终态并移除活动操作

## 调用

- [[adblab.application.operations.OperationManager._finish_from_unit_results_locked]]
- [[adblab.application.operations.OperationManager._matching_entry_locked]]

## 实例化

- [[adblab.application.operations.OperationTransitionError]]
- [[adblab.application.operations.OperationUnitResult]]

