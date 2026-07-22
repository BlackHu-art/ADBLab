# 模块地图

## 总表

| 模块 | 路径 | 职责 | 入口 | 上游 | 下游 | 核心文件 | 测试 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 启动与元数据 | `main.py`、`utils/app_metadata.py` | CLI 分派、GUI 启动、打包自检、版本 | `main.py` | 用户、PyInstaller | Qt、MainFrame、MobilePerf | `main.py` | `test_model_execution.py` |
| GUI 壳与接线 | `gui/main_frame.py` | 主窗口、设备扫描、懒加载页签、信号接线、关闭清理 | `MainFrame` | 启动入口 | panels、dialogs、controller | `main_frame.py` | `test_model_execution.py` |
| 面板 | `gui/panels/` | 设备/应用/系统/Remote/日志交互 | Qt 事件与 `SidePanelSignals` | 用户、MainFrame | controller、remote service | `side_panel.py`、`app_panel.py`、`remote_panel.py` | `test_model_execution.py`、`test_remote_services.py` |
| 对话框 | `gui/dialogs/` | 应用管理、文件、logcat、MobilePerf、截图、设置 | MainFrame/面板按钮 | 用户、MainFrame | workers、services、文件系统 | `app_manager.py`、`file_explorer.py`、`performance_launcher.py` | `test_model_execution.py` |
| Controller | `controllers/` | Qt 信号到 model 调用及结果聚合 | `ADBController` | MainFrame、panels | ADB models、DeviceStore、邮件 | `_base.py` 与 6 个 mixin | `test_model_execution.py` |
| ADB Model | `models/adb_*.py` | 设备、应用、系统、网络、测试和高级命令 | `*_async` 方法 | Controller | CommandRunner、ProcessRunner、ADBBridge | `adb_model.py`、`adb_testing.py` | `test_model_execution.py` |
| 命令与进程 | `models/base/` | 短命令结果规范化、长进程管理、前台包检测 | `CommandRunner.run`、`ProcessRunner.start` | models、dialogs、remote | subprocess、ADB | `command_runner.py`、`process_runner.py` | `test_model_execution.py` |
| 核心基础设施 | `core/` | 设置、日志、性能追踪、持久输入 shell | 单例/服务类 | 全应用 | JSON、Qt、subprocess | `settings_manager.py`、`log_service.py`、`adb_bridge.py` | `test_model_execution.py` |
| 设备存储 | `models/device_store.py` | 设备元数据读写和旧文件迁移 | `DeviceStore` | Controller、DeviceManager | YAML、用户目录 | `device_store.py` | `test_model_execution.py` |
| 应用管理 Worker | `models/app_manager_worker.py` | 应用列表、详情、权限、备份恢复 | `AppManagerWorker.run` | App Manager 对话框 | ADB、ZIP、线程池 | `app_manager_worker.py` | `test_model_execution.py` |
| 文件浏览器 | `models/file_explorer_*`、`gui/dialogs/file_explorer.py` | 路径/命令构建、列表解析、传输和文件 UI | `FileExplorerDialog` | MainFrame | ADB、文件系统 | `file_explorer_service.py`、`file_explorer_worker.py` | 3 个测试文件均有覆盖 |
| Remote | `models/remote/`、`gui/panels/remote_panel.py` | scrcpy 预检/启动/FPS、ADB 输入、窗口聚焦 | `RemotePanel` | SidePanel | scrcpy、ADBBridge、Win32 | `scrcpy_service.py`、`control_service.py` | `test_remote_services.py` |
| MobilePerf 适配 | `models/mobileperf/`、`gui/dialogs/performance_launcher.py` | 配置生成、子进程生命周期、日志和结果定位 | `PerformanceLauncherDialog` | MainFrame | MobilePerf 内核、ADB | `runner.py`、`performance_launcher.py` | `test_model_execution.py` |
| MobilePerf 内核 | `mobileperf/android/` | 多指标采集、Monkey、logcat、CSV/XLSX 报告 | `StartUp.run` | MobilePerfRunner/CLI | ADB、线程、XLSXWriter | `startup.py`、各 monitor、`androiddevice.py` | `test_model_execution.py` 部分覆盖 |
| 临时邮箱 | `core/mail/` | 获取临时账号、轮询邮件、提取验证码 | `GetRandomEmailTask.run` | Controller | 外部 HTTPS API、YAML | `email_service.py`、`email_task.py` | 无专门测试 |
| 工具与路径 | `utils/` | ADB/资源/用户目录解析、ZIP 安全、批次跟踪 | 函数/小类 | 全应用 | OS、文件系统 | `runtime_tools.py`、`archive.py` 等 | `test_runtime_tools.py`、`test_model_execution.py` |
| 构建与发布 | `ADBLab.spec`、`.github/workflows/` | 测试、三平台打包、Release 和清理 | GitHub 事件/本地 PyInstaller | 开发者、GitHub | PyInstaller、GitHub API | `Build-exe.yaml`、`Auto-Clean.yaml` | 工作流契约测试 |

