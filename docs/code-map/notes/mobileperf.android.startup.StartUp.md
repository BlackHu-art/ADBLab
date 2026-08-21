---
kind: class
---

# StartUp

- 模块：[[mobileperf.android.startup]]
- 全名：mobileperf.android.startup.StartUp

> 管理单次 Android 性能采集会话的启动、等待和停止流程

## 方法

- [[mobileperf.android.startup.StartUp.__init__]] — （无 docstring）
- [[mobileperf.android.startup.StartUp._init_queue]] — 创建各类性能指标的进程内消息队列
- [[mobileperf.android.startup.StartUp.get_queue_dic]] — 返回监控器与数据处理器约定的队列映射
- [[mobileperf.android.startup.StartUp.add_monitor]] — （无 docstring）
- [[mobileperf.android.startup.StartUp.remove_monitor]] — （无 docstring）
- [[mobileperf.android.startup.StartUp.parse_data_from_config]] — 读取并校验包名、采样频率、设备序列号等采集配置
- [[mobileperf.android.startup.StartUp.check_config_option]] — （无 docstring）
- [[mobileperf.android.startup.StartUp._monkey_config_options]] — （无 docstring）
- [[mobileperf.android.startup.StartUp._monkey_int_options]] — （无 docstring）
- [[mobileperf.android.startup.StartUp._optional_config_defaults]] — （无 docstring）
- [[mobileperf.android.startup.StartUp._monkey_options]] — （无 docstring）
- [[mobileperf.android.startup.StartUp._config_error]] — （无 docstring）
- [[mobileperf.android.startup.StartUp.run]] — 启动所有采集器并等待超时、停止文件或异常退出信号
- [[mobileperf.android.startup.StartUp.clear_heapdump]] — 删除目标应用超过三天的历史堆转储，避免与本次采集混淆
- [[mobileperf.android.startup.StartUp.stop]] — 停止监控器、生成报告并回收本次采集产生的设备侧文件
- [[mobileperf.android.startup.StartUp.memory_analyse]] — 保留内存分析兼容入口，当前未启用具体实现
- [[mobileperf.android.startup.StartUp.pull_heapdump]] — 将目标应用的设备侧堆转储拉取到本次结果目录
- [[mobileperf.android.startup.StartUp.pull_log_files]] — 将配置的设备日志目录拉取到本次结果目录
- [[mobileperf.android.startup.StartUp.save_device_info]] — 记录本次采集使用的设备和应用版本信息
- [[mobileperf.android.startup.StartUp.add_device_info]] — （无 docstring）
- [[mobileperf.android.startup.StartUp.check_exit_signal_quit]] — （无 docstring）
- [[mobileperf.android.startup.StartUp.check_stop_file_quit]] — （无 docstring）

