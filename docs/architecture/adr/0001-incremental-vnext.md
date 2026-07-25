# ADR-0001：采用兼容 Facade 的渐进式 vNext 迁移

- 状态：Accepted
- 日期：2026-07-25

## 背景

当前 ADBLab 已有 229 项回归测试、稳定的 Qt signal 入口、CommandRunner/ProcessRunner
基础，以及多个可独立工作的 service/worker。与此同时，Controller 共享状态、Qt 任务生命周期、
错误成功语义和外部命令边界存在已确认风险。

测试、import/patch 路径和 PyInstaller 配置与现有包结构耦合较深。一次性移动全部代码会同时扩大
运行、测试和打包风险。

## 决策

1. 保留 `ADBController` 和现有 Qt signals 作为迁移期 facade。
2. 新架构先以 add-only 方式提供 Operation、Cancellation、Supervision 和 Qt bridge。
3. 先迁移 Screenshot、LiveLogcat 和 Install Batch 三条纵向切片。
4. 三条切片通过 Gate 后，才继续迁移 Remote、MobilePerf 和剩余功能。
5. 物理包重排放在核心迁移完成后，作为独立可选阶段。
6. 不引入 `asyncio/qasync` 或重量级全局 EventBus。

## 后果

优点：

- 保持现有 UI 和测试可运行；
- 每条功能可独立回退；
- 架构失败可在小范围内被发现；
- PyInstaller 变更延后并可单独验证。

代价：

- 迁移期会存在新旧两套路径；
- 需要兼容 envelope 和 facade；
- 旧路径删除时间晚于功能迁移完成时间。

