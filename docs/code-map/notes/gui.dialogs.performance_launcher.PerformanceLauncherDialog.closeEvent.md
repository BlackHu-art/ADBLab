---
kind: method
---

# closeEvent(self, event)

- 定义于：[[gui.dialogs.performance_launcher.PerformanceLauncherDialog]]
- 全名：gui.dialogs.performance_launcher.PerformanceLauncherDialog.closeEvent

> 停止界面定时器并断开信号，资源等待由已注册的关闭任务接管

## 调用

- [[gui.dialogs.lifecycle.safe_disconnect]]
- [[gui.dialogs.lifecycle.wait_for_thread_later]]
- [[gui.dialogs.performance_launcher.PerformanceLauncherDialog.stop_mobileperf]]
- [[tests.test_remote_services._FaultInjectingLaunchWorker.requestInterruption]]
- [[tests.test_remote_services._FaultInjectingLaunchWorker.setParent]]

