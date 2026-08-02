# Phase 2 Gate B：LiveLogcat 账本

## 结论

Gate B 按评审结果拆成两个可独立验证、但必须全部通过的子门：

- **B1 LiveLogcat component：自动化 Pass**
- **B2 MainFrame integrated shutdown：No-Go，尚未实施**

因此 **Gate B 总体仍为 No-Go**，不得进入 Gate C。当前工作只证明 LiveLogcat 对话框组件
具备新的资源治理接缝，不代表整个应用关闭链路已经非阻塞，也不代表真实 Android/ADB
进程树验证完成。

## B1 已实施

### TaskSupervisor

- `TaskSupervisor` 与 `OperationManager` 分离，只表达资源处置，不推导业务成功。
- task 使用随机 owner/task identity；超时任务保留在 active snapshot 中作为 residual/orphan。
- 同一 task 的停止具有原子 claim；重复停止不会并发拥有同一资源。
- owner 停止先向所有 task 广播取消，再共享一个绝对 deadline；不按 task 数量累加 timeout。
- graceful、forced、already-stopped、timed-out 和 failed 使用不同结果。
- `wait()` 返回后再次检查 `is_running()`，不能仅凭 wait callback 宣称资源归零。
- Qt adapter 使用应用自有 `QThreadPool`，停止和等待不在 GUI 线程执行。

### LiveLogcat

- `threading.Event` 替代裸布尔停止标志。
- PID 探测前后及 process spawn 前均有取消检查；stop-before-start 不再启动 logcat。
- PID 探测命令失败时 fail-closed，不再静默退化成全量日志。
- worker 使用 producer-side bounded batch；最多 8 个在途 batch，每批最多 100 行，
  过载时丢弃并报告计数，避免逐行 queued signal 无界增长。
- 用户停止、启动失败和非预期退出使用 typed termination，不以 `QThread.finished` 推导成功。
- dialog 的 Stop/Close 只调度后台清理，不在 GUI 线程执行 process wait/kill。
- finished/status/batch handler 均绑定 worker generation；旧 worker 的晚到信号不能清理新 worker。
- package worker 的 finished closure 可精确断开，不再用不同 callable 尝试 disconnect。
- `ProcessRunner` 只有在确认退出后才移除 tracking；强停使用总时间预算。
- `MainFrame` 创建应用自有 QtTaskSupervisor，并注入所有 LiveLogcat dialog。

## B1 自动化证据

`tests/test_phase2_live_logcat_gate.py` 覆盖：

- graceful/forced/timed-out 语义；
- residual snapshot；
- owner broadcast-first 和共享 deadline；
- 重复停止 claim；
- ProcessRunner 未退出时保持 tracking；
- Stop/Close 调度耗时小于 100 ms；
- stubborn cleanup 期间 Qt timer heartbeat；
- cancel-before-run；
- PID probe fail-closed；
- producer batch 上限和过载丢弃；
- 非零/自然退出不是成功；
- 旧 generation finished 隔离；
- 关闭后 late batch 只做 transport ack，不更新 UI。

Gate A/B1 快速门禁当前为 52 项通过；全量回归为 320 项通过。

## B2 阻断项

`MainFrame.closeEvent()` 仍包含多个同步关闭边界：

- `_stop_scan_thread(blocking=True)`；
- 已加载 Remote panel 的 process stop 和 QThread wait；
- `ADBController.shutdown()` 内各 model 的同步 `ProcessRunner.stop_all()`；
- 全局 `ProcessRunner.stop_all_tracked()`。

B2 必须增加主窗口异步关闭状态机：首次 close 只进入 closing、停止 UI 入口并发出广播，
事件循环继续；所有应用资源归零或达到绝对 deadline 后再完成第二阶段 close。任何 residual
都必须留在 supervisor snapshot 中并明确报告，不能清空 registry 或宣称成功。

## 待确认

- Windows 真实 helper process tree 的 terminate/force/orphan 集成测试。
- 授权 Android 设备上的 package PID filter、阻塞 stdout 解锁和 adb server 异常。
- 多 LiveLogcat 窗口加主窗口关闭的真实 heartbeat 与资源归零。
