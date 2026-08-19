# Phase 1 变更账本

## 范围

- 新增 `adblab.application` add-only 包；
- Operation 状态、active registry、fan-out unit result 与 artifact 契约；
- CancellationToken；
- versioned metadata envelope；
- `async_command` 保留参数剥离、成功/异常统一发射；
- Controller vNext handler 路由；
- 不迁移任何业务功能，不修改旧 Qt signal 签名。

## 关键不变量

- OperationManager 不拥有资源；
- 终态首次写入获胜并立即移出 active registry；
- fan-out 缺失 unit 不得结束，混合成功/失败为 PARTIAL；
- 取消请求不直接等同于 CANCELLED；
- metadata 未知、过期、不匹配或缺 handler 时不得进入 legacy handler；
- 旧 handler 不看到 metadata/perf 内部包装；
- worker 业务 `RuntimeError` 必须返回失败结果，只有发射到已删除 QObject 时才静默。

## 自动验证

- `tests/test_phase1_operations.py`：23 项通过。
- 覆盖合法/非法状态转换、进度单调、fan-out 六类汇总、缺失/未知/冲突 unit、
  artifact 幂等、取消意图、多线程单次取消、20 线程终态竞争、任意 payload envelope、
  perf 组合、保留参数剥离、业务 RuntimeError、提交异常、Controller vNext/stale/handler error。
- 既有 `tests/test_model_execution.py`：188 项通过。
- 全量：291 项通过。

## 剩余项

- QObject 销毁时 pending operation 的 owner 级取消属于 TaskSupervisor。
- 终态事件到 UI 的 typed Qt bridge 属于后续阶段。
- Screenshot/LiveLogcat/Install batch 尚未迁移，本阶段只提供契约。
- Ruff 未安装；现有 pytest、自检和 diff 门禁不依赖 Ruff。

## Go/No-Go

**Go：公共契约可以进入 Phase 2 Gate A（Screenshot）纵向验证。**
