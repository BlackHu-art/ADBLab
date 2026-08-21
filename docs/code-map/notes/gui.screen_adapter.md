---
kind: file
---

# gui.screen_adapter

> 主窗口屏幕查询与信号连接的适配层

- 路径：gui/screen_adapter.py

## 类

- [[gui.screen_adapter.QtScreenAdapter]] — 把真实 QWindow/QScreen 信号包装为可统一断开的 token
- [[gui.screen_adapter.ScreenAdapter]] — 隔离 MainFrame 所需的 Qt 屏幕查询和信号连接

