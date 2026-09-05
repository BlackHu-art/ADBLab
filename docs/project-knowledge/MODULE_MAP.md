---
status: current
last_verified: 2026-09-05
related: [ARCHITECTURE.md, BUSINESS_FLOW.md, DEPENDENCY_MAP.md]
---

# 模块地图

本页只回答“功能在哪、边界是什么、从哪里验证”。调用顺序见
[BUSINESS_FLOW](BUSINESS_FLOW.md)，线程与生命周期见 [ARCHITECTURE](ARCHITECTURE.md)，外部依赖见
[DEPENDENCY_MAP](DEPENDENCY_MAP.md)。测试列均相对于 `tests/`，只列代表性入口，不维护文件数量。

| 区域 | 当前职责与边界 | 主要入口 | 代表性测试 |
| --- | --- | --- | --- |
| 启动与元数据 | CLI 分派、GUI 比例预加载、QApplication 初始化、诊断转交、打包自检和版本 | `main.py`、`utils/app_metadata.py` | `test_gui_bootstrap.py`、`test_model_meta.py`、`test_runtime_tools.py` |
| 主窗口与顶层页面 | FluentWindow 组合根；负责页面注册、主题与屏幕适配、设备扫描、信号接线和异步关闭 | `gui/main_frame.py`、`gui/main_frame_actions.py`、`gui/pages/fluent_pages.py`、`gui/close_controller.py` | `test_main_window_layout.py`、`test_phase2_mainframe_shutdown_gate.py` |
| 内嵌功能路由与会话 | WorkspaceRoute 映射、会话设备、内容宿主，以及页面的懒创建、激活、停用与释放 | `gui/pages/workspace_features.py`、`gui/features/base.py` | `test_workspace_feature_host.py`、`test_main_window_layout.py` |
| 全局设备上下文与概览 | 功能页设备栏与会话投影；概览页内连接刷新、缓存元数据、设备卡选择与单设备工具入口 | `gui/widgets/device_context_bar.py`、`gui/pages/device_hub.py` | `test_global_device_context.py`、`test_device_hub_page.py` |
| 一级功能与应用包工具 | 左栏语义导航、功能标题映射、截图与诊断顶部常显的应用包卡；与单设备会话分开所有权 | `gui/main_frame.py`、`gui/panels/app_panel.py` | `test_flat_feature_navigation.py`、`test_workspace_consolidation.py` |
| 自适应功能导航 | 独立宿主与分类栈的 Pivot/ComboBox 呈现、选择提交和焦点连续性；主窗口中隐藏，不拥有业务会话 | `gui/widgets/adaptive_navigation.py` | `test_adaptive_navigation.py`、`test_adaptive_category_stack.py` |
| 任务中心 | 展示活动 operation 和进程内完成历史，接收取消意图并桥接部分资源停止动作 | `gui/pages/tasks_page.py`、`services/task_history.py` | `test_task_center.py`、`test_task_history.py` |
| 业务面板与分类布局 | Devices、Apps、System、Remote 的业务内容、信号、设备上下文和响应式布局 | `gui/panels/`、`gui/widgets/category_stack.py`、`gui/widgets/responsive_*.py` | `test_app_panel_categories.py`、`test_system_panel_categories.py`、`test_responsive_panels.py`、`test_model_panels.py` |
| 内嵌功能页 | App Manager、File Explorer、Live Logcat、Performance、Screenshot 与 Settings About 页面 | `gui/features/`、`gui/dialogs/app_manager*.py`、`gui/dialogs/file_explorer*.py`、`gui/dialogs/live_logcat*.py`、`gui/dialogs/performance_launcher*.py`、`gui/dialogs/screenshot_viewer_*.py` | `test_app_manager_selection.py`、`test_screenshot_page.py`、`test_model_performance_launcher.py` |
| 瞬态交互与样式 | 消息、输入、短操作表单、系统文件选择器，以及主题、字体、无边框内容分区和复合控件 | `gui/dialogs/fluent_dialog.py`、`gui/styles/`、`gui/widgets/content_section.py`、`gui/widgets/preset_spin_box.py` | `test_fluent_dialog_contract.py`、`test_fluent_components.py`、`test_content_section.py`、`test_feature_typography.py` |
| Controller 与业务用例 | Qt 信号路由、结果聚合、operation 身份/所有权/代次和批次状态机；不直接实现 UI | `controllers/`、`adblab/application/` | `test_phase1_operations.py`、`test_device_batch_use_case.py`、`test_phase2_install_batch_gate.py` |
| ADB model 与执行层 | 设备、应用、系统、网络、测试命令；短命令和长进程统一结果/停止边界 | `models/adb_*.py`、`core/exec.py`、`core/adb_bridge.py` | `test_model_*.py`、`test_process_utils.py` |
| 设置、日志与设备存储 | schema 化 JSON 设置、内存/UI 日志、性能追踪、设备 YAML 原子读写 | `core/settings_manager.py`、`core/log_service.py`、`models/device_store.py` | `test_settings_persistence.py`、`test_logging_contract.py`、`test_device_store_concurrency.py` |
| 文件与 Remote 服务 | 文件命令/传输、scrcpy 启停、输入映射、持久 ADB shell 和 Remote 生命周期 | `services/file_explorer.py`、`models/file_explorer_worker.py`、`services/remote/` | `test_file_explorer_service.py`、`test_remote_services.py` |
| MobilePerf | GUI 适配层管理隔离子进程；移植内核负责指标采样和报告 | `services/mobileperf_runner.py`、`mobileperf/android/` | `test_model_mobileperf.py`、`test_mobileperf_runner_concurrency.py` |
| 工具、构建与发布 | 用户/资源/ADB 路径、ZIP 安全、输入校验、PyInstaller 与 GitHub Actions | `utils/`、`ADBLab.spec`、`.github/workflows/` | `test_runtime_tools.py`、`test_ci_contracts.py` |

当前 UI 代码只使用安装的 PySide6-Fluent-Widgets；上游源码定位规则见
[DEPENDENCY_MAP 的 Fluent 来源边界](DEPENDENCY_MAP.md#fluent-运行时来源边界)。
