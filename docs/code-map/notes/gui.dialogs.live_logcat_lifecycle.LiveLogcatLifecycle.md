---
kind: class
---

# LiveLogcatLifecycle

- 模块：[[gui.dialogs.live_logcat_lifecycle]]
- 全名：gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle

> 组合进 LiveLogcatDialog 的生命周期控制器，通过 ``self._frame`` 访问对话框

## 方法

- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle.__init__]] — （无 docstring）
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._on_task_stopped]] — （无 docstring）
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._on_current_pkg]] — （无 docstring）
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._release_pkg_worker]] — 释放已经停止的包名查询线程，并返回它是否仍是当前线程
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._on_pkg_worker_finished]] — （无 docstring）
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._release_logcat_worker]] — 仅在线程和受跟踪进程都停止后释放 Logcat 工作对象
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._on_worker_finished]] — （无 docstring）
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._poll_worker_release]] — 在窗口保持打开时释放线程先结束、进程稍后退出的日志任务
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._owner_residual_tasks]] — 返回仍由当前日志窗口负责的受监督资源
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._schedule_cleanup_recheck]] — 在停止流程返回后继续观察晚退出的线程或外部进程
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._poll_close_cleanup]] — 重新核对资源屏障，避免线程先结束而进程晚退出时丢失唤醒
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._prune_stopped_owner_tasks]] — 注销已确认停止但仍残留在监督注册表中的当前窗口任务
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._try_finalize_close]] — 仅在工作对象和监督注册均清零后允许销毁窗口
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._on_owner_stopped]] — 停止流程返回后复核真实资源屏障，不把超时误判为已停止
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._disconnect_worker]] — （无 docstring）
- [[gui.dialogs.live_logcat_lifecycle.LiveLogcatLifecycle._disconnect_pkg_worker]] — （无 docstring）

