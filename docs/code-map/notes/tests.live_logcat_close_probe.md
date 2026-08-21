---
kind: file
---

# tests.live_logcat_close_probe

> 在独立进程中压力验证实时日志窗口的关闭生命周期

- 路径：tests/live_logcat_close_probe.py

## 类

- [[tests.live_logcat_close_probe.StreamingProcess]] — 模拟持续输出且可被 ProcessRunner 正常终止的 logcat 进程

## 函数

- [[tests.live_logcat_close_probe.run_probe]] — 连续关闭正在输出的日志窗口，并分类记录主窗口和应用退出事件

