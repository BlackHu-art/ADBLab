---
status: current
last_verified: 2026-09-03
related: [ARCHITECTURE.md, MODULE_MAP.md, RISKS_AND_DEBT.md]
---

# 依赖地图

## 内部依赖方向

正常主链路的依赖方向为：

`main` → `gui` → `controllers` → `models` → `core/utils` → 操作系统与设备。

复杂功能页是例外：`gui/features` 的页面实现和 `gui/panels/remote_panel.py` 会直接依赖 `models`
service/worker。部分页面组合控制器仍位于 `gui/dialogs/*.py`，但它们由 Workspace 作为 QWidget
承载，不代表独立窗口边界。`core` 仅 `log_service.py` 依赖 Qt；设置层错误日志经
`set_error_sink` 注入。`CommandRunner`/`ProcessRunner` 位于 `core/exec.py`，`core` 不反向依赖
`models`。

## 主要内部模块依赖

| 上游 | 下游 | 用途 | 方向约束/说明 |
| --- | --- | --- | --- |
| `main.py` | `gui.main_frame`、`core.settings_manager` | GUI 组合根 | 启动层依赖应用层 |
| `gui/main_frame.py` | `controllers`、`gui/panels`、`gui/pages`、`gui/features` | UI 接线、深层路由和会话生命周期 | MainFrame 是最高耦合热点 |
| `gui/pages/workspace_features.py`、`gui/features/base.py` | `gui/features`、TaskSupervisor | 懒创建、复用、停用和释放按设备功能会话 | 页面不能绕过 registry 自行成为长期顶层窗口 |
| `controllers/_base.py` | 四个 ADB model、DeviceStore、`adblab.application`（OperationManager/InstallBatchUseCase） | 命令分派和结果聚合 | Controller 不应反向被 model 导入 |
| `models/adb_*.py` | `core.exec`、`core.adb_bridge` | 执行 ADB 与长进程 | 常规短命令走 CommandRunner，受控长进程走 ProcessRunner |
| `gui/features/app_manager.py`（实现拆在 `gui/dialogs/app_manager*.py`） | `models/app_manager_worker.py` | 内嵌页专用异步任务 | 跳过统一 Controller |
| `gui/features/file_explorer.py`（实现拆在 `gui/dialogs/file_explorer*.py`） | `services/file_explorer.py`、`models/file_explorer_worker.py` | 文件命令构建和传输 | 跳过统一 Controller |
| `gui/panels/remote_panel.py` | `services.remote`、ProcessRunner | scrcpy 与 Remote 输入 | panel 同时承担较多编排状态 |
| `gui/features/performance.py`（实现拆在 `gui/dialogs/performance_launcher*.py`） | `services.mobileperf_runner` | 性能任务启动、停止和结果 | MobilePerf 内核在独立进程 |
| `core.settings_manager` | `utils.user_data`、`utils.resource_path` | 用户配置路径与种子资源 | 错误日志经可注入 `set_error_sink` 输出，不直接依赖 log_service |
| `mobileperf/android/*` | `mobileperf/android/tools/androiddevice.py` | 采集设备指标 | 与主应用执行层重复实现 |

## 第三方 Python 依赖

精确版本以三个 requirements 文件为准，长期文档只记录用途和边界。

| 依赖 | 实际用途 | 证据/备注 |
| --- | --- | --- |
| PySide6 / Addons / Essentials / shiboken6 | GUI、线程、信号槽、Qt 对象有效性检查 | `requirements.txt`、`gui/`、`models/adb_model.py` |
| PyYAML | DeviceStore YAML | `models/device_store.py` |
| PyInstaller | 本地/CI 打包 | `requirements-build.txt`、`ADBLab.spec`、workflow |
| psutil | TCP 端口占用查找与进程树终止 | `requirements.txt`、`core/process_utils.py` |
| PySide6-Fluent-Widgets (qfluentwidgets) | 主窗口、Workspace、内嵌功能页、控件、主题和瞬态消息 | `requirements.txt`、`gui/`；许可分发风险见 RISKS_AND_DEBT |
| XlsxWriter 移植副本 | MobilePerf CSV 转 XLSX | `mobileperf/extlib/xlsxwriter/`、`mobileperf/android/excel.py` |

### Fluent 运行时来源边界

- 运行时以 `requirements.txt` 固定的 `PySide6-Fluent-Widgets` 为唯一组件来源，生产代码
  直接 `import qfluentwidgets`；`ADBLab.spec` 也从已安装包收集其子模块。
- 仓库不保存 `reference/` 上游副本；`.gitignore` 中的排除项用于防止误加入。查询实际 API 时，
  先用项目解释器的 `importlib.util.find_spec()` 定位当前 `qfluentwidgets` 安装路径，再按需查看上游
  [PySide6 分支](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6)的单个文件。
- 上游仓库默认分支是 PyQt5 变体，不能作为本项目 API 依据。历史 Gallery 页面改写及许可归属记录
  在根目录 `THIRD_PARTY_NOTICES.md`；该记录不构成运行时依赖。

依赖按 `requirements.txt`（运行）、`requirements-build.txt`（构建）和
`requirements-dev.txt`（开发/测试）逐层包含；精确版本只以这些文件为准。

## 外部系统与工具依赖

