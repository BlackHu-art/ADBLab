---
kind: class
---

# CancellationToken

- 模块：[[adblab.application.cancellation]]
- 全名：adblab.application.cancellation.CancellationToken

> 提供线程安全且幂等的取消信号

## 方法

- [[adblab.application.cancellation.CancellationToken.__init__]] — （无 docstring）
- [[adblab.application.cancellation.CancellationToken.is_cancelled]] — （无 docstring）
- [[adblab.application.cancellation.CancellationToken.request]] — 请求取消，仅首次请求返回 True
- [[adblab.application.cancellation.CancellationToken.cancel]] — 保留兼容入口，语义与 request() 相同
- [[adblab.application.cancellation.CancellationToken.wait]] — 等待取消信号，避免调用方直接依赖 Event
- [[adblab.application.cancellation.CancellationToken.raise_if_cancelled]] — 在取消检查点抛出 CancellationError，否则保持静默

