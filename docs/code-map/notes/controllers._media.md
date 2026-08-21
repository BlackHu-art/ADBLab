---
kind: file
---

# controllers._media

> 提供截图、录屏和设备诊断信息采集的控制能力

- 路径：controllers/_media.py

## 类

- [[controllers._media.ADBMediaMixin]] — 协调截图、录屏、dumpsys、电池、Logcat、进程和运行时长操作

## 函数

- [[controllers._media._emit_readonly_diagnostic_result]] — 把固定命令的结果裁剪后发布到可见操作日志
- [[controllers._media._emit_record_target_finished]] — 发布带批次标识的录屏终态，并保留旧兼容通知