## 模块明细

### 启动与元数据

- **职责/接口**：`main.py::_dispatch_cli()` 识别 GUI、`--mobileperf-worker`、`--self-check packaging`；`_run_gui()` 创建 QApplication 和 MainFrame；`utils/app_metadata.py` 提供版本常量。
- **输入/输出**：命令行参数、应用设置和资源路径；输出 GUI 事件循环退出码或自检文本/退出码。
- **上下游**：上游为用户或打包程序；下游为 PySide6、`AppSettings`、`BaseStyles`、`MainFrame`、`mobileperf.android.startup.StartUp`。
- **配置/数据/外部服务**：读取主题和资源；自检写入后删除用户目录探针；Windows 设置 AppUserModelID。
- **测试/风险/待确认**：入口、版本和自检有测试/CI；未知 CLI 参数会静默进入 GUI，是否符合期望待确认。

### GUI 壳与面板

- **职责/接口**：`MainFrame` 构建工具栏、左右分栏、Device/Apps/System/Remote 页签和对话框；`_ScanThread` 周期执行设备发现；`SidePanelSignals`/`ADBControllerSignals` 是 UI 对外接口。
- **输入/输出**：Qt 事件、选中设备和表单值；输出控制信号、日志、状态栏和对话框。
- **上下游**：上游是 QApplication/用户；下游是 `ADBController`、各 panel/dialog、`CommandRunner`、`AppSettings`。
- **配置/数据/外部服务**：`continuous_device_scan`、`device_scan_interval_ms`、窗口尺寸/分栏、主题、保存目录；通过 ADB 扫描设备。
- **测试/风险/待确认**：懒加载、扫描、主题、窗口关闭和 Remote 有测试；Remote 正在控制的设备与 UI 后续选中的设备可能不一致；真实多设备 UI 压测待确认。

### 对话框

- **职责/接口**：`AppManagerDialog`、`FileExplorerDialog`、`LiveLogcatDialog`、`PerformanceLauncherDialog`、`ScreenshotViewer`、`SettingsDialog` 分别处理复杂交互；`gui/dialogs/lifecycle.py` 提供安全断开和延后等待线程。
- **输入/输出**：设备标识、文件/包名、用户配置；输出 ADB 操作、结果文件、日志和设置。
- **上下游**：上游为 MainFrame/用户；下游为专用 QThread、model service、ProcessRunner、文件系统。
- **配置/数据/外部服务**：保存目录、日志上限、主题、MobilePerf 参数；调用 ADB、scrcpy、Perfetto URL。
- **测试/风险/待确认**：大量轻量 GUI 测试覆盖关闭清理；App Manager 对若干 ADB 失败仍报告成功；文件删除有独立确认，但全局危险操作开关未接入；真实 Qt/设备端长时间稳定性待确认。

### Controller

- **职责/接口**：`controllers.__init__.ADBController` 用多重继承组合设备、应用、文件、输入、媒体和系统 mixin；`_ADBControllerBase` 创建 model、建立方法名 handler map、接收 `command_finished` 并发出 UI 反馈。
- **输入/输出**：Qt signals 的设备/命令参数；输出日志、进度、设备列表、截图路径和操作完成信号。
- **上下游**：上游 MainFrame/panels；下游四个 ADB model、DeviceStore、线程池、临时邮箱任务。
- **配置/数据/外部服务**：性能日志阈值、保存目录和 Monkey 参数；维护 `_pending_ops`、批次 tracker、截图/录屏共享状态。
- **测试/风险/待确认**：信号覆盖和关键处理器有测试；`_pending_ops` 可能持续增长，同名批次和并发截图共享可变状态可能相互覆盖，多设备并发行为待压力验证。

