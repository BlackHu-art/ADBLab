---
kind: class
---

# Monkey

- 模块：[[mobileperf.android.monkey]]
- 全名：mobileperf.android.monkey.Monkey

> 管理 Monkey 命令、输出线程和停止清理

## 方法

- [[mobileperf.android.monkey.Monkey.__init__]] — 初始化 Monkey 目标、事件分布和运行时限
- [[mobileperf.android.monkey.Monkey.start]] — 记录开始时间并启动 Monkey
- [[mobileperf.android.monkey.Monkey.stop]] — 停止 Monkey 进程和日志读取线程
- [[mobileperf.android.monkey.Monkey.start_monkey]] — 构造命令并启动 Monkey 进程及日志读取线程
- [[mobileperf.android.monkey.Monkey._build_monkey_cmd]] — （无 docstring）
- [[mobileperf.android.monkey.Monkey._percent]] — （无 docstring）
- [[mobileperf.android.monkey.Monkey._event_percentage_total]] — （无 docstring）
- [[mobileperf.android.monkey.Monkey._event_count_for_timeout]] — （无 docstring）
- [[mobileperf.android.monkey.Monkey.stop_monkey]] — （无 docstring）
- [[mobileperf.android.monkey.Monkey._monkey_thread_func]] — 持续读取并分片保存 Monkey 日志，异常关键字由其他监控器处理
- [[mobileperf.android.monkey.Monkey.save]] — （无 docstring）

