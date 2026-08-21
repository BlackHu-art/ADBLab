---
kind: method
---

# closeEvent(self, event)

- 定义于：[[gui.dialogs.live_logcat.LiveLogcatDialog]]
- 全名：gui.dialogs.live_logcat.LiveLogcatDialog.closeEvent

> 先隐藏并清理后台资源，完成后再销毁日志窗口

## 调用

- [[gui.dialogs.lifecycle.safe_disconnect]]
- [[gui.dialogs.live_logcat.LiveLogcatDialog._debug_lifecycle]]
- [[gui.dialogs.live_logcat.LiveLogcatDialog._disconnect_pkg_worker]]
- [[gui.dialogs.live_logcat.LiveLogcatDialog._disconnect_worker]]
- [[gui.dialogs.live_logcat.LiveLogcatDialog._owner_residual_tasks]]
- [[gui.dialogs.live_logcat.LiveLogcatDialog._release_logcat_worker]]
- [[gui.dialogs.live_logcat.LiveLogcatDialog._release_pkg_worker]]
- [[tests.test_phase2_mainframe_shutdown_gate.CloseEvent.accept]]
- [[tests.test_phase2_mainframe_shutdown_gate.CloseEvent.ignore]]

