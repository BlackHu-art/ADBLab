# 测试指南

## 测试框架与现状

- 框架：pytest；`pyproject.toml` 把项目根加入 `pythonpath`。
- 测试目录：`tests/`；`conftest.py` 提供 session 级 `qt_application` 引用保持、autouse
  `isolated_ui_state`（每个用例结束后恢复主题/字体、清理新建顶层窗口的定时器并调用 shutdown）
  与 `isolated_ui_state_probe` 断言入口，隔离跨测试的 Qt 延迟销毁状态。
- 2026-08-18 使用 Python 3.11 的全量回归为 **930 项通过**，套件约 11 分钟；2026-08-19 增补
  P0/P1 测试后为 **940 项通过**，本机约 5 分钟（此前 11 分钟含机器负载差异）。响应式几何扫描
  测试通过 autouse 把 `ResponsiveCoordinator.RESIZE_DEBOUNCE_MS` 降到 1ms，单文件从约 6 分钟
  降到约 1.5 分钟。
- 测试主要使用 monkeypatch、临时目录、轻量 fake/stub 和通过 `__new__` 构造的最小 Qt 对象；不要求真实 Android 设备。
- 没有覆盖率工具配置或覆盖率基线，不能由“930 项通过”推导语句/分支覆盖率。

## 测试目录

| 文件 | 规模/职责 | 主要类型 |
| --- | --- | --- |
| `tests/conftest.py` | session 级 QApplication 引用保持；autouse UI 状态隔离/探针 | 共享夹具 |
| `tests/test_model_*.py` | 由原 `test_model_execution.py` 按 ADR-0003 Phase 2 拆出的 10 个主题文件（meta/processes/mainframe/performance_launcher/mobileperf/ci_controller/device/panels/apps/media_adb），共 236 项；启动、GUI 生命周期、命令/进程、Controller、ADB model、MobilePerf、App/File/Log 等综合回归 | 单元 + 轻量组件/契约测试 |
| `tests/test_remote_services.py` | Remote launch plan、scrcpy 参数/版本/预检、输入映射、面板启动停止和关闭、TaskSupervisor completion_error | service 单元 + 轻量 UI |
| `tests/test_file_explorer_service.py` | `ls` 解析、安全文件名、权限模式、命令构建 | 纯单元测试 |
| `tests/test_runtime_tools.py` | frozen/开发/onedir 工具路径、ADB 解析优先级 | 纯单元测试 |
| `tests/test_logging_contract.py` | DEBUG 源码 stderr 分流、界面/文件隔离、root handler、停止态；面板渲染三元组批次、源时间戳、按块增量裁剪 | 日志基础契约 |
| `tests/test_logging_routing_mobileperf.py` | MainFrame 工具栏/窗口生命周期、Remote 路由、MobilePerf stdout/stderr、脱敏和 windowed 标准流 | 日志集成契约 |
| `tests/test_mobileperf_runner_concurrency.py` | 双管道压力、回调异常排空和连续运行代次隔离 | 进程/线程并发契约 |
| `tests/test_mobileperf_androiddevice_log_safety.py` | MobilePerf 遗留 ADB 层日志/脱敏安全 | 安全契约 |
| `tests/test_mobileperf_port_cleanup.py` | 5037 端口冲突清理（`core/process_utils` 契约，Phase 1） | 单元契约 |
| `tests/test_process_utils.py` | 端口监听查找与进程树终止的 psutil 行为 | 纯单元测试 |
| `tests/test_comment_language.py` | 中文注释识别、豁免规则、模块说明和渐进受控范围 | 静态规范门禁 |
| `tests/test_device_store_concurrency.py` | 并发 upsert、原子替换故障、损坏备份恢复 | 并发/故障注入 |
| `tests/test_phase0_failure_semantics.py` | Monkey fail-closed、AppManager 错误传播 | 失败语义 |
| `tests/test_device_batch_use_case.py` | `DeviceBatchUseCase` 汇总/部分失败/晚到结果/并发（ADR-0003 Phase 3） | 纯单元测试 |
| `tests/test_screen_record_use_case.py` | `ScreenRecordUseCase` 登记/幂等标记/批次校验/终态移除（ADR-0003 Phase 3） | 纯单元测试 |
| `tests/test_phase0_remote_mobileperf.py` | Remote 活动会话绑定、当前报告和退出状态 | 运行边界 |
| `tests/test_ci_contracts.py` | 最小权限、固定 SHA、同版本不可变、保留最新 5 个版本 tag、只读保留审计、CI lint 步骤 | CI 安全契约 |
| `tests/test_phase1_operations.py` | Operation 状态/fan-out/并发、取消、metadata/perf envelope、单元接口（`cancel_pending_units` 等）与 Controller 路由 | 架构契约 |
| `tests/test_phase2_screenshot_gate.py` | 重叠截图、乱序/部分失败、artifact、提交异常、取消（generation 原子化）、重复/晚到和兼容 signal | 架构 Gate A |
| `tests/test_phase2_live_logcat_gate.py` | supervisor deadline/停止语义、GUI heartbeat、进程 tracking、日志背压、超时保活和独立进程关闭压力 | 架构 Gate B1 |
| `tests/test_phase2_install_batch_use_case.py` | `InstallBatchUseCase` 状态机：start/complete/fail/cancel/retry、部分失败、owner/generation 边界 | 架构 Gate C 用例 |
| `tests/test_phase2_install_batch_gate.py` | 安装批次 Controller 集成：提交预留、所有权、协作取消、失败项 retry、晚到结果 | 架构 Gate C 门禁 |
| `tests/test_phase2_mainframe_shutdown_gate.py` | 主窗口两阶段异步关闭：广播-first deadline、非阻塞/幂等、资源归零与 residual snapshot | 架构 Gate B2 契约 |
| `tests/live_logcat_close_probe.py` | 真实延迟删除下连续关闭输出中的 LiveLogcat，并区分主窗口 Close、Qt 正常退出和原生崩溃 | Gate B1 子进程探针 |
| `tests/test_window_lifecycle.py` | 二级窗口的 parent 约束、关闭隔离和 owner 屏幕适配 | 轻量 UI 生命周期契约 |
| `tests/test_responsive_panels.py` | 响应式面板几何扫描（autouse 降防抖到 1ms）、控件身份保持、溢出收敛 | 轻量 UI 契约 |
| `tests/test_responsive_layout_controller.py` | `ResponsiveCoordinator` 度量/重排/收敛轮次与防抖 | 组件契约 |
| `tests/test_preset_spin_box.py` | 严格整数预设输入（`StrictIntComboBox`）与合法性边界 | 组件单元 |
| `tests/test_ui_geometry_helpers.py`、`tests/ui_geometry_helpers.py` | 真实 Qt 几何断言工具与状态隔离探针 | 测试工具 |
| `tests/test_ui_dpi_matrix.py`、`tests/ui_dpi_probe.py` | 隔离子进程中的 Qt 缩放/DPI 探针契约 | 探针 |
| `tests/test_main_window_layout.py` | 主窗口布局、尺寸/分栏校验、工具栏溢出、屏幕适配 | 轻量 UI |
| `tests/test_settings_persistence.py` | 正式设置键（含 `scrcpy_*`）在应用重建后的持久化与旧 JSON 兼容 | 持久化契约 |
| `tests/test_settings_typography.py`、`test_settings_window_layout.py`、`test_typography_core.py`、`test_panel_typography.py`、`test_dialog_typography.py` | 设置、字体角色、字体信号与窗口布局契约 | UI/字体契约 |
| `tests/test_accessibility_contract.py` | 图标按钮 accessibleName/提示、可访问性契约 | UI 契约 |
| `tests/test_app_manager_selection.py` | App Manager 选择、过滤、可见详情批次 | UI 契约 |
| `tests/test_button_tooltips.py` | 按钮文本与 tooltip 一致性 | UI 契约 |
| `tests/test_agent_skill_gateway.py` | 内置 agent 技能网关 PoC | 工具契约 |

