---
kind: file
---

# mobileperf.common.log

> 配置 MobilePerf 子进程的标准输出、开发诊断和文件日志

- 路径：mobileperf/common/log.py

## 类

- [[mobileperf.common.log._ExactDebugFilter]] — 只允许 DEBUG 记录通过，避免 INFO 以上日志在两个流中重复
- [[mobileperf.common.log._RedactingFormatter]] — 在最终格式化后统一脱敏，包括异常堆栈中的文本

## 函数

- [[mobileperf.common.log._configure_logger]] — 建立互斥日志通道：业务日志走 stdout，源码 DEBUG 只走 stderr
- [[mobileperf.common.log._create_file_handler]] — 按显式目录创建 INFO 级轮转文件，失败时不影响采集主流程
- [[mobileperf.common.log._is_frozen_runtime]] — 判断当前是否运行在 PyInstaller 打包进程中
- [[mobileperf.common.log._mark_handler]] — （无 docstring）
- [[mobileperf.common.log._redact_sensitive_text]] — 从日志文本中移除本次运行的设备、邮箱和本地路径
- [[mobileperf.common.log._remove_owned_handlers]] — 仅清理本模块创建的 handler，不影响宿主进程或第三方日志配置
- [[mobileperf.common.log._sensitive_values]] — 读取父进程提供的本次运行敏感值，解析失败时安全降级为空集合
- [[mobileperf.common.log._writable_stream]] — 返回可写的标准流；windowed 打包环境没有标准流时返回 None

