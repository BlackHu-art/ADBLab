---
kind: function
---

# test_finished_before_timeout_rechecks_process_that_exits_later()

- 定义于：[[tests.test_phase2_live_logcat_gate]]
- 全名：tests.test_phase2_live_logcat_gate.test_finished_before_timeout_rechecks_process_that_exits_later

> 线程完成信号早到时，仍要观察随后退出的外部进程并最终销毁窗口

## 调用

- [[core.settings_manager.AppSettings.instance]]

## 实例化

- [[adblab.application.supervision.TaskStopResult]]
- [[gui.dialogs.live_logcat.LiveLogcatDialog]]
- [[tests.test_phase2_live_logcat_gate.FakeDialogWorker]]
- [[tests.test_phase2_live_logcat_gate.FakeQtTaskSupervisor]]

