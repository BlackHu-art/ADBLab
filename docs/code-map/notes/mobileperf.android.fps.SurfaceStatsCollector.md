---
kind: class
---

# SurfaceStatsCollector

- 模块：[[mobileperf.android.fps]]
- 全名：mobileperf.android.fps.SurfaceStatsCollector

> 从 SurfaceFlinger 输出中采集当前 Surface 的帧统计数据

## 方法

- [[mobileperf.android.fps.SurfaceStatsCollector.__init__]] — （无 docstring）
- [[mobileperf.android.fps.SurfaceStatsCollector.start]] — 启动 Surface 统计数据采集和计算线程
- [[mobileperf.android.fps.SurfaceStatsCollector.stop]] — 停止 Surface 统计数据采集线程
- [[mobileperf.android.fps.SurfaceStatsCollector.get_focus_activity]] — 通过 dumpsys window windows 获取当前焦点 Activity 的窗口名
- [[mobileperf.android.fps.SurfaceStatsCollector._calculate_results]] — 根据帧时间戳计算 FPS 和卡顿次数
- [[mobileperf.android.fps.SurfaceStatsCollector._calculate_results_new]] — 根据帧数量选择对应算法计算 FPS 和卡顿次数
- [[mobileperf.android.fps.SurfaceStatsCollector._calculate_jankey_new]] — 同时满足以下条件时计为一次卡顿
- [[mobileperf.android.fps.SurfaceStatsCollector._calculate_janky]] — （无 docstring）
- [[mobileperf.android.fps.SurfaceStatsCollector._calculator_thread]] — 消费 SurfaceFlinger 数据并将 FPS 结果写入文件或上报队列
- [[mobileperf.android.fps.SurfaceStatsCollector._collector_thread]] — 循环采集帧数据
- [[mobileperf.android.fps.SurfaceStatsCollector._clear_surfaceflinger_latency_data]] — 清空 SurfaceFlinger 延迟数据，并返回设备是否支持该命令
- [[mobileperf.android.fps.SurfaceStatsCollector._get_surfaceflinger_frame_data]] — 返回屏幕刷新周期和已完成帧的时间戳列表
- [[mobileperf.android.fps.SurfaceStatsCollector._get_surface_stats_legacy]] — 返回 JellyBean 之前兼容路径的 Surface 索引和时间戳

