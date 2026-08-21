---
kind: function
---

# test_remote_user_stop_claim_prevents_shutdown_and_supervisor_duplicate_terminate(qt_application)

- 定义于：[[tests.test_remote_services]]
- 全名：tests.test_remote_services.test_remote_user_stop_claim_prevents_shutdown_and_supervisor_duplicate_terminate

> 用户 Stop 正在等待时，直接关闭与 supervisor 不得再次终止同一进程

## 调用

- [[gui.panels.remote_panel.RemotePanel.register_shutdown_task]]
- [[gui.panels.side_panel.SidePanel._ensure_tab_loaded]]

## 实例化

- [[adblab.application.supervision.TaskSupervisor]]
- [[core.exec.ProcessRunner]]
- [[gui.panels.side_panel.SidePanel]]
- [[tests.test_phase2_live_logcat_gate.BlockingProcess]]

