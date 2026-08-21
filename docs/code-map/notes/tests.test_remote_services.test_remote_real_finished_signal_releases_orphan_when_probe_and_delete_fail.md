---
kind: function
---

# test_remote_real_finished_signal_releases_orphan_when_probe_and_delete_fail(qt_application)

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_real_finished_signal_releases_orphan_when_probe_and_delete_fail

> 真实 finished 是可靠终态，探测与删除永久失败也不得留下回收闭包

## 调用

- [[gui.panels.remote_panel.RemotePanel._defer_launch_worker_delete]]
- [[gui.panels.remote_panel.RemotePanel._forget_launch_worker]]
- [[tests.test_remote_services._wait_for_qt]]

## 实例化

- [[tests.test_remote_services._ProbeAndDeleteFailingQThread]]

