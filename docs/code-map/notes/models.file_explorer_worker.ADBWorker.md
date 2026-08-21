---
kind: class
---

# ADBWorker

- 模块：[[models.file_explorer_worker]]
- 全名：models.file_explorer_worker.ADBWorker

> 执行短 ADB Shell 命令，并通过业务结果信号返回输出或错误

## 方法

- [[models.file_explorer_worker.ADBWorker.__init__]] — （无 docstring）
- [[models.file_explorer_worker.ADBWorker.abort]] — 设置中止意图，命令返回后不再发送完成结果
- [[models.file_explorer_worker.ADBWorker.run]] — 执行一次短命令，并将失败状态作为信号参数传播