### ADB Model

- **职责/接口**：`@async_command` 将 `*_async` 方法提交 QThreadPool；`ADBDevice`、`ADBApp`、`ADBAdvanced`、`ADBTesting` 提供设备、应用、系统、测试命令。
- **输入/输出**：设备序列号和业务参数；输出 `CommandResult.to_dict()` 风格字典或专用数据。
- **上下游**：上游 Controller；下游 CommandRunner、ProcessRunner、ADBBridge、ADB device。
- **配置/数据/外部服务**：ADB、aapt、Java、设备文件、日志/截图/录屏/bugreport。
- **测试/风险/待确认**：多数命令适配与失败分支有单测；Monkey 超时检测路径与 CommandRunner 语义不匹配，`get_current_activity_async()` 可能在无结果时仍返回成功，Android 版本差异待实机矩阵确认。

### 命令、进程与 ADBBridge

- **职责/接口**：`CommandRunner.run/run_to_file` 统一短命令；`ProcessRunner.start/stop/spawn/stop_all_tracked` 管理长进程；`ADBBridge`/`ADBInputSession` 维持低延迟 shell。
- **输入/输出**：参数数组、超时、流；输出 `CommandResult` 或 `Popen`/布尔发送状态。
- **上下游**：上游 models/dialogs/Remote；下游操作系统、ADB 和 taskkill。
- **配置/数据/外部服务**：解析内置 ADB；记录活跃命令计数和全局进程表。
- **测试/风险/待确认**：替换、停止、并发和清理有单测；`ADBBridge` 直接使用 Popen，MobilePerf 内核也绕过统一边界；持久输入仅确认写入成功，不能确认设备实际执行。

### 设置、日志与性能追踪

- **职责/接口**：`AppSettings` 管理 JSON；`LogService` 用 QMutex 缓冲并批量发信号；`core.perf_trace` 的函数记录并汇总异步操作耗时。
- **输入/输出**：设置键值、日志消息、时间戳；输出用户配置文件、UI 日志和慢操作记录。
- **上下游**：上游全应用；下游用户目录、Qt 定时器/信号、Python logging。
- **配置/数据/外部服务**：`DEFAULTS` 中的主题、窗口、扫描、保存路径、日志、Monkey；无网络依赖。
- **测试/风险/待确认**：迁移、日志线程和 flush 有测试；AppSettings 的 debounce Timer 与数据字典无锁，`LogService` 清空 root logger handlers 有全局副作用；真实并发写设置待确认。

### DeviceStore

- **职责/接口**：`load/save/upsert_devices/get_device` 管理用户目录 `connected_devices.yaml` 并迁移旧 `resources/connected_devices.yaml`。
- **输入/输出**：ADB 设备标识与属性；输出 YAML 和设备字典。
- **上下游**：上游 Controller/DeviceManager；下游 PyYAML、用户目录。
- **配置/数据/外部服务**：存储设备连接信息和显示属性；无数据库。
- **测试/风险/待确认**：迁移有测试；保存不是原子写，且变更锁在写盘前释放，重叠写可能丢数据或损坏 YAML；现有旧文件含设备标识，仓库分发合规性待确认。

### App Manager

- **职责/接口**：`AppManagerWorker.run()` 根据 operation 分派列表、详情、权限、修改、备份、恢复；对话框负责选择、过滤、预设和 worker 生命周期。
- **输入/输出**：包名、动作、备份 ZIP、预设 JSON；输出应用列表、权限、备份包和日志。
- **上下游**：上游 AppManagerDialog；下游 ADB、ThreadPoolExecutor、zipfile、本地文件系统。
- **配置/数据/外部服务**：全局保存目录；设备 `/data/app` 与应用数据。
- **测试/风险/待确认**：批量详情、关闭清理有测试；备份 pull/restore install/权限结果存在未检查后仍成功提示的路径；备份恢复完整性和 Android 新版本权限待实机确认。

### 文件浏览器

