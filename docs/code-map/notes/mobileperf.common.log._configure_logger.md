---
kind: function
---

# _configure_logger(target)

- 定义于：[[mobileperf.common.log]]
- 全名：mobileperf.common.log._configure_logger

> 建立互斥日志通道：业务日志走 stdout，源码 DEBUG 只走 stderr

## 调用

- [[mobileperf.common.log._create_file_handler]]
- [[mobileperf.common.log._is_frozen_runtime]]
- [[mobileperf.common.log._mark_handler]]
- [[mobileperf.common.log._remove_owned_handlers]]
- [[mobileperf.common.log._writable_stream]]

## 实例化

- [[mobileperf.common.log._ExactDebugFilter]]
- [[mobileperf.common.log._RedactingFormatter]]

