---
kind: class
---

# CpuCollector

- 模块：[[mobileperf.android.cpu_top]]
- 全名：mobileperf.android.cpu_top.CpuCollector

> 通过 top 命令按固定间隔采集 CPU 信息

## 方法

- [[mobileperf.android.cpu_top.CpuCollector.__init__]] — 配置采集设备、目标包、采集间隔和最长运行时间
- [[mobileperf.android.cpu_top.CpuCollector.get_sdkversion]] — （无 docstring）
- [[mobileperf.android.cpu_top.CpuCollector.start]] — 启动后台线程采集 CPU 信息
- [[mobileperf.android.cpu_top.CpuCollector.stop]] — 停止 CPU 采集线程和仍在运行的 top 进程
- [[mobileperf.android.cpu_top.CpuCollector._top_cpuinfo]] — （无 docstring）
- [[mobileperf.android.cpu_top.CpuCollector.get_max_freq]] — （无 docstring）
- [[mobileperf.android.cpu_top.CpuCollector._collect_package_cpu_thread]] — 按指定间隔循环采集并保存 CPU 信息

