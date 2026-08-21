---
kind: method
---

# shutdown(self)

- 定义于：[[gui.panels.remote_panel.RemotePanel]]
- 全名：gui.panels.remote_panel.RemotePanel.shutdown

> 先停止 scrcpy 和启动 worker，再关闭输入队列及持久 ADB 会话

## 调用

- [[gui.panels.remote_panel.RemotePanel._request_scrcpy_stop_once]]
- [[gui.panels.remote_panel.RemotePanel._stop_launch_worker]]

