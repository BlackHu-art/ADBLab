---
status: current
last_verified: 2026-08-25
related: [ARCHITECTURE.md, BUSINESS_FLOW.md]
---

# 模块地图

## 总表

| 模块 | 路径 | 职责 | 入口 | 上游 | 下游 | 核心文件 | 测试 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 启动与元数据 | `main.py`、`utils/app_metadata.py` | CLI 分派、GUI 启动、打包自检、版本 | `main.py` | 用户、PyInstaller | Qt、MainFrame、MobilePerf | `main.py` | `test_model_*.py` |
| GUI 壳与接线 | `gui/main_frame.py`、`gui/window_layout.py`、`gui/widgets/frameless_resize.py` | 主窗口、原生无边框移动/缩放、尺寸与分栏恢复、设备扫描、信号接线、关闭清理 | `MainFrame` | 启动入口 | panels、dialogs、controller、AppSettings | `main_frame.py`、`window_layout.py` | `test_model_*.py`、`test_main_window_layout.py` |
| 面板 | `gui/panels/`、`gui/widgets/responsive_layout.py`、`gui/widgets/responsive_controller.py`（re-export，实体在 `responsive_primitives.py`/`responsive_coordinator.py`/`responsive_binding.py`） | 设备/应用/系统/Remote/日志交互、懒加载滚动容器与响应式重排（`ResponsiveCoordinator` 单一协调入口） | Qt 事件与 `SidePanelSignals` | 用户、MainFrame | controller、remote service | `side_panel.py`、`base_panel.py`、`app_panel.py`、`system_panel.py`、`remote_panel.py`、`device_manager.py`（+ `device_manager_layout.py`/`device_manager_view.py`/`device_manager_responsive.py`）、`responsive_controller.py` | `test_model_*.py`、`test_remote_services.py`、`test_responsive_panels.py`、`test_responsive_layout_controller.py` |
| 对话框 | `gui/dialogs/` | 应用管理、文件、logcat、MobilePerf、截图、设置 | MainFrame/面板按钮 | 用户、MainFrame | workers、services、文件系统 | `app_manager.py`（+ `app_manager_details/form/views/batch.py`）、`file_explorer.py`（+ `file_explorer_list/view/ops/image.py`）、`live_logcat.py`（+ `live_logcat_worker/highlighter/form/stream/lifecycle.py`）、`screenshot_viewer.py`（+ `screenshot_viewer_widgets/ui/nav/actions.py`）、`performance_launcher.py`、`settings_dialog.py`、`lifecycle.py` | `test_model_*.py`、`test_settings_typography.py`、`test_settings_window_layout.py`、`test_window_lifecycle.py`、`test_app_manager_selection.py` |
| 样式与字体 | `gui/styles/` | 主题、QSS、应用级字体配置、字体角色与细粒度变更信号 | `BaseStyles`、`TypographyManager` | 启动入口、SettingsDialog | QApplication、全局 GUI | `typography.py`、`fonts.py`、`theme.py` | `test_typography_core.py`、`test_panel_typography.py`、`test_dialog_typography.py` |
| 屏幕适配 | `gui/screen_adapter.py` | `ScreenAdapter` 协议 + `QtScreenAdapter`：屏幕/可用几何/DPI 与变更订阅 | `QtScreenAdapter` | MainFrame、二级窗口生命周期 | QScreen、QGuiApplication | `screen_adapter.py` | `test_main_window_layout.py`、`test_ui_geometry_helpers.py`、`test_ui_dpi_matrix.py` |
| Controller | `controllers/` | Qt 信号到 model 调用及结果聚合、批次所有权/generation 边界 | `ADBController` | MainFrame、panels | ADB models、DeviceStore、InstallBatchUseCase/OperationManager | `_base.py` 与 6 个 mixin | `test_model_*.py` |
| vNext Operation | `adblab/application/` | 业务 operation 状态、fan-out、取消意图与兼容 metadata envelope；安装批次用例 | `OperationManager`、`InstallBatchUseCase` | 迁移中的 Controller/use case | 纯 Python 锁与值对象 | `operations.py`、`cancellation.py`、`envelope.py`、`install_batch.py` | `test_phase1_operations.py`、`test_phase2_install_batch_use_case.py`、`test_phase2_install_batch_gate.py` |
| ADB Model | `models/adb_*.py` | 设备、应用、系统、网络、测试和高级命令；operation token 透传 | `*_async` 方法 | Controller | CommandRunner、ProcessRunner、ADBBridge | `adb_model.py`、`adb_testing.py` | `test_model_*.py` |
| 命令与进程 | `core/exec.py`（旧 `models/base/*runner*` 路径已删除） | 短命令结果规范化、长进程管理、ADB 路径解析、进程句柄协议 | `CommandRunner.run`、`ProcessRunner.start`、`ExecHandle` | models、dialogs、remote、services | subprocess、ADB | `exec.py` | `test_model_*.py` |
| 核心基础设施 | `core/` | 设置（schema 版本化迁移）、日志、性能追踪、持久输入 shell | 单例/服务类 | 全应用 | JSON、Qt、subprocess | `settings_manager.py`、`log_service.py`、`adb_bridge.py` | `test_model_*.py` |
| 设备存储 | `models/device_store.py` | 设备元数据原子读写、损坏备份和旧文件迁移 | `DeviceStore` | Controller、DeviceManager | YAML、用户目录 | `device_store.py` | `test_model_*.py`、`test_device_store_concurrency.py` |
| 应用管理 Worker | `models/app_manager_worker.py` | 应用列表、详情、权限、备份恢复 | `AppManagerWorker.run` | App Manager 对话框 | ADB、ZIP、线程池 | `app_manager_worker.py` | `test_model_*.py` |
| 文件浏览器 | `services/file_explorer.py`、`models/file_explorer_worker.py`、`gui/dialogs/file_explorer.py`（+ `file_explorer_list.py`/`file_explorer_view.py`/`file_explorer_ops.py`/`file_explorer_image.py` 组合控制器） | 路径/命令构建、列表解析、传输和文件 UI | `FileExplorerDialog` | MainFrame | ADB、文件系统 | `file_explorer.py`、`file_explorer_worker.py` | 3 个测试文件均有覆盖 |
| Remote | `services/remote/`、`gui/panels/remote_panel.py`（+ `remote_panel_form.py`/`remote_panel_scrcpy.py`/`remote_panel_input.py` 组合控制器） | scrcpy 预检/启动/FPS、ADB 输入、窗口聚焦 | `RemotePanel` | SidePanel | scrcpy、ADBBridge、Win32 | `scrcpy_service.py`、`control_service.py` | `test_remote_services.py` |
| MobilePerf 适配 | `services/mobileperf_runner.py`、`gui/dialogs/performance_launcher.py`（+ `performance_launcher_form.py`/`performance_launcher_run.py`/`performance_launcher_log.py` 组合控制器） | 配置生成、子进程生命周期、日志和结果定位 | `PerformanceLauncherDialog` | MainFrame | MobilePerf 内核、ADB | `mobileperf_runner.py`、`performance_launcher*.py` | `test_model_*.py` |
| MobilePerf 内核 | `mobileperf/android/` | 多指标采集、Monkey、logcat、CSV/XLSX 报告 | `StartUp.run` | MobilePerfRunner/CLI | ADB、线程、XLSXWriter | `startup.py`、各 monitor、`androiddevice.py` | `test_model_*.py` 部分覆盖 |
| 工具与路径 | `utils/` | ADB/资源/用户目录解析、ZIP 安全、诊断值校验 | 函数/小类 | 全应用 | OS、文件系统 | `runtime_tools.py`、`archive.py`、`adb_values.py` 等 | `test_runtime_tools.py`、`test_model_*.py` |
| 构建与发布 | `ADBLab.spec`、`.github/workflows/` | 测试、三平台打包、Release 和清理 | GitHub 事件/本地 PyInstaller | 开发者、GitHub | PyInstaller、GitHub API | `Build-exe.yaml`、`Auto-Clean.yaml` | 工作流契约测试 |

