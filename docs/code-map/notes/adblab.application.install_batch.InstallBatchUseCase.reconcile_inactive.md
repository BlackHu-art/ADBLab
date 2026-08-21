---
kind: method
---

# reconcile_inactive(self, operation_id, *, owner_token=None)

- 定义于：[[adblab.application.install_batch.InstallBatchUseCase]]
- 全名：adblab.application.install_batch.InstallBatchUseCase.reconcile_inactive

> 仅在缓存 generation 已不在 manager 中时回收安装身份

## 调用

- [[adblab.application.install_batch.InstallBatchUseCase._drop_active_locked]]
- [[adblab.application.install_batch.InstallBatchUseCase._manager_identity_locked]]
- [[adblab.application.install_batch.InstallBatchUseCase._owned_units_locked]]

