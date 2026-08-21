---
kind: function
---

# _bind_settings_finalizer(frame, settings)

- 定义于：[[tests.test_phase2_mainframe_shutdown_gate]]
- 全名：tests.test_phase2_mainframe_shutdown_gate._bind_settings_finalizer

> 让关机用例只保存自身设置，避免共享事件队列命中其他用例的全局补丁

## 调用

- [[core.settings_manager.AppSettings._save_atomic]]