## 模块明细

### 启动与元数据

- **职责/接口**：`main.py::_dispatch_cli()` 识别 GUI、`--mobileperf-worker`、`--self-check packaging`；
  `_run_gui()` 创建 QApplication，加载应用级字体与主题后创建 MainFrame；
  `utils/app_metadata.py` 提供版本常量。
- **输入/输出**：命令行参数、应用设置和资源路径；输出 GUI 事件循环退出码或自检文本/退出码。
- **上下游**：上游为用户或打包程序；下游为 PySide6、`AppSettings`、`BaseStyles`、`MainFrame`、`mobileperf.android.startup.StartUp`。
- **配置/数据/外部服务**：读取主题和资源；自检写入后删除用户目录探针；Windows 设置 AppUserModelID。
- **测试/风险/待确认**：入口、版本和自检有测试/CI；未知 CLI 参数会静默进入 GUI，是否符合期望待确认。

### GUI 壳与面板

- **职责/接口**：`MainFrame` 构建工具栏、左右分栏、Device/Apps/System/Remote 页签和对话框；
  `FramelessResizeController` 通过四边四角共八个透明热区调用原生缩放；
  `window_layout_snapshot/restore_default_window_size/reset_panel_split` 是 Settings 使用的公开布局接口；
  `_ScanThread` 周期执行设备发现（扫描超时 15 秒以兼容端点防护拖慢的 adb 启动），失败仅更新
  发现状态为 unavailable，不再自动恢复 ADB Server；`SidePanelSignals`/`ADBControllerSignals` 是 UI 业务接口；
  主窗口通过 `QtScreenAdapter` 获取所在屏幕、可用几何和逻辑 DPI，并据此约束工作区（工具栏溢出、
  保存路径省略、日志区最小高度、二级窗口按 owner 屏幕适配）。
