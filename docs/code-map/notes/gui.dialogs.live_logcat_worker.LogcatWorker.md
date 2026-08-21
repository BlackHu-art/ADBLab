---
kind: class
---

# LogcatWorker

- 模块：[[gui.dialogs.live_logcat_worker]]
- 全名：gui.dialogs.live_logcat_worker.LogcatWorker

## 方法

- [[gui.dialogs.live_logcat_worker.LogcatWorker.__init__]] — （无 docstring）
- [[gui.dialogs.live_logcat_worker.LogcatWorker.request_stop]] — 向 logcat 线程和受跟踪进程发送幂等停止请求
- [[gui.dialogs.live_logcat_worker.LogcatWorker.force_stop]] — 在给定预算内强制终止受跟踪进程
- [[gui.dialogs.live_logcat_worker.LogcatWorker.stop]] — 保留兼容停止入口；这里只请求停止，不等待进程退出
- [[gui.dialogs.live_logcat_worker.LogcatWorker.is_active]] — （无 docstring）
- [[gui.dialogs.live_logcat_worker.LogcatWorker.wait_for_stop]] — 等待线程和进程均退出，但不超过调用方给定的预算
- [[gui.dialogs.live_logcat_worker.LogcatWorker.acknowledge_batch]] — （无 docstring）
- [[gui.dialogs.live_logcat_worker.LogcatWorker.run]] — （无 docstring）
- [[gui.dialogs.live_logcat_worker.LogcatWorker._emit_batch]] — （无 docstring）
- [[gui.dialogs.live_logcat_worker.LogcatWorker._emit_remaining_drop_count]] — （无 docstring）
- [[gui.dialogs.live_logcat_worker.LogcatWorker._parse_level]] — （无 docstring）

