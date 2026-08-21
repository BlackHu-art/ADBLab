---
kind: class
---

# DeviceMonitor

- 模块：[[mobileperf.android.devicemonitor]]
- 全名：mobileperf.android.devicemonitor.DeviceMonitor

> 轮询目标应用的前台 Activity，并提供卸载状态检查能力

## 方法

- [[mobileperf.android.devicemonitor.DeviceMonitor.__init__]] — 初始化监控目标、轮询间隔、允许的 Activity 列表和结果队列
- [[mobileperf.android.devicemonitor.DeviceMonitor.start]] — （无 docstring）
- [[mobileperf.android.devicemonitor.DeviceMonitor.stop]] — （无 docstring）
- [[mobileperf.android.devicemonitor.DeviceMonitor._activity_monitor_thread]] — （无 docstring）
- [[mobileperf.android.devicemonitor.DeviceMonitor._uninstaller_checker_thread]] — 轮询目标应用是否已卸载，并通过事件通知上层结束采集

