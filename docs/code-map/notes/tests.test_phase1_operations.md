---
kind: file
---

# tests.test_phase1_operations

- 路径：tests/test_phase1_operations.py

## 类

- [[tests.test_phase1_operations._EnvelopeModel]] — （无 docstring）
- [[tests.test_phase1_operations._FailingPool]] — （无 docstring）
- [[tests.test_phase1_operations._ImmediatePool]] — （无 docstring）

## 函数

- [[tests.test_phase1_operations._controller_for_operations]] — （无 docstring）
- [[tests.test_phase1_operations._manager]] — （无 docstring）
- [[tests.test_phase1_operations.test_async_command_carries_manager_generation_without_forwarding_it_to_model_method]] — （无 docstring）
- [[tests.test_phase1_operations.test_async_command_carries_owner_token_without_forwarding_it_to_model_method]] — （无 docstring）
- [[tests.test_phase1_operations.test_async_command_keeps_signal_signature_and_strips_reserved_operation_kwargs]] — （无 docstring）
- [[tests.test_phase1_operations.test_async_command_reports_business_runtime_error_with_same_operation_metadata]] — （无 docstring）
- [[tests.test_phase1_operations.test_async_command_submission_failure_is_synchronous_for_owner_cleanup]] — （无 docstring）
- [[tests.test_phase1_operations.test_cancel_pending_units_finishes_after_cancel_intent_was_already_recorded]] — （无 docstring）
- [[tests.test_phase1_operations.test_cancel_pending_units_preserves_all_completed_success_results]] — （无 docstring）
- [[tests.test_phase1_operations.test_cancel_pending_units_uses_current_results_and_finishes_atomically]] — （无 docstring）
- [[tests.test_phase1_operations.test_cancellation_is_idempotent_intent_and_does_not_choose_terminal_state]] — （无 docstring）
- [[tests.test_phase1_operations.test_cancellation_token_only_accepts_one_concurrent_request]] — （无 docstring）
- [[tests.test_phase1_operations.test_concurrent_terminal_writes_have_exactly_one_winner]] — （无 docstring）
- [[tests.test_phase1_operations.test_controller_drops_stale_metadata_instead_of_falling_back_to_legacy_handler]] — （无 docstring）
- [[tests.test_phase1_operations.test_controller_handler_exception_fails_and_cleans_operation_once]] — （无 docstring）
- [[tests.test_phase1_operations.test_controller_routes_metadata_only_to_registered_vnext_handler]] — （无 docstring）
- [[tests.test_phase1_operations.test_every_operation_mutation_rejects_wrong_generation_before_validation]] — （无 docstring）
- [[tests.test_phase1_operations.test_fanout_aggregation_has_explicit_partial_failure_semantics]] — （无 docstring）
- [[tests.test_phase1_operations.test_fanout_rejects_missing_unknown_and_conflicting_unit_results]] — （无 docstring）
- [[tests.test_phase1_operations.test_guarded_mutations_reject_stale_generation_before_input_validation]] — （无 docstring）
- [[tests.test_phase1_operations.test_operation_artifacts_are_idempotent_and_bound_to_expected_units]] — （无 docstring）
- [[tests.test_phase1_operations.test_operation_envelope_round_trips_arbitrary_legacy_payload]] — （无 docstring）
- [[tests.test_phase1_operations.test_operation_generation_is_opaque_and_compare_safe_across_reused_ids]] — （无 docstring）
- [[tests.test_phase1_operations.test_operation_rejects_invalid_transition_and_backwards_progress]] — （无 docstring）
- [[tests.test_phase1_operations.test_operation_state_machine_cleans_terminal_entry_and_ignores_duplicate_finish]] — （无 docstring）
- [[tests.test_phase1_operations.test_unguarded_mutations_keep_legacy_input_validation_for_missing_operation]] — （无 docstring）

