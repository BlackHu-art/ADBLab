---
kind: function
---

# test_remote_finished_qthread_retries_delete_without_reemitting_finished(qt_application)

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_finished_qthread_retries_delete_without_reemitting_finished

> 已结束线程的首次删除失败后，事件循环必须主动重试而不是等待旧信号

## 调用

- [[tests.test_remote_services._wait_for_qt]]

## 实例化

- [[tests.test_remote_services._DeleteFailingQThread]]

