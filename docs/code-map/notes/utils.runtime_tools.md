---
kind: file
---

# utils.runtime_tools

> 解析内置外部工具，并避免从 PyInstaller 临时目录运行长进程

- 路径：utils/runtime_tools.py

## 函数

- [[utils.runtime_tools._ensure_runtime_copy]] — 在进程内串行补齐用户缓存中的工具目录
- [[utils.runtime_tools._is_onefile_extraction]] — 判断 PyInstaller 当前是否从 onefile 临时解压目录运行
- [[utils.runtime_tools._runtime_root]] — （无 docstring）
- [[utils.runtime_tools.bundled_tool_path]] — 返回内置外部程序或数据文件的可用路径

