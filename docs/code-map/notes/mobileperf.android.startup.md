---
kind: file
---

# mobileperf.android.startup

> 编排 MobilePerf 配置解析、监控器生命周期和采集结果收尾

- 路径：mobileperf/android/startup.py

## 类

- [[mobileperf.android.startup.App]] — 保存应用包名、名称和版本信息的轻量数据对象
- [[mobileperf.android.startup.StartUp]] — 管理单次 Android 性能采集会话的启动、等待和停止流程

## 函数

- [[mobileperf.android.startup._remove_config_bom_prefix]] — 连续移除配置文件开头的 Unicode 或历史 BOM 表示
- [[mobileperf.android.startup._split_config_list]] — 清理分号列表的首尾空白和空项，同时保留顺序与重复项

