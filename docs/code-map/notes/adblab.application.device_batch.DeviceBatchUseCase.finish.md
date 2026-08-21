---
kind: method
---

# finish(self, operation_id)

- 定义于：[[adblab.application.device_batch.DeviceBatchUseCase]]
- 全名：adblab.application.device_batch.DeviceBatchUseCase.finish

> 全部单元收口后汇总终态；未收口或未知操作时抛出异常

## 调用

- [[adblab.application.device_batch.DeviceBatchUseCase._drop_active_locked]]
- [[adblab.application.device_batch.DeviceBatchUseCase._finish_locked]]

## 实例化

- [[adblab.application.operations.IncompleteOperationError]]
- [[adblab.application.operations.OperationTransitionError]]

