---
kind: file
---

# controllers._app_install

> 提供应用安装、卸载、清数据、重启与当前 Activity 查询的控制能力

- 路径：controllers/_app_install.py

## 类

- [[controllers._app_install.ADBAppInstallMixin]] — 协调应用安装、卸载、清数据、重启和当前 Activity 查询
- [[controllers._app_install._InstallOperationOwner]] — 标识只属于 Controller 安装 generation 的不透明所有权

## 函数

- [[controllers._app_install._record_device_batch_result]] — 把无 envelope 的遗留批次结果记入 DeviceBatchUseCase，返回进度字符串
- [[controllers._app_install._unit_for_device]] — 返回批次中指定设备的执行单元；设备不在批次中时返回 None

