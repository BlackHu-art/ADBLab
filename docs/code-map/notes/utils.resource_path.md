---
kind: file
---

# utils.resource_path

> 资源路径解析工具 — 同时兼容开发环境和 PyInstaller 打包后的运行环境

- 路径：utils/resource_path.py

## 函数

- [[utils.resource_path._base_dir]] — 返回资源根目录的绝对路径
- [[utils.resource_path.resource_path]] — 将相对路径转为操作系统原生绝对路径
- [[utils.resource_path.setup_qt_search_paths]] — 注册 Qt 资源搜索前缀，使样式表 url() 可使用短别名引用图标

