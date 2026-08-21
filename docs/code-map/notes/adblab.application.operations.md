---
kind: file
---

# adblab.application.operations

> 维护线程安全的业务操作状态和活动操作注册表

- 路径：adblab/application/operations.py

## 类

- [[adblab.application.operations.ConflictingOperationResultError]] — 同一单元上报两个不同终态时抛出
- [[adblab.application.operations.IncompleteOperationError]] — 扇出单元尚未全部上报就请求汇总时抛出
- [[adblab.application.operations.OperationArtifact]] — 记录操作产物及其可选的来源单元
- [[adblab.application.operations.OperationManager]] — 管理业务操作状态，但不拥有线程、进程或 Qt 对象
- [[adblab.application.operations.OperationSnapshot]] — 提供某一时刻可安全跨线程读取的业务操作快照
- [[adblab.application.operations.OperationState]] — 定义业务操作从排队到终态的有限状态集合
- [[adblab.application.operations.OperationTransitionError]] — 活动操作收到非法状态转换时抛出
- [[adblab.application.operations.OperationUnitResult]] — 记录扇出操作中一个执行单元的不可变终态
- [[adblab.application.operations._OperationEntry]] — （无 docstring）

