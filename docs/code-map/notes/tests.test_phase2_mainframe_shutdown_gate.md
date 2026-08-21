---
kind: file
---

# tests.test_phase2_mainframe_shutdown_gate

- 路径：tests/test_phase2_mainframe_shutdown_gate.py

## 类

- [[tests.test_phase2_mainframe_shutdown_gate.CloseEvent]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.FakeLeftPanel]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.ScanThread]] — （无 docstring）

## 函数

- [[tests.test_phase2_mainframe_shutdown_gate._bind_settings_finalizer]] — 让关机用例只保存自身设置，避免共享事件队列命中其他用例的全局补丁
- [[tests.test_phase2_mainframe_shutdown_gate._drain_frame_signals]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate._drive_until]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate._frame]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_active_dialog_tasks_are_registered_before_dialog_close]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_application_shutdown_lane_is_not_starved_by_owner_cleanup_pool]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_application_stop_broadcasts_across_owners_before_any_wait]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_application_stop_uses_one_wall_clock_deadline_for_many_slow_tasks]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_late_scan_notifications_are_ignored_after_close_starts]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_mainframe_deadline_closes_with_residual_without_claiming_resource_zero]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_mainframe_two_stage_close_is_nonblocking_broadcast_first_and_idempotent]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_performance_dialog_close_delegates_running_stop_without_waiting]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_preclaimed_task_remains_visible_to_application_residual_snapshot]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_shutdown_callable_failure_is_failed_and_remains_residual]] — （无 docstring）
- [[tests.test_phase2_mainframe_shutdown_gate.test_slow_shutdown_finalizer_does_not_block_gui_and_is_reported_residual]] — （无 docstring）