- **职责/接口**：`models.file_explorer_service` 的模块级纯函数负责安全文件名、引用、路径、`ls` 解析与命令构建；两个 worker 负责短命令/传输；对话框负责浏览和操作。
- **输入/输出**：设备路径、文件名、本地路径；输出目录项、传输文件、编辑结果和状态。
- **上下游**：上游 MainFrame/用户；下游 CommandRunner、ProcessRunner、ADB、文件系统。
- **配置/数据/外部服务**：保存目录、root 命令包装；无数据库。
- **测试/风险/待确认**：引用、解析、传输失败和 UI 表格有测试；删除使用递归 `rm -rf` 但有确认；root 模式、脚本执行和大文件取消在真实设备上的行为待确认。

### Remote

- **职责/接口**：`ScrcpyService` 构建 `ScrcpyLaunchPlan` 并启动/停止；`RemoteControlService`/`RemoteInputEngine` 转换按键、滑动和旋转；`RemotePanel` 管理 worker、stderr/FPS、watchdog 和串行输入 executor。
- **输入/输出**：设备、编码器、码率/分辨率/FPS/方向等设置；输出 scrcpy 窗口、状态/FPS 和 ADB 输入。
- **上下游**：上游 SidePanel；下游 scrcpy、ADBBridge、Win32 window API、ProcessRunner。
- **配置/数据/外部服务**：`scrcpy_*` 设置键、尺寸 TTL 缓存。
- **测试/风险/待确认**：服务、面板与关闭清理覆盖较好；非 Windows 依赖系统 scrcpy，未在 CI 做功能测试；切换当前设备后 Remote 输入目标是否应锁定启动设备待确认。

### MobilePerf 适配与内核

- **职责/接口**：`MobilePerfRunConfig.write_config()` 生成临时配置；`MobilePerfRunner.start/stop/request_stop` 管理隔离子进程；`StartUp.run/stop` 启停各 monitor 并生成报告。
- **输入/输出**：设备、包名、频率、时长、Monkey、dumpheap、日志路径；输出 CSV/XLSX、设备信息、日志与 heapdump。
- **上下游**：上游 PerformanceLauncherDialog；下游 `python -m mobileperf.android.startup` 或冻结程序 worker、ADB、XLSXWriter。
- **配置/数据/外部服务**：临时 config、`ADB_PATH`、停止标记、结果目录；MobilePerf 使用类级 RuntimeData 和多个原生线程。
- **测试/风险/待确认**：配置、启动/停止、报告名、停止文件和部分 Monkey 参数有测试；内核有直接 Popen/`shell=True`、全局 `os.chdir`、`os._exit(0)` 和重复 ADB 生命周期；因隔离子进程降低影响但仍需实机长跑和异常恢复验证。

### 临时邮箱

- **职责/接口**：`EmailService.get_random_email/get_email_list/get_email_detail/fetch_and_process_email` 调用外部服务；`GetRandomEmailTask.run` 在 QRunnable 中轮询并发信号。
- **输入/输出**：本地邮件配置和外部 JSON；输出临时账号与验证码信号。
- **上下游**：上游 Controller；下游 Requests、外部 API、`core/mail/mail.yaml`。
- **配置/数据/外部服务**：请求签名/指纹类材料和账号状态；具体敏感值不进入本知识库。
- **测试/风险/待确认**：无专门测试；跟踪配置疑似含敏感材料，服务会记录账号、邮件内容/验证码等敏感信息，部分请求缺少 timeout，且 PyInstaller spec 未包含 mail YAML；服务授权、可用性和打包行为均待确认。

### 工具、构建与发布

- **职责/接口**：`utils/` 提供资源/用户目录/ADB/目标校验/ZIP/批次工具；PyInstaller 和 Actions 负责打包发布。
- **输入/输出**：平台、冻结状态、连接目标、ZIP、Git 事件；输出路径、标准化目标、解压文件和三平台制品/Release。
- **上下游**：上游全应用/开发者/GitHub；下游 OS 文件系统、PyInstaller、GitHub API。
- **配置/数据/外部服务**：requirements、spec、workflow permissions、版本常量。
- **测试/风险/待确认**：路径、ZIP 和工作流契约有测试；Auto-Clean 使用 `write-all` 与浮动 action 分支，Release 流程会删除同版本发布和旧标签；macOS/Linux 实际功能、代码签名与发布审批待确认。
