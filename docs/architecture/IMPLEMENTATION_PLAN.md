# ADBLab vNext 渐进式实施方案

## 1. 目的与范围

本方案整合架构、Qt 运行时、产品性能、安全与交付治理评审结论，用于指导
ADBLab 在保持现有功能入口和打包能力的前提下渐进演进。

实施原则：

1. 不做一次性目录搬迁或全量重写。
2. 先修复安全风险和错误成功语义，再引入新架构契约。
3. `ADBController` 和现有 Qt signals 在迁移期继续作为兼容 facade。
4. 每个阶段先补 characterization tests，再实现，再同步知识文档。
5. 每个阶段必须通过 Go/No-Go 门禁；未通过时不得扩散到下一功能。
6. 无授权设备验证时明确记录“待确认”，不得宣称产品级完成。

## 2. 目标架构

依赖方向：

```text
Presentation / Qt Adapter
        ↓
Application Use Cases
        ↓
Domain Rules and Results

Infrastructure Adapters → Application Ports
Bootstrap / Composition Root → 负责装配
```

第一阶段只新增真正需要的架构内核，不机械套用四层目录：

```text
adblab/
├── application/
│   ├── operations.py
│   ├── cancellation.py
│   └── supervision.py
├── infrastructure/
│   └── execution.py
└── presentation/
    └── qt_operation_bridge.py
```

旧 `controllers/`、`models/`、`gui/`、`core/` 和 `utils/` 在核心迁移完成前保持原路径。
物理包重排属于最后的可选阶段。

## 3. 两个独立运行模型

### 3.1 OperationManager

负责业务语义：

- operation identity；
- 状态转换；
- 逐设备结果；
- artifact；
- 部分失败；
- 最终结果和重复完成防护。

首版状态机：

```text
QUEUED → RUNNING → SUCCEEDED | PARTIAL | FAILED | CANCELLED
                     ↘ FINALIZING（仅报告/制品类任务）
```

### 3.2 TaskSupervisor

负责资源生命周期：

- QThread/QRunnable/Future；
- 外部进程；
- cancel callback；
- bounded wait；
- shutdown deadline；
- 遗留资源 snapshot。

线程或进程结束不能直接推导业务成功。`OperationManager` 和 `TaskSupervisor`
不得合并为一个万能任务对象。

## 4. 兼容迁移接缝

保留 `models.adb_model.ADBModelCore.command_finished = Signal(str, object)`。
通过兼容 envelope 附加 operation metadata，不一次性修改全部 signal 签名：

1. `OperationManager.begin()` 创建 operation id。
2. `async_command` 接收内部保留参数 `_operation_id`。
3. 调用实际 model 方法前移除保留参数。
4. 返回值附加 operation metadata。
5. Controller 先拆 metadata，再进入现有 method handler。
6. 新 handler 更新 OperationManager。
7. 旧 handler 和旧 Qt signal 继续可用。

## 5. 架构验证 Gate

### Gate A：Screenshot

验证 operation identity、多设备 fan-out、乱序完成、artifact、部分失败和兼容 signal。

通过条件：

- 两批截图并发且结果不串台；
- 任一设备失败时批次不显示全成功；
- callback 全部携带 operation id；
- 终态后 registry 无泄漏；
- 旧截图和 operation completed signal 保持兼容。

### Gate B：LiveLogcat

验证 QThread、ProcessRunner、阻塞 stdout、高频事件、dialog close 和 MainFrame close。

通过条件：

- 关闭期间 Qt heartbeat 不出现超过 100 ms 的停顿；
- deadline 内 QThread 和进程树归零；
- 已关闭 UI 不接收晚到更新；
- graceful stop 和 force stop 有不同结果。

### Gate C：Install Batch

验证 parent/child operation、重叠批次、逐设备结果、部分失败、取消和失败项重试。

三个 Gate 全部通过后，才允许把新架构扩展到剩余功能。

## 6. 阶段路线

| 阶段 | 内容 | 关键门禁 |
| --- | --- | --- |
| Phase 0 | 安全止血、ADR、特征测试、失败语义、持久化可靠性 | P0 测试、全 pytest、自检、diff check |
| Phase 1 | Operation 类型、Registry、CancellationToken、metadata envelope | 旧接口兼容、并发/重复完成测试 |
| Phase 2 | Screenshot、LiveLogcat、Install Batch 三个 Gate | 三个 Gate 全部通过 |
| Phase 3 | TaskSupervisor v1、应用自有 pool、异步关闭 | UI 非阻塞、资源归零 |
| Phase 4 | RemoteSession、有界输入队列 | active device invariant、输入压力测试 |
| Phase 5 | MobilePerf v2 protocol、run manifest、精确结果目录 | 故障注入、30 分钟/长跑实机 |
| Phase 6 | Task Center、剩余功能、结构化本地观测 | 逐功能迁移门禁 |
| Phase 7 | 可选物理包整理、打包单一来源 | Windows 完整打包和兼容 import |

当前执行状态（2026-07-25）：

- Phase 0：自动化门禁 Go；实机项待确认。
- Phase 1：公共 Operation/Cancellation/envelope 契约完成。
- Phase 2：Gate A Screenshot 自动化通过；Gate B1 LiveLogcat component 自动化通过
  （全量回归 320 项），
  Gate B2 MainFrame integrated shutdown 仍为 No-Go；按门禁约束尚未进入 Gate C。

## 7. Qt 约束

- 不引入 `asyncio/qasync`。
- Worker 不得访问 QWidget。
- 禁止 `QThread.terminate()`。
- 禁止 UI 线程长时间 `wait()`、`Future.result()` 或进程 wait。
- `QThread.requestInterruption()` 不视为能打断阻塞子进程。
- TaskSupervisor 第一版使用应用自有 QThreadPool，不控制或清空 global instance。
- Typed event 通过主线程 `QtOperationBridge.Signal(object)` 进入 UI。
- Remote 高频输入不得使用无界 executor 队列。

## 8. Agent 与文件所有权

共享工作区内，多个 writer 必须拥有互斥文件范围。

主集成 agent 独占：

- 公共契约和 async envelope；
- `controllers/_base.py`；
- `models/adb_model.py`；
- `gui/main_frame.py`；
- settings、DeviceStore、打包公共配置；
- 知识库索引和最终文档收口；
- git 暂存、提交、冲突解决和发布。

专项 agent 只能修改任务中明确列出的文件；不得 `git add .`、提交、推送或修改公共契约。

## 9. 质量门禁

最低门禁：

```powershell
py -3.11 -m pytest -q
py -3.11 main.py --self-check packaging
git diff --check
```

逐步增加：

- Ruff/Black；
- 架构 import/AST 守卫；
- workflow 安全契约；
- changed-lines coverage；
- 敏感信息扫描；
- Windows packaged self-check；
- 授权设备最小验证；
- 线程/进程残留和长跑测试。

## 10. 明确不授权事项

除非用户单独授权，否则实施过程不：

- 推送分支；
- 创建或修改 Release/tag；
- 执行清理 workflow；
- 清理 Git 历史；
- 覆盖当前工作区用户修改；
- 在输出中展示邮件配置、设备标识或其他敏感值。
