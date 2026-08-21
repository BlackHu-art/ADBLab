---
kind: class
---

# ProcessRunner

- 模块：[[core.exec]]
- 全名：core.exec.ProcessRunner

> 统一管理后台子进程，支持按 key 启动/停止/轮询

## 方法

- [[core.exec.ProcessRunner.__init__]] — （无 docstring）
- [[core.exec.ProcessRunner.start]] — 启动子进程，同名 key 会先停止旧进程
- [[core.exec.ProcessRunner.spawn]] — 启动不进入活动进程表的子进程，调用方必须自行管理其生命周期
- [[core.exec.ProcessRunner.stop]] — 停止指定 key 的子进程，返回 exit code 或 None
- [[core.exec.ProcessRunner.request_stop]] — 请求进程正常终止，但不等待退出，也不提前移除跟踪记录
- [[core.exec.ProcessRunner.force_stop]] — 在调用方给定的总时限内强制停止一个被跟踪进程
- [[core.exec.ProcessRunner._kill_process_tree_bounded]] — 在共享绝对截止时间内通过 psutil 终止进程树（ADR-0005 Step C）
- [[core.exec.ProcessRunner._stop_proc]] — 先请求正常退出，超时后终止进程树并返回可确认的退出码
- [[core.exec.ProcessRunner._kill_process_tree]] — 通过 psutil 终止目标进程及其子进程（ADR-0005 Step C 统一实现）
- [[core.exec.ProcessRunner.poll]] — 检查指定 key 的进程是否仍在运行
- [[core.exec.ProcessRunner.active_keys]] — （无 docstring）
- [[core.exec.ProcessRunner.stop_all]] — 停止当前实例跟踪的所有进程
- [[core.exec.ProcessRunner.stop_all_tracked]] — 兜底停止所有由 ``start`` 管理的进程；``spawn`` 创建的进程不纳入
- [[core.exec.ProcessRunner.tracked_active_count]] — 返回全局跟踪表中仍存活的进程数量，并清理已退出记录
- [[core.exec.ProcessRunner.force_all_tracked]] — 在共享截止时间内强制停止所有全局跟踪进程
- [[core.exec.ProcessRunner._register_global]] — （无 docstring）
- [[core.exec.ProcessRunner._unregister_global]] — （无 docstring）

