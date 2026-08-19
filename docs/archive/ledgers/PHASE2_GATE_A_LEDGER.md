# Phase 2 Gate A：Screenshot 账本

## 目标

用第一条真实纵向切片证明 OperationManager 与 metadata envelope 在 Controller/Model/Qt signal
兼容链路中的可行性，同时删除截图批次共享状态。

## 实施

- 一次用户请求创建一个 `kind=screenshot` parent operation；
- 每个设备任务由 Controller 预生成 task/unit id，并随 operation id、目标和预期 artifact 路径进入
  versioned metadata；业务 method 看不到内部保留参数；
- 文件名包含 operation id 和微秒时间，避免同设备同秒重叠覆盖；
- Model payload 的目标、路径、文件存在性与 PNG signature 全部验证后才记录成功 artifact；
- fan-out 乱序结果按 task id 汇总，全成功为 SUCCEEDED，混合结果为 PARTIAL，全失败为 FAILED；
- PARTIAL/FAILED/CANCELLED 在旧 `operation_completed` 中均使用 `success=False`；
- `screenshot_captured` 仍逐 artifact 发射，viewer 每 operation 最多打开一次；
- 重复 callback 在 unit 层忽略，终态后的晚到 callback 在 Base 路由层丢弃；
- 提交异常同步记 unit failure；所有提交失败时不等待 callback；
- 取消意图将未完成 unit 记为 CANCELLED，迟到结果不复活 operation；
- 保留无 envelope 的旧 `_process_screenshot_result()` 兼容路径，但主入口已只走 vNext。

## 删除的共享状态

主截图路径不再创建或依赖：

- `_screenshot_paths`
- `_screenshot_remaining`
- `_screenshot_devices`
- 截图用途的 `_pending_ops`

## 自动验证

`tests/test_phase2_screenshot_gate.py` 覆盖：

- 两批重叠截图交错完成且 viewer/artifact 不串台；
- 同批 task ID 唯一、跨批 operation ID/路径隔离；
- 部分失败不报告全成功；
- 全失败无 artifact/signal/viewer；
- 文件缺失、非 PNG、目标不一致和预期路径不一致；
- 重复与终态晚到 callback 无重复副作用；
- 所有提交同步失败；
- 中途取消后部分结果与迟到结果；
- 空/重复目标去重；
- metadata mismatch fail-closed 且仍发兼容失败终态。

验证结果：

- Phase 1 + Gate A：32 项通过。
- 全量：300 项通过。
- active registry 在所有终态路径归零。

## Gate 结论

**自动化 Gate A：Pass。**

由于当前没有授权 Android 设备，真实 `exec-out`/fallback pull、多设备乱序和 viewer 用户体验仍标记
待确认；该待确认项不阻止进入 Gate B 的代码与故障注入验证，但阻止宣称产品级实机验收完成。
