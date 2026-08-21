---
kind: method
---

# _poll_close_cleanup(self)

- 定义于：[[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle]]
- 全名：gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._poll_close_cleanup

> 重新核对资源屏障，避免线程先结束而进程晚退出时丢失唤醒

## 调用

- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._schedule_cleanup_recheck]]
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._try_finalize_close]]

