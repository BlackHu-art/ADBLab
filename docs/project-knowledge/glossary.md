---
status: current
last_verified: 2026-09-05
related: [PROJECT_OVERVIEW.md, ARCHITECTURE.md, BUSINESS_FLOW.md]
---

# 术语表

本页集中定义项目专有概念和高频缩写。新增文档或功能时，若引入新的模块名、外部工具、数据格式或缩写，应同步补充本页。

## 项目专有概念

| 术语 | 含义 | 对应代码 |
| --- | --- | --- |
| ADBLab | 本项目，Android 设备管理、测试与性能诊断桌面工具 | `main.py`、`utils/app_metadata.py` |
| ADB | Android Debug Bridge，主设备命令边界 | `utils/adb_resolver.py`、`models/adb_*.py` |
| device id / serial | ADB 设备选择标识，可能是 USB serial 或网络地址 | model/controller 的 `device_ip`/`device_id` 参数 |
| MainFrame | 主窗口和 GUI 组合根 | `gui/main_frame.py::MainFrame` |
| SidePanel | 持有业务概览面板和共享设备状态的兼容门面 | `gui/panels/side_panel.py::SidePanel` |
| DeviceManager | 隐藏的原设备面板控制器；其列表复选状态仍是批量目标的兼容状态源，不是单设备会话 registry | `gui/panels/device_manager.py::DeviceManager` |
| DeviceContextBar | 页面堆叠外的全局设备栏，提交批量选择/连接动作，并投影可见宿主的会话控件 | `gui/widgets/device_context_bar.py::DeviceContextBar` |
| DeviceHubPage | 设备概览与工作流入口，只显示发现快照，不持有独立选择或设备命令 | `gui/pages/device_hub.py::DeviceHubPage` |
| WorkspaceRoute | 定位业务宿主、功能、可选设备和载荷的路由值对象 | `gui/pages/workspace_features.py::WorkspaceRoute` |
| WorkspaceFeatureHost | 承载 Workspace 路由、设备上下文、内容栈和关闭屏障的宿主 | `gui/pages/workspace_features.py::WorkspaceFeatureHost` |
| 主左栏 | 九个业务功能与首页、任务、设置共十二个一级入口；直接提交语义路由 | `gui/main_frame.py::MainFrame` |
| CollapsibleTools | 应用管理同页共享工具的展开/收起容器，只管显隐，不拥有业务会话 | `gui/widgets/collapsible_tools.py::CollapsibleTools` |
| AdaptiveNavigation | 在页签与下拉框之间自适应切换的功能选择控件，不拥有业务页面与历史 | `gui/widgets/adaptive_navigation.py::AdaptiveNavigation` |
| AdaptiveCategoryStack | 业务面板内部一次显示一个分类的内容栈 | `gui/widgets/category_stack.py::AdaptiveCategoryStack` |
| 批量操作目标 | 全局设备栏复选形成的零台或多台设备集合，提交到原设备状态源 | `gui/widgets/device_context_bar.py`、`gui/panels/side_panel.py::SidePanel.selected_devices` |
| 会话设备 | 单设备功能或 Remote 独立绑定的设备，不等同于批量操作目标 | `gui/pages/workspace_features.py::WorkspaceFeatureHost` |
| FeatureSessionKey | 由 feature、device_id、generation 组成的不可变页面会话标识 | `gui/features/base.py::FeatureSessionKey` |
| FeatureSessionRegistry | 懒创建并复用内嵌功能页，转发 activate/deactivate/request_dispose 和关闭任务登记 | `gui/features/base.py::FeatureSessionRegistry` |
| ADBController | 把 Qt signals 协调到 ADB models 的多 mixin Controller | `controllers/__init__.py::ADBController` |
| handler map | 合并各 Controller mixin 的 `_handlers` 注册表，按异步 model method 名称选择 `_process_*_result` 处理器 | `controllers/_base.py` |
| Model | 封装 ADB 操作并输出标准结果的逻辑层 | `models/adb_device.py` 等 |
| Service | 较低 Qt 耦合的可复用业务/外部工具适配 | `services/remote/`、`services/file_explorer.py` |
| Worker | 在 QThread/QRunnable/子进程中执行耗时任务的执行体 | `AppManagerWorker`、文件浏览器的 `ADBWorker`/`TransferWorker` |
| `async_command` | 把 model 方法包装成 QRunnable 并发出 `command_finished` | `models/adb_model.py` |
| CommandRunner | 返回标准 CommandResult 的短生命周期 subprocess 执行器 | `core/exec.py` |
| CommandResult | 包含 success/output/error/returncode 的标准命令结果 | `core/exec.py` |
| ProcessRunner | 长生命周期进程注册、停止和全局清理器 | `core/exec.py` |
| ADBBridge | ADB shell 适配，支持持久输入 session | `core/adb_bridge.py` |
| ADBInputSession | 每设备持久 `adb shell`，用于低延迟 input 命令 | `core/adb_bridge.py` |
| DeviceStore | 按 alias 保存含 `ip` 标识和属性的 YAML 元数据存储；历史记录不代表当前在线设备或复选目标 | `models/device_store.py` |
| AppSettings | 应用设置单例和 JSON 存储 | `core/settings_manager.py` |
| LogService | 线程安全缓冲、批量向 Qt 发日志信号的服务 | `core/log_service.py` |
| perf trace | 由 `build_async_perf/attach_perf/split_perf/summarize_perf` 等函数记录和汇总异步耗时 | `core/perf_trace.py` |
| DeviceBatchUseCase | 卸载、清数据、重启、当前 Activity 等多设备批次的状态与汇总用例 | `adblab/application/device_batch.py` |
| OperationManager | 管理业务操作身份、状态机、进度、取消意图和结果汇总的纯 Python registry，不拥有线程/进程 | `adblab/application/operations.py` |
| OperationMetadata | `async_command` 为 operation 调用组装的信封：operation/unit/task/target 身份、预期 artifact、owner/generation token | `adblab/application/envelope.py` |
| InstallBatchUseCase | 安装批次 start/complete/fail/cancel/retry、部分失败与失败项重试状态机 | `adblab/application/install_batch.py` |
| ResponsiveCoordinator | 响应式布局的度量、重排和溢出收敛入口 | `gui/widgets/responsive_coordinator.py` |
| ScreenAdapter / QtScreenAdapter | 屏幕适配协议与 Qt 实现：所在屏幕、可用几何、逻辑 DPI 与变更订阅 | `gui/screen_adapter.py` |
| Remote | 左侧“远程控制”的 scrcpy 投屏与 ADB 远程输入功能，使用独立会话设备 | `gui/panels/remote_panel.py`、`services/remote/` |
| scrcpy | Android 投屏/控制外部工具 | `scrcpy-win64/`、`ScrcpyService` |
| ScrcpyConfig | scrcpy 用户配置数据类 | `services/remote/types.py` |
| PreflightResult | scrcpy 启动前设备可达性和详情检查结果 | `services/remote/types.py` |
| ScrcpyLaunchPlan | 可执行文件、参数、预检结果的启动计划 | `services/remote/types.py` |
| MobilePerf | 随项目移植的 Android 性能采集内核 | `mobileperf/` |
| MobilePerfRunner | GUI 到 MobilePerf 子进程的适配器 | `services/mobileperf_runner.py` |
| MobilePerfRunConfig | 运行参数数据类，可写临时 config | `services/mobileperf_runner.py` |
| StartUp | MobilePerf 内核组合和运行入口 | `mobileperf/android/startup.py::StartUp` |
| monitor | MobilePerf 的单类指标采集器，如 CPU/Mem/FPS | `mobileperf/android/*.py` |
| RuntimeData | MobilePerf 每运行一份的运行时状态；类属性读写经元类代理转发到当前运行实例，调用点保持兼容 | `mobileperf/android/globaldata.py` |
| Monkey | Android 随机事件压力工具；项目有普通测试模式和 MobilePerf 可选 monitor | `models/adb_testing.py`、`mobileperf/android/monkey.py` |
| 前台包名检测 | 通过多个 dumpsys 路径解析前台包名的模块级函数（无 FocusDetector 类） | `models/base/focus_detector.py`（`detect_current_package` / `extract_package_name`） |
| bugreport | Android 系统诊断归档，可选经 chkbugreport JAR 转换 | `models/adb_testing.py` |
| ANR | Application Not Responding 诊断文件/状态 | Controller/testing model |
| Perfetto | 外部性能 trace 分析网站，本项目只提供打开链接 | `PerformancePage.open_perfetto` |
| 用户数据目录 | 应用可写配置根目录；当前日志主要保存在内存并显示于 UI，不保证写入该目录 | `utils/user_data.py`、`core/log_service.py` |
| resource path | 开发目录或 PyInstaller `_MEIPASS` 的只读资源定位 | `utils/resource_path.py` |
| runtime tool cache | frozen onefile 场景复制长进程工具的稳定平台 cache 目录 | `utils/runtime_tools.py` |
| 待确认 | 仓库代码不能独立证明，需要产品、运维、服务方或实机验证 | 本知识库统一标记 |
