---
kind: class
---

# Monitor

- 模块：[[mobileperf.common.basemonitor]]
- 全名：mobileperf.common.basemonitor.Monitor

> 性能测试数据采集能力基类

## 方法

- [[mobileperf.common.basemonitor.Monitor.__init__]] — 初始化监控器
- [[mobileperf.common.basemonitor.Monitor.start]] — 由子类实现开始采集的具体行为
- [[mobileperf.common.basemonitor.Monitor.clear]] — 清空监控器保存的数据
- [[mobileperf.common.basemonitor.Monitor.stop]] — 由子类停止采集，并在需要后续解析时保存数据文件
- [[mobileperf.common.basemonitor.Monitor.save]] — 由子类实现数据保存行为

