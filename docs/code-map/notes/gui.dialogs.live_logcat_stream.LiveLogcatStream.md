---
kind: class
---

# LiveLogcatStream

- 模块：[[gui.dialogs.live_logcat_stream]]
- 全名：gui.dialogs.live_logcat_stream.LiveLogcatStream

> 组合进 LiveLogcatDialog 的流式控制器，通过 ``self._frame`` 访问对话框

## 方法

- [[gui.dialogs.live_logcat_stream.LiveLogcatStream.__init__]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._min_level]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._passes]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._rebuild]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._schedule_filter_rebuild]] — 合并连续输入，避免每个按键都完整重建日志文档
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._update_content_actions]] — 按已知可见状态更新动作，避免复制整份日志文档
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._fetch_current_pkg]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._start]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._stop]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._clear]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._toggle_wrap]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._export]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_lines_signal]] — 通过对话框 QObject 槽接收批次，避免匿名回调越过窗口生命周期
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_dropped_signal]] — 接收当前工作线程报告的背压丢弃数量
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_worker_status_signal]] — 接收当前工作线程的状态变更
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_worker_terminated_signal]] — 接收当前工作线程的终止语义
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_worker_finished_signal]] — 在线程 finished 信号到达 GUI 线程后释放工作对象
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_pkg_worker_finished_signal]] — 在包名查询线程 finished 信号到达 GUI 线程后释放工作对象
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._extract_tag]] — 从 threadtime 格式日志中提取 TAG 字段
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_line]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_lines]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_dropped]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._schedule_line_flush]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._flush_pending_lines]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_status]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_worker_status]] — （无 docstring）
- [[gui.dialogs.live_logcat_stream.LiveLogcatStream._on_worker_terminated]] — （无 docstring）

