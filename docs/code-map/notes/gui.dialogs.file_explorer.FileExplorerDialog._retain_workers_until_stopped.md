---
kind: method
---

# _retain_workers_until_stopped(cls, workers)

- 定义于：[[gui.dialogs.file_explorer.FileExplorerDialog]]
- 全名：gui.dialogs.file_explorer.FileExplorerDialog._retain_workers_until_stopped

> 解除窗口所有权后持续持有线程，避免运行中的 QThread 被销毁

## 调用

- [[tests.test_remote_services._FaultInjectingLaunchWorker.setParent]]

