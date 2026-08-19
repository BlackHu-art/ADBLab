---
status: current
last_verified: 2026-08-19
related: [MODULE_MAP.md, DATA_FLOW.md]
---

# 主要业务流程

## 1. 应用启动与设备发现

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户运行 `main.py`/ADBLab 可执行文件且未指定 worker/self-check 子命令 |
| 前置条件 | Python 依赖可导入；资源可定位；ADB 可从内置目录或 PATH 解析 |
| 主流程 | 创建 QApplication → 批量读取并校验字体设置 → 设置应用级 UI 字体 → 加载主题 → 创建 MainFrame/Controller/Models → 校验并恢复普通窗口尺寸和分栏比例 → 构建界面、原生缩放热区和信号 → 延后首次刷新 → 可选启动持续扫描 |
| 异常流程 | 不可用字体回退到 Qt 系统字体；非法字号、窗口尺寸或分栏比例回退/限制到安全范围；资源或 Qt 导入失败会在启动阶段退出；ADB 不可用时设备刷新返回失败并写日志；关闭时取消尚未触发的刷新和扫描 |
| 涉及模块 | `main.py`、`gui/main_frame.py`、`gui/window_layout.py`、`gui/styles/typography.py`、`core/settings_manager.py`、`controllers/`、`models/adb_device.py` |
| 涉及数据 | AppSettings、FontConfig、设备列表、窗口尺寸/分栏比例、日志 |
| 代码位置 | `main.py::_run_gui`、`MainFrame.__init__/_start_device_discovery/closeEvent`、`_ScanThread.run` |

```mermaid
flowchart TD
    Start["启动"] --> CLI{"_dispatch_cli 是否命中子模式"}
    CLI -->|"worker"| MP["MobilePerf worker"]
    CLI -->|"self-check"| Check["打包资源自检"]
    CLI -->|"否"| Qt["QApplication + 应用字体 + 主题"]
    Qt --> Layout["校验窗口尺寸与分栏比例"]
    Layout --> Frame["构建 MainFrame / Controller / Panels / 缩放热区"]
    Frame --> Initial["定时器触发首次设备刷新"]
    Frame --> Scan{"continuous_device_scan"}
    Scan -->|"开启"| Poll["周期 adb devices"]
    Poll --> Changed{"设备集合变化"}
    Changed -->|"是"| Refresh["刷新设备信息与 UI"]
    Changed -->|"否"| Poll
```

### 1.1 字体、窗口缩放与响应式布局

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户在 Settings 修改字体/字号或点击布局重置；用户拖动主窗口边角、工具栏或透明分隔热区；主分栏或页签滚动视口宽度变化 |
| 前置条件 | QApplication 已创建；MainFrame 已完成窗口和面板初始化；Settings 以 MainFrame 为 parent 时才启用两个布局重置按钮 |
| 字体主流程 | Settings 将字体族和字号通过 `AppSettings.update()` 批量更新 → `BaseStyles.reload_from_settings()` 生成并应用不可变 FontConfig → QApplication 接收 UI 字体 → 按实际变化发送 `ui_font_changed`、`log_font_changed` 和总括 `fonts_changed` → 主窗口、日志面板、面板/对话框分别刷新自己订阅的字体角色、安全最小高度和分组标题净空；普通操作文案统一使用 UI，提示/元数据使用 UI_SMALL，技术数据和日志分别使用 MONO/LOG |
| 窗口主流程 | 四边或四角透明热区按压 → `QWindow.startSystemResize()` → 普通窗口尺寸变化 → 350 毫秒防抖批量保存宽高；工具栏空白区按压优先调用 `startSystemMove()`，双击在最大化与普通状态间切换 |
| 分栏与响应式主流程 | 用户拖动 8 像素透明 QSplitter 热区 → 300 毫秒防抖批量保存左右像素宽度和左栏比例 → 左栏实际宽度驱动 Device，各功能页只以自身滚动视口实际宽度为准 → Device 在 360 像素处切换“列表侧栏/列表上方按钮网格”，Apps/System/Remote 按 420/560 默认断点重排既有控件；设备区允许纵向收缩且日志区至少保留 120 像素；每个懒加载页签位于禁用横向滚动的可纵向滚动区域；顶部全局保存路径从 860 像素最小窗口宽度起显示末级目录，1040 像素起按字体度量省略完整路径 |
| Settings 布局流程 | Settings 调用 `window_layout_snapshot()` 展示当前普通窗口尺寸与左右比例；“Reset Size”调用 `restore_default_window_size()`，“Reset Split”调用 `reset_panel_split()`；Appearance、Window、Storage & Logs 依据滚动视口宽度及 UI 字号在双列/纵向布局间切换，保存目录按钮始终入布局，内容超高时只使用纵向滚动区，固定页脚保持可操作 |
| 异常/回退 | 原生移动或缩放未被窗口系统接受时，工具栏移动保留手动拖动回退，缩放热区不自行模拟尺寸；最大化/全屏时缩放热区隐藏且不保存该状态尺寸；无 MainFrame parent 的独立 Settings 只展示设置回退值并禁用布局重置；重排不销毁控件、不重复连接信号 |
| 涉及模块 | `gui/styles/typography.py`、`gui/styles/fonts.py`、`gui/main_frame.py`、`gui/window_layout.py`、`gui/widgets/frameless_resize.py`、`gui/widgets/responsive_layout.py`、`gui/dialogs/settings_dialog.py`、`gui/panels/`、`core/settings_manager.py` |

