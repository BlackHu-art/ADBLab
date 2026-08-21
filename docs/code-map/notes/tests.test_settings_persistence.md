---
kind: file
---

# tests.test_settings_persistence

> 验证正式设置键在应用重建后的持久化与旧 JSON 兼容性

- 路径：tests/test_settings_persistence.py

## 函数

- [[tests.test_settings_persistence.isolated_settings]] — 把 AppSettings 单例和文件路径隔离到临时目录
- [[tests.test_settings_persistence.test_existing_json_scrcpy_keys_load_without_migration]] — （无 docstring）
- [[tests.test_settings_persistence.test_future_schema_version_keeps_known_values_and_version]] — （无 docstring）
- [[tests.test_settings_persistence.test_saved_file_stamps_current_schema_version]] — （无 docstring）
- [[tests.test_settings_persistence.test_scrcpy_settings_round_trip_across_app_settings_rebuild]] — （无 docstring）
- [[tests.test_settings_persistence.test_unknown_keys_pruned_with_warning]] — （无 docstring）
- [[tests.test_settings_persistence.test_update_ignores_schema_version]] — （无 docstring）
- [[tests.test_settings_persistence.test_v1_file_migrates_and_stamps_current_schema_version]] — （无 docstring）

