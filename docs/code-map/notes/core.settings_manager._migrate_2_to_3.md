---
kind: function
---

# _migrate_2_to_3(stored)

- 定义于：[[core.settings_manager]]
- 全名：core.settings_manager._migrate_2_to_3

> v2 → v3：剔除未知键（含 monkey_params 内的死键）并记录警告（ADR-0006）

## 调用

- [[core.settings_manager._prune_unknown_keys]]