- **输入/输出**：Qt 事件、选中设备和表单值；输出控制信号、日志、状态栏和对话框。
- **上下游**：上游是 QApplication/用户；下游是 `ADBController`、各 panel/dialog、`CommandRunner`、`AppSettings`、`gui/screen_adapter.py`。
- **配置/数据/外部服务**：`continuous_device_scan`、`device_scan_interval_ms`、窗口尺寸、
  `panel_split_ratio`、主题、字体、保存目录；通过 ADB 扫描设备。普通窗口尺寸限制为不小于
  860×500；屏幕可用范围不小于该最小值时再裁剪到可用范围内，最小尺寸优先；左栏比例限制为
  0.20–0.70。
- **测试/风险/待确认**：原生缩放热区、尺寸/比例校验、批量设置适配和响应式断点有单测；
  MainFrame 现在持有应用自有 `QtTaskSupervisor` 并注入 LiveLogcat，
  同时作为设备对话框、Performance Launcher 和 ScreenshotViewer 的统一生命周期 owner；
  这些非模态窗口不建立 Qt parent/transient owner，允许与主界面自由切换；
  原生缩放在不同窗口管理器下的实际手感、窄屏及高 DPI 布局仍需人工验证；主窗口 close 已改为
  两阶段异步关闭（broadcast-first deadline，Gate B2 通过，契约测试见
  `test_phase2_mainframe_shutdown_gate.py`）；`main_frame.py` 已按 ADR-0003 Phase 2 拆出
  `main_frame_toolbar.py`/`secondary_windows.py`/`close_controller.py` 三个组合模块
  （MainFrame 约 1,700 行，保留同名委托 wrapper）。

### 对话框

- **职责/接口**：`AppManagerDialog`、`FileExplorerDialog`、`LiveLogcatDialog`、`PerformanceLauncherDialog`、`ScreenshotViewer`、`SettingsDialog` 分别处理复杂交互；LiveLogcat 使用
  `TaskSupervisor`/producer-side bounded batch，阻塞 stdout 由受控 reader 读取，Worker 按包名周期刷新
  全部 PID 并在本地严格过滤；运行中重新获取前台包会切换过滤 generation。其他对话框主要使用
  `gui/dialogs/lifecycle.py`。
- **输入/输出**：设备标识、文件/包名、用户配置；输出 ADB 操作、结果文件、日志和设置。
- **上下游**：上游为 MainFrame/用户；下游为专用 QThread、model service、ProcessRunner、文件系统。
- **配置/数据/外部服务**：保存目录、日志上限、主题、字体、窗口布局、MobilePerf 参数；
  SettingsDialog 通过 MainFrame 公开接口展示/恢复窗口尺寸和分栏，并用纵向滚动区及字号感知
  断点重排外观、窗口、保存目录和日志设置；保存目录选择入口与页脚始终可见，其他对话框按
  字体角色刷新。调用 ADB、scrcpy、Perfetto URL。
