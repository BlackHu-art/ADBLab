---
kind: class
---

# DeviceBatchUseCase

- 模块：[[adblab.application.device_batch]]
- 全名：adblab.application.device_batch.DeviceBatchUseCase

> 把多设备批次的计数与汇总委托给 OperationManager

## 方法

- [[adblab.application.device_batch.DeviceBatchUseCase.__init__]] — （无 docstring）
- [[adblab.application.device_batch.DeviceBatchUseCase.start]] — 创建多设备批次，并为每个设备登记一个执行单元
- [[adblab.application.device_batch.DeviceBatchUseCase.active_start]] — 返回仍在活动中的批次身份，未知或已收口返回 None
- [[adblab.application.device_batch.DeviceBatchUseCase.progress]] — 返回与旧 BatchOperationTracker 一致的进度字符串，如 "(1/2)"
- [[adblab.application.device_batch.DeviceBatchUseCase.record_unit_result]] — 记录单设备结果；重复或终态后的晚到结果被忽略
- [[adblab.application.device_batch.DeviceBatchUseCase.finish]] — 全部单元收口后汇总终态；未收口或未知操作时抛出异常
- [[adblab.application.device_batch.DeviceBatchUseCase._finish_locked]] — （无 docstring）
- [[adblab.application.device_batch.DeviceBatchUseCase._drop_active_locked]] — （无 docstring）
- [[adblab.application.device_batch.DeviceBatchUseCase._new_id]] — （无 docstring）
- [[adblab.application.device_batch.DeviceBatchUseCase._non_empty]] — （无 docstring）

