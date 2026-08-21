---
kind: class
---

# DeviceBatchOutcome

- 模块：[[adblab.application.device_batch]]
- 全名：adblab.application.device_batch.DeviceBatchOutcome

> 汇总批次终态，暴露成功标记、用户文案与失败设备列表

## 方法

- [[adblab.application.device_batch.DeviceBatchOutcome.failed_units]] — 返回上报失败结果的执行单元
- [[adblab.application.device_batch.DeviceBatchOutcome.failed_devices]] — 返回失败设备标识列表，顺序与批次注册顺序一致
- [[adblab.application.device_batch.DeviceBatchOutcome.succeeded_count]] — 返回成功单元数量
- [[adblab.application.device_batch.DeviceBatchOutcome.failed_count]] — 返回失败单元数量
- [[adblab.application.device_batch.DeviceBatchOutcome.success]] — 全设备成功时返回 True，存在失败设备时返回 False
- [[adblab.application.device_batch.DeviceBatchOutcome.message]] — 复刻旧 BatchOperationTracker 的汇总文案

