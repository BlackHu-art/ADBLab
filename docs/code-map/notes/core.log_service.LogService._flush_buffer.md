---
kind: method
---

# _flush_buffer(self)

- 定义于：[[core.log_service.LogService]]
- 全名：core.log_service.LogService._flush_buffer

> 在对象所属线程中取出并发布当前用户日志批次

## 调用

- [[core.log_service.LogService._drain_buffer_locked]]
- [[core.log_service.LogService._emit_batch]]
- [[core.log_service.LogService._request_stop_flush_timer]]

