---
kind: method
---

# shutdown(self)

- 定义于：[[controllers._base._ADBControllerBase]]
- 全名：controllers._base._ADBControllerBase.shutdown

> 应用退出时统一收口后台资源，避免 adb/logcat/scrcpy 等子进程残留

## 调用

- [[core.exec.ProcessRunner.stop_all_tracked]]