- **测试/风险/待确认**：Gate B1 覆盖 LiveLogcat heartbeat、停止语义、背压、稀疏尾批、动态包/PID
  过滤、超时保活和晚到信号；
  独立子进程还以真实 `WA_DeleteOnClose` 连续压力覆盖日志输出期间的窗口销毁、主窗口 Close
  事件及 `lastWindowClosed/aboutToQuit` 隔离；
  二级窗口关闭隔离覆盖 About、Settings、App Manager、File Explorer、LiveLogcat、
  Performance Launcher 和 ScreenshotViewer；
  真实 ADB 阻塞 stdout/进程树与 MainFrame 集成关闭仍待确认。

### Controller

- **职责/接口**：`controllers.__init__.ADBController` 用多重继承组合设备、应用、文件、输入、媒体和系统 mixin；`_ADBControllerBase` 创建 model、建立方法名 handler map、接收 `command_finished` 并发出 UI 反馈；安装批次通过 `InstallBatchUseCase` 完成提交预留、所有权（`_InstallOperationOwner`）与 generation 边界，Monkey/录屏批次使用独立 stop-request 映射并发出 `monkey_target_finished`/`record_target_finished` 终态信号。
- **输入/输出**：Qt signals 的设备/命令参数；输出日志、进度、设备列表、截图路径和操作完成信号。
- **上下游**：上游 MainFrame/panels；下游四个 ADB model、DeviceStore、线程池、`InstallBatchUseCase`/`OperationManager`。
- **配置/数据/外部服务**：性能日志阈值、保存目录和 Monkey 参数；卸载/清数据/重启/当前 Activity
  批次已迁入 `DeviceBatchUseCase`（ADR-0003 Phase 3），录屏状态已迁入 `ScreenRecordUseCase`；
  通用 `_pending_ops` 已删除，Controller 仍保留 `_batch_starts` 兼容索引、安装所有权/generation
  映射和 Monkey 停止映射等编排状态。
- **测试/风险/待确认**：Screenshot 两批交错、部分失败、artifact、取消和晚到结果已有 Gate A
  故障注入测试；安装批次 Gate C 有独立 use-case 与 gate 测试；卸载/清数据/重启/当前 Activity 与录屏
  已迁入 DeviceBatchUseCase/ScreenRecordUseCase，旧 `_pending_ops` 登记已整体删除。

### ADB Model

- **职责/接口**：`@async_command` 将 `*_async` 方法提交 QThreadPool（普通命令走全局池，`long_running=True` 走每模型 `long_pool`）；每个 model 的终态栅栏在 Controller shutdown 开始时永久关闭新提交，并让已排队但未开始的任务返回取消结果。装饰器只把 operation 身份/
  owner/generation token 组装进 `OperationMetadata` 信封，不透传给 model 方法体；
  `ADBDevice`、`ADBApp`、`ADBAdvanced`、`ADBTesting` 提供设备、应用、系统、测试命令；
  `adb_system.py` 对包名、dumpsys 服务名等诊断参数做白名单/规范化校验（`utils/adb_values.py`）。
- **输入/输出**：设备序列号和业务参数；输出 `CommandResult.to_dict()` 风格字典或专用数据。
- **上下游**：上游 Controller；下游 CommandRunner、ProcessRunner、ADBBridge、ADB device。
- **配置/数据/外部服务**：ADB、aapt、Java、设备文件、日志/截图/录屏/bugreport。
- **测试/风险/待确认**：多数命令适配与失败分支有单测；终态栅栏、Controller 先栅栏后清理、录屏和 Monkey/logcat 启停的锁内顺序已有确定性并发测试。Monkey 超时探测已实现 `_wait_for_monkey_abort`（短轮询探测 abort 信号，消除真实等待并允许中断）；已开始的短命令仍只能按既有超时结束，Android 版本差异待实机矩阵确认。

### 命令、进程与 ADBBridge

