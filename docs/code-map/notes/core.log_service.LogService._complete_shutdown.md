---
kind: method
---

# _complete_shutdown(self)

- 定义于：[[core.log_service.LogService]]
- 全名：core.log_service.LogService._complete_shutdown

> 在对象所属线程排空日志并同步停止全部 Qt 和文件资源

## 调用

- [[core.log_service.LogService._drain_buffer_locked]]
- [[core.log_service.LogService._emit_batch]]
- [[core.log_service.LogService._stop_flush_timer]]

