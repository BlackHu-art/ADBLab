---
status: current
last_verified: 2026-09-25
related: [ARCHITECTURE.md, MODULE_MAP.md, RISKS_AND_DEBT.md]
---

# 依赖地图

## 内部依赖方向

正常主链路的依赖方向为：

`main` → `gui` → `controllers` → `models` → `core/utils` → 操作系统与设备。

复杂功能页是例外：`gui/features` 的页面实现和 `gui/panels/remote_panel.py` 会直接依赖 `models`
或 `services` 中的 worker/service。部分页面组合控制器仍位于 `gui/dialogs/*.py`，但它们由 Workspace 作为 QWidget
承载，不代表独立窗口边界。`core` 仅 `log_service.py` 依赖 Qt；设置层错误日志经
`set_error_sink` 注入。`CommandRunner`/`ProcessRunner` 位于 `core/exec.py`，`core` 不反向依赖
`models`。

模块定位及测试入口见 [MODULE_MAP](MODULE_MAP.md)，会话与资源归属见
[ARCHITECTURE](ARCHITECTURE.md)。MobilePerf 内核在独立子进程中维护自己的 ADB 执行边界。

## 第三方 Python 依赖

依赖清单按 `requirements.txt`（运行）、`requirements-build.txt`（构建）、
`requirements-dev.txt`（开发）逐层包含；直接依赖版本以这些文件为准，活动传递依赖由
`constraints.txt` 固定。约束快照的环境范围和更新方式见 [构建指南](../guides/BUILD_AND_RUN.md#安装)。

| 依赖 | 实际用途 | 证据/备注 |
| --- | --- | --- |
| PySide6 / Addons / Essentials / shiboken6 | GUI、线程、信号槽、Qt 对象有效性检查及 QtNetwork 异步 HTTPS | `requirements.txt`、`gui/`、`models/adb_model.py`、`core/log_service.py`、`adblab/presentation/qt_app_update.py` |
| PyYAML | DeviceStore YAML | `models/device_store.py` |
| Segno | 内存生成无线 ADB 配对 PNG；固定整数模块尺寸与白色静区，不读写二维码文件 | `services/adb_pairing.py`；版本见运行依赖与约束，BSD-3-Clause 原文随包收集 |
| PyInstaller | 本地/CI 打包 | `requirements-build.txt`、`ADBLab.spec`、workflow |
| psutil | TCP 端口占用查找与进程树终止 | `requirements.txt`、`core/process_utils.py` |
| PySide6-Fluent-Widgets (qfluentwidgets) | 窗口、导航、控件、主题和消息 | `requirements.txt`、`gui/`；许可记录见 [THIRD_PARTY_NOTICES](../../THIRD_PARTY_NOTICES.md) |
| PySideSix-Frameless-Window (qframelesswindow) | 项目直接使用的无边框对话框 | `requirements.txt`、`gui/dialogs/fluent_dialog.py`；显式声明，避免依赖 Fluent 的传递安装行为 |
| XlsxWriter 移植副本 | MobilePerf CSV 转 XLSX | `mobileperf/extlib/xlsxwriter/`、`mobileperf/android/excel.py` |

更新检查匿名读取 GitHub 公共 Releases API，仓库与 URL 统一来自 `utils/app_metadata.py`；
复用现有 PySide6.QtNetwork 和平台 TLS 后端，不引入独立 HTTP 依赖或客户端令牌。
用户流程见 [BUSINESS_FLOW](BUSINESS_FLOW.md#11-应用更新检查)。

### Fluent 运行时来源边界

- 运行时以 `requirements.txt` 固定的 `PySide6-Fluent-Widgets` 为唯一组件来源，生产代码
  直接 `import qfluentwidgets`；`ADBLab.spec` 也从已安装包收集其子模块。
- Git 不跟踪 `reference/` 上游副本；用户要求拉取时可保留官方 PySide6 分支的本地参考，不能成为运行或打包
  依赖。截图浏览直接引用已安装的 `HorizontalFlipView`、`HorizontalPipsPager` 与 `CommandBar`，示例归属见
  [THIRD_PARTY_NOTICES](../../THIRD_PARTY_NOTICES.md)。查询实际 API 时，先用项目解释器的 `importlib.util.find_spec()` 定位当前 `qfluentwidgets`
  安装路径，再按需查看上游
  [PySide6 分支](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6)的单个文件。
- 上游仓库默认分支是 PyQt5 变体，不能作为本项目 API 依据。历史 Gallery 页面改写及许可归属记录
  在根目录 `THIRD_PARTY_NOTICES.md`；该记录不构成运行时依赖。

## 外部系统与工具依赖

| 外部依赖 | 用途 | 解析/调用位置 | 缺失行为 |
| --- | --- | --- | --- |
| ADB | 几乎所有设备操作 | `utils/adb_resolver.py`（当前平台内置 → `ADB_PATH` → Android SDK platform-tools → PATH，进程内缓存，重新检测可失效；可用配置 `adb_client` 固定客户端）、`services/adb_clients.py`（候选只跑一次 `adb version`，不连 5037 服务）、CommandRunner、MobilePerf ADB | 操作失败，由设置页提示未找到客户端，不阻止窗口启动；支持内置包的平台自检文件、权限和版本命令 |
| scrcpy | 投屏和视频流 | `services/remote/scrcpy_service.py`、`utils/tool_manifest.py` | Remote 启动失败；工具准备和平台范围见 [构建指南](../guides/BUILD_AND_RUN.md#linux-本地开发) |
| Android device | 命令执行和数据源 | 各 ADB model | 返回 device not found/offline 等错误 |
| aapt | 本地 APK 元数据解析 | `models/adb_app.py` | 解析功能返回失败 |
| Java + `resources/chkbugreport-0.5-215.jar` | bugreport 转换 | `models/adb_testing.py` | 转换失败，但原始 bugreport 可能仍存在 |
| Android `app_process` + `resources/app-icon-helper.jar` | 在设备端批量读取应用名称、版本或图标 | `services/app_metadata.py`、`services/app_icons.py`、`tools/app_icons/Main.java` | 图标保留占位；元数据仅在明确不支持时执行有限兼容查询；主机正常运行不依赖 Java/Android SDK，重新生成 helper 的要求见 [BUILD_AND_RUN](../guides/BUILD_AND_RUN.md#应用图标读取工具) |
| Perfetto 网站 | 手动打开性能分析页面 | `PerformancePage.open_perfetto()` | 只影响跳转，不影响采集 |
| GitHub Actions/API | 构建、制品、Release、清理 | `.github/workflows/` | 只影响 CI/CD |

## 外部边界与命令接口

ADBLab 不提供 HTTP/REST/WebSocket/RPC 服务。`main.py` 提供桌面 GUI、
`--mobileperf-worker --config <path>`、`--self-check packaging`，以及隔离原生工具环境的
内部 `--adblab-native-launch` 入口；后者由 `core/native_process.py` 调用，不是用户设备操作接口。

主应用的出站 HTTP 仅限应用更新检查：匿名读取 `utils/app_metadata.py` 中的 GitHub 公共
Releases API，复用 QtNetwork 与平台 TLS 后端且不携带令牌。About 的 GitHub 链接和 Perfetto
链接仍只交给系统浏览器打开。

### ADB 命令接口地图

ADB 是项目实际最重要的外部操作 API。参数通常以数组传给 subprocess，设备 shell 内的复合命令由
service/model 构造。

`CommandRunner` 的受支持短命令可经 `AdbRuntime` 直连默认本机 ADB 服务，命令和失败结果仍通过
现有执行接口交付；自定义 Shell、特殊参数、传输和长期进程保留原生边界。自动选择、取消、
恢复及不重放规则由 [ADB_FAST](../guides/ADB_FAST.md#应用内自动选择) 维护。

| 能力组 | 主要入口 | 典型外部接口 | 输入 | 输出 | 校验/保护 |
| --- | --- | --- | --- | --- | --- |
| 设备发现/连接 | `_ScanThread`、`ADBDevice`、`ADBNetworkMixin` | `adb devices/connect/disconnect/reboot` | device/target | 文本、设备列表 | connect target 由 UI/Controller 校验 IPv4/IPv6+port；既有网络 mixin 的 pair 入口保留兼容 |
| 无线配对 | `services/adb_pairing.py`、`QtAdbPairing` | `adb mdns check/services`、`pair`、`connect`、`devices`、目标 `getprop persist.adb.wifi.guid` | 配对地址、临时口令、精确服务名/GUID | 固定状态与原因、已验证连接地址 | 会话固定客户端与环境；口令仅经 stdin；配对成功不能代替在线身份确认；不向通用连接校验器开放任意服务名 |
| 设备属性 | `ADBDevice.get_device_overview_info` | `getprop`、`dumpsys`、`wm` | device | 概览属性字典 | 分段解析、指标单位规范化；查询失败回退基础属性 |
| 应用生命周期 | `ADBApp`、`ADBSystemMixin` | `pm`、`am`、`monkey` | package/APK/action | CommandResult | 校验以各入口实现为准，不能将单一路径的保护推广到全部 model 接口 |
| 输入控制 | `ADBAdvanced`、`ADBApp`、`ADBBridge` | `input tap/swipe/text/keyevent` | 坐标、文本、key code | 命令结果或写入状态 | Remote 优先已验证直连；原生兼容持久 shell 的成功写入不等于设备执行确认；文本在 ADBApp 中 quote 后执行短命令 |
| 文件与传输 | File Explorer/model | `shell ls/cp/mv/rm/chmod`、`push/pull` | 设备/本地路径 | 列表/文件/状态 | 安全文件名、shell quote；删除校验目标并排除 `..` |
| 网络/端口 | `ADBNetworkMixin`、Controller file mixin | `forward/reverse/tcpip/pair` | host/device port | CommandResult | forward/reverse 的 TCP 端口在 Controller 校验；tcpip/pair 的端口在 model 校验；直接调用 forward/reverse model 不重复校验 |
| 日志与诊断 | `ADBTesting`、LiveLogcat | `logcat`、`bugreport`、ANR pull | package/path | 流、文件、目录 | ZIP 安全解压；部分诊断包名和 dumpsys 服务名经 `utils/adb_values.py` 规范化，LiveLogcat 另有包/PID 过滤边界 |
| 截图/录屏 | `ADBTesting`、`ADBAdvanced` | `exec-out screencap`、`screenrecord`、`pull` | device/path/time/batch_id | PNG/MP4 | 截图在工作线程完整解码 PNG，未取消才原子发布；仅客户端明确不支持 `exec-out` 时兼容回退。录屏启动前校验时长/码率/成对宽高，pull 与远端 cleanup 分离报告，结果携带 `batch_id` |
| 性能采集 | MobilePerf monitor | `top`、`dumpsys meminfo`、SurfaceFlinger、`/proc` | package/device/interval | CSV 采样 | 独立参数/配置解析及 ADB 执行边界，不能假设经过主应用 Controller |
| Shell、Intent 与 Android 设置 | SystemPanel、`ADBAdvanced`、`ADBSystemMixin` | `adb shell ...`、`am start/broadcast`、`settings` | 用户命令或字段 | CommandResult | 自定义 Shell 按用户命令执行；结构化 Intent 的组件/URI/字符串 extras 及设置 namespace/key/value 使用 `shlex.quote` 保持参数边界 |
| Monkey | `ADBTesting` | `monkey`、`am force-stop` | package/events/throttle/flags | CommandResult | 前台探测 fail-closed；`_wait_for_monkey_abort` 短轮询探测中止 |

### scrcpy 进程接口

`services/remote/scrcpy_args.py` 将 `ScrcpyConfig` 转为参数数组，`ScrcpyService.build_launch_plan()`
先检查版本、ADB 预检和可选编码器，再由 `ProcessRunner.start()` 启动。stdout/stderr 均排空，
INFO 中的纹理/录制就绪与 FPS 更新页面状态，错误与开发诊断统一脱敏。
非空 `SCRCPY_PATH` 显式覆盖路径；默认 Windows/Linux x86_64 使用内置可执行文件，
环境工具按 PATH/macOS Homebrew 策略发现，详见 [构建与运行](../guides/BUILD_AND_RUN.md#配置)；没有网络服务端暴露。
满足 scrcpy 4.1、已验证快速设备、专用入口与服务端文件可用等条件的 direct 计划，才由
`start_plan()` 通过子进程 `ADB` 指向随包独立 CLI；其他计划保留选定的原生 ADB。专用协议、
会话归属及失败不重放边界见 [ADB_FAST](../guides/ADB_FAST.md#remote-投屏与输入)。
CLI 仅依赖 Python 标准库，构建复用现有 PyInstaller，不新增生产依赖。

### 执行边界约束

参数 quote、外部 ZIP 和受控进程的协作规则见 [AGENTS.md](../../AGENTS.md)；当前执行器与
停止语义见 [ARCHITECTURE](ARCHITECTURE.md#协调与执行边界)。

MobilePerf 的有限超时同步 shell 由单次运行拥有的 `MobilePerfAdbExecutor` 复用核心双后端，保留
采样所需的原始双流和文本转换；异步调用、文件传输、合并输出和无限等待仍使用原生
Popen/ADB（参数数组、`shell=False`）。5037 端口清理由 `core.process_utils` 负责；
`get_adb_path()` 的最终回退走 `utils.adb_resolver`。进程环境与收尾准入见
[ADB_FAST](../guides/ADB_FAST.md#mobileperf-采集进程)。
未闭环的执行、平台与许可问题只在 [RISKS_AND_DEBT](RISKS_AND_DEBT.md) 维护。