旧性能测试已删除或合并，当前 MobilePerf 相关测试集中在 `tests/test_model_mobileperf.py`。邮件服务已移除，`tests/test_email_service.py` 已随 `core/mail/` 一并删除。

## 执行命令

实际验证过（Python 3.11）：

```powershell
py -3.11 -m pytest --collect-only -q
py -3.11 -m pytest -q
py -3.11 main.py --self-check packaging
ruff check .
```

`py -3.11 -m pytest -q` 全量 940 项通过、本机约 5 分钟；`ruff check .` 0 错误。`tests/ui_geometry_helpers.py::wait_until` 的默认 deadline 为 6000ms：全量套件末尾 Qt 延迟删除事件累积会拖慢单次 `processEvents`，1500ms 曾在顺序相关场景下确定性超时（单独跑该文件不复现），放宽后顺序无关且全量稳定。测试分层 marker 由
ADR-0003 Phase 0 引入：`unit`（纯逻辑）、`ui`（Qt 几何/字体/窗口）、`integration`（子进程/探针），
文件到 marker 的映射集中在 `tests/conftest.py::pytest_collection_modifyitems`。CI 在完整测试前先跑
快速子集（unit + integration，不含 UI 几何扫描）：

```powershell
py -3.11 -m pytest -q -m "not ui"
```

新增 UI 类测试文件时同步登记 conftest 映射；在 CI/提交前仍应执行完整命令。

## 覆盖分层

