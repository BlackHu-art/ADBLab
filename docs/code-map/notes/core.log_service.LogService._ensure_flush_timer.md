---
kind: method
---

# _ensure_flush_timer(self)

- 定义于：[[core.log_service.LogService]]
- 全名：core.log_service.LogService._ensure_flush_timer

> 确保刷新定时器只在 LogService 所在线程启动，避免跨线程操作 QTimer