- **职责/接口**：`CommandRunner.run/run_to_file` 统一短命令；`ProcessRunner.start/stop/spawn/stop_all_tracked` 管理长进程；`ADBBridge`/`ADBInputSession` 维持低延迟 shell。
- **输入/输出**：参数数组、超时、流；输出 `CommandResult` 或 `Popen`/布尔发送状态。
- **上下游**：上游 models/dialogs/Remote；下游操作系统、ADB 和 taskkill。
- **配置/数据/外部服务**：解析内置 ADB；记录活跃命令计数和全局进程表。
- **测试/风险/待确认**：替换、停止、并发和清理有单测；`ADBInputSession` 通过实例
  `ProcessRunner` 进入实例与全局跟踪，MobilePerf 内核仍是独立 Popen/ADB 执行边界；持久输入仅确认
  写入成功，不能确认设备实际执行。

### 设置、日志与性能追踪

- **职责/接口**：`AppSettings` 管理 JSON，提供 `get/set/update/set_many/reset`；`update()` 和
  `set_many()` 在一次锁内更新后只安排一次防抖保存；Remote 的 `scrcpy_*` 键通过
  `SCRCPY_SETTING_DEFAULTS` 白名单纳入 `DEFAULTS` 并可跨会话恢复；`LogService` 用 QMutex 缓冲
  用户日志并批量发信号，记录为 `(时间戳, 级别, 消息)` 三元组（时间戳在产生时生成），缓冲区
  溢出时累计 `dropped_count` 并在下一次批量发送时插入一条 WARNING 提示（日志突发治理）；DEBUG
  仅在源码模式写入线程安全的 stderr；`core.perf_trace` 记录并汇总异步操作耗时。
- **输入/输出**：设置键值、日志消息、时间戳；输出用户配置文件、INFO 及以上 UI 日志和
  仅供开发环境查看的 DEBUG 诊断。
- **上下游**：上游全应用；下游用户目录、Qt 定时器/信号。
- **配置/数据/外部服务**：`DEFAULTS` 中的主题、字体、窗口尺寸、分栏比例、`device_log_split_ratio`、
  扫描、保存路径、日志、Monkey、`scrcpy_*` 白名单；无网络依赖。
- **测试/风险/待确认**：迁移、日志线程、DEBUG 分流、root handler 保留、停止态和 flush
  有测试；AppSettings 使用 RLock 保护数据、计时器和快照，以独立写锁串行保存回调，批量更新、
  字段边界、并发保存不覆盖新快照和旧分栏字段迁移有单测。设置已使用 `schema_version` 和
  v1→v2→v3 迁移链；`_load()` 对受支持版本完成迁移并剔除未知键，对未来版本只载入
  `DEFAULTS` 中的已知键且不立即改写原文件；未载入的未来字段经 `_future_extra` 在保存时
  合并回写并保留较高版本号（有 `future_key` 回归断言）。

### 样式、字体与响应式布局

- **职责/接口**：`TypographyManager` 持有不可变 `FontConfig`；`FontRole` 定义 `UI`、
  `UI_SMALL`、`MONO`、`LOG`、`TITLE`；`BaseStyles.font_for_role()` 和
  `control_height()` 是视图使用的统一工厂，`group_box_title_margin()` 按字体度量提供分组标题
  净空。普通操作文案使用 `UI`，`UI_SMALL` 仅用于提示和
  元数据，技术数据与日志分别使用 `MONO`、`LOG`。`responsive_column_count()` 和
  `reflow_widgets()` 负责根据宽度移动既有控件；`ResponsiveCoordinator`（
  `gui/widgets/responsive_controller.py`）统一度量并收敛溢出布局（`MAX_APPLY_ROUNDS = 3`、
  40ms 防抖）；`StrictIntComboBox`（`gui/widgets/preset_spin_box.py`）提供严格整数预设输入。
- **输入/输出**：输入 `font_family`、`ui_font_size`、`log_font_size` 和容器逻辑像素宽度；
  输出 QApplication 默认字体、角色 QFont、控件安全最小高度、响应式网格列数和三类字体信号。
- **上下游**：上游为 `main.py`、SettingsDialog、MainFrame/SidePanel 的宽度事件；下游为
  QApplication、主窗口、面板和对话框。
