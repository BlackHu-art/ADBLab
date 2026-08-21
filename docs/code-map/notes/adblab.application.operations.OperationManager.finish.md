---
kind: method
---

# finish(self, operation_id, state, *, message='', expected_kind=None, expected_generation=None)

- 定义于：[[adblab.application.operations.OperationManager]]
- 全名：adblab.application.operations.OperationManager.finish

> 完成非扇出操作，并从活动注册表中原子移除

## 调用

- [[adblab.application.operations.OperationManager._finish_locked]]
- [[adblab.application.operations.OperationManager._matching_entry_locked]]
- [[adblab.application.operations.OperationManager._validate_transition]]

## 实例化

- [[adblab.application.operations.OperationTransitionError]]

