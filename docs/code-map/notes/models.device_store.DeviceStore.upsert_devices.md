---
kind: method
---

# upsert_devices(cls, devices)

- 定义于：[[models.device_store.DeviceStore]]
- 全名：models.device_store.DeviceStore.upsert_devices

> 批量写入设备信息，一轮刷新只落盘一次，减少 YAML I/O 抖动

## 调用

- [[models.device_store.DeviceStore._write_snapshot_atomic]]

