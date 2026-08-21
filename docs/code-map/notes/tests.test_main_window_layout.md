---
kind: file
---

# tests.test_main_window_layout

- 路径：tests/test_main_window_layout.py

## 类

- [[tests.test_main_window_layout._FakeMouseButtons]] — （无 docstring）
- [[tests.test_main_window_layout._FakeScreen]] — （无 docstring）
- [[tests.test_main_window_layout._FakeScreenAdapter]] — 为 MainFrame 屏幕生命周期测试提供确定性 token 和信号
- [[tests.test_main_window_layout._MainFrameSettings]] — （无 docstring）
- [[tests.test_main_window_layout._VisibilityEventCounter]] — 记录真实 QWidget 的 Show/Hide 事件，不替换被测控件

## 函数

- [[tests.test_main_window_layout.assert_non_overlapping]] — 断言一组可见工具栏控件均位于父控件内且互不相交
- [[tests.test_main_window_layout.begin_native_user_resize]] — （无 docstring）
- [[tests.test_main_window_layout.build_main_frame]] — 用本地依赖替身构造 MainFrame，不访问 ADB 或外部 helper
- [[tests.test_main_window_layout.test_applied_preferred_size_uses_design_minimum_without_small_screen_cap]] — （无 docstring）
- [[tests.test_main_window_layout.test_apply_window_size_persists_without_resize_event]] — （无 docstring）
- [[tests.test_main_window_layout.test_configured_preferred_size_uses_design_minimum_without_small_screen_cap]] — （无 docstring）
- [[tests.test_main_window_layout.test_device_medium_compact_transition_does_not_collapse_wide_right_panel_rows]] — Devices 的高度反馈必须独立收敛，不能让宽右栏在相同宽度变成全单列
- [[tests.test_main_window_layout.test_frameless_resize_controller_builds_eight_invisible_edge_zones]] — （无 docstring）
- [[tests.test_main_window_layout.test_frameless_resize_zone_cancels_when_window_handle_is_missing]] — （无 docstring）
- [[tests.test_main_window_layout.test_frameless_resize_zone_reports_native_start_result]] — （无 docstring）
- [[tests.test_main_window_layout.test_frameless_resize_zones_follow_maximized_state]] — （无 docstring）
- [[tests.test_main_window_layout.test_initial_small_screen_clamp_is_not_recorded_as_user_resize]] — （无 docstring）
- [[tests.test_main_window_layout.test_main_frame_settings_update_falls_back_to_individual_keys]] — （无 docstring）
- [[tests.test_main_window_layout.test_main_frame_settings_update_prefers_batch_api]] — （无 docstring）
- [[tests.test_main_window_layout.test_main_window_resize_batch_settles_side_panel_once_with_final_geometry]] — 一次真实主窗口 resize 只能提交一代，并应用最终 viewport 几何
- [[tests.test_main_window_layout.test_marked_user_resize_without_screen_transition_is_saved_after_debounce]] — （无 docstring）
- [[tests.test_main_window_layout.test_minimum_window_keeps_log_panel_visible_with_large_font]] — 在隔离 Qt 进程中验证最小窗口和最大字号组合
- [[tests.test_main_window_layout.test_native_screen_resize_before_signal_does_not_replace_preferred_size]] — （无 docstring）
- [[tests.test_main_window_layout.test_normalize_panel_ratio]] — （无 docstring）
- [[tests.test_main_window_layout.test_normalize_window_size_handles_invalid_and_offscreen_values]] — （无 docstring）
- [[tests.test_main_window_layout.test_panel_ratio_round_trip_uses_actual_splitter_sizes]] — （无 docstring）
- [[tests.test_main_window_layout.test_programmatic_panel_ratio_triggers_responsive_reflow]] — （无 docstring）
- [[tests.test_main_window_layout.test_reflow_widgets_preserves_declared_column_weights]] — （无 docstring）
- [[tests.test_main_window_layout.test_responsive_column_count_expands_breakpoints_for_large_font]] — （无 docstring）
- [[tests.test_main_window_layout.test_responsive_column_count_uses_stable_breakpoints]] — （无 docstring）
- [[tests.test_main_window_layout.test_restore_default_window_size_leaves_maximized_state]] — （无 docstring）
- [[tests.test_main_window_layout.test_screen_binding_restores_preferred_size_and_disconnects_old_screen]] — （无 docstring）
- [[tests.test_main_window_layout.test_settings_dialog_opens_as_reusable_non_modal_window]] — （无 docstring）
- [[tests.test_main_window_layout.test_settings_dialog_reuses_existing_window]] — （无 docstring）
- [[tests.test_main_window_layout.test_show_binds_screen_once_after_window_handle_exists]] — （无 docstring）
- [[tests.test_main_window_layout.test_small_screen_clamp_does_not_replace_preferred_window_size]] — （无 docstring）
- [[tests.test_main_window_layout.test_supported_minimum_toolbar_keeps_every_action_directly_reachable]] — 860px 下不得出现空 More，原动作按钮必须完整留在工具栏
- [[tests.test_main_window_layout.test_toolbar_action_identity_and_single_trigger_survive_resize]] — 缩放前后 QAction/QToolButton 身份不变，单击仍只触发一次业务动作
- [[tests.test_main_window_layout.test_toolbar_buttons_are_excluded_from_window_drag_target]] — （无 docstring）
- [[tests.test_main_window_layout.test_toolbar_height_does_not_follow_vertical_window_resize]] — 在隔离 Qt 进程中验证工具栏只响应字体尺寸，不吸收窗口剩余高度
- [[tests.test_main_window_layout.test_toolbar_resize_does_not_toggle_stable_action_buttons]] — 成员未变化的连续缩放不能产生按钮 Show/Hide 往返
- [[tests.test_main_window_layout.test_unmarked_programmatic_resize_does_not_persist_after_debounce]] — （无 docstring）
- [[tests.test_main_window_layout.test_user_resize_keeps_only_latest_size_while_mouse_remains_pressed]] — （无 docstring）
- [[tests.test_main_window_layout.test_user_resize_waits_for_mouse_release_before_accepting_first_resize]] — （无 docstring）

