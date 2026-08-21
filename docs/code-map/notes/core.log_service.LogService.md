---
kind: class
---

# LogService

- 模块：[[core.log_service]]
- 全名：core.log_service.LogService

> 在线程间缓冲用户日志，并将开发调试日志隔离到标准错误流

## 方法

- [[core.log_service.LogService.__new__]] — （无 docstring）
- [[core.log_service.LogService.__init__]] — 初始化进程内唯一的日志服务
- [[core.log_service.LogService._setup_logging]] — 配置项目独享的文件记录器和 Qt 缓冲定时器
- [[core.log_service.LogService._add_file_handler]] — 在用户可写目录中创建仅接收 INFO 及以上级别的处理器
- [[core.log_service.LogService.log]] — 记录日志；DEBUG 仅在源码运行时写入开发环境控制台
- [[core.log_service.LogService._ensure_flush_timer]] — 确保刷新定时器只在 LogService 所在线程启动，避免跨线程操作 QTimer
- [[core.log_service.LogService._stop_flush_timer]] — 停止定时器也必须回到所属线程，后台线程只负责追加和搬运缓冲区
- [[core.log_service.LogService._request_stop_flush_timer]] — 后台线程需要停止定时器时，通过 Qt 信号投递回所属线程
- [[core.log_service.LogService._flush_buffer]] — 在对象所属线程中取出并发布当前用户日志批次
- [[core.log_service.LogService._drain_buffer_locked]] — （无 docstring）
- [[core.log_service.LogService.dropped_count]] — 返回本次服务生命周期内因背压被丢弃的累计记录数
- [[core.log_service.LogService._emit_batch]] — 将单个批次写入文件并通过兼容信号发布给界面
- [[core.log_service.LogService._write_file_log]] — 将用户日志写入已启用的 INFO 级别文件处理器
- [[core.log_service.LogService.write_developer_console]] — 仅在源码模式下原子写入 IDE 可见的标准错误流
- [[core.log_service.LogService.enable_file_logging]] — 动态启用或停用用户目录中的文件日志
- [[core.log_service.LogService.set_flush_interval]] — 设置缓冲区刷新间隔（毫秒）
- [[core.log_service.LogService.request_shutdown]] — 从任意线程非阻塞请求关闭，并立即拒绝请求后的晚到日志
- [[core.log_service.LogService.shutdown]] — 在对象所属线程幂等关闭服务；后台线程应调用 ``request_shutdown``
- [[core.log_service.LogService._complete_shutdown]] — 在对象所属线程排空日志并同步停止全部 Qt 和文件资源

