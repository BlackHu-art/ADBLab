---
kind: file
---

# tests.test_remote_services

- 路径：tests/test_remote_services.py

## 类

- [[tests.test_remote_services._DeleteFailingQThread]] — 用真实线程完成信号验证删除重试，不允许测试手工重发 ``finished``
- [[tests.test_remote_services._FaultInjectingLaunchWorker]] — 在指定 QThread 生命周期步骤注入异常，并记录最终所有权动作
- [[tests.test_remote_services._ProbeAndDeleteFailingQThread]] — 真实发出 ``finished``，同时永久拒绝状态探测和延迟删除
- [[tests.test_remote_services._TestSignal]] — 提供 launch worker 延迟释放测试所需的最小信号协议

## 函数

- [[tests.test_remote_services._scrcpy_config]] — （无 docstring）
- [[tests.test_remote_services._wait_for_qt]] — 在有界事件循环轮次内等待真实 Qt 回收条件
- [[tests.test_remote_services.test_adb_bridge_warm_input_session_prepares_persistent_session]] — （无 docstring）
- [[tests.test_remote_services.test_adb_input_session_warm_opens_shell_without_writing_input]] — （无 docstring）
- [[tests.test_remote_services.test_build_scrcpy_args_appends_extra_args_before_print_fps]] — （无 docstring）
- [[tests.test_remote_services.test_build_scrcpy_args_enables_prefer_text_and_window_title]] — （无 docstring）
- [[tests.test_remote_services.test_remote_control_service_perform_action_dispatches_known_actions]] — （无 docstring）
- [[tests.test_remote_services.test_remote_control_service_perform_action_rejects_unknown_action]] — （无 docstring）
- [[tests.test_remote_services.test_remote_control_service_reuses_cached_dimensions_for_fast_gestures]] — （无 docstring）
- [[tests.test_remote_services.test_remote_control_service_rotation_clears_dimension_cache]] — （无 docstring）
- [[tests.test_remote_services.test_remote_control_service_rotation_falls_back_to_legacy_setting]] — （无 docstring）
- [[tests.test_remote_services.test_remote_control_service_sends_keyevent_and_directional_swipe]] — （无 docstring）
- [[tests.test_remote_services.test_remote_control_service_uses_launch_plan_dimensions_without_adb_query]] — （无 docstring）
- [[tests.test_remote_services.test_remote_defer_worker_tracks_before_set_parent_failure]] — defer 的辅助 Qt 操作失败前，worker 必须已经进入强引用集合
- [[tests.test_remote_services.test_remote_finished_delete_failure_releases_after_bounded_retries]] — finished 已确认终止时，删除耗尽后必须结束 orphan 跟踪
- [[tests.test_remote_services.test_remote_finished_qthread_delete_retry_exhaustion_has_finite_terminal_state]] — 删除始终失败时，已停止线程不得永久残留或继续忙重试
- [[tests.test_remote_services.test_remote_finished_qthread_retries_delete_without_reemitting_finished]] — 已结束线程的首次删除失败后，事件循环必须主动重试而不是等待旧信号
- [[tests.test_remote_services.test_remote_input_engine_delegates_window_focus]] — （无 docstring）
- [[tests.test_remote_services.test_remote_mapping_uses_safe_default_dimensions]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_close_requests_scrcpy_stop_without_waiting]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_control_targets_selected_device_without_mirroring_session]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_controls_follow_full_session_state]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_failed_stop_restores_running_controls_for_live_process]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_ignores_known_scrcpy_noise_lines]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_ignores_repeated_stop_while_stopping]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_launch_failure_returns_controls_to_idle]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_launch_finished_clears_active_device_when_start_fails]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_launch_finished_only_recycles_stale_worker]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_launch_ready_uses_scrcpy_service_start]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_remote_action_delegates_to_control_service]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_remote_action_uses_executor_when_available]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_shutdown_detaches_launch_worker_without_blocking]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_start_ignores_shortcut_while_stopping_after_worker_exits]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_start_scrcpy_resolves_executable_via_service]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_stop_scrcpy_uses_scrcpy_service_stop]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_successful_stop_completion_returns_to_idle]] — （无 docstring）
- [[tests.test_remote_services.test_remote_panel_worker_start_failure_returns_to_idle]] — （无 docstring）
- [[tests.test_remote_services.test_remote_real_finished_signal_releases_orphan_when_probe_and_delete_fail]] — 真实 finished 是可靠终态，探测与删除永久失败也不得留下回收闭包
- [[tests.test_remote_services.test_remote_shutdown_claim_before_user_stop_does_not_start_blocking_stop]] — 关闭链路先取得 claim 后，晚到的用户 Stop 不得创建第二位 owner
- [[tests.test_remote_services.test_remote_shutdown_executor_exception_does_not_skip_adb_cleanup]] — 输入执行器关闭失败时，持久 ADB 会话仍由独立边界清理
- [[tests.test_remote_services.test_remote_shutdown_input_thread_start_failure_closes_sessions_synchronously]] — direct shutdown 在线程无法启动时也必须实际关闭持久输入会话
- [[tests.test_remote_services.test_remote_shutdown_request_exception_allows_supervisor_retry_and_input_cleanup]] — 直接停止异常后 supervisor 可重试，executor 与 ADB 清理仍能完成
- [[tests.test_remote_services.test_remote_shutdown_worker_exception_does_not_skip_executor_or_adb_cleanup]] — 启动 worker 清理失败时，executor 与 ADB 会话仍各自收口
- [[tests.test_remote_services.test_remote_stop_claim_release_cannot_clear_a_new_session_claim]] — 旧停止调用晚到释放时，不得清除新会话已经取得的 claim
- [[tests.test_remote_services.test_remote_stop_launch_worker_fault_keeps_worker_owned_until_cleanup]] — worker 任一步异常后必须已等待删除，或由 orphan 集合强引用
- [[tests.test_remote_services.test_remote_supervisor_async_input_error_survives_process_timeout]] — 正常启动的输入清理线程失败时，进程残余结果必须保留关闭异常
- [[tests.test_remote_services.test_remote_supervisor_input_fallback_error_survives_process_timeout]] — 进程同时超时时，输入同步兜底的实际异常仍应作为残余原因上报
- [[tests.test_remote_services.test_remote_supervisor_input_fallback_failure_stays_visible_and_not_graceful]] — 同步输入兜底也失败时，监督结果必须保留失败和残余证据
- [[tests.test_remote_services.test_remote_supervisor_input_thread_start_failure_completes_with_error]] — 输入清理线程无法启动时，必须同步关闭真实持久会话后再收口
- [[tests.test_remote_services.test_remote_supervisor_process_probe_exception_still_requests_all_cleanup]] — 进程探测异常应回传错误，但不能阻止 scrcpy 请求与 ADB 会话清理
- [[tests.test_remote_services.test_remote_user_stop_claim_prevents_shutdown_and_supervisor_duplicate_terminate]] — 用户 Stop 正在等待时，直接关闭与 supervisor 不得再次终止同一进程
- [[tests.test_remote_services.test_remote_user_stop_exception_releases_claim_for_shutdown_retry]] — 阻塞 stop 抛错后释放当前 token，让关闭路径可以重新请求停止
- [[tests.test_remote_services.test_remote_window_manager_focus_accepts_already_foreground_window]] — （无 docstring）
- [[tests.test_remote_services.test_remote_window_manager_non_windows_focus_is_noop]] — （无 docstring）
- [[tests.test_remote_services.test_scrcpy_service_builds_launch_plan_with_preflight_and_encoder]] — （无 docstring）
- [[tests.test_remote_services.test_scrcpy_service_caches_version_per_executable]] — （无 docstring）
- [[tests.test_remote_services.test_scrcpy_service_force_stop_only_confirms_released_process_key]] — 底层只尝试 kill 但进程仍受跟踪时，不得把强停误报为成功
- [[tests.test_remote_services.test_scrcpy_service_launch_plan_warns_and_skips_device_info_when_preflight_fails]] — （无 docstring）
- [[tests.test_remote_services.test_scrcpy_service_parse_fps_returns_status_text]] — （无 docstring）
- [[tests.test_remote_services.test_scrcpy_service_resolves_bundled_windows_executable]] — （无 docstring）
- [[tests.test_remote_services.test_scrcpy_service_resolves_path_scrcpy_on_non_windows]] — （无 docstring）
- [[tests.test_remote_services.test_scrcpy_service_start_and_stop_delegate_to_process_runner]] — （无 docstring）
- [[tests.test_remote_services.test_task_supervisor_completed_task_with_completion_error_remains_failed]] — 资源已停止但清理失败时，单项与批量路径都不得报告成功或移除残余
- [[tests.test_remote_services.test_task_supervisor_timeout_error_priority_is_identical_for_single_and_batch]] — 超时结果按 force、request、completion 顺序保留最有用的错误

