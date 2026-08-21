---
kind: method
---

# mark_pull_submitted(self, device_ip, batch_id)

- 定义于：[[adblab.application.screen_record.ScreenRecordUseCase]]
- 全名：adblab.application.screen_record.ScreenRecordUseCase.mark_pull_submitted

> 幂等标记拉取已提交；仅首次提交返回 True（替代旧的防重入标记）

