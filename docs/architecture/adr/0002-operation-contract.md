# ADR-0002：Operation 身份、状态与兼容 Envelope 契约

- 状态：Accepted
- 日期：2026-07-25

## 背景

旧 Controller 的 `_pending_ops` 生成 operation id，但多数调用没有把 ID 传给 Model，
结果只能按 method、设备或共享字段匹配。重叠截图/批次因此可能串台，且旧
`operation_completed(success=True)` 同时表达“已开始”和“已完成”，不能作为新业务终态来源。

`ADBModelCore.command_finished = Signal(str, object)` 已被 104 个异步方法和大量测试依赖，
不能在迁移第一步修改 signal 签名。

## 决策

1. `OperationManager` 只管理业务身份、状态、单元结果、artifact、取消意图和 active registry；
   不拥有 QThread、QRunnable、Future 或进程。
2. 状态只包含 `QUEUED/RUNNING/FINALIZING/SUCCEEDED/PARTIAL/FAILED/CANCELLED`。
3. 终态写入和 active registry 移除在同一锁区间完成；重复/晚到终态返回 `None`，不复活操作。
4. fan-out 操作按预期 unit 集合汇总；缺失 unit 禁止完成，部分失败不能标全成功。
5. `CancellationToken` 只是线程安全、不可重置的取消意图；资源停止由后续 TaskSupervisor 负责。
6. 迁移调用向 `async_command` 传内部 `_operation_id` 与 `_operation_kind`；decorator 在调用业务方法
   前移除保留参数，并生成不可变、version=1 的 `OperationMetadata`。
7. metadata 使用显式 `OperationEnvelope` 包住已有 perf envelope，signal 仍为 `(str, object)`；
   Controller 先拆 operation，再拆 perf，旧 handler 最终仍接收原 payload。
8. 只要存在 operation envelope，就只能按 operation id 进入已注册 vNext handler；
   未知 ID、method/kind 不匹配或缺 handler 都不得降级到 legacy handler。
9. 线程正常返回、无异常、非 dict payload或旧 `success=True` 进度消息，都不能自动推导业务成功；
   feature handler 必须显式完成 operation。

## 后果

- 旧调用完全不传 metadata，行为和 signal 签名保持不变。
- 新旧路径可在同一 Controller 中按具体 operation handler 并存。
- 业务 `RuntimeError` 不再被误当作 QObject 已删除而静默吞掉。
- 终态历史不在 Manager 内持久化；需要展示历史时由后续 Task Center 消费终态事件，而不是让
  active registry 变成无界历史库。
- 父子自动级联、重试、持久化、EventBus、TaskSupervisor 和 Qt bridge 均不属于本 ADR。
