---
kind: file
---

# core.perf_trace

> 提供慢路径性能追踪所需的轻量辅助函数

- 路径：core/perf_trace.py

## 函数

- [[core.perf_trace._float]] — （无 docstring）
- [[core.perf_trace.attach_perf]] — 附加性能数据，并保证 split_perf() 后仍可恢复原始载荷
- [[core.perf_trace.build_async_perf]] — 构建单个异步模型任务的阶段耗时数据
- [[core.perf_trace.elapsed_ms]] — 根据单调时钟时间戳计算非负毫秒耗时
- [[core.perf_trace.format_perf]] — 将性能追踪数据格式化为紧凑的单行文本
- [[core.perf_trace.should_log_perf]] — 仅在任一阶段或总耗时达到阈值时记录性能日志
- [[core.perf_trace.split_perf]] — 在业务处理器消费结果前剥离内部性能数据
- [[core.perf_trace.summarize_perf]] — 合并工作线程排队、模型执行和控制器界面处理耗时

