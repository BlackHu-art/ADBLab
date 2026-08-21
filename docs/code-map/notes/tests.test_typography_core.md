---
kind: file
---

# tests.test_typography_core

> 验证字体核心层、独立信号和设置批量持久化

- 路径：tests/test_typography_core.py

## 函数

- [[tests.test_typography_core.test_font_config_validates_sizes_and_falls_back_to_system_family]] — （无 docstring）
- [[tests.test_typography_core.test_reload_updates_legacy_projection_before_signal_and_does_not_emit_theme]] — （无 docstring）
- [[tests.test_typography_core.test_settings_atomic_writes_cannot_overwrite_newer_snapshot]] — 并发保存必须在取得写锁后取快照，最终文件保留最新设置
- [[tests.test_typography_core.test_settings_load_migrates_legacy_panel_widths_to_ratio]] — （无 docstring）
- [[tests.test_typography_core.test_settings_loads_and_validates_device_log_split_ratio]] — （无 docstring）
- [[tests.test_typography_core.test_settings_update_validates_fonts_and_schedules_one_save]] — （无 docstring）
- [[tests.test_typography_core.test_typography_manager_emits_only_changed_role_and_sets_application_font]] — （无 docstring）

