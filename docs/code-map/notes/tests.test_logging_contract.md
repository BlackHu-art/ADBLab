---
kind: file
---

# tests.test_logging_contract

> 验证应用日志与开发调试日志之间的隔离契约

- 路径：tests/test_logging_contract.py

## 函数

- [[tests.test_logging_contract.create_log_service]] — 为每个用例隔离进程级日志服务，避免停止状态在用例之间传播
- [[tests.test_logging_contract.test_debug_is_silent_when_frozen_or_stderr_is_unavailable]] — （无 docstring）
- [[tests.test_logging_contract.test_debug_lines_are_atomic_across_worker_threads]] — （无 docstring）
- [[tests.test_logging_contract.test_debug_only_writes_to_source_stderr]] — （无 docstring）
- [[tests.test_logging_contract.test_developer_console_can_be_used_without_constructing_log_service]] — （无 docstring）
- [[tests.test_logging_contract.test_file_logging_uses_user_directory_and_excludes_debug]] — （无 docstring）
- [[tests.test_logging_contract.test_initialization_preserves_root_logger_handlers]] — （无 docstring）
- [[tests.test_logging_contract.test_log_panel_applies_new_line_limit_immediately]] — （无 docstring）
- [[tests.test_logging_contract.test_log_panel_batch_records_carry_source_timestamps]] — （无 docstring）
- [[tests.test_logging_contract.test_log_panel_renders_records_verbatim]] — 面板不再二次过滤级别：DEBUG 拦截是 LogService 的单一职责
- [[tests.test_logging_contract.test_shutdown_is_idempotent_and_rejects_late_logs]] — （无 docstring）
- [[tests.test_logging_contract.test_shutdown_rejects_worker_thread_call]] — （无 docstring）
- [[tests.test_logging_contract.test_worker_request_shutdown_is_nonblocking_and_completes_on_owner_thread]] — （无 docstring）

