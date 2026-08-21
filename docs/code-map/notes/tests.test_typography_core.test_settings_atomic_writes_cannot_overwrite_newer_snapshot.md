---
kind: function
---

# test_settings_atomic_writes_cannot_overwrite_newer_snapshot(tmp_path, monkeypatch)

- 定义于：[[tests.test_typography_core]]
- 全名：tests.test_typography_core.test_settings_atomic_writes_cannot_overwrite_newer_snapshot

> 并发保存必须在取得写锁后取快照，最终文件保留最新设置

