---
kind: file
---

# utils.adb_resolver

> 按内置工具、系统 PATH、不可用的顺序解析 ADB 路径

- 路径：utils/adb_resolver.py

## 函数

- [[utils.adb_resolver.adb_path]] — 返回已解析的 ADB 路径；不可用时回退为命令名 adb
- [[utils.adb_resolver.is_adb_available]] — 检查是否存在可用的 ADB 可执行文件
- [[utils.adb_resolver.resolve_adb_path]] — 查找可用的 ADB 可执行文件，并在首次解析后缓存结果

