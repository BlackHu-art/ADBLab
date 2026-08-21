---
kind: file
---

# mobileperf.android.cpu_top

> 采集并解析 Android top 输出中的整机和目标进程 CPU 指标

- 路径：mobileperf/android/cpu_top.py

## 类

- [[mobileperf.android.cpu_top.CpuCollector]] — 通过 top 命令按固定间隔采集 CPU 信息
- [[mobileperf.android.cpu_top.CpuMonitor]] — 管理 CPU 采集器及其结果目录
- [[mobileperf.android.cpu_top.DeviceCpuinfo]] — （无 docstring）
- [[mobileperf.android.cpu_top.PckCpuinfo]] — 解析一次 top 输出中的整机和目标包 CPU 数据

