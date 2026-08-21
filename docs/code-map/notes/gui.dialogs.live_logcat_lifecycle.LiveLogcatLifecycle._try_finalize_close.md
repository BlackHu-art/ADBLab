---
kind: method
---

# _try_finalize_close(self, trigger, *, log_deferred=True)

- 定义于：[[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle]]
- 全名：gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._try_finalize_close

> 仅在工作对象和监督注册均清零后允许销毁窗口

## 调用

- [[gui.dialogs.lifecycle.safe_disconnect]]
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._owner_residual_tasks]]
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._prune_stopped_owner_tasks]]
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._release_logcat_worker]]
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._release_pkg_worker]]
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._schedule_cleanup_recheck]]