- **配置/数据/外部服务**：空字体族表示系统默认；不可用字体回退到 Qt 系统字体；UI 字号
  8–22、日志字号 7–16；通用面板断点为 420/560 逻辑像素，Device 按控件最小宽度动态切换列表/网格布局，
  Settings 紧凑断点为 `640 + max(0, UI 字号 - 12) × 18`，工具栏保存路径在最小窗口宽度起显示
  末级目录，并按工具栏剩余宽度动态省略。无网络或设备依赖。
- **测试/风险/待确认**：`ui_font_changed`、`log_font_changed`、`fonts_changed` 与
  `theme_changed` 相互独立；日志字号变化不会触发界面字体订阅者，主题变化不会伪装成字体变化。
  单测覆盖信号、字体回退、面板/对话框刷新、控件身份保持、最大字号无横向溢出及分组标题净空、
  `ResponsiveCoordinator` 溢出收敛与严格整数输入；测试通过 autouse 把防抖降到 1ms 加速几何扫描；
  真实平台字体替代、中文回退和高 DPI 视觉效果仍需人工验证。

### DeviceStore

- **职责/接口**：`load/save/upsert_devices/get_all/get_basic_devices_info/get_full_devices_info` 管理用户目录 `connected_devices.yaml` 并迁移旧 `resources/connected_devices.yaml`（ADR-0006 起为空映射占位，不再携带历史设备标识）。
- **输入/输出**：ADB 设备标识与属性；输出 YAML 和设备字典。
- **上下游**：上游 Controller/DeviceManager；下游 PyYAML、用户目录。
- **配置/数据/外部服务**：存储设备连接信息和显示属性；无数据库。
- **测试/风险/待确认**：迁移、并发 upsert、原子替换失败和损坏文件备份有测试；读取和写入位于
  同一可重入锁域，写盘使用临时文件、`fsync` 和 `os.replace`。仓库内已无真实设备标识，
  合规问题随 ADR-0006 闭环。

### App Manager

- **职责/接口**：`AppManagerWorker.run()` 根据 operation 分派列表、详情、权限、修改、备份、恢复；若 worker 在真正开始前已 abort/interruption，则不再分派任何设备操作。对话框负责选择、过滤、预设和 worker 生命周期。
- **输入/输出**：包名、动作、备份 ZIP、预设 JSON；输出应用列表、权限、备份包和日志。
- **上下游**：上游 AppManagerDialog；下游 ADB、ThreadPoolExecutor、zipfile、本地文件系统。
- **配置/数据/外部服务**：全局保存目录；设备 `/data/app` 与应用数据。
- **测试/风险/待确认**：批量详情、关闭清理及 launch/clear/permission/backup/restore
  失败传播有测试；备份先写 staging 再原子替换，恢复不会在 install 失败后报告成功。
  备份内容完整性、hash/manifest 和 Android 新版本权限仍待实机确认。

### 文件浏览器

- **职责/接口**：`services.file_explorer` 的模块级纯函数负责安全文件名、引用、路径、`ls` 解析与命令构建；两个 worker 负责短命令/传输，并在执行入口拒绝已经 abort/interruption 的任务；对话框负责浏览和操作。
- **输入/输出**：设备路径、文件名、本地路径；输出目录项、传输文件、编辑结果和状态。
- **上下游**：上游 MainFrame/用户；下游 CommandRunner、ProcessRunner、ADB、文件系统。
- **配置/数据/外部服务**：保存目录、root 命令包装；无数据库。
- **测试/风险/待确认**：引用、解析、传输失败和 UI 表格有测试；删除会校验目标并排除 `..`，
  但不再弹窗确认，随后使用递归 `rm -rf`；root 模式、脚本执行和大文件取消在真实设备上的行为待确认。

### Remote

- **职责/接口**：`ScrcpyService` 构建 `ScrcpyLaunchPlan` 并启动/停止（强制停止只在进程已解除
  tracking 时确认成功）；`RemoteControlService` 转换按键、滑动和旋转（旋转
  前置设置失败会中止），`RemoteInputEngine` 负责外部投屏窗口标题与聚焦；`RemotePanel` 管理 worker、stderr/FPS、
  watchdog 和串行输入 executor，并把关闭/超时经 TaskSupervisor 治理。关闭时输入提交与 executor 摘除在同一生命周期锁中排序，后台清理等待 executor 和全部 warmup producer 后才关闭持久输入会话。
