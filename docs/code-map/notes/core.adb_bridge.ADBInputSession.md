---
kind: class
---

# ADBInputSession

- 模块：[[core.adb_bridge]]
- 全名：core.adb_bridge.ADBInputSession

> 维护持久化的 adb shell 会话，降低输入命令延迟

## 方法

- [[core.adb_bridge.ADBInputSession.__init__]] — （无 docstring）
- [[core.adb_bridge.ADBInputSession._key]] — （无 docstring）
- [[core.adb_bridge.ADBInputSession.send]] — 通过标准输入发送命令；返回 False 时由调用方执行降级路径
- [[core.adb_bridge.ADBInputSession.close]] — （无 docstring）
- [[core.adb_bridge.ADBInputSession.warm]] — 在第一条真实输入命令前预先打开持久 Shell
- [[core.adb_bridge.ADBInputSession._ensure_process]] — （无 docstring）
- [[core.adb_bridge.ADBInputSession._close_locked]] — （无 docstring）

