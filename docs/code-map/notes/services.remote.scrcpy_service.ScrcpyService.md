---
kind: class
---

# ScrcpyService

- 模块：[[services.remote.scrcpy_service]]
- 全名：services.remote.scrcpy_service.ScrcpyService

> 在不依赖 Qt 控件的前提下准备并管理 scrcpy 进程

## 方法

- [[services.remote.scrcpy_service.ScrcpyService.__init__]] — （无 docstring）
- [[services.remote.scrcpy_service.ScrcpyService.run_command]] — 通过统一短命令边界执行 scrcpy 或 ADB 预检命令
- [[services.remote.scrcpy_service.ScrcpyService.resolve_executable]] — 解析 scrcpy 可执行文件路径，UI 层不直接关心平台和打包目录
- [[services.remote.scrcpy_service.ScrcpyService.version]] — （无 docstring）
- [[services.remote.scrcpy_service.ScrcpyService.device_info]] — （无 docstring）
- [[services.remote.scrcpy_service.ScrcpyService.preflight_check]] — 检查设备响应和基础传输速度，但不因速度警告阻止启动
- [[services.remote.scrcpy_service.ScrcpyService.detect_encoder]] — （无 docstring）
- [[services.remote.scrcpy_service.ScrcpyService.build_launch_plan]] — 完成版本、设备和编码器预检，并生成不含运行状态的启动计划
- [[services.remote.scrcpy_service.ScrcpyService.start]] — 启动由 ``ProcessRunner`` 跟踪的 scrcpy 长进程
- [[services.remote.scrcpy_service.ScrcpyService.stop]] — 等待 scrcpy 在时限内退出，必要时由 ``ProcessRunner`` 强制清理
- [[services.remote.scrcpy_service.ScrcpyService.request_stop]] — 只发送停止请求，不等待进程退出
- [[services.remote.scrcpy_service.ScrcpyService.force_stop]] — 强制停止 scrcpy，并仅在进程已解除跟踪时确认成功
- [[services.remote.scrcpy_service.ScrcpyService.is_active]] — （无 docstring）
- [[services.remote.scrcpy_service.ScrcpyService.parse_fps]] — （无 docstring）