| 外部依赖 | 用途 | 解析/调用位置 | 缺失行为 |
| --- | --- | --- | --- |
| ADB | 几乎所有设备操作 | `utils/adb_resolver.py`、CommandRunner、MobilePerf ADB | 操作失败；自检在 Windows 检查内置文件 |
| scrcpy | 投屏和视频流 | `services/remote/scrcpy_service.py` | Remote 启动失败；非 Windows 要求 PATH 提供 |
| Android device | 命令执行和数据源 | 各 ADB model | 返回 device not found/offline 等错误 |
| aapt | 本地 APK 元数据解析 | `models/adb_app.py` | 解析功能返回失败 |
| Java + `resources/chkbugreport-0.5-215.jar` | bugreport 转换 | `models/adb_testing.py` | 转换失败，但原始 bugreport 可能仍存在 |
| Perfetto 网站 | 手动打开性能分析页面 | `PerformancePage.open_perfetto()` | 只影响跳转，不影响采集 |
| GitHub Actions/API | 构建、制品、Release、清理 | `.github/workflows/` | 只影响 CI/CD |

## 外部边界与命令接口

ADBLab 不提供 HTTP/REST/WebSocket/RPC 服务。`main.py` 只有桌面 GUI、
`--mobileperf-worker --config <path>` 和 `--self-check packaging` 三种本地入口。

主应用也不调用外部 HTTP API。About 的 GitHub 链接和 Perfetto 链接仅交给系统浏览器打开。

### ADB 命令接口地图

ADB 是项目实际最重要的外部操作 API。参数通常以数组传给 subprocess，设备 shell 内的复合命令由
service/model 构造。

| 能力组 | 主要入口 | 典型外部接口 | 输入 | 输出 | 校验/保护 | 测试 |
| --- | --- | --- | --- | --- | --- | --- |
| 设备发现/连接 | `ADBDevice` | `adb devices/connect/disconnect/pair/reboot` | device/target | 文本、设备列表 | connect target 有 IPv4/IPv6+port 校验 | 有 |
| 设备属性 | `ADBDevice.get_device_info_async` | `getprop`、`dumpsys`、`wm` | device | 属性字典 | 批量 labeled section 解析 | 有 |
| 应用生命周期 | `ADBApp`、`ADBSystemMixin` | `pm`、`am`、`monkey` | package/APK/action | CommandResult | package 校验不统一；批量 worker 有部分校验 | 有，实机缺 |
| 输入控制 | `ADBAdvanced`、`ADBBridge` | `input tap/swipe/text/keyevent` | 坐标、文本、key code | 结果或乐观布尔 | 低延迟持久 shell；设备执行未回读 | 有 |
| 文件与传输 | File Explorer/model | `shell ls/cp/mv/rm/chmod`、`push/pull` | 设备/本地路径 | 列表/文件/状态 | 安全文件名、shell quote；删除校验目标并排除 `..` | 有 |
| 网络/端口 | `ADBNetworkMixin`、Controller file mixin | `forward/reverse/tcpip/pair` | host/device port | CommandResult | connect target 校验；其他端口校验不完整 | 部分 |
| 日志与诊断 | `ADBTesting`、LiveLogcat | `logcat`、`bugreport`、ANR pull | package/path | 流、文件、目录 | ZIP 安全解压；诊断参数经 `utils/adb_values.py` 白名单/规范化（包名、dumpsys 服务名、tcp 端口、geo 坐标） | 有 |
| 截图/录屏 | `ADBTesting`、`ADBAdvanced` | `exec-out screencap`、`screenrecord`、`pull` | device/path/time/batch_id | PNG/MP4 | PNG 签名检查和回退；录屏 pull 与远端 cleanup 分离报告，结果携带 `batch_id` | 有 |
| 性能采集 | MobilePerf monitor | `top`、`dumpsys meminfo`、SurfaceFlinger、`/proc` | package/device/interval | CSV 采样 | 移植内核校验较弱、命令实现独立 | 部分 |
| 任意 shell/intent | SystemPanel/ADBSystemMixin | `adb shell ...`、`am start/broadcast`、`dumpsys netstats` | 用户文本 | CommandResult | 参数校验仍不完整（弹窗确认已全局移除，防护依赖校验与日志） | 部分 |
| Monkey | `ADBTesting` | `monkey`、`am force-stop` | package/events/throttle/flags | CommandResult | 前台探测 fail-closed；`_wait_for_monkey_abort` 短轮询探测中止 | 有 |

### scrcpy 进程接口

`services/remote/scrcpy_args.py` 将 `ScrcpyConfig` 转为参数数组，`ScrcpyService.build_launch_plan()`
先检查版本、ADB 预检和可选编码器，再由 `ProcessRunner.start()` 启动。stderr 用于状态/FPS 解析。
Windows 使用内置可执行文件，非 Windows 使用 PATH；没有网络服务端暴露。

### 文件与进程接口安全约定

- 主应用短命令优先使用参数数组，不启用宿主 shell。
- 设备 shell 复合命令必须在 service/model 层集中构造并对动态路径使用 quote。
- 外部 ZIP 必须用 `utils.archive.safe_extract_zip()`，防止目录穿越。
- 长进程应注册到 ProcessRunner；带 UI 生命周期的复合 worker/process task 还应注册到
  TaskSupervisor。只有确认退出后才能移除 tracking，timeout 必须保留 residual snapshot。
- MobilePerf 内核仍保留独立的直接 Popen/ADB 执行边界，但当前使用参数数组和 `shell=False`；
  5037 端口清理由 `core.process_utils` 负责；ADB 可执行路径已统一：`get_adb_path()` 的
  最终回退走 `utils.adb_resolver`（内置平台二进制已移除），与主应用共用同一 ADB 事实来源。
  详见 [RISKS_AND_DEBT.md](RISKS_AND_DEBT.md)。

未闭环的依赖方向、平台能力检查和 MobilePerf 执行边界只在
[RISKS_AND_DEBT.md](RISKS_AND_DEBT.md) 维护。
