---
kind: file
---

# mobileperf.android.tools.androiddevice

> 封装 MobilePerf 使用的 ADB 设备操作和日志采集能力

- 路径：mobileperf/android/tools/androiddevice.py

## 类

- [[mobileperf.android.tools.androiddevice.ADB]] — 本地ADB
- [[mobileperf.android.tools.androiddevice.AndroidDevice]] — 封装Android设备基本操作

## 函数

- [[mobileperf.android.tools.androiddevice._is_safe_shell_path]] — 拒绝包含 shell 元字符的路径，防止 rm/mkdir 等命令注入
- [[mobileperf.android.tools.androiddevice._payload_length]] — 返回命令输出长度；无法读取长度时安全降级为零
- [[mobileperf.android.tools.androiddevice._safe_adb_verb]] — 仅返回受控的 ADB 动作名，绝不回显调用方传入的参数

