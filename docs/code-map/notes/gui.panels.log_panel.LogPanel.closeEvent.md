---
kind: method
---

# closeEvent(self, event)

- 定义于：[[gui.panels.log_panel.LogPanel]]
- 全名：gui.panels.log_panel.LogPanel.closeEvent

> 关闭时停止防抖定时器并断开类级信号，避免晚到事件触碰已销毁面板

## 调用

- [[gui.panels.log_panel.LogPanel._cancel_pending_render]]