```mermaid
flowchart LR
    Settings["Settings 字体控件"] -->|"一次批量更新"| AppSettings["AppSettings.update / set_many"]
    AppSettings --> Typography["TypographyManager.apply"]
    Typography --> AppFont["QApplication UI 字体"]
    Typography --> UISignal["ui_font_changed"]
    Typography --> LogSignal["log_font_changed"]
    Typography --> AllSignal["fonts_changed"]
    Resize["窗口或分栏宽度变化"] --> Main["MainFrame 防抖与宽度转发"]
    Main --> Store["尺寸与 panel_split_ratio"]
    Main --> Panels["SidePanel / Panels 响应式重排"]
```

## 2. 连接设备并读取信息

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户输入 `ip:port`/`[IPv6]:port` 并点击连接，或请求刷新 |
| 前置条件 | 目标通过 `normalize_adb_target()`；ADB server 可用；设备允许调试 |
| 主流程 | UI 校验 → Controller 调用 `connect_device_async` → `adb connect` → 解析返回 → 刷新设备列表 → 并行/批量读取 getprop 和探测信息 → DeviceStore upsert → 更新 UI |
| 异常流程 | 地址不完整在 UI/Controller 拒绝；ADB 超时/返回非零形成失败结果；已连接文本仍会触发刷新；离线/未授权设备信息不完整 |
| 涉及模块 | `gui/panels/device_manager.py`、`controllers/_device.py`、`models/adb_device.py`、`models/device_store.py` |
| 涉及数据 | 设备标识、型号、Android 版本、分辨率、电池/网络等展示信息 |
| 代码位置 | `DeviceManager` 连接槽、`ADBDeviceMixin.connect_device/_process_connect_device_result/publish_detected_devices`、`ADBDevice` |

```mermaid
sequenceDiagram
    participant U as "用户"
    participant DM as "DeviceManager"
    participant C as "ADBDeviceMixin"
    participant M as "ADBDevice"
    participant A as "ADB"
    participant S as "DeviceStore"

    U->>DM: 输入连接目标
    DM->>DM: normalize_adb_target
    DM-->>C: connect_device_requested
    C->>C: 再次校验/建立 pending trace
    C->>M: connect_device_async
    M->>A: adb connect target
    A-->>M: stdout/stderr/returncode
    M-->>C: command_finished
    alt 成功或已连接
        C->>M: get_devices/basic_info
        M->>A: adb devices + getprop/probes
        A-->>M: 设备属性
        M-->>C: 设备数据
        C->>S: upsert_devices
        C-->>DM: devices_updated/basic_info_updated
    else 失败
        C-->>DM: operation_result + 日志
    end
```

