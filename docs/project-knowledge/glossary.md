---
status: current
last_verified: 2026-08-19
related: [PROJECT_OVERVIEW.md, ARCHITECTURE.md]
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
| SidePanel | Device/Apps/System/Remote 功能页容器 | `gui/panels/side_panel.py::SidePanel` |
| ADBController | 把 Qt signals 协调到 ADB models 的多 mixin Controller | `controllers/__init__.py::ADBController` |
| handler map | 合并各 Controller mixin 的 `_handlers` 注册表，按异步 model method 名称选择 `_process_*_result` 处理器 | `controllers/_base.py` |
| Model | 封装 ADB 操作并输出标准结果的逻辑层 | `models/adb_device.py` 等 |
| Service | 较低 Qt 耦合的可复用业务/外部工具适配 | `models/remote/`、`file_explorer_service.py` |
| Worker | 在 QThread/QRunnable/子进程中执行耗时任务的执行体 | `AppManagerWorker`、文件浏览器的 `ADBWorker`/`TransferWorker` |
| `async_command` | 把 model 方法包装成 QRunnable 并发出 `command_finished` | `models/adb_model.py` |
| CommandRunner | 短生命周期 subprocess 执行器 | `models/base/command_runner.py` |
| CommandResult | 包含 success/output/error/returncode/timed_out 等的标准命令结果 | `models/base/command_runner.py` |
| ProcessRunner | 长生命周期进程注册、停止和全局清理器 | `models/base/process_runner.py` |
| ADBBridge | ADB shell 适配，支持持久输入 session | `core/adb_bridge.py` |
| ADBInputSession | 每设备持久 `adb shell`，用于低延迟 input 命令 | `core/adb_bridge.py` |
| DeviceStore | 连接设备元数据的 YAML 存储 | `models/device_store.py` |
| AppSettings | 应用设置单例和 JSON 存储 | `core/settings_manager.py` |
| LogService | 线程安全缓冲、批量向 Qt 发日志信号的服务 | `core/log_service.py` |
| perf trace | 由 `build_async_perf/attach_perf/split_perf/summarize_perf` 等函数记录和汇总异步耗时 | `core/perf_trace.py` |
| BatchOperationTracker | 统计多设备/多包批次完成数的轻量对象 | `utils/batch_tracker.py` |
| OperationManager | 管理业务操作身份、状态机、进度、取消意图和结果汇总的纯 Python registry，不拥有线程/进程 | `adblab/application/operations.py` |
| OperationMetadata | `async_command` 为 operation 调用组装的信封：operation/unit/task/target 身份、预期 artifact、owner/generation token | `adblab/application/envelope.py` |
| InstallBatchUseCase | 安装批次 Gate C 用例：start/complete/fail/cancel/retry 状态机、部分失败与失败项重试 | `adblab/application/install_batch.py` |
| Gate A / Gate B / Gate C | vNext 三个架构门：Screenshot operation 隔离（已过）、LiveLogcat 资源托管与主窗口两阶段异步关闭（B1/B2 已过）、Install batch 批次部分失败语义（已过） | `docs/architecture/adr/0001-incremental-vnext.md` |
| ResponsiveCoordinator | 响应式重排的单一协调入口：度量 → 布局计划 → 溢出收敛（最多 3 轮、40ms 防抖） | `gui/widgets/responsive_controller.py` |
| ScreenAdapter / QtScreenAdapter | 屏幕适配协议与 Qt 实现：所在屏幕、可用几何、逻辑 DPI 与变更订阅 | `gui/screen_adapter.py` |
| Remote | scrcpy 投屏与 ADB 远程输入功能 | `gui/panels/remote_panel.py`、`models/remote/` |
| scrcpy | Android 投屏/控制外部工具 | `scrcpy-win64-v3.3.1/`、`ScrcpyService` |
| ScrcpyConfig | scrcpy 用户配置数据类 | `models/remote/types.py` |
| PreflightResult | scrcpy 启动前设备可达性和详情检查结果 | `models/remote/types.py` |
| ScrcpyLaunchPlan | 可执行文件、参数、预检结果的启动计划 | `models/remote/types.py` |
| MobilePerf | 随项目移植的 Android 性能采集内核 | `mobileperf/` |
| MobilePerfRunner | GUI 到 MobilePerf 子进程的适配器 | `models/mobileperf/runner.py` |
| MobilePerfRunConfig | 运行参数数据类，可写临时 config | `models/mobileperf/runner.py` |
| StartUp | MobilePerf 内核组合和运行入口 | `mobileperf/android/startup.py::StartUp` |
| monitor | MobilePerf 的单类指标采集器，如 CPU/Mem/FPS | `mobileperf/android/*.py` |
| RuntimeData | MobilePerf 的类级全局运行状态 | `mobileperf/android/globaldata.py` |
| Monkey | Android 随机事件压力工具；项目有普通测试模式和 MobilePerf 可选 monitor | `models/adb_testing.py`、`mobileperf/android/monkey.py` |
| FocusDetector | 通过多个 dumpsys 路径解析前台包名 | `models/base/focus_detector.py` |
| bugreport | Android 系统诊断归档，可选经 chkbugreport JAR 转换 | `models/adb_testing.py` |
| ANR | Application Not Responding 诊断文件/状态 | Controller/testing model |
| Perfetto | 外部性能 trace 分析网站，本项目只提供打开链接 | `PerformanceLauncherDialog.open_perfetto` |
| 用户数据目录 | 应用可写配置、日志和运行时工具缓存根目录 | `utils/user_data.py` |
| resource path | 开发目录或 PyInstaller `_MEIPASS` 的只读资源定位 | `utils/resource_path.py` |
| runtime tool cache | onefile 场景复制长进程工具的稳定用户目录 | `utils/runtime_tools.py` |
| 待确认 | 仓库代码不能独立证明，需要产品、运维、服务方或实机验证 | 本知识库统一标记 |

