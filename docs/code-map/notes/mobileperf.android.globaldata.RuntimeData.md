---
kind: class
---

# RuntimeData

- 模块：[[mobileperf.android.globaldata]]
- 全名：mobileperf.android.globaldata.RuntimeData

> 集中保存当前采集会话的共享状态（每运行一个实例）

## 方法

- [[mobileperf.android.globaldata.RuntimeData.__init__]] — （无 docstring）
- [[mobileperf.android.globaldata.RuntimeData.begin_run]] — 开始一次采集运行：创建全新的运行级实例并切换代理目标
- [[mobileperf.android.globaldata.RuntimeData.end_run]] — 结束采集运行并丢弃运行级状态，防止跨会话残留