## 3. 应用管理与批量操作

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户在 Apps 面板或 App Manager 选择安装、卸载、启停、清数据、权限、备份/恢复等操作 |
| 前置条件 | 已选择设备；包名/APK/备份文件存在且相关系统工具可用 |
| 主流程 | 已知危险动作先经统一策略和 `confirm_dangerous_ops` 确认；简单操作再走 SidePanel signal → ADBController → ADBApp/Advanced/System model；复杂列表/详情/备份走 AppManagerWorker QThread → ADB → signal 更新对话框 |
| 异常流程 | 用户拒绝确认时不调用 Controller/worker；Model 和 AppManagerWorker 都传播命令失败，备份使用 staging 后原子替换，恢复 install 失败不会报告成功；aapt 缺失导致 APK 解析失败 |
| 涉及模块 | `gui/panels/app_panel.py`、`gui/dialogs/app_manager.py`、`controllers/_app.py`、`models/adb_app.py`、`models/app_manager_worker.py` |
| 涉及数据 | 包名、APK 路径、权限、应用详情、预设 JSON、备份 ZIP |
| 代码位置 | `ADBAppMixin`、`ADBApp`、`AppManagerWorker.run` 及 `_backup_app/_restore_apps/_modify_permission` 路径 |

批量操作使用 `BatchOperationTracker` 聚合完成数；当前 tracker 按操作名存储，重叠同类批次会覆盖状态。App Panel 的“Disable for User”按钮实际发出与普通 Disable 相同的信号，最终调用 `pm disable`，没有实现名称所暗示的 `disable-user`。

安装批次（Gate C）不再使用共享 tracker：`InstallBatchUseCase`（`adblab/application/install_batch.py`）
为每次提交创建带 `operation_id`/unit 身份的批次，通过 `start/complete/fail/cancel/retry` 状态机
管理整批与逐 unit 结果，支持部分失败（PARTIAL）与失败项重试；Controller 在提交前先
`_reserve_install_start` 预留并绑定 `_InstallOperationOwner` 所有权，结果按 owner/generation
token 校验归属与代次，晚到或错代结果直接丢弃；批次级协作取消把取消意图广播给仍待处理的
pending units。

## 4. Monkey 稳定性测试

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户配置包名、事件比例、事件数/throttle/flags 后启动 Monkey（支持批次：`start_monkey_batch_requested`） |
| 前置条件 | 设备在线、目标包已安装、事件参数可被 Android Monkey 接受 |
| 主流程 | AppPanel → Controller → `ADBTesting.run_monkey_test_async` → 检测当前包 → 启动并跟踪 Monkey 进程 → 同步 logcat/恢复目标包 → 输出日志和结果；批次路径按 batch id 登记 stop 意图，每台设备完成/失败/取消后发 `monkey_target_finished(batch_id, device)` |
| 异常流程 | 非零退出返回失败；用户中止会停止进程；前台探测超时、失败或空结果均按失败处理，连续 3 次失败后终止任务并进入清理，不再把未知状态当作前台正常；等待阶段通过 `_wait_for_monkey_abort` 短轮询探测中止请求，避免真实阻塞 |
| 涉及模块 | `gui/panels/app_panel.py`、`controllers/_app.py`、`models/adb_testing.py`、`models/base/focus_detector.py` |
| 涉及数据 | Monkey 参数、随机种子、当前包名、logcat 和执行日志 |
| 代码位置 | `ADBTesting.run_monkey_test_async`、`_wait_for_monkey_abort`、`detect_current_package`、Controller Monkey handlers |

