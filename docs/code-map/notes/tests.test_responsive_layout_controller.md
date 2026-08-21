---
kind: file
---

# tests.test_responsive_layout_controller

- 路径：tests/test_responsive_layout_controller.py

## 类

- [[tests.test_responsive_layout_controller.FakeTarget]] — （无 docstring）
- [[tests.test_responsive_layout_controller.MetricWidget]] — （无 docstring）
- [[tests.test_responsive_layout_controller.RecordingBinding]] — （无 docstring）
- [[tests.test_responsive_layout_controller.ResizeEchoTarget]] — 记录每代真实采用的最终宽度，模拟用户连续拖动顶层窗口

## 函数

- [[tests.test_responsive_layout_controller.test_binding_applies_complete_plan_and_exposes_conservative_snapshot]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_binding_column_minimums_match_weighted_plan_geometry_and_clear_when_narrowed]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_binding_rebuilds_context_and_remeasures_every_round]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_binding_rejects_reversed_modes_before_context_provider_runs]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_binding_unregisters_when_container_is_destroyed]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_bound_context_provider_owner_is_weak_and_not_called_after_pending_delete]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_coordinator_attach_top_level_routes_responsive_events]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_coordinator_attaches_real_window_handle_screen_signal_after_show]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_coordinator_coalesces_external_burst_and_forces_conservative_third_plan]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_coordinator_detach_reattach_keeps_one_destroyed_cleanup]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_coordinator_fallback_locks_a_to_b_to_a_oscillation]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_coordinator_fallback_only_conservatizes_targets_that_are_still_changing]] — 一个目标达到轮次上限时，不得把同批稳定目标一起降到最保守模式
- [[tests.test_responsive_layout_controller.test_coordinator_rebinds_screen_signal_when_window_handle_changes]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_external_reasons_during_settling_create_one_followup_generation]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_height_only_settling_snapshot_does_not_consume_an_apply_round]] — 行高反馈只同步只读快照，后续真实宽度变化仍可在本代正常应用
- [[tests.test_responsive_layout_controller.test_internal_layout_request_during_settling_does_not_create_generation]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_paired_modes_keep_every_label_next_to_its_field]] — paired_mode 必须显式保证所有 label-field 在 3/2/1 组布局中相邻
- [[tests.test_responsive_layout_controller.test_plan_distributes_span_deficit_by_positive_column_weights]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_plan_distributes_spanning_item_deficit_across_covered_columns]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_plan_orders_modes_by_strict_conservatism_rank_and_fingerprints_all_inputs]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_plan_rejects_invalid_mode_definitions]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_plan_reports_fit_and_minimum_column_overflow]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_real_binding_forces_third_round_fallback_and_one_readonly_verify]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_real_binding_queued_layout_request_does_not_start_extra_generation]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_real_binding_scheduled_round_does_not_access_deleted_qobject]] — （无 docstring）
- [[tests.test_responsive_layout_controller.test_resize_drag_coalesces_interleaved_events_and_applies_only_final_width]] — 真实拖动会在 resize 之间处理事件，仍只能在尾沿提交一次最终布局
- [[tests.test_responsive_layout_controller.test_shrinkable_binding_does_not_use_dynamic_preferred_width]] — SHRINKABLE 的布局度量不得随当前文本造成的 sizeHint 漂移
- [[tests.test_responsive_layout_controller.test_span_tail_plan_uses_full_second_row_and_real_width]] — （无 docstring）

