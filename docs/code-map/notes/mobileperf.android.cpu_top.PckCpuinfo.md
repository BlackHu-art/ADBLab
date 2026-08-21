---
kind: class
---

# PckCpuinfo

- 模块：[[mobileperf.android.cpu_top]]
- 全名：mobileperf.android.cpu_top.PckCpuinfo

> 解析一次 top 输出中的整机和目标包 CPU 数据

## 方法

- [[mobileperf.android.cpu_top.PckCpuinfo.__init__]] — 初始化解析器
- [[mobileperf.android.cpu_top.PckCpuinfo._parse_package]] — 解析 top 输出中与目标包完全匹配的进程 CPU 信息
- [[mobileperf.android.cpu_top.PckCpuinfo._parse_cpu_usage]] — 根据 Android 版本解析 top 中的整机 CPU 汇总信息
- [[mobileperf.android.cpu_top.PckCpuinfo.sum_procs_cpurate]] — 累计同一 UID 下所有进程的 CPU 使用率
- [[mobileperf.android.cpu_top.PckCpuinfo.get_cpucol_index]] — 返回 CPU 百分比字段在当前 top 输出中的列索引
- [[mobileperf.android.cpu_top.PckCpuinfo.get_pcycol_index]] — 返回 top 输出中 PCY 字段的列索引
- [[mobileperf.android.cpu_top.PckCpuinfo.get_packagenamecol_index]] — 返回 top 输出中进程名字段的列索引
- [[mobileperf.android.cpu_top.PckCpuinfo.get_vsscol_index]] — （无 docstring）
- [[mobileperf.android.cpu_top.PckCpuinfo.get_rss_col_index]] — （无 docstring）
- [[mobileperf.android.cpu_top.PckCpuinfo.get_uidcol_index]] — 兼容 UID 和 USER 两种表头并返回对应列索引
- [[mobileperf.android.cpu_top.PckCpuinfo.get_col_index]] — 按候选列名查找 top 字段索引，未找到时返回默认值

