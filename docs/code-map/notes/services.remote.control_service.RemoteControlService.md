---
kind: class
---

# RemoteControlService

- 模块：[[services.remote.control_service]]
- 全名：services.remote.control_service.RemoteControlService

> 提供与 RemotePanel 解耦的设备控制原语

## 方法

- [[services.remote.control_service.RemoteControlService.__init__]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.remember_dimensions]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.clear_dimensions]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.get_dimensions]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.send_keyevent]] — 把逻辑按键名转换为 Android keyevent 并发送到指定设备
- [[services.remote.control_service.RemoteControlService.perform_action]] — 按 UI 动作名分发到遥控能力，避免面板层保存底层方法映射
- [[services.remote.control_service.RemoteControlService.swipe]] — 构造并发送 Android input swipe 命令
- [[services.remote.control_service.RemoteControlService.directional_swipe]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.expand_notifications]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.collapse_notifications]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.rotate_portrait]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.rotate_landscape]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService.reset_rotation]] — （无 docstring）
- [[services.remote.control_service.RemoteControlService._set_rotation]] — 关闭自动旋转并写入方向；主键失败时回退兼容设置键

