---
kind: file
---

# main

> 分派 CLI 子模式并启动 ADBLab 图形界面

- 路径：main.py

## 函数

- [[main._dispatch_cli]] — 分派已知 CLI 子模式；未命中时返回 None 以继续启动 GUI
- [[main._run_gui]] — 创建 QApplication、加载主题并进入主界面事件循环
- [[main._run_mobileperf_worker]] — 在隔离子进程中运行 MobilePerf 采集内核
- [[main._run_self_check]] — 解析并执行无需启动 Qt 界面的自检子命令
- [[main._self_check_packaging]] — 验证打包所需依赖、资源和用户数据目录的基本可用性
- [[main.windows_app_user_model_id]] — 生成随主次版本变化的 Windows AppUserModelID

