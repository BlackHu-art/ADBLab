---
status: current
last_verified: 2026-10-24
related: [ARCHITECTURE.md, BUSINESS_FLOW.md, DEPENDENCY_MAP.md, UI_IMPLEMENTATION.md]
---

# 模块地图

本页只回答“功能在哪、边界是什么、从哪里验证”。调用顺序见
[BUSINESS_FLOW](BUSINESS_FLOW.md)，线程与生命周期见 [ARCHITECTURE](ARCHITECTURE.md)，外部依赖见
[DEPENDENCY_MAP](DEPENDENCY_MAP.md)。测试列均相对于 `tests/`，只列代表性入口，不维护文件数量。
界面组件的组合、呈现接入方式和有意保留的例外见 [UI_IMPLEMENTATION](UI_IMPLEMENTATION.md)。

## 目录职责与兼容入口

| 目录 | 实际职责 | 保留入口与边界 |
| --- | --- | --- |
| `gui/features/`、`gui/pages/` | 按功能组织页面与协作者、首页和工作区容器 | 旧 dialogs 指向同一实现；fluent_pages 保留设置实现和首页/容器导出 |
| `controllers/`、`controllers/media/` | 信号协调、模型装配、截图/录屏/诊断处理 | 旧媒体组合 mixin 和 Controller 公共入口保留 |
| `services/tasks/`、`services/devices/` | 业务操作身份与结果、设备上下文和批次用例 | 纯 Python；不持有 QWidget 或用户数据目录 |
| `core/tasks/` | 取消、资源监督及显式 Qt 监督器 | 纯包根不导入 Qt；业务状态不归资源监督器所有 |
| `gui/adapters/`、`gui/workers/` | 运行时服务的 Qt 适配，以及设备发现、应用和文件 Qt worker | 包根轻量；两个 models 旧模块为同模块兼容入口；窗口/页面仍拥有实例与关闭流程 |
| `services/apps/`、`services/performance/`、`services/remote/windowing/` | 应用事务与 helper、性能配置/结果、窗口平台适配 | 原公开入口兼容；运行器/平台策略保留原资源 owner |
| `models/`、`core/`、`core/settings/` | 设备能力模型、命令/进程/日志基础设施、设置规则 | 模型可保留 Qt 异步边界；settings_manager 仍是唯一持久化与保存生命周期 owner |
| `utils/`、`resources/`、`runtime-tools/` | 路径、安全工具与随包资源 | 用户数据和运行时缓存使用原目录解析，资源及外部二进制不随源码归包迁移 |

Qt worker 旧/新导入身份、依赖重绑定及新入口导入边界由
`test_worker_module_compatibility.py` 验证。目录归位不改变数据格式和页面工厂替换点。

## 启动、界面与功能宿主

