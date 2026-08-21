---
kind: file
---

# services.remote.types

> 定义 Remote 服务层使用的配置、预检结果和启动计划

- 路径：services/remote/types.py

## 类

- [[services.remote.types.PreflightResult]] — 记录 Remote 启动预检是否通过及其用户提示
- [[services.remote.types.ScrcpyConfig]] — 描述一次 scrcpy 启动所需的可执行文件、设备和视频选项
- [[services.remote.types.ScrcpyLaunchPlan]] — 保存预检后可直接交给进程层的 scrcpy 启动计划