```mermaid
flowchart TD
    Config["Monkey 参数"] --> Warn{"事件比例是否为 100%"}
    Warn -->|"否"| Continue["警告后仍继续"]
    Warn -->|"是"| Run["启动 Monkey"]
    Continue --> Run
    Run --> Monitor["读取输出并检测当前包"]
    Monitor --> Stop{"完成/中止/失败"}
    Stop -->|"正常完成"| Success["成功结果"]
    Stop -->|"非零/明确失败"| Failure["失败结果"]
    Stop -->|"连续 3 次前台探测失败"| ProbeFail["失败并清理 Monkey/logcat"]
```

## 5. 截图、录屏与诊断

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户选择一个或多个设备执行截图、录屏、bugreport、ANR、日志导出 |
| 前置条件 | 设备在线；保存目录可写；录屏/bugreport 相关设备命令可用；可选 Java 已安装 |
| 主流程 | Screenshot 为一次请求创建 parent operation 和每设备 task metadata → model 执行 exec-out/pull → Controller 校验目标、预期路径与 PNG artifact → fan-out 汇总 → 逐项发 `screenshot_captured` 且每批最多打开一次 viewer；录屏/诊断走 Controller/model 路径，批次录屏按 batch id 跟踪，每台设备停止/失败后发 `record_target_finished(batch_id, device)` |
| 异常流程 | 截图 exec-out 非 PNG 时回退设备临时文件；缺失/无效/路径不符 artifact 视为失败；部分失败终态为 PARTIAL 且兼容 success=False；重复/晚到 callback 丢弃（截图取消经 `cancel_pending_units` 按 generation 原子化）；bugreport ZIP 路径逃逸被拒绝；录屏 pull 与远端清理分离报告，pull 成功但 cleanup 失败会整体报告失败 |
| 涉及模块 | `controllers/_media.py`、`controllers/_app.py`、`models/adb_advanced.py`、`models/adb_testing.py`、`utils/archive.py`、`gui/dialogs/screenshot_viewer.py`、`gui/dialogs/lifecycle.py` |
| 涉及数据 | PNG、MP4、ZIP、txt、ANR、bugreport 转换目录 |
| 代码位置 | `take_screenshot_async`、`start/stop_screen_record_async`、`pull_recorded_video_async`、`capture_bugreport_async`、`safe_extract_zip` |

Screenshot Gate A 已删除 Controller 共享路径/剩余计数，重叠批次按 operation/task id 隔离；
录屏批次已接入 batch id 与 `record_target_finished` 终态信号，但其共享状态仍由 Controller
持有，尚未迁入 OperationManager。

## 6. 设备文件浏览与传输

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户打开 File Explorer，浏览目录或执行 pull/push/edit/copy/move/delete/chmod/install/execute |
| 前置条件 | 已选择设备；路径和文件名可被服务层接受；本地目标目录可写 |
| 主流程 | Dialog 构造规范化设备路径 → `models.file_explorer_service` 模块级纯函数安全引用/构造命令 → 短操作由 `ADBWorker`/CommandRunner 执行，传输由 `TransferWorker`/ProcessRunner 执行 → 成功后刷新列表 |
| 异常流程 | 非法文件名拒绝；失败结果显示错误且不刷新；删除前确认；关闭对话框时中止 worker；root 包装或设备权限不足会失败 |
| 涉及模块 | `gui/dialogs/file_explorer.py`、`models/file_explorer_service.py`、`models/file_explorer_worker.py` |
| 涉及数据 | 目录项、文件内容、临时设备/本地文件、权限模式 |
| 代码位置 | `models/file_explorer_service.py` 的 `safe_name/shell_quote/parse_ls_output/*_command`、`FileExplorerDialog._navigate/_pull_file/_delete_selected/_paste_items/closeEvent` |

```mermaid
sequenceDiagram
    participant U as "用户"
    participant D as "FileExplorerDialog"
    participant S as "file_explorer_service 纯函数"
    participant W as "Worker"
    participant A as "ADB/设备文件系统"

    U->>D: 选择文件操作
    D->>S: 校验名称/路径并构造命令
    S-->>D: 参数或引用后的 shell 命令
    D->>W: 启动短命令或传输
    W->>A: adb shell/pull/push
    A-->>W: 输出与返回码
    W-->>D: finished(output, error)
    alt 成功
        D->>D: 更新状态并刷新目录
    else 失败
        D->>D: 显示错误，不刷新成功状态
    end
```

