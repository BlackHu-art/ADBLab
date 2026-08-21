---
kind: method
---

# closeEvent(self, event)

- 定义于：[[gui.dialogs.app_manager_details.AppDetailsDialog]]
- 全名：gui.dialogs.app_manager_details.AppDetailsDialog.closeEvent

> 中止详情 worker，并把等待操作移交后台，避免阻塞关闭事件

## 调用

- [[gui.dialogs.lifecycle.safe_disconnect]]
- [[gui.dialogs.lifecycle.wait_for_threads_later]]
- [[tests.test_remote_services._FaultInjectingLaunchWorker.setParent]]

