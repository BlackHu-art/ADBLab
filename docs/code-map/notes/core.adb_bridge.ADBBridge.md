---
kind: class
---

# ADBBridge

- 模块：[[core.adb_bridge]]
- 全名：core.adb_bridge.ADBBridge

> 封装 ADB Shell、输入、屏幕尺寸和设备列表命令

## 方法

- [[core.adb_bridge.ADBBridge.__init__]] — （无 docstring）
- [[core.adb_bridge.ADBBridge.shell]] — 执行 ADB Shell 命令并返回标准化结果
- [[core.adb_bridge.ADBBridge.shell_input]] — 向设备 Shell 发送 input 命令，例如 keyevent 或 swipe
- [[core.adb_bridge.ADBBridge.warm_input_session]] — 预热持久输入 Shell，缩短首条真实输入命令的等待时间
- [[core.adb_bridge.ADBBridge.close_input_sessions]] — 关闭持久输入 Shell 会话，供面板或服务停止时清理资源
- [[core.adb_bridge.ADBBridge._input_session]] — （无 docstring）
- [[core.adb_bridge.ADBBridge._session_key]] — （无 docstring）
- [[core.adb_bridge.ADBBridge.get_dimensions]] — 通过 wm size 获取设备屏幕尺寸，返回宽高列表或 None
- [[core.adb_bridge.ADBBridge.devices]] — 返回由设备序列号和连接状态组成的设备列表