### 单元测试

- File Explorer：路径、quote、`ls -l` 变体、symlink、chmod 和命令契约。
- Remote：参数构建、FPS 解析、尺寸缓存、按键/滑动/旋转映射、窗口聚焦。
- 工具：ADB target、资源/运行时路径、ZIP 安全解压。
- parsers：设备列表、getprop、labeled sections、前台包名、APK 信息、包列表。
- MobilePerf：配置生成、事件比例/事件数、报告 sheet 名、停止文件、结果定位。

### 组件与接口测试

- `CommandRunner`/`ProcessRunner` 的返回、替换、停止、流参数和全局清理。
- Controller signal map、handler、批次更新、shutdown 和异步分派。
- DeviceStore/AppSettings 旧文件迁移。
- ScrcpyService 与 RemotePanel 的 service 边界。
- MainFrame 的延后启动、扫描 debounce、对话框复用、parent 注入和关闭路径。

### UI 测试

当前是轻量 Qt 行为测试，不是端到端自动化：主题切换、字体/图标、按钮状态、对话框
close cleanup/主窗口关闭隔离、截图导航、App Manager 可见详情批次、Performance Launcher
表单/日志/状态、Settings 宽窄布局和保存目录入口、8–22pt 分组标题净空等。

没有 Playwright/Selenium/Appium/QtBot 的完整用户路径测试，也没有截图对比。

### 集成测试

- 当前没有连接真实 ADB server/device 的自动化集成测试。
- 没有真实 scrcpy、aapt、Java 或 PyInstaller 三平台运行集成测试（邮件服务已移除，不再有外部 HTTP 集成面）。
- CI 的 Windows packaged self-check 是打包冒烟测试，但不启动 GUI、不连接设备。

### 性能测试

项目本身采集设备性能，但没有对 ADBLab UI/worker 的基准、负载、内存泄漏或长时间稳定性自动测试。响应式几何扫描测试是全量套件的主要耗时来源（单文件约 1.5 分钟）。

## Mock 机制

- pytest `monkeypatch` 替换 subprocess、路径解析、设置和 platform/frozen 状态。
- fake process 实现 `poll/terminate/kill/wait/stdout` 等协议，验证 ProcessRunner 和 MobilePerfRunner。
- `tmp_path` 隔离 JSON/YAML/截图/报告/临时配置。
- Qt 测试尽量直接调用方法并替换 widget/service，避免启动真实外部进程；`ResponsiveCoordinator.RESIZE_DEBOUNCE_MS` 通过 autouse monkeypatch 降到 1ms。
- 测试工作流 YAML 的关键文本/结构，防止打包模式和发布资产回归。

## 当前覆盖缺口

1. `scrcpy_*` 白名单持久化已有 `test_settings_persistence.py` 覆盖；其余动态设置键的 schema/版本迁移策略仍无测试。
2. Controller 剩余 `_pending_ops`（input/refresh/设备日志）清理尚无 operation-id 压力测试；Screenshot Gate A、
   Install batch Gate C、DeviceBatch/ScreenRecord 用例已覆盖各自的重叠/晚到结果。
3. Android 多版本/厂商 ROM 的 dumpsys、top、SurfaceFlinger、bugreport 输出变体无实机矩阵。
4. MobilePerf 多线程停止、报告完整性、长时间运行、断线重连无集成测试（`os._exit`/`os.chdir`
   已按 ADR-0004 移除，停止路径结构化收口，长跑验证仍待实机）。
5. 非 Windows scrcpy/ADB 和 macOS/Linux PyInstaller 产物只有构建/自检，没有真实功能验证。
6. 全局 QRunnable 未统一注册/等待的关机边界无长任务测试。
7. 设备日志、bugreport、heapdump、截图等结果的敏感信息处理和保留期无安全测试。
8. 全量套件约 12 分钟，响应式几何扫描占比较高；已引入 unit/ui/integration marker 和 CI 快速子集（Phase 0，本地约 16 秒/458 项），`test_model_execution.py` 已按 Phase 2 拆为 10 个主题文件，纯逻辑测试进入快速子集。

## 推荐新增测试

按优先级：

1. MainFrame 异步关闭（Gate B2）契约已落地：`test_phase2_mainframe_shutdown_gate.py` 11 项测试
   覆盖首次关闭不阻塞事件循环、所有 owner 广播停止、资源归零或保留 residual snapshot；剩余
   为真实设备 helper 进程树集成验证。
2. 录屏批次迁移 OperationManager 后的并发/取消契约测试。
3. 可选硬件集成 job：至少一台测试设备，覆盖连接、包列表、截图、logcat、Remote 预检、5 分钟 MobilePerf。
4. PyInstaller Windows 打包能力检查；macOS/Linux 加 scrcpy 缺失的明确降级测试。
5. 为全量套件引入按层/按模块的 fast 子集与耗时预算，缓解约 11 分钟的门禁时长。

