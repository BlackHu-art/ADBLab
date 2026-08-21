---
kind: class
---

# ScreenRecordUseCase

- 模块：[[adblab.application.screen_record]]
- 全名：adblab.application.screen_record.ScreenRecordUseCase

> 管理每设备录屏记录与停止请求的登记、幂等标记和终态移除

## 方法

- [[adblab.application.screen_record.ScreenRecordUseCase.__init__]] — （无 docstring）
- [[adblab.application.screen_record.ScreenRecordUseCase.start]] — 登记一条新录屏；该设备已有活动录屏时返回 False
- [[adblab.application.screen_record.ScreenRecordUseCase.active]] — 返回设备的活动录屏记录；无则 None
- [[adblab.application.screen_record.ScreenRecordUseCase.mark_started]] — 补记录制远端路径与文件名；批次不匹配或记录已移除返回 False
- [[adblab.application.screen_record.ScreenRecordUseCase.mark_pull_submitted]] — 幂等标记拉取已提交；仅首次提交返回 True（替代旧的防重入标记）
- [[adblab.application.screen_record.ScreenRecordUseCase.mark_stop_succeeded]] — 标记"停止成功、等待启动结果后立即拉取"
- [[adblab.application.screen_record.ScreenRecordUseCase.is_stop_succeeded]] — （无 docstring）
- [[adblab.application.screen_record.ScreenRecordUseCase.finish]] — 终态移除设备记录；批次不匹配或不存在返回 None
- [[adblab.application.screen_record.ScreenRecordUseCase.request_stop]] — 幂等登记停止请求；该批次首次请求返回 True
- [[adblab.application.screen_record.ScreenRecordUseCase.stop_requested]] — （无 docstring）
- [[adblab.application.screen_record.ScreenRecordUseCase.clear_stop_request]] — 停止请求已处理或已失效时清理登记
- [[adblab.application.screen_record.ScreenRecordUseCase.active_devices]] — （无 docstring）