| 区域 | 当前职责与边界 | 主要入口 | 代表性测试 |
| --- | --- | --- | --- |
| 入口与元数据 | CLI 分派、GUI 比例预加载、版本，以及不创建主窗口的自检；packaging 自检验证资源、翻译解码和外部工具边界 | `main.py`、`utils/app_metadata.py` | `test_gui_bootstrap.py`、`test_model_meta.py`、`test_runtime_tools.py` |
| GUI 启动与早期诊断 | 启动图标首帧门禁、设置回写与历史加载、分阶段主窗构建、首帧交接和中止清理；独立显示进程失败时回退本地图标，诊断覆盖日志服务尚未就绪的失败 | `main.py`、`gui/startup.py`、`gui/startup_task.py`、`gui/startup_stages.py`、`gui/startup_process.py`、`gui/startup_worker.py`、`gui/widgets/startup_splash.py`、`core/startup_diagnostics.py` | `test_gui_startup.py`、`test_mainframe_startup.py`、`test_startup_process.py`、`test_startup_splash.py`、`test_startup_diagnostics.py` |
| 界面语言 | 创建页面前安装 Qt、Fluent 与应用翻译；设置页保存语言偏好，显示文案和稳定业务值分离；静态资源模块注册 `.qm`，加载失败保留源文案并记录诊断 | `gui/i18n.py`、`gui/generated/translations_rc.py`、`resources/i18n/`、`gui/pages/fluent_pages.py` | `test_i18n.py`、`test_application_languages.py`、`test_dialog_languages.py`、`test_gui_bootstrap.py` |
| 主窗口与顶层页面 | FluentWindow 组合根；负责页面注册、主题与屏幕适配、设备扫描、信号接线和异步关闭 | `gui/main_frame.py`、`gui/main_frame_actions.py`、`gui/pages/fluent_pages.py`、`gui/close_controller.py` | `test_main_window_layout.py`、`test_phase2_mainframe_shutdown_gate.py` |
| 首页与工作区容器 | 首页快捷卡与设备摘要、Gallery/分类/工作区容器；完整类分别归位，旧fluent入口静态导出同一对象，设置类与其依赖替换点仍原位 | `gui/pages/home.py`、`gui/pages/workspace_containers.py`、`gui/pages/fluent_pages.py` | `test_home_workspace_module_compatibility.py`、`test_home_banner.py`、`test_page_layout.py`、`test_workspace_route_payload.py` |
| 内嵌功能路由与会话 | WorkspaceRoute 映射、会话设备、内容宿主，以及页面的懒创建、激活、停用与释放；可选回调在会话发布前校验，异步释放要求完成信号 | `gui/pages/workspace_features.py`、`gui/features/base.py`、`gui/features/contracts.py` | `test_workspace_feature_host.py`、`test_workspace_route_payload.py`、`test_workspace_device_recovery.py`、`test_feature_contracts.py` |
| 设备操作准入 | 固定会话的新命令要求设备已选且在线；停止使用原任务目标 | `gui/pages/workspace_features.py`、各功能页的 `set_device_selected` 与提交边界 | `test_session_device_admission.py`、`test_file_app_device_admission.py` |
| 全局设备上下文与概览 | 纯 DeviceContext 拥有选择/发现状态；SidePanel 与 DeviceManager 桥接 Qt 输入和快照；功能页设备栏、会话与概览投影 | `services/devices/device_context.py`、`gui/panels/side_panel.py`、`gui/panels/device_manager.py`、`gui/widgets/device_context_bar.py`、`gui/pages/device_hub.py` | `test_device_context.py`、`test_device_context_adapter.py`、`test_global_device_context.py`、`test_device_hub_page.py` |
| 无线 ADB 配对 | 可收起的页内连接区、二维码/六位码配对、精确 GUID 在线确认与补填地址续连；环境失效、取消和客户端退出屏障 | `gui/widgets/device_connection.py`、`gui/adapters/adb_pairing.py`、`services/adb_pairing.py`、`controllers/_device.py`、`core/native_process.py` | `test_adb_pairing.py`、`test_qt_adb_pairing.py`、`test_device_connection.py`、`test_wireless_pairing_flow.py`、`test_wireless_pairing_layout.py`、`test_wireless_connection_history.py`、`test_native_command_scope.py` |
| 一级功能与应用包工具 | 左栏语义导航、可访问名称映射、应用与诊断顶部常显的应用包卡、截图与屏幕页复用的设备工具；与单设备会话分开所有权 | `gui/main_frame.py`、`gui/panels/app_panel.py` | `test_flat_feature_navigation.py`、`test_workspace_consolidation.py` |
| 侧栏主题入口 | 收起时图标切换、展开时原生深色开关；复用应用主题状态和设置持久化，不参与页面导航 | `gui/widgets/navigation_theme.py`、`gui/main_frame.py` | `test_navigation_theme.py` |
| 自适应功能导航 | 独立宿主与分类栈的 Pivot/ComboBox 呈现、选择提交和焦点连续性；主窗口中隐藏，不拥有业务会话 | `gui/widgets/adaptive_navigation.py` | `test_adaptive_navigation.py`、`test_adaptive_category_stack.py` |
| 操作反馈与任务中心 | 声明式动作归属、逐台 ActionResult 和通知；任务中心同时显示普通操作在途入口、可取消 operation 和测试归档，TaskHistoryStore 留作独立页面的兼容入口 | `controllers/action_catalog.py`、`services/tasks/action_results.py`、`gui/action_feedback.py`、`gui/pages/tasks_page.py`、`gui/widgets/action_result_view.py` | `test_task_center.py`、`test_action_results.py`、`test_action_feedback.py`、`test_task_history.py` |
| 测试结果与方案 | 跨重启的有界结果索引、命名参数方案、跨实例保存协调、附件打开与历史参数回填 | `services/run_library.py`、`gui/run_library.py`、`gui/widgets/run_results.py`、`gui/widgets/run_preset_bar.py`、`gui/features/performance/library.py` | `test_run_library.py`、`test_run_library_concurrency.py`、`test_run_library_ui.py`、`test_run_results.py`、`test_run_library_integration.py`、`test_monkey_library.py`、`test_performance_library.py` |
| 业务面板与分类布局 | DeviceManager、AppPanel、SystemPanel 和 RemotePanel 的内容、信号、设备上下文和响应式布局 | `gui/panels/`、`gui/widgets/category_stack.py`、`gui/widgets/responsive_*.py` | `test_app_panel_categories.py`、`test_system_panel_categories.py`、`test_responsive_panels.py`、`test_model_panels.py` |
| 内嵌功能页 | App Manager、File Explorer、Live Logcat、Performance、Screenshot 与 Settings About 页面；五类功能的实现和协作者在各自功能包，旧 dialogs 路径兼容；media 保留实际包入口定义 | `gui/features/app_manager/`、`gui/features/file_explorer/`、`gui/features/logcat/`、`gui/features/performance/`、`gui/features/media/`、`gui/widgets/performance_progress.py` | `test_app_manager_selection.py`、`test_screenshot_page.py`、`test_model_performance_launcher.py`、`test_logcat_module_compatibility.py`、`test_app_manager_module_compatibility.py`、`test_file_explorer_module_compatibility.py`、`test_performance_module_compatibility.py`、`test_media_module_compatibility.py` |
| 瞬态交互与样式 | 窗口内非模态消息、模态输入与短操作表单、系统文件选择器，以及主题、字体、无边框内容分区和复合控件 | `gui/notifications.py`、`gui/dialogs/fluent_dialog.py`、`gui/styles/`、`gui/widgets/content_section.py`、`gui/widgets/preset_spin_box.py` | `test_fluent_dialog_contract.py`、`test_fluent_components.py`、`test_content_section.py`、`test_feature_typography.py` |
| 页面滚动、展开与响应式协调 | 局部滚轮控制、按屏幕刷新率近似采样、自然内容裁切、有界布局收敛；文本及图片保留专用输入语义，具体接入见 [UI 实现](UI_IMPLEMENTATION.md) | `gui/widgets/settings_scroll.py`、`gui/widgets/frame_animation.py`、`gui/widgets/layout_settle.py`、`gui/widgets/responsive_*.py`、`gui/widgets/setting_card_layout.py` | `test_page_scroll_integration.py`、`test_frame_animation.py`、`test_scroll_reflow_efficiency.py`、`test_device_selector_animation.py`、`test_connection_expansion_animation.py`、`test_device_details_animation.py` |

