---
kind: class
---

# TransferWorker

- 模块：[[models.file_explorer_worker]]
- 全名：models.file_explorer_worker.TransferWorker

> 执行 pull 或 push 长进程，并分别发送进度和业务结果

## 方法

- [[models.file_explorer_worker.TransferWorker.__init__]] — （无 docstring）
- [[models.file_explorer_worker.TransferWorker.abort]] — 请求中止并停止当前传输进程
- [[models.file_explorer_worker.TransferWorker.run]] — 启动传输进程；无论成功、失败或异常都取消进程注册