## 7. Remote 投屏与输入

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户在 Remote 页选择设备和 scrcpy 参数并启动 |
| 前置条件 | scrcpy 可解析；ADB 设备可达；预检可获得必要信息或允许带警告继续 |
| 主流程 | RemotePanel 将启动选择绑定为 `_active_device` → 创建 launch worker → ScrcpyService 检查版本/设备/编码器并生成 LaunchPlan → ProcessRunner 启动 scrcpy → stderr/FPS reader 和 watchdog 更新状态 → 输入只向活动会话设备发送 |
| 异常流程 | 未运行活动会话时拒绝输入；多选启动只绑定首个选择并警告；预检或启动失败恢复按钮状态并清空活动设备；旋转等前置设置失败会中止后续动作；强制停止仅在进程已解除 tracking 时确认成功；关闭页签停止 scrcpy、worker、executor 和 input session；supervisor 超时结果携带 `completion_error`；非 Windows 找不到系统 scrcpy 则无法启动 |
| 涉及模块 | `gui/panels/remote_panel.py`、`models/remote/*`、`core/adb_bridge.py` |
| 涉及数据 | `ScrcpyConfig`、`PreflightResult`、`ScrcpyLaunchPlan`、设备尺寸缓存、FPS 文本 |
| 代码位置 | `ScrcpyService.build_launch_plan/start/stop`、`RemoteControlService.perform_action`、`RemotePanel.shutdown` |

```mermaid
sequenceDiagram
    participant UI as "RemotePanel"
    participant S as "ScrcpyService"
    participant P as "ProcessRunner"
    participant X as "scrcpy"
    participant R as "RemoteControlService"
    participant B as "ADBBridge"

    UI->>S: 解析可执行文件并构建 LaunchPlan
    S->>S: version / adb preflight / encoder
    S-->>UI: plan + warnings + dimensions
    UI->>S: start(plan)
    S->>P: 注册并启动进程
    P->>X: scrcpy args
    X-->>UI: stderr/FPS/退出状态
    loop 用户按键或手势
        UI->>R: perform_action / swipe
        R->>B: shell_input
        B-->>R: 写入持久 adb shell 是否成功
    end
    UI->>S: stop
    S->>P: 终止进程树
```

## 8. MobilePerf 性能采集

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户选择设备/包名，配置采样与 Monkey 后在 Performance Launcher 启动 |
| 前置条件 | 设备在线、目标包已安装、保存目录可写、MobilePerf 模块可导入 |
| 主流程 | 表单生成 `MobilePerfRunConfig`（`__post_init__` 规范化分号字段）→ Runner 记录运行前结果/报告签名并创建运行代次上下文 → 写临时配置 → 根据开发/冻结状态启动 module 或 `--mobileperf-worker` → StartUp 逐层剥离配置 BOM 前缀后验证设备/包并采集 → stdout/stderr reader 分别排空且共同收口后通知完成 → GUI 只定位本次新建或变化的非空报告；退出码 0 且有当前报告才显示 Completed/100 |
| 异常流程 | 启动异常立即恢复 UI；停止先写 stop 文件并等待报告，超时后强制终止；非零退出、缺少当前报告或只有旧报告均显示 Failed/Warning 且进度低于 100；内核仍可能最终 `os._exit` |
| 涉及模块 | `gui/dialogs/performance_launcher.py`、`models/mobileperf/runner.py`、`mobileperf/android/startup.py` 与各 monitor |
| 涉及数据 | 临时 config、指标 CSV、XLSX、设备信息、logcat、heapdump、外部设备日志 |
| 代码位置 | `PerformanceLauncherDialog.start_mobileperf/stop_mobileperf`、`MobilePerfRunner.start/stop`、`StartUp.run/stop` |

## 9. 安装批次（Gate C）

