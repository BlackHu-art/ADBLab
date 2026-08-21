---
kind: function
---

# test_remote_finished_delete_failure_releases_after_bounded_retries(qt_application)

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_finished_delete_failure_releases_after_bounded_retries

> finished 已确认终止时，删除耗尽后必须结束 orphan 跟踪

## 调用

- [[gui.panels.remote_panel.RemotePanel._defer_launch_worker_delete]]
- [[tests.test_remote_services._wait_for_qt]]

## 实例化

- [[tests.test_remote_services._FaultInjectingLaunchWorker]]

