---
kind: function
---

# test_remote_stop_launch_worker_fault_keeps_worker_owned_until_cleanup(qt_application, faults, expected_error, deferred)

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_stop_launch_worker_fault_keeps_worker_owned_until_cleanup

> worker 任一步异常后必须已等待删除，或由 orphan 集合强引用

## 调用

- [[tests.test_remote_services._wait_for_qt]]

## 实例化

- [[tests.test_remote_services._FaultInjectingLaunchWorker]]

