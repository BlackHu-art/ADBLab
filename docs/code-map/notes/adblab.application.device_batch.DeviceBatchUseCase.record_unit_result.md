---
kind: method
---

# record_unit_result(self, unit_id, device, success, message='')

- 定义于：[[adblab.application.device_batch.DeviceBatchUseCase]]
- 全名：adblab.application.device_batch.DeviceBatchUseCase.record_unit_result

> 记录单设备结果；重复或终态后的晚到结果被忽略

## 调用

- [[adblab.application.device_batch.DeviceBatchUseCase._drop_active_locked]]
- [[adblab.application.device_batch.DeviceBatchUseCase._finish_locked]]

## 实例化

- [[adblab.application.operations.OperationUnitResult]]

