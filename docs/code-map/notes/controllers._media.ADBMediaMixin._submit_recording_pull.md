---
kind: method
---

# _submit_recording_pull(self, device_ip, info)

- 定义于：[[controllers._media.ADBMediaMixin]]
- 全名：controllers._media.ADBMediaMixin._submit_recording_pull

> 每个设备批次只提交一次录屏拉取；提交失败时立即释放终态

## 调用

- [[controllers._base._ADBControllerBase._emit_operation]]
- [[controllers._media._emit_record_target_finished]]