- **输入/输出**：设备、编码器、码率/分辨率/FPS/方向等设置；输出 scrcpy 窗口、状态/FPS 和 ADB 输入。
- **上下游**：上游 SidePanel；下游 scrcpy、ADBBridge、Win32 window API、ProcessRunner。
- **配置/数据/外部服务**：`scrcpy_*` 设置键（已入 DEFAULTS 白名单）、尺寸 TTL 缓存。
- **测试/风险/待确认**：服务、面板与关闭清理覆盖较好；输入提交/关闭捕获、warmup 发布/启动以及多个重叠 warmup 的关闭顺序有确定性并发测试。启动与输入均要求恰好一个选中设备（多选直接拒绝，警告不含设备标识）；
  `_active_device` 用于 warmup 与脱敏，会话未运行时拒绝输入；
  supervisor 超时结果携带 `completion_error`，避免把强制停止误报为成功。
  应用级全局 tracked-process 兜底可与 Remote 监督任务并发，底层输入 Shell 可能先被终止，但
  Remote 最终仍会清理由晚到 producer 重建的逻辑 session；该顺序及非 Windows 系统 scrcpy 依赖仍待实机验证。

### MobilePerf 适配与内核

- **职责/接口**：`MobilePerfRunConfig.write_config()` 生成临时配置（`__post_init__` 在模型边界
  规范化分号字段，避免空项/多余空白）；`MobilePerfRunner.start/stop/request_stop` 以单次运行
  上下文管理隔离子进程、双管道 reader 和完成通知；`StartUp.run/stop` 启停各 monitor 并生成报告，
  读取连续运行配置时逐层剥离 Unicode/历史字节序标记（`_CONFIG_BOM_PREFIXES`）并保持输入只读。
- **输入/输出**：设备、包名、频率、时长、Monkey、dumpheap、日志路径；输出 CSV/XLSX、设备信息、日志与 heapdump。
- **上下游**：上游 PerformanceLauncherDialog；下游 `python -m mobileperf.android.startup` 或冻结程序 worker、ADB、XLSXWriter。
- **配置/数据/外部服务**：临时 config、`ADB_PATH`、停止标记、结果目录；MobilePerf 使用每运行一份的 RuntimeData 实例上下文与多个 daemon 采集线程（ADR-0004）。
- **测试/风险/待确认**：配置、启动/停止、报告名、停止文件、当前运行产物筛选、退出码状态、
  stdout/stderr 高并发排空、回调异常、连续运行隔离与 BOM 前缀兼容有测试；
  只有退出码 0 且存在本次生成的非空报告才显示 Completed/100。`shell=True` 已按 ADR-0003
  Phase 1 移除：5037 端口清理改走 `core/process_utils`（psutil），14 个文件的 sys.path
  引导块已删除（内核经 `-m` 或 frozen worker 以包模式运行）。内核仍保留独立 Popen
  生命周期（参数数组）；`os.chdir` 与 `os._exit` 已按 ADR-0004 移除，停止路径结构化收口；
  长跑/断线故障测试与实机验证待确认。

### 工具、构建与发布

- **职责/接口**：`utils/` 提供资源/用户目录/ADB/目标校验/ZIP/批次工具；PyInstaller 和 Actions 负责打包发布。
- **输入/输出**：平台、冻结状态、连接目标、ZIP、Git 事件；输出路径、标准化目标、解压文件和三平台制品/Release。
- **上下游**：上游全应用/开发者/GitHub；下游 OS 文件系统、PyInstaller、GitHub API。
- **配置/数据/外部服务**：requirements、spec、workflow permissions、版本常量。
- **测试/风险/待确认**：路径、ZIP 和工作流安全契约有测试；Actions 固定到已核验 commit SHA，
  默认最小权限，Release job 单独获得 `contents: write`；现存同版本 Release/tag 禁止覆盖，发布后
  自动保留最新 5 个版本并删除更旧的 tag/Release。macOS/Linux 实际功能、代码签名与发布审批
  仍待确认。
