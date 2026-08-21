---
kind: method
---

# update(self, values)

- 定义于：[[core.settings_manager.AppSettings]]
- 全名：core.settings_manager.AppSettings.update

> 批量更新多项设置，并仅安排一次防抖持久化

## 调用

- [[core.settings_manager.AppSettings._schedule_save]]
- [[core.settings_manager._log_error]]
- [[core.settings_manager._normalise_setting]]

