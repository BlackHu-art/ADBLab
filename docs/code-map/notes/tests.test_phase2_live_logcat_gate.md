---
kind: file
---

# tests.test_phase2_live_logcat_gate

- 路径：tests/test_phase2_live_logcat_gate.py

## 类

- [[tests.test_phase2_live_logcat_gate.BlockingProcess]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.FakeDialogWorker]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.FakeProcess]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.FakeQtTaskSupervisor]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.FakeStdout]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.YieldingProcess]] — （无 docstring）

## 函数

- [[tests.test_phase2_live_logcat_gate.test_active_logcat_close_keeps_main_window_open_until_cleanup_finishes]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_concurrent_duplicate_stop_has_only_one_resource_owner]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_continuous_logcat_close_stress_never_enters_main_window_exit_path]] — 在隔离进程中覆盖真实延迟删除、高频输出和应用退出信号
- [[tests.test_phase2_live_logcat_gate.test_cross_thread_burst_keeps_transport_bounded]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_dialog_acknowledges_late_batch_without_touching_closed_ui]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_dialog_reports_graceful_forced_and_orphan_cleanup_distinctly]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_disconnect_clears_dialog_capturing_handlers_from_orphan_worker]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_finished_before_timeout_rechecks_process_that_exits_later]] — 线程完成信号早到时，仍要观察随后退出的外部进程并最终销毁窗口
- [[tests.test_phase2_live_logcat_gate.test_late_old_worker_finished_cannot_clear_new_worker]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_live_logcat_stop_and_close_only_schedule_background_cleanup]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_logcat_cancel_before_run_never_spawns_process]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_logcat_pid_probe_failure_is_start_failure_without_spawn]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_logcat_producer_batches_lines_and_bounds_each_transport_message]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_logcat_transport_drops_instead_of_growing_unbounded]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_logcat_transport_resumes_and_reports_drops_after_ack]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_mainframe_composition_root_injects_owned_supervisor_into_logcat_dialogs]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_mainframe_does_not_reopen_a_logcat_dialog_that_is_closing]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_owner_stop_broadcasts_all_requests_before_waiting_and_shares_deadline]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_owner_timeout_keeps_logcat_dialog_alive_until_worker_really_finishes]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_process_runner_does_not_untrack_a_process_that_survives_stop]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_qt_supervisor_keeps_event_loop_responsive_during_stubborn_cleanup]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_real_qthread_dialog_close_reaps_blocking_process_off_gui_thread]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_task_stop_callback_releases_worker_after_process_exits_late]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_task_supervisor_distinguishes_graceful_and_forced_stop]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_task_supervisor_retains_timed_out_orphan]] — （无 docstring）
- [[tests.test_phase2_live_logcat_gate.test_worker_finished_does_not_unregister_a_surviving_process]] — （无 docstring）