## 注释与文档风格

### 目标

生产代码中的注释和文档字符串统一使用规范中文，重点记录业务原因、边界条件、失败语义、线程或
进程归属以及资源生命周期。ADB、Qt、API、类名、字段名、命令和协议名称保留原文，不做生硬翻译。

### 编写规则

1. 每个生产模块应提供简短的中文模块文档字符串，说明职责和关键边界。
2. 公共类、公共接口以及涉及线程、进程、取消、超时、危险 ADB 操作、持久化和清理的函数，
   应使用中文文档字符串说明契约。
3. 注释解释"为什么"和"必须满足什么约束"，不复述赋值、分支或界面布局等显然代码。
4. 不保留注释掉的历史代码、无上下文的阶段编号或已经失效的实现说明。
5. 修改注释时必须人工核对相邻实现；禁止脱离调用链批量机械翻译。
6. 用户界面文案、异常消息、协议字段和外部命令输出不属于注释语言治理范围。

以下内容允许保持英文或机器格式：

- shebang、源文件编码声明；
- `noqa`、`type: ignore`、`pylint`、`ruff`、`fmt` 等工具指令；
- URL、许可证和版权声明；
- 可直接执行的 `py`、`python`、`pytest`、`ruff`、`git`、`adb` 等命令；
- 单独出现的技术标识，例如 `OperationState.SUCCEEDED`。

### 渐进门禁

检查器位于 `scripts/check_comment_language.py`，使用 `tokenize` 识别真实注释，使用 AST 识别模块、
类和函数的文档字符串，避免把普通字符串误判为注释。检查器还会独立识别 Unicode 替换符和 `锛`、
`銆`、`鈥` 等常见误解码片段，含乱码的中文不会被当作合规内容。

当前受控范围：`adblab/`、`controllers/`、`core/`、`gui/`、`models/`、`utils/`、`main.py`、
`mobileperf/common/`、`mobileperf/android/`（包括其中一方 Python 适配代码）。以上一方源码已经
完成人工治理并进入默认门禁。第三方、生成文件、缓存、资源、二进制工具、`mobileperf/extlib/` 和
平台二进制工具始终排除；新增一方源码必须同步纳入受控目录，不得通过扩大排除表规避检查。

运行默认门禁：

```powershell
py -3.11 scripts/check_comment_language.py
```

评审待治理目录时可以显式传入路径；该方式用于生成债务清单，不代表该目录已经进入默认门禁：

```powershell
py -3.11 scripts/check_comment_language.py controllers gui
```

门禁只解决可自动判断的语言一致性问题。注释是否准确、是否提供必要的生命周期和失败语义，仍需
代码评审结合入口、调用链、失败路径和清理路径确认。

## 提交前门禁

dev 推送到 main 前，先确认 `utils/app_metadata.py` 中的 `APP_VERSION` 相对上次发布已递增（默认补丁 +1），
并确保没有复用历史版本；本地与 dev 提交不修改版本号。

最低门禁：

```powershell
py -3.11 -m pytest -q
py -3.11 main.py --self-check packaging
ruff check .
git diff --check
```

若修改 PyInstaller/资源/入口，再执行 spec 构建和打包后 self-check。若修改 ADB 命令、Remote 或 MobilePerf，除单测外应在授权测试设备上执行最小实机验证，并确保日志不含真实敏感值。

## 质量工具链

除 pytest/ruff 外，`requirements-dev.txt` 提供以下工具（配置随仓库）：

- **pyright**（类型检查，基线范围 `adblab/` + `services/` + `core/`，配置见 `pyrightconfig.json`）：
  `py -3.11 -m pyright`（venv 内 `pyright` 可执行文件亦可直接运行）。
- **pytest-cov**（覆盖率）：`py -3.11 -m pytest -q -m "not ui" --cov=adblab --cov=services --cov-report=term-missing`。
  基线（2026-08-19，快速子集）：adblab + services 合计 88%（2301 语句，279 未覆盖）。
- **pytest-xdist**（并行）：`py -3.11 -m pytest -q -n auto`。注意：含子进程探针的
  `test_phase2_live_logcat_gate.py` 在并行 worker 下不稳定，并行运行请限定纯逻辑子集
  （如 `-n 4 -m "not ui" --ignore=tests/test_phase2_live_logcat_gate.py`）；CI 仍保持串行全量。
- **pre-commit**（本地钩子）：`.pre-commit-config.yaml` 已配置 ruff、中文注释门禁与
  文档链接校验三个本地钩子；首次使用执行 `pre-commit install`（依赖 pre-commit 本体与
  `.venv` 已安装）。
