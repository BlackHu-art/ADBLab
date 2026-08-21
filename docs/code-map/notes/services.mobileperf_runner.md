---
kind: file
---

# services.mobileperf_runner

> 在 Qt 主进程与内置 MobilePerf 命令行采集器之间提供进程隔离适配

- 路径：services/mobileperf_runner.py

## 类

- [[services.mobileperf_runner.MobilePerfMonkeyConfig]] — 写入 MobilePerf 临时配置的结构化 Monkey 命令选项
- [[services.mobileperf_runner.MobilePerfRunConfig]] — 承载界面提交的 MobilePerf 单次运行配置
- [[services.mobileperf_runner.MobilePerfRunner]] — 在与 Qt 应用隔离的子进程中启动、停止并跟踪 MobilePerf
- [[services.mobileperf_runner._MobilePerfRunContext]] — 保存单次 MobilePerf 运行中不得跨代复用的进程和回调状态

## 函数

- [[services.mobileperf_runner._normalize_package]] — 规范化分号分隔的包名，并保留原有顺序、大小写和重复项
- [[services.mobileperf_runner._primary_package]] — （无 docstring）
- [[services.mobileperf_runner._split_semicolon]] — （无 docstring）
- [[services.mobileperf_runner.normalize_local_path]] — （无 docstring）

