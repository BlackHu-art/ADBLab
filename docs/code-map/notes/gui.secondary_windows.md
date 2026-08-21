---
kind: file
---

# gui.secondary_windows

> 二级窗口托管、事件过滤与实时设置刷新

- 路径：gui/secondary_windows.py

## 类

- [[gui.secondary_windows.SecondaryWindowHost]] — 组合进 MainFrame 的二级窗口托管器，通过 ``self._frame`` 访问主窗口

## 函数

- [[gui.secondary_windows._debug_log]] — 转发开发诊断日志到主窗口模块，避免循环导入

