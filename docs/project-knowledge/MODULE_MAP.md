---
status: current
last_verified: 2026-09-04
related: [ARCHITECTURE.md, BUSINESS_FLOW.md, DEPENDENCY_MAP.md]
---

# 模块地图

本页只回答“功能在哪、边界是什么、从哪里验证”。调用顺序见
[BUSINESS_FLOW](BUSINESS_FLOW.md)，线程与生命周期见 [ARCHITECTURE](ARCHITECTURE.md)，外部依赖见
[DEPENDENCY_MAP](DEPENDENCY_MAP.md)。测试列为代表性入口，不维护文件数量。

| 区域 | 当前职责与边界 | 主要入口 | 代表性测试 |
| --- | --- | --- | --- |
| 启动与元数据 | CLI 分派、QApplication 初始化、打包自检和版本；版本只在元数据模块维护 | `main.py`、`utils/app_metadata.py` | `test_model_meta.py`、`test_runtime_tools.py` |
| 主窗口与顶层页面 | FluentWindow 的七个物理页面及唯一主左栏；设备、应用、系统以不可选树分组承载可选功能叶节点，Remote 归入设备组；负责主题与屏幕适配、设备扫描、信号接线和异步关闭 | `gui/main_frame.py`、`gui/main_frame_actions.py`、`gui/pages/fluent_pages.py`、`gui/close_controller.py` | `test_main_window_layout.py`、`test_phase2_mainframe_shutdown_gate.py` |
| 内嵌功能路由与会话 | 主左栏叶节点与 WorkspaceRoute 的映射、独立会话设备、深层路由与短屏滚动；按功能、设备和代次懒创建、原子激活、复用、停用与异步释放页面 | `gui/pages/workspace_features.py`、`gui/features/base.py` | `test_workspace_feature_host.py`、`test_main_window_layout.py` |
| 任务中心 | 展示 OperationManager 活动快照和进程内兼容完成历史；取消总是登记意图，MainFrame 当前只为安装批次和截图补充资源停止路由 | `gui/pages/tasks_page.py`、`services/task_history.py` | `test_task_center.py`、`test_task_history.py` |
| 业务面板与分类布局 | Devices/Apps/System/Remote 内容、设备页批量目标、业务信号和响应式重排；模块切换由主左栏树承担，AdaptiveCategoryStack 只作隐藏导航的内部内容栈；SidePanel 是兼容门面，不是可见导航栏 | `gui/panels/`、`gui/widgets/category_stack.py`、`gui/widgets/responsive_*.py` | `test_app_panel_categories.py`、`test_system_panel_categories.py`、`test_responsive_panels.py`、`test_model_panels.py` |
| 内嵌功能页 | App Manager、File Explorer、Live Logcat、Performance、Screenshot 与 Settings About；长期任务均属于主窗口 QWidget 树 | `gui/features/`、`gui/dialogs/app_manager*.py`、`file_explorer*.py`、`live_logcat*.py`、`performance_launcher*.py` | `test_app_manager_selection.py`、`test_screenshot_page.py`、`test_model_performance_launcher.py` |
| 瞬态交互与样式 | 消息、文本输入、短操作表单和系统文件选择器；qfluentwidgets 主题、字体角色及少量业务复合控件 | `gui/dialogs/fluent_dialog.py`、`gui/styles/`、`gui/widgets/preset_spin_box.py` | `test_fluent_dialog_contract.py`、`test_fluent_components.py`、`test_feature_typography.py` |
| Controller 与业务用例 | Qt 信号路由、结果聚合、operation 身份/所有权/代次和批次状态机；不直接实现 UI | `controllers/`、`adblab/application/` | `test_phase1_operations.py`、`test_device_batch_use_case.py`、`test_phase2_install_batch_gate.py` |
| ADB model 与执行层 | 设备、应用、系统、网络、测试命令；短命令和长进程统一结果/停止边界 | `models/adb_*.py`、`core/exec.py`、`core/adb_bridge.py` | `test_model_*.py`、`test_process_utils.py` |
| 设置、日志与设备存储 | schema 化 JSON 设置、内存/UI 日志、性能追踪、设备 YAML 原子读写 | `core/settings_manager.py`、`core/log_service.py`、`models/device_store.py` | `test_settings_persistence.py`、`test_logging_contract.py`、`test_device_store_concurrency.py` |
| 文件与 Remote 服务 | 文件命令/传输、scrcpy 启停、输入映射、持久 ADB shell 和 Remote 生命周期 | `services/file_explorer.py`、`models/file_explorer_worker.py`、`services/remote/` | `test_file_explorer_service.py`、`test_remote_services.py` |
| MobilePerf | GUI 适配层管理隔离子进程；移植内核负责指标采样和报告 | `services/mobileperf_runner.py`、`mobileperf/android/` | `test_model_mobileperf.py`、`test_mobileperf_runner_concurrency.py` |
| 工具、构建与发布 | 用户/资源/ADB 路径、ZIP 安全、输入校验、PyInstaller 与 GitHub Actions | `utils/`、`ADBLab.spec`、`.github/workflows/` | `test_runtime_tools.py`、`test_ci_contracts.py` |

当前 UI 代码只使用安装的 PySide6-Fluent-Widgets；上游源码定位规则见
[DEPENDENCY_MAP 的 Fluent 来源边界](DEPENDENCY_MAP.md#fluent-运行时来源边界)。
