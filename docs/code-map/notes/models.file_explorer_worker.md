---
kind: file
---

# models.file_explorer_worker

> 提供在 QThread 中执行 ADB Shell 和文件传输的后台任务

- 路径：models/file_explorer_worker.py

## 类

- [[models.file_explorer_worker.ADBWorker]] — 执行短 ADB Shell 命令，并通过业务结果信号返回输出或错误
- [[models.file_explorer_worker.TransferWorker]] — 执行 pull 或 push 长进程，并分别发送进度和业务结果