## 外部工具与文件格式

| 术语 | 含义 | 对应位置 |
| --- | --- | --- |
| aapt | Android Asset Packaging Tool，用于解析本地 APK 元数据 | `models/adb_app.py` |
| chkbugreport JAR | 可选 bugreport 转换工具 | `resources/chkbugreport-0.5-215.jar`、`models/adb_testing.py` |
| PyInstaller | 桌面应用打包工具 | `ADBLab.spec`、`.github/workflows/Build-exe.yaml` |
| YAML | 人类可读配置格式；项目用于设备元数据 | `models/device_store.py` |
| JSON | 轻量数据交换/配置格式；项目用于应用设置和 App Manager 预设 | `core/settings_manager.py`、`gui/dialogs/app_manager.py` |
| CSV | 逗号分隔表格文件；MobilePerf 各指标先落 CSV | `mobileperf/android/` |
| XLSX | Excel 工作簿格式；MobilePerf 汇总报告输出格式 | `mobileperf/android/report.py` |
| ZIP | 压缩归档格式；项目用于备份、bugreport 和安全解压场景 | `utils/archive.py`、`models/app_manager_worker.py` |
| APK | Android 应用安装包 | `models/adb_app.py`、App Manager |
| PNG | 截图输出格式 | `models/adb_testing.py`、`gui/dialogs/screenshot_viewer.py` |
| MP4 | 录屏输出格式 | `models/adb_advanced.py` |

## 通用缩写

| 缩写 | 含义 | 本项目语境 |
| --- | --- | --- |
| API | Application Programming Interface；外部接口或命令边界 | 本项目没有入站 Web API；主要是 ADB、HTTP 和进程接口 |
| CLI | Command Line Interface；命令行入口 | `main.py --self-check packaging`、`--mobileperf-worker` |
| CI | Continuous Integration；持续集成 | `.github/workflows/Build-exe.yaml` |
| GUI | Graphical User Interface；图形界面 | PySide6 主应用 |
| UI | User Interface；用户界面 | panels、dialogs、日志和状态栏 |
| HTTP | Hypertext Transfer Protocol；外部服务调用协议 | 主应用无出站 HTTP 客户端；仅浏览器打开 GitHub/Perfetto 链接 |
| HTTPS | HTTP over TLS；加密 HTTP | 同上；历史邮件 API 已移除 |
| FPS | Frames Per Second；每秒帧数 | Remote stderr 解析、MobilePerf FPS monitor |
| PATH | 操作系统可执行文件搜索路径 | 非 Windows 解析 adb/scrcpy/aapt/Java |
| JAR | Java Archive；Java 归档文件 | chkbugreport 工具 |
| README | 仓库首页文档 | 当前存在性能旧路径漂移，不能单独作为架构事实来源 |
