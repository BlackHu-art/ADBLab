---
kind: function
---

# test_remote_defer_worker_tracks_before_set_parent_failure(qt_application)

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_defer_worker_tracks_before_set_parent_failure

> defer 的辅助 Qt 操作失败前，worker 必须已经进入强引用集合

## 调用

- [[gui.panels.remote_panel.RemotePanel._defer_launch_worker_delete]]
- [[tests.test_remote_services._wait_for_qt]]

## 实例化

- [[tests.test_remote_services._FaultInjectingLaunchWorker]]

