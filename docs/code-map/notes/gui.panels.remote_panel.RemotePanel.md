---
kind: class
---

# RemotePanel

- 模块：[[gui.panels.remote_panel]]
- 全名：gui.panels.remote_panel.RemotePanel

> 管理 scrcpy 会话、串行 Remote 输入队列和相关界面状态

## 方法

- [[gui.panels.remote_panel.RemotePanel.__init__]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel.connect_signals]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._update_action_states]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel.update_action_states]] — 供设备选择协调层刷新 Remote Start 的可用状态
- [[gui.panels.remote_panel.RemotePanel._set_running]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._update_status]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._selected_remote_device]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._should_ignore_scrcpy_log_line]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel.showEvent]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._log]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._redact_remote_diagnostic]] — 移除 Remote 诊断信息中的当前设备标识，并限制异常输出长度
- [[gui.panels.remote_panel.RemotePanel.shutdown]] — 先停止 scrcpy 和启动 worker，再关闭输入队列及持久 ADB 会话
- [[gui.panels.remote_panel.RemotePanel.register_shutdown_task]] — 在界面断开引用前注册 scrcpy、启动 worker 和输入会话清理任务
- [[gui.panels.remote_panel.RemotePanel._shutdown_lifecycle_lock]] — 兼容轻量测试实例，并为直接关闭与 supervisor 提供同一把锁
- [[gui.panels.remote_panel.RemotePanel._disconnect_launch_worker]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._defer_launch_worker_delete]] — 持有未回收 worker，并在其 GUI 线程中执行有界删除重试
- [[gui.panels.remote_panel.RemotePanel._schedule_launch_worker_delete]] — 幂等安排一次删除尝试；真实 QObject 始终回到自身 GUI 线程执行
- [[gui.panels.remote_panel.RemotePanel._retry_launch_worker_delete]] — 执行一次删除尝试，并在固定次数耗尽后进入明确终态
- [[gui.panels.remote_panel.RemotePanel._release_stopped_launch_worker]] — 仅在线程明确停止时释放残余；运行或未知状态继续强引用
- [[gui.panels.remote_panel.RemotePanel._forget_launch_worker]] — 原子移除指定 worker 的回收状态和进程级强引用
- [[gui.panels.remote_panel.RemotePanel.closeEvent]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel.build_ui]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._build_mirroring]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._create_checkbox]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._build_control]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._remote_key_button]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._remote_action_button]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._startup_configuration_controls]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._on_custom_setting_changed]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._save]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._save_all]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._load]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel.reload_from_settings]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._on_preset_changed]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._on_record_toggled]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._allocate_record_path]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._display_record_path]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._start_scrcpy]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._on_launch_ready]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._on_launch_finished]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._read_stderr]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._poll_process]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._stop_scrcpy]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._on_stop_completed]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._set_session_state]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._scrcpy_config]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._focus_scrcpy_window]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._stop_launch_worker]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._claim_scrcpy_stop]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._release_scrcpy_stop_claim]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._reset_scrcpy_stop_claim]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._request_scrcpy_stop_once]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._request_launch_worker_interruption_once]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._submit_remote_input]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._mark_remote_submitted]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._mark_remote_completed]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._remote_input_succeeded]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._emit_remote_queue_status]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._update_remote_queue_status]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._send_keyevent]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._send_remote_action]] — （无 docstring）
- [[gui.panels.remote_panel.RemotePanel._warm_remote_input_session]] — （无 docstring）

