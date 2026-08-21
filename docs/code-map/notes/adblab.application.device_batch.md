---
kind: file
---

# adblab.application.device_batch

> 以纯应用层操作状态协调多设备批次操作的收口

- 路径：adblab/application/device_batch.py

## 类

- [[adblab.application.device_batch.DeviceBatchOutcome]] — 汇总批次终态，暴露成功标记、用户文案与失败设备列表
- [[adblab.application.device_batch.DeviceBatchStart]] — 记录已创建批次的操作标识、类型与执行单元
- [[adblab.application.device_batch.DeviceBatchUnit]] — 记录批次中单个设备执行单元的身份
- [[adblab.application.device_batch.DeviceBatchUseCase]] — 把多设备批次的计数与汇总委托给 OperationManager

