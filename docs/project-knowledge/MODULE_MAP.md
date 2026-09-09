---
status: current
last_verified: 2026-09-09
related: [ARCHITECTURE.md, BUSINESS_FLOW.md, DEPENDENCY_MAP.md]
---

# 模块地图

本页只回答“功能在哪、边界是什么、从哪里验证”。调用顺序见
[BUSINESS_FLOW](BUSINESS_FLOW.md)，线程与生命周期见 [ARCHITECTURE](ARCHITECTURE.md)，外部依赖见
[DEPENDENCY_MAP](DEPENDENCY_MAP.md)。测试列均相对于 `tests/`，只列代表性入口，不维护文件数量。

| 区域 | 当前职责与边界 | 主要入口 | 代表性测试 |
| --- | --- | --- | --- |
| 启动与元数据 | CLI 分派、GUI 比例预加载、QApplication 初始化、诊断转交、打包自检和版本 | `main.py`、`utils/app_metadata.py` | `test_gui_bootstrap.py`、`test_model_meta.py`、`test_runtime_tools.py` |
| 界面语言 | 创建页面前安装 Qt、Fluent 与应用翻译；设置页保存语言偏好，显示文案和稳定业务值分离 | `gui/i18n.py`、`gui/generated/translations_rc.py`、`resources/i18n/`、`gui/pages/fluent_pages.py` | `test_i18n.py`、`test_application_languages.py`、`test_dialog_languages.py` |
| 主窗口与顶层页面 | FluentWindow 组合根；负责页面注册、主题与屏幕适配、设备扫描、信号接线和异步关闭 | `gui/main_frame.py`、`gui/main_frame_actions.py`、`gui/pages/fluent_pages.py`、`gui/close_controller.py` | `test_main_window_layout.py`、`test_phase2_mainframe_shutdown_gate.py` |
| 内嵌功能路由与会话 | WorkspaceRoute 映射、会话设备、内容宿主，以及页面的懒创建、激活、停用与释放 | `gui/pages/workspace_features.py`、`gui/features/base.py` | `test_workspace_feature_host.py`、`test_workspace_route_payload.py`、`test_workspace_device_recovery.py` |
| 设备操作准入 | 固定会话的新命令要求设备已选且在线；停止使用原任务目标 | `gui/pages/workspace_features.py`、各功能页的 `set_device_selected` 与提交边界 | `test_session_device_admission.py`、`test_file_app_device_admission.py` |
| 全局设备上下文与概览 | 功能页设备栏与会话投影；概览页内连接刷新、缓存元数据、设备卡选择与单设备工具入口 | `gui/widgets/device_context_bar.py`、`gui/pages/device_hub.py` | `test_global_device_context.py`、`test_device_hub_page.py` |
| 一级功能与应用包工具 | 左栏语义导航、可访问名称映射、应用与诊断顶部常显的应用包卡、截图与屏幕页复用的设备工具；与单设备会话分开所有权 | `gui/main_frame.py`、`gui/panels/app_panel.py` | `test_flat_feature_navigation.py`、`test_workspace_consolidation.py` |
| 侧栏主题入口 | 收起时图标切换、展开时原生深色开关；复用应用主题状态和设置持久化，不参与页面导航 | `gui/widgets/navigation_theme.py`、`gui/main_frame.py` | `test_navigation_theme.py` |
| 自适应功能导航 | 独立宿主与分类栈的 Pivot/ComboBox 呈现、选择提交和焦点连续性；主窗口中隐藏，不拥有业务会话 | `gui/widgets/adaptive_navigation.py` | `test_adaptive_navigation.py`、`test_adaptive_category_stack.py` |
| 操作反馈与任务中心 | 声明式动作归属、逐台 ActionResult 和通知；任务中心同时显示普通操作在途入口、可取消 operation 和测试归档，TaskHistoryStore 留作独立页面的兼容入口 | `controllers/action_catalog.py`、`adblab/application/action_results.py`、`gui/action_feedback.py`、`gui/pages/tasks_page.py`、`gui/widgets/action_result_view.py` | `test_task_center.py`、`test_action_results.py`、`test_action_feedback.py`、`test_task_history.py` |
| 测试结果与方案 | 跨重启的有界结果索引、命名参数方案、附件打开与历史参数回填 | `services/run_library.py`、`gui/run_library.py`、`gui/widgets/run_results.py`、`gui/widgets/run_preset_bar.py`、`gui/dialogs/performance_library.py` | `test_run_library.py`、`test_run_library_ui.py`、`test_run_results.py`、`test_run_library_integration.py`、`test_monkey_library.py`、`test_performance_library.py` |
| 业务面板与分类布局 | DeviceManager、AppPanel、SystemPanel 和 RemotePanel 的内容、信号、设备上下文和响应式布局 | `gui/panels/`、`gui/widgets/category_stack.py`、`gui/widgets/responsive_*.py` | `test_app_panel_categories.py`、`test_system_panel_categories.py`、`test_responsive_panels.py`、`test_model_panels.py` |
| 内嵌功能页 | App Manager、File Explorer、Live Logcat、Performance、Screenshot 与 Settings About 页面 | `gui/features/`、`gui/dialogs/app_manager*.py`、`gui/dialogs/file_explorer*.py`、`gui/dialogs/live_logcat*.py`、`gui/dialogs/performance_launcher*.py`、`gui/widgets/performance_progress.py`、`gui/dialogs/screenshot_viewer_*.py` | `test_app_manager_selection.py`、`test_screenshot_page.py`、`test_model_performance_launcher.py` |
| 瞬态交互与样式 | 窗口内非模态消息、模态输入与短操作表单、系统文件选择器，以及主题、字体、无边框内容分区和复合控件 | `gui/notifications.py`、`gui/dialogs/fluent_dialog.py`、`gui/styles/`、`gui/widgets/content_section.py`、`gui/widgets/preset_spin_box.py` | `test_fluent_dialog_contract.py`、`test_fluent_components.py`、`test_content_section.py`、`test_feature_typography.py` |
| Controller 与业务用例 | Qt 信号路由、结果聚合、operation 身份/所有权/代次和批次状态机；不直接实现 UI | `controllers/`、`adblab/application/` | `test_phase1_operations.py`、`test_device_batch_use_case.py`、`test_phase2_install_batch_gate.py` |
| ADB model 与执行层 | 设备、应用、系统、网络、测试命令；短命令和长进程统一结果/停止边界 | `models/adb_*.py`、`core/exec.py`、`core/adb_bridge.py` | `test_model_*.py`、`test_process_utils.py` |
| ADB 自动适配 | 协议传输、后台能力验证与原生耗时比较、按设备选择短命令后端，以及 Qt 启动/关闭接入；独立快速命令不注入 GUI 运行实例 | `core/adb_transport.py`、`core/adb_runtime.py`、`adblab/presentation/qt_adb_runtime.py`、`scripts/adb_fast.py` | `test_adb_runtime.py`、`test_adb_fast.py`、`test_qt_adb_runtime.py`、`test_adb_injection_argv.py` |
| 设置、日志与设备存储 | schema 化 JSON 设置、内存/UI 日志、脱敏应用诊断、性能追踪、设备 YAML 原子读写 | `core/settings_manager.py`、`core/log_service.py`、`core/diagnostics.py`、`models/device_store.py` | `test_settings_persistence.py`、`test_logging_contract.py`、`test_diagnostics.py`、`test_device_store_concurrency.py` |
| 应用更新检查 | 设置 About 卡片、公开正式发布解析、异步检查和关闭清理 | `gui/features/about.py`、`services/app_update.py`、`adblab/presentation/qt_app_update.py`、`utils/app_metadata.py` | `test_app_update.py`、`test_qt_app_update.py`、`test_settings_typography.py` |
| 应用图标 | 临时设备端 DEX 渲染 Drawable，后台分批读取与页面缓存 | `services/app_icons.py`、`gui/dialogs/app_manager_icons.py`、`tools/app_icons/Main.java` | `test_app_icons_service.py`、`test_app_manager_icons.py` |
| 文件与 Remote 服务 | 文件命令/传输、scrcpy 启停、输入映射、持久 ADB shell 和 Remote 生命周期 | `services/file_explorer.py`、`models/file_explorer_worker.py`、`services/remote/` | `test_file_explorer_service.py`、`test_remote_services.py` |
| MobilePerf | GUI 适配层管理隔离子进程；移植内核负责指标采样和报告 | `services/mobileperf_runner.py`、`mobileperf/android/` | `test_model_mobileperf.py`、`test_mobileperf_runner_concurrency.py` |
| 性能进度、会话与图表 | 各设备参数和运行状态投影、估算进度、完成后 CSV 指标解析与 QtCharts 静态图表 | `gui/widgets/performance_sessions.py`、`gui/widgets/performance_progress.py`、`gui/dialogs/performance_launcher_run.py`、`services/perf_chart_data.py`、`gui/widgets/perf_chart_view.py` | `test_performance_sessions.py`、`test_performance_progress.py`、`test_perf_chart_data.py`、`test_performance_responsive.py` |
| 工具、构建与发布 | 用户/资源/ADB 路径、ZIP 安全、输入校验、PyInstaller 与 GitHub Actions | `utils/`、`ADBLab.spec`、`.github/workflows/` | `test_runtime_tools.py`、`test_ci_contracts.py` |

当前 UI 代码只使用安装的 PySide6-Fluent-Widgets；上游源码定位规则见
[DEPENDENCY_MAP 的 Fluent 来源边界](DEPENDENCY_MAP.md#fluent-运行时来源边界)。
