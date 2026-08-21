---
kind: file
---

# adblab.application.envelope

> 通过旧 Qt 信号传递操作身份的兼容信封

- 路径：adblab/application/envelope.py

## 类

- [[adblab.application.envelope.OperationEnvelope]] — 将原始业务结果与内部操作元数据放入同一信号载荷
- [[adblab.application.envelope.OperationMetadata]] — 描述一次兼容信号所关联的操作、任务和预期产物

## 函数

- [[adblab.application.envelope.attach_operation_metadata]] — 仅在存在内部操作元数据时包装业务结果
- [[adblab.application.envelope.split_operation_metadata]] — 在旧业务处理器运行前拆分操作元数据

