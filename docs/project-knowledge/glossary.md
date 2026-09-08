---
status: current
last_verified: 2026-09-08
related: [PROJECT_OVERVIEW.md, ARCHITECTURE.md, BUSINESS_FLOW.md]
---

# 术语表

本页只解释容易混淆的项目概念；完整模块入口和测试见 [MODULE_MAP](MODULE_MAP.md)，
外部工具用途见 [DEPENDENCY_MAP](DEPENDENCY_MAP.md)。

## 项目专有概念

| 术语 | 含义 | 对应代码 |
| --- | --- | --- |
| device id / serial | ADB 设备选择标识，可能是 USB serial 或网络地址 | model/controller 的 `device_ip`/`device_id` 参数 |
| MainFrame | 主窗口和 GUI 组合根 | `gui/main_frame.py::MainFrame` |
| SidePanel | 持有业务概览面板和共享设备状态的兼容门面 | `gui/panels/side_panel.py::SidePanel` |
| DeviceManager | 隐藏的原设备面板控制器；其列表复选状态仍是批量目标的兼容状态源，不是单设备会话 registry | `gui/panels/device_manager.py::DeviceManager` |
| DeviceContextBar | 页面堆叠外的设备选择及会话控件；内部管理连接弹层，连接入口锚定设备概览 | `gui/widgets/device_context_bar.py::DeviceContextBar` |
| DeviceHubPage | 设备概览与工作流入口，只显示发现快照，不持有独立选择或设备命令 | `gui/pages/device_hub.py::DeviceHubPage` |
| WorkspaceRoute | 定位业务宿主、功能、可选设备和载荷的路由值对象 | `gui/pages/workspace_features.py::WorkspaceRoute` |
| WorkspaceFeatureHost | 承载 Workspace 路由、设备上下文、内容栈和关闭屏障的宿主 | `gui/pages/workspace_features.py::WorkspaceFeatureHost` |
| CollapsibleTools | 展开/收起容器；当前用于测试参数和性能会话，只管显隐，不拥有业务会话 | `gui/widgets/collapsible_tools.py::CollapsibleTools` |
| AdaptiveNavigation | 在页签与下拉框之间自适应切换的功能选择控件，不拥有业务页面与历史 | `gui/widgets/adaptive_navigation.py::AdaptiveNavigation` |
| AdaptiveCategoryStack | 业务面板内部一次显示一个分类的内容栈 | `gui/widgets/category_stack.py::AdaptiveCategoryStack` |
| 批量操作目标 | 从设备概览或功能页设备栏提交的零台或多台共享目标集合，以原 DeviceManager 复选状态为准 | `gui/widgets/device_context_bar.py`、`gui/panels/side_panel.py::SidePanel.selected_devices` |
| 会话设备 | 应用管理、文件、Logcat、性能等功能页绑定的设备；查看会话和批量勾选不是同一概念，已运行任务保持原目标 | `gui/pages/workspace_features.py::WorkspaceFeatureHost` |
| FeatureSessionKey | 由 feature、device_id、generation 组成的不可变页面会话标识 | `gui/features/base.py::FeatureSessionKey` |
| FeatureSessionRegistry | 懒创建并复用内嵌功能页，转发 activate/deactivate/request_dispose 和关闭任务登记 | `gui/features/base.py::FeatureSessionRegistry` |
| ADBController | 把 Qt signals 协调到 ADB models 的多 mixin Controller | `controllers/__init__.py::ADBController` |
| handler map | 合并各 Controller mixin 的 `_handlers` 注册表，按异步 model method 名称选择 `_process_*_result` 处理器 | `controllers/_base.py` |
| `async_command` | 把 model 方法包装成 QRunnable 并发出 `command_finished` | `models/adb_model.py` |
| CommandRunner | 短命令统一执行边界；根据当前 ADB 运行策略选择原生进程或已验证的直连后端，返回 CommandResult | `core/exec.py` |
| CommandResult | 含 success/output/error/returncode 及 stale 标记的命令结果；stale 表示过期设备快照，应保留当前状态而非发布故障 | `core/exec.py` |
| ProcessRunner | 长生命周期进程注册、停止和全局清理器 | `core/exec.py` |
| AdbRuntime / QtAdbRuntime | 当前进程的 ADB 能力探测、后端选择和在途请求生命周期；Qt 适配器提供延迟启动及信号投递 | `core/adb_runtime.py`、`adblab/presentation/qt_adb_runtime.py` |
| ADBBridge | ADB shell 适配，支持持久输入 session | `core/adb_bridge.py` |
| ADBInputSession | 每设备持久 `adb shell`，用于低延迟 input 命令 | `core/adb_bridge.py` |
| DeviceStore | 按 alias 保存含 `ip` 标识和属性的 YAML 元数据存储；历史记录不代表当前在线设备或复选目标 | `models/device_store.py` |
| RunLibrary / RunLibraryController | 跨重启测试结果与参数方案；Qt 控制器串行执行存储操作 | `services/run_library.py`、`gui/run_library.py` |
| TaskHistoryStore | 进程内兼容任务终态历史；主窗口的“本次操作”由 ActionResults 提供，“测试结果”由 RunLibrary 提供 | `services/task_history.py`、`gui/pages/tasks_page.py` |
| ActionResults / ActionResult | 通用用户操作的请求登记与不可变结果快照；提交时冻结目标和显示名称，不拥有执行资源、不跨重启保存 | `adblab/application/action_results.py` |
| ActionJob / ActionEnvelope | 异步命令携带的 request/job/target 身份及载荷包装，可与原 OperationMetadata 同时存在 | `adblab/application/action_results.py`、`models/adb_model.py` |
| ActionFeedbackPresenter | 主窗口拥有的结果分发器，向任务中心、Toast 和专用阅读器投影明确结果，不从日志推断成功 | `gui/action_feedback.py` |
| TaskSupervisor / QtTaskSupervisor | 资源登记、停止、等待与残留快照；不判断业务成功 | `adblab/application/supervision.py`、`adblab/presentation/qt_task_supervisor.py` |
| AppSettings | 应用设置单例和 JSON 存储 | `core/settings_manager.py` |
| LogService | 线程安全缓冲、批量向 Qt 发日志信号的服务 | `core/log_service.py` |
| DiagnosticJournal | 当前会话的有界警告/错误摘要，负责显示前遮蔽；不持有线程或文件 I/O，落盘交给结果库队列 | `core/diagnostics.py`、`gui/run_library.py` |
| DeviceBatchUseCase | 卸载、清数据、重启、当前 Activity 等多设备批次的状态与汇总用例 | `adblab/application/device_batch.py` |
| OperationManager | 管理业务操作身份、状态机、进度、取消意图和结果汇总的纯 Python registry，不拥有线程/进程 | `adblab/application/operations.py` |
| OperationMetadata | `async_command` 为 operation 调用组装的信封：operation/unit/task/target 身份、预期 artifact、owner/generation token | `adblab/application/envelope.py` |
| InstallBatchUseCase | 安装批次 start/complete/fail/cancel/retry、部分失败与失败项重试状态机 | `adblab/application/install_batch.py` |
| ResponsiveCoordinator | 响应式布局的度量、重排和溢出收敛入口 | `gui/widgets/responsive_coordinator.py` |
| Remote | 左侧“远程控制”的 scrcpy 多设备投屏与 ADB 输入广播；镜像进程保留启动目标，停止不改向当前勾选 | `gui/panels/remote_panel.py`、`services/remote/` |
| MobilePerf | 随项目移植的 Android 性能采集内核 | `mobileperf/` |
| MobilePerfRunner | GUI 到 MobilePerf 子进程的适配器 | `services/mobileperf_runner.py` |
| MobilePerfRunConfig | 运行参数数据类，可写临时 config | `services/mobileperf_runner.py` |
| RuntimeData | MobilePerf 每运行一份的运行时状态；类属性读写经元类代理转发到当前运行实例，调用点保持兼容 | `mobileperf/android/globaldata.py` |
| Monkey | Android 随机事件压力工具；项目有普通测试模式和 MobilePerf 可选 monitor | `models/adb_testing.py`、`mobileperf/android/monkey.py` |
