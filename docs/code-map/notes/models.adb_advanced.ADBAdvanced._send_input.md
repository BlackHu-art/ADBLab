---
kind: method
---

# _send_input(self, device_ip, input_args)

- 定义于：[[models.adb_advanced.ADBAdvanced]]
- 全名：models.adb_advanced.ADBAdvanced._send_input

> 复用持久 adb shell input 通道；失败时降级为有界同步命令并校验结果

## 调用

- [[models.adb_advanced.ADBAdvanced._input_bridge]]