| 项目 | 内容 |
| --- | --- |
| 触发条件 | 用户在 Apps 面板选择多设备/多 APK 安装或点击批量安装（`batch_install_requested`） |
| 前置条件 | 已选择设备；APK 文件存在且可被 aapt/install 接受 |
| 主流程 | Controller 校验请求并 `_reserve_install_start` 预留批次 → 创建 `InstallBatchUseCase` 批次（operation id + 每 unit 身份，绑定 `_InstallOperationOwner` 所有权与 generation）→ 逐 unit 经 `install_apk_async`（`async_command` 透传 owner/generation token 到 `OperationMetadata`）提交 → 每 unit 结果按 owner/generation 校验归属后记录 → 全部结束后按 unit 结果汇总终态（成功/部分失败/失败），失败项可整批重试（retry） |
| 异常流程 | 选择取消/空请求直接失败；提交阶段异常丢弃预留；晚到或错代结果标记 stale 并丢弃；协作取消（cancel）把意图广播给未处理 units；部分 unit 失败不影响其他 unit 收口，终态为 PARTIAL 且兼容 success=False |
| 涉及模块 | `gui/panels/app_panel.py`、`controllers/_app.py`、`adblab/application/install_batch.py`、`adblab/application/operations.py`、`models/adb_app.py` |
| 涉及数据 | 安装请求列表、unit 结果、批次终态、owner/generation token |
| 代码位置 | `InstallBatchUseCase.start/complete/fail/cancel/retry`、`_reserve_install_start/_submit_install_unit/_finish_install_start`、`OperationManager.cancel_pending_units/record_unit_result/finish_from_unit_results` |

## 10. 应用关闭

MainFrame 打开的设备对话框、Performance Launcher 以及 Controller 打开的 ScreenshotViewer
都作为无 Qt parent/transient owner 的独立非模态顶层窗口运行，并由 MainFrame/Controller
持有强引用、安装事件过滤器和执行显式关闭清理，因此可以与主界面自由切换。About 与 Settings
继续使用模态交互。用户关闭任一非模态二级窗口只清理该窗口资源，不进入 MainFrame
应用级关闭状态机。源码运行时会向开发控制台输出窗口创建、复用、关闭请求和关闭完成等
DEBUG 诊断；运行中 LiveLogcat 还会输出隐藏等待、资源停止和最终销毁阶段。

MainFrame 关闭时先刷新尚未落盘的普通窗口尺寸和分栏状态，再停止扫描、关闭对话框、shutdown 已加载面板、停止 Controller 的
testing/advanced model、全局 tracked process 和 executor，并显式调用 `LogService.shutdown()`。
LiveLogcat 对话框已将 worker/process 注册到 MainFrame 注入的 TaskSupervisor：Stop 只广播
后台清理；运行中关闭窗口时先隐藏并断开数据界面信号，保留 `finished` 槽作为线程屏障。
`owner_stopped` 仅表示停止流程已返回，对话框还会复核工作对象与 owner residual；只有两者
全部清零才销毁窗口。graceful/forced/timeout 分离，超时资源继续保留 residual snapshot，
隐藏窗口也继续持有 QObject，避免仍运行的 QThread 被提前析构；LiveLogcat 显式关闭
`WA_QuitOnClose`，不会参与应用的最后窗口退出判定。若线程完成信号先于超时结果到达，
关闭复核定时器会继续观察晚退出的受跟踪进程，并在实际清零后完成销毁。
MainFrame 自身也已改为两阶段异步关闭（Gate B2）：首次 close 事件只进入 closing 状态、停止 UI
定时器并断开生产者信号，随后按扫描、面板、对话框、Controller 顺序注册关闭任务，以
broadcast-first + 共享 wall-clock deadline 广播停止；全部资源归零或到达 deadline 后，后台
finalizer 原子落盘配置并重新触发 close 完成销毁，超时资源保留在 residual snapshot 中且不
宣称资源归零。该链路由 `test_phase2_mainframe_shutdown_gate.py` 的 11 项契约测试覆盖。
