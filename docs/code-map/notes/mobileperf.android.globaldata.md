---
kind: file
---

# mobileperf.android.globaldata

> 保存 MobilePerf 采集会话在线程之间共享的运行时状态

- 路径：mobileperf/android/globaldata.py

## 类

- [[mobileperf.android.globaldata.RuntimeData]] — 集中保存当前采集会话的共享状态（每运行一个实例）
- [[mobileperf.android.globaldata._RuntimeDataMeta]] — 把运行时字段的读写代理到当前运行实例，保持既有调用点兼容

