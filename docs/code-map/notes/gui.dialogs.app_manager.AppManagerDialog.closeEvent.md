---
kind: method
---

# closeEvent(self, event)

- 定义于：[[gui.dialogs.app_manager.AppManagerDialog]]
- 全名：gui.dialogs.app_manager.AppManagerDialog.closeEvent

> 断开晚到信号并中止 worker；已注册时由统一监督器负责等待

## 调用

- [[gui.dialogs.lifecycle.is_qobject_alive]]
- [[gui.dialogs.lifecycle.safe_disconnect]]
- [[gui.dialogs.lifecycle.wait_for_threads_later]]
- [[tests.test_remote_services._FaultInjectingLaunchWorker.setParent]]