## 业务协调、执行与资源生命周期

| 区域 | 当前职责与边界 | 主要入口 | 代表性测试 |
| --- | --- | --- | --- |
| Controller 与业务用例 | Qt 信号路由、结果聚合、operation 身份/所有权/代次、批次状态机和录屏保存重试身份；不直接实现 UI | `controllers/`、`services/tasks/`、`services/devices/`、`services/apps/install_batch.py`、`services/screen_record.py` | `test_phase1_operations.py`、`test_device_batch_use_case.py`、`test_phase2_install_batch_gate.py`、`test_recording_publication.py` |
| Controller 模型装配 | 无参工厂按原顺序创建独占模型；保留公开构造、模型属性、信号接线与关闭归属 | `controllers/model_dependencies.py`、`controllers/__init__.py`、`controllers/_base.py` | `test_controller_model_factory.py`、`test_controller_model_injection.py`、`test_controller_model_wiring.py` |
| Controller 媒体协调 | 截图 operation、录屏保存/重试与诊断分别拥有方法和处理器表；旧 mixin 组合入口保留 | `controllers/media/screenshot.py`、`controllers/media/recording.py`、`controllers/media/diagnostics.py`、`controllers/_media.py` | `test_controller_media_boundaries.py`、`test_phase2_screenshot_gate.py`、`test_recording_publication.py`、`test_diagnostic_artifact_identity.py` |
| 连续设备发现 Qt 适配 | 扫描线程与带代次载荷；窗口仍拥有线程、接线、防抖及关闭，旧类入口为同对象导出 | `gui/workers/device_discovery.py`、`gui/main_frame.py` | `test_device_discovery_adapter.py`、`test_device_scan_cleanup.py`、`test_device_scan_lifecycle.py`、`test_qt_adb_runtime.py` |
| APK 文件选择 | 同步选择接口与 Qt 文件框适配；保留原路径、取消含义和 Controller 入口，窗口显式注入，旧构造提供兼容默认值 | `services/apps/apk_selection.py`、`gui/adapters/apk_file_picker.py` | `test_apk_file_picker.py`、`test_controller_apk_picker.py`、`test_action_feedback.py`、`test_dialog_languages.py` |
| 设备连接生命周期 | 无线历史动态准入与重启通知接口；适配器封装窗口依赖，保留后绑定、关闭检查和既有执行/存储归属 | `services/devices/device_connection_lifecycle.py`、`gui/adapters/device_connection_lifecycle.py`、`controllers/_device.py` | `test_device_connection_lifecycle.py`、`test_controller_device_lifecycle.py`、`test_wireless_connection_history.py`、`test_adb_environment_integration.py`、`test_action_feedback.py` |
| 任务资源监督与关闭 | 资源登记、单任务及 owner 停止、应用关闭准入、共享截止时间和残留快照；GUI 停止阶段与后台设置/归档收尾分开，业务终态不等于资源已退出 | `core/tasks/supervision.py`、`core/tasks/qt_supervisor.py`、`gui/close_controller.py` | `test_phase2_mainframe_shutdown_gate.py`、`test_window_lifecycle.py`、`test_model_shutdown_admission.py`、`test_run_library_integration.py` |
| Monkey 业务批次 | 纯应用层维护批次、停止屏障及一次性归档交付，Controller 适配模型与信号 | `services/monkey_batch.py`、`controllers/_app_monkey.py` | `test_monkey_batch_state.py`、`test_monkey_batch_cancellation.py`、`test_monkey_library.py` |
| 进程与远端租约归属 | Monkey 按 PID/starttime 精确停止；MobilePerf worker、显式客户端与远端租约分别确认退出，不把独立 ADB 服务纳入终止目标 | `core/monkey_process.py`、`core/owned_process.py`、`core/native_process.py` | `test_monkey_process_ownership.py`、`test_monkey_lease_shell.py`、`test_mobileperf_owned_processes.py`、`test_mobileperf_monkey_lifecycle.py` |
| ADB model 与执行层 | 设备、应用、系统、网络、测试命令；短命令和长进程统一结果/停止边界，清理失败保留客户端归属 | `models/adb_*.py`、`core/exec.py`、`core/adb_bridge.py`、`core/adb_runtime.py` | `test_model_*.py`、`test_process_utils.py`、`test_adb_execution_selection.py`、`test_native_capture_cleanup.py`、`test_adb_runtime_native_ownership.py` |
| ADB 自动适配 | 协议传输、后台能力验证与原生耗时比较、按设备选择短命令后端和查询预算，以及 Qt 启动/关闭接入；独立快速命令不注入 GUI 运行实例 | `core/adb_transport.py`、`core/adb_discovery.py`、`core/adb_runtime.py`、`core/adb_query.py`、`utils/adb_resolver.py`、`services/adb_clients.py`、`gui/widgets/adb_client_card.py`（客户端卡与执行环境卡）、`gui/adapters/adb_runtime.py`、`utils/adb_debug.py`、`scripts/adb_fast.py` | `test_adb_resolver.py`、`test_adb_clients.py`、`test_adb_runtime.py`、`test_adb_discovery.py`、`test_adb_debug.py`、`test_adb_query.py`、`test_adb_fast.py`、`test_qt_adb_runtime.py`、`test_adb_injection_argv.py` |
| 设置、日志与设备存储 | 纯设置规则/字典迁移、JSON持久化及保存关闭屏障、内存/UI日志、脱敏诊断、设备YAML原子读写 | `core/settings/schema.py`、`core/settings/migrations.py`、`core/settings_manager.py`、`core/log_service.py`、`core/diagnostics.py`、`models/device_store.py`、`utils/console_colors.py` | `test_settings_schema.py`、`test_settings_migrations.py`、`test_settings_module_compatibility.py`、`test_settings_persistence.py`、`test_settings_save_lifecycle.py`、`test_logging_contract.py`、`test_diagnostics.py`、`test_device_store_concurrency.py` |
| 应用更新检查 | 设置 About 卡片、公开正式发布解析、异步检查和关闭清理 | `gui/features/about.py`、`services/app_update.py`、`gui/adapters/app_update.py`、`utils/app_metadata.py` | `test_app_update.py`、`test_qt_app_update.py`、`test_settings_typography.py` |
| Windows 安装包升级 | 有界下载、缓存完整性、用户确认、严格关闭报告与独立进程交接 | `services/installer_update.py`、`gui/adapters/installer_update.py`、`gui/adapters/installer_handoff.py`、`core/installer_handoff.py`、`core/installer_update_protocol.py`、`core/installer_update_process.py` | `test_installer_update.py`、`test_qt_installer_update.py`、`test_installer_update_ui.py`、`test_installer_handoff.py` |
| 应用名称与图标 | 临时 DEX 批量查询 PackageManager 元数据或渲染 Drawable；独立 helper 持有部署与清理边界，可见文字优先、图标按身份增量缓存 | `services/apps/helper.py`、`services/app_metadata.py`、`services/app_icons.py`、`gui/features/app_manager/views.py`、`gui/features/app_manager/icons.py`、`tools/app_icons/Main.java` | `test_app_metadata.py`、`test_app_metadata_worker.py`、`test_app_manager_metadata.py`、`test_app_icons_service.py`、`test_app_icons_inline.py`、`test_app_manager_icons.py`、`test_app_helper_boundary.py` |
| 应用查询与解析 | 纯包信息解析、用户核验与完整只读事务；批量和兼容查询共享预算，Qt worker显式注入执行依赖并发布原信号 | `services/apps/package_details.py`、`services/apps/queries.py`、`gui/workers/app_manager.py` | `test_app_package_details.py`、`test_app_queries.py`、`test_app_query_boundary.py`、`test_app_metadata_worker.py` |
| 应用动作与归档 | 四种写动作及备份/恢复完整事务；保持同步通知、逐写用户复核、串行拉取、暂存压缩和原子发布 | `services/apps/actions.py`、`services/apps/archives.py`、`gui/workers/app_manager.py` | `test_app_actions.py`、`test_app_archives.py`、`test_app_write_boundary.py`、`test_app_manager_restore_cancellation.py` |
| 应用管理用户与权限 | 列表成功快照绑定 Android 用户，写入前复核；权限按活动包及明确用户解析，共享 UID 按身份关联 | `services/apps/queries.py`、`gui/workers/app_manager.py`、`services/app_permissions.py`、`gui/features/app_manager/details.py` | `test_app_manager_worker_users.py`、`test_app_manager_user_context.py`、`test_app_permissions.py` |
| 文件服务与传输 | 目录快照呈现与筛选、文件协议、四种独立读写事务；页面串行传输、后台图片解码、传输取消及准备资源归还 | `services/file_explorer.py`、`services/file_operations.py`、`services/file_download.py`、`gui/workers/file_explorer.py`、`gui/features/file_explorer/list.py`、`gui/features/file_explorer/transfers.py`、`gui/features/file_explorer/preview_tasks.py` | `test_file_operations.py`、`test_file_operation_adapters.py`、`test_file_explorer_population.py`、`test_file_explorer_ordering.py`、`test_file_explorer_service.py`、`test_file_explorer_preview.py`、`test_file_explorer_text.py` |
| Remote 视图与服务 | scrcpy 多设备并发预检与会话启停（含自然退出的进程身份释放）、直连/持久输入和关闭屏障；按键、手势及参数由面板分工承接 | `gui/panels/remote_panel.py`、`gui/panels/remote_panel_controls.py`、`gui/panels/remote_panel_input.py`、`gui/panels/remote_panel_scrcpy.py`、`services/remote/` | `test_scrcpy_process_release.py`、`test_remote_services.py`、`test_remote_orientation.py`、`test_remote_sessions.py`、`test_remote_input_backend.py`、`test_remote_input_shutdown.py` |
| Remote原生窗口跟踪 | 策略/工厂保留原入口，DTO/协议与Win32、X11、事件hook分工；唯一连接/回调集合按原生命周期清理 | `services/remote/window_tracking.py`、`services/remote/windowing/`；旧X11/events模块为兼容导出 | `test_remote_windowing_imports.py`、`test_remote_window_tracking.py`、`test_window_tracking_platform.py`、`test_x11_window_tracking.py`、`test_remote_window_events.py`、`test_remote_dock_updates.py` |
| scrcpy 专用 ADB | 限定协议、独立 CLI、父进程观察、会话端口归属与租约清理 | `core/scrcpy_adb_protocol.py`、`core/scrcpy_session.py`、`scripts/scrcpy_adb_bridge.py`、`utils/scrcpy_bridge.py` | `test_scrcpy_adb_protocol.py`、`test_scrcpy_adb_bridge.py`、`test_scrcpy_session.py`、`test_scrcpy_backend.py` |
| MobilePerf | 独立配置/结果服务；运行器管理隔离子进程，移植内核负责指标采样和报告 | `services/performance/config.py`、`services/performance/results.py`、`services/mobileperf_runner.py`、`mobileperf/android/` | `test_performance_service_boundaries.py`、`test_model_mobileperf.py`、`test_mobileperf_runner_concurrency.py` |
| 性能进度、会话与图表 | 各设备参数和运行状态投影、估算进度、后台结果发现与有界 CSV 指标解析、QtCharts 单位轴和可滚动图表 | `gui/widgets/performance_sessions.py`、`gui/widgets/performance_progress.py`、`gui/features/performance/run.py`、`gui/features/performance/result_tasks.py`、`services/perf_chart_data.py`、`gui/widgets/perf_chart_view.py` | `test_performance_sessions.py`、`test_performance_progress.py`、`test_perf_chart_data.py`、`test_performance_result_loading.py`、`test_performance_responsive.py` |
| 堆转储归属 | 生成前登记设备与任务命名空间、成功拉取后精确清理 | `mobileperf/android/heap_ownership.py`、`mobileperf/android/tools/androiddevice.py` | `test_mobileperf_heap_ownership.py` |

## 工具与交付

| 区域 | 当前职责与边界 | 主要入口 | 代表性测试 |
| --- | --- | --- | --- |
| 工具、构建与发布 | 用户/资源/ADB 路径、ZIP 安全、输入校验、PyInstaller 与 GitHub Actions | `utils/`、`scripts/packaging_manifest.py`、`scripts/build_app.py`、`scripts/build_scrcpy_adb_bridge.py`、`scripts/check_source_text.py`、`ADBLab.spec`、`.github/workflows/` | `test_runtime_tools.py`、`test_ci_contracts.py`、`test_build_app.py`、`test_build_scrcpy_adb_bridge.py`、`test_source_text.py` |

当前 UI 代码只使用安装的 PySide6-Fluent-Widgets；上游源码定位规则见
[DEPENDENCY_MAP 的 Fluent 来源边界](DEPENDENCY_MAP.md#fluent-运行时来源边界)。
