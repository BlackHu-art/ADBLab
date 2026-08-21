---
kind: class
---

# DeviceStore

- 模块：[[models.device_store]]
- 全名：models.device_store.DeviceStore

> 维护设备信息快照，并以原子替换方式写入用户配置目录

## 方法

- [[models.device_store.DeviceStore.load]] — 加载用户设备文件，并在首次使用时迁移有效的旧版数据
- [[models.device_store.DeviceStore.save]] — 在线程锁内保存当前设备快照
- [[models.device_store.DeviceStore.initialize_empty]] — （无 docstring）
- [[models.device_store.DeviceStore._write_snapshot_atomic]] — 写入同目录临时文件并原子替换目标文件，失败时清理临时文件
- [[models.device_store.DeviceStore._backup_corrupt_file]] — 尽力备份损坏文件；备份失败不覆盖原始加载失败结果
- [[models.device_store.DeviceStore.add_device]] — （无 docstring）
- [[models.device_store.DeviceStore.upsert_devices]] — 批量写入设备信息，一轮刷新只落盘一次，减少 YAML I/O 抖动
- [[models.device_store.DeviceStore.get_all]] — （无 docstring）
- [[models.device_store.DeviceStore.get_basic_devices_info]] — （无 docstring）
- [[models.device_store.DeviceStore.get_full_devices_info]] — （无 docstring）

