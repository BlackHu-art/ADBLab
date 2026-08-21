---
kind: file
---

# models.adb_model

> 提供异步命令装饰器和 ADB 模型基类

- 路径：models/adb_model.py

## 类

- [[models.adb_model.ADBModelCore]] — 提供信号、线程池和命令执行等共享基础设施

## 函数

- [[models.adb_model.async_command]] — 将同步方法提交到 QThreadPool，并通过信号发送标准化结果

