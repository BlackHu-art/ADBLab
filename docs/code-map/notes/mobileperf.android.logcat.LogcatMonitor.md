---
kind: class
---

# LogcatMonitor

- 模块：[[mobileperf.android.logcat]]
- 全名：mobileperf.android.logcat.LogcatMonitor

> 管理设备 logcat 的启动、停止和实时回调

## 方法

- [[mobileperf.android.logcat.LogcatMonitor.__init__]] — 初始化目标设备、进程过滤条件和日志匹配配置
- [[mobileperf.android.logcat.LogcatMonitor.start]] — 启动 logcat 并注册启动耗时回调
- [[mobileperf.android.logcat.LogcatMonitor.stop]] — 移除回调并停止设备 logcat 进程
- [[mobileperf.android.logcat.LogcatMonitor.parse]] — （无 docstring）
- [[mobileperf.android.logcat.LogcatMonitor.set_exception_list]] — （无 docstring）
- [[mobileperf.android.logcat.LogcatMonitor.add_log_handle]] — 添加实时日志处理器，每产生一条日志就调用一次
- [[mobileperf.android.logcat.LogcatMonitor.remove_log_handle]] — 删除已经注册的实时日志处理器
- [[mobileperf.android.logcat.LogcatMonitor.handle_exception]] — 匹配最新日志中的异常关键字，并保存异常文本和旧进程堆栈

