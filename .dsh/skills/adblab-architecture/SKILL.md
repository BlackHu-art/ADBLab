---
name: adblab-architecture
description: >-
  ADBLab 的代码地图与跨模块不变量：分层与依赖方向、CommandRunner/ProcessRunner 的执行与停止语义、
  Operation/ActionResults 的身份与结果流、Workspace 会话与 generation 规则、设备上下文单一真源、
  关闭阶段与落盘、日志脱敏边界。Use when locating where a behavior lives, before changing shared
  state or lifetimes, or when deciding which layer a fix belongs to.
whenToUse: 需要在 ADBLab 中定位实现位置、判断改动归属层，或改动共享状态/线程/关闭路径之前。
---

# ADBLab 架构与不变量

单一事实来源是代码与测试；本技能只做导航。细节以
`docs/project-knowledge/ARCHITECTURE.md`、`BUSINESS_FLOW.md`、`DATA_FLOW.md`、
`DEPENDENCY_MAP.md` 为准（入口 `docs/README.md`）。

## 分层与依赖方向

```
main.py → gui/ → controllers/ → models/ → core/ + utils/ → 设备与操作系统
                    ↘ adblab/application（纯用例）  ↙
gui/features、gui/panels/remote_panel 例外：直接依赖 models/ 或 services/ 的 worker/service
```

- `core/` 不反向依赖 `models`/`gui`；`core/` 内只有 `log_service.py` 依赖 Qt，
  `core/__init__.py` 禁止导入 Qt（保住 mobileperf 的无 Qt 边界）。
- 设置层错误日志经 `core.settings_manager.set_error_sink` 注入，不在 core 里 import Qt。

## 执行边界

- **短命令**：`core/exec.py::CommandRunner.run` → 预取消 → `AdbRuntime.try_run`（直连 127.0.0.1:5037）
  → 剩余预算耗尽 → `native_capture`（仅传了 cancelled）→ `run_native`。
  结果 `CommandResult.outcome ∈ {succeeded, failed, cancelled, timed_out, stale}`；
  `stale` 表示被拒收的过期 devices 快照，**不能当故障上报**。
- **长进程**：`ProcessRunner`（实例表 + 全局表，锁外 spawn 后 CAS 注册）。只有确认退出且句柄身份一致
  才摘跟踪；自然退出用 `release_finished(key, process)`，不得用 `stop()` 顶替。
- `native_capture` 取消/超时最多 0.5s 清理预算；普通与冻结 `run_native` 共用最多 2s 清理预算；
  无法确认客户端退出时返回执行失败。

## 操作身份与结果流

```
GUI 信号 → controllers/<mixin> 入口（生成 operation_id/unit_id）
        → models @async_command → CommandTask → 附 perf + OperationMetadata + ActionEnvelope
        → command_finished(method, payload) → _ADBControllerBase._handle_async_response
        → 校验 owner/generation → _operation_handlers / _handlers → ActionResults → ActionFeedbackPresenter
```

- `_build_handler_map` 按**反向 MRO** 合并各 mixin 的 `_handlers`：同名键由 MRO 靠前的类胜出，冲突只记 WARNING。
- `OperationMetadata` 携带业务操作身份，`ActionEnvelope` 可同时携带通用结果请求身份；
  `owner_token` 用 `is` 恒等比较，代次不符时拒绝旧结果。
- `ActionResults`：提交时冻结目标；同 key 有在途请求时不重复执行；`OperationManager`、`TaskSupervisor`
  分别拥有业务状态与资源状态，两者都不该互相推断。
- 结果呈现的唯一消费者是 `gui/action_feedback.py::ActionFeedbackPresenter`；
  新增接线必须在 `controllers/action_catalog.py::ACTION_SIGNALS` 里声明归属，否则启动即抛错。

## 会话、设备与关闭

- `WorkspaceRoute` → `WorkspaceFeatureHost` → `FeatureSessionRegistry`，键 `(feature, device_id, generation)`；
  **generation 只增不减**，旧代次页面永不复活。
- 页面 `request_dispose()` 返回 `False` 时必须提供 `dispose_ready` 信号；缺完成通知是契约错误，
  不能当成已释放。
- 设备选择的单一真源是 `SidePanel.device_context_snapshot()`；`DeviceHubPage`、`DeviceContextBar`、
  各功能页会话都只做投影，回写统一走 `set_selected_devices`。
- 关闭由 `gui/close_controller.py::CloseController` 分阶段异步执行（封闭监督器准入 → 注册任务 → 停 UI 并请求释放 →
  `stop_all_async` → 后台 finalizer 落盘 → 重入 close），共享 6s deadline；
  "超时返回"不等于"资源已退出"。
- 日志：`LogService` 跨线程缓冲，`DiagnosticJournal` 有界摘要；控制台出口统一 `redact_diagnostic`
  脱敏（界面原文不脱敏），`console_log_level` 只影响控制台。

## 改动前的自检

1. 这个状态由谁拥有？有没有第二个来源（缓存/副本/局部布尔）？
2. 失败、取消、超时、重复启动、关闭五条路径分别发生什么？
3. 线程/进程由谁登记、谁等待、谁在超时后保留 residual？
4. 文案、日志、诊断里会不会泄露密钥、真实设备标识或不必要的本机路径？
