---
kind: method
---

# closeEvent(self, event)

- 定义于：[[gui.dialogs.file_explorer.FileExplorerDialog]]
- 全名：gui.dialogs.file_explorer.FileExplorerDialog.closeEvent

> 先隔离全部界面回调，再中止并持续持有尚未退出的 worker

## 调用

- [[gui.dialogs.file_explorer.FileExplorerDialog._disconnect_worker_ui]]
- [[gui.dialogs.file_explorer.FileExplorerDialog._retain_workers_until_stopped]]
- [[gui.dialogs.lifecycle.safe_disconnect]]

