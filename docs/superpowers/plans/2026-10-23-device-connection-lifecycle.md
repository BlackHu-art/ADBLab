# Controller 设备连接生命周期依赖收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. Preserve the selected method: main agent implements serially, then one independent review.

**Goal:** 将无线配对接纳与 ADB 重启的窗口依赖收敛为显式生命周期接口，保持现有功能、数据及失败/关闭语义。

**Architecture:** 应用层定义 DeviceConnectionLifecycle 和 WirelessHistoryGuard；presentation 适配器封装动态 owner 解析、配对准入及窗口通知。Controller 保留自身 shutdown 检查、历史写入与重启执行顺序，MainFrame 显式装配，公开构造提供兼容默认值。

**Tech Stack:** Python 3.11、PySide6、pytest、Ruff、Pyright；使用项目 `.venv`，不新增依赖。

**Spec:** [设备连接生命周期依赖收敛设计](../specs/2026-10-23-device-connection-lifecycle-design.md)

## Global Constraints

- 保持现有入口、检查时机、异常语义、任务归属和数据兼容，沿用 Python 3.11、PySide6 及现有依赖。
- 不新增全局状态、线程、Timer、信号或关闭接口；后台不调用 Qt 方法或控件。
- 不改变 PairingOutcome、历史别名、`ip/Brand/Model/Aversion`、YAML 路径/格式或设置；不追加历史专用 ADB 查询。
- 保留 MainFrame 第一层 accepts_outcome、Controller shutdown 及所有历史复核点；不冻结历史写入许可。
- 保留 `window_owner` 兼容属性和 APK picker，保留构造后设置/更换 owner 的语义。
- 重启成功仍按通知 → `QTimer.singleShot(3000, self.signals, self.refresh_devices)` → 原反馈执行；失败不通知或安排该 timer。
- 保留文档第 6 节列出的普通取消、已开始写入、关闭和重启失败边界，不顺手加强或统一行为。
- 既有未提交修改均为前置资产；本计划不授权 commit、push、发布、依赖或 CI 修改。

## Review Focus

1. 构造时 owner 尚未设置、随后更换 owner、显式假值依赖：延迟解析且旧历史 guard 失效。（任务 1、2、3）
2. owner/pairing 更换但 revision 相等，以及等锁/读缓存时关闭：所有原复核点仍拒绝写入。（任务 1、2）
3. GUI 已受理后普通取消/新请求，以及 add_device 已进入：不无意扩大撤销语义，后台不重调 accepts。（任务 1、2）
4. 失效/通知回调异常、model 提交异常、失败结果：顺序和原异常传播保持，不伪造成功。（任务 1、2、3）
5. 两种启动/历史预加载分支、晚到重启结果、关闭后 timer 回调：不漏注入，不新增查询/结果或后台资源。（任务 2、3）

---

## 状态与执行基线

2026-10-23：已完成代码实施与独立审阅；实际验证、既有失败和环境边界记录在文末。
设计已经过独立 builder check，结论为没有影响制定计划的重要缺口；这不是代码实现审阅或测试通过结论。
沿用主 agent 串行实施、完成后独立审阅。

当前分支 `ui-redesign`，HEAD `e0c0d04`；设备上下文和 APK picker 两阶段成果仍在未提交工作树中。
实施基线必须包含这些文件，不能只从 HEAD 新建一个缺少前置成果的工作树。实施前重新检查状态、
局部规则和目标差异，保存本阶段前的文件快照；不要把此前已验收文件重新算作本轮范围。

## 文件地图

| 文件 | 本阶段责任 |
| --- | --- |
| 新增 `adblab/application/device_connection_lifecycle.py` | 两个纯 Python 协议；PairingOutcome 仅类型检查时导入 |
| 新增 `adblab/presentation/qt_device_connection_lifecycle.py` | 同一个默认/显式适配器与私有动态 guard |
| `controllers/__init__.py`、`controllers/_base.py` | 公开可选注入、内部必填依赖与保存 |
| `controllers/_device.py` | 三处业务入口消费新接口，原存储与重启流程保留 |
| `gui/main_frame.py` | 两个构造分支显式注入；修正重启通知 docstring 对 timer 归属的描述 |
| 新增 `tests/test_device_connection_lifecycle.py` | 协议导入、适配器惰性、guard 与通知契约 |
| 新增 `tests/test_controller_device_lifecycle.py` | 构造兼容、接口消费、关闭与异常路径 |
| `tests/test_wireless_connection_history.py` | 原历史工厂接入适配器，扩展确定性竞态，保留 YAML/脱敏断言 |
| `tests/test_model_ci_controller.py` | 原重启替身接入假接口，增强成功/失败顺序断言 |
| `tests/test_mainframe_startup.py`、`tests/test_main_window_layout.py`、`tests/test_model_mainframe.py` | 构造替身显式接收新关键字，启动/兼容测试 |
| `tests/test_adb_environment_integration.py`、`tests/test_action_feedback.py` | 窗口 facade、无线入口与真实重启信号调用链 |
| `docs/project-knowledge/ARCHITECTURE.md`、`MODULE_MAP.md`、`docs/README.md` | 实施完成后同步新边界；不提前写成当前事实 |

`QtAdbPairing`、`QtAdbRuntime`、core runtime、model、DeviceStore、CloseController 和 TaskSupervisor
生产实现不在修改范围；关联测试用于确认原有行为。没有新数据格式，不需要迁移或双写。

## 实施前基线

- [x] 保存现有差异/文件哈希，核对目标没有新冲突；以当前工作树为基线。
- [x] 使用下列直接节点确认历史、重启、窗口重检和旧构造兼容。失败先定位，不能放宽断言。

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests/test_wireless_connection_history.py tests/test_model_ci_controller.py::test_restart_adb_success_notifies_runtime_before_refresh tests/test_model_ci_controller.py::test_restart_adb_failure_keeps_runtime_state_untouched tests/test_adb_environment_integration.py tests/test_controller_apk_picker.py::test_default_picker_is_lazy_and_uses_late_window_owner tests/test_mainframe_startup.py::test_controller_loads_history_by_default_and_honors_explicit_preload
```

预期退出码 0，记录实际计数。上一阶段布局字体失败、默认 Pyright 解释器解析错误和历史 mock-macOS
路径断言仅是诊断参考；本轮若遇到相同问题仍核对当前证据，不预先跳过用例或把旧失败说成新回归。

## Task 1: 定义生命周期接口与窗口适配器

**Files:** 新增两个生产模块及 `tests/test_device_connection_lifecycle.py`。

**Interfaces:**
- Produces: `WirelessHistoryGuard.is_current(self) -> bool`。
- Produces: `DeviceConnectionLifecycle.capture_wireless_history(self, outcome: PairingOutcome) -> WirelessHistoryGuard | None`。
- Produces: `DeviceConnectionLifecycle.invalidate_wireless_pairing(self, reason: str) -> None`、`note_adb_server_restarted(self) -> None`。
- Produces: `QtDeviceConnectionLifecycle.__init__(self, owner_provider: Callable[[], object | None]) -> None`，实现上述接口；私有 guard 不作为公共导出。

- [x] **1. 写失败测试。** 用 SimpleNamespace/Mock 与真实 PairingOutcome 测试边界，不打开窗口或执行 ADB。

| 新测试 | 必须断言 |
| --- | --- |
| `test_lifecycle_protocol_import_is_isolated` | 新子进程只导入协议，sys.modules 无 controllers、services.adb_pairing、PySide6；不以父 pytest 进程判断 |
| `test_adapter_is_lazy_and_tracks_late_owner` | 构造不调用 provider；None→owner A→owner B 后每次通知到当前对象；capture 无 owner 返回 None |
| `test_capture_delegates_original_outcome_and_preserves_rejection` | owner closing、无 pairing、accepts 缺失/不可调用、accepts=False 时返回 None；接受时传递同一 outcome 对象，复制结果由 fake accepts 拒绝 |
| `test_guard_rejects_owner_pairing_revision_and_closing_changes` | 分别改变 owner identity、pairing identity（同 revision）、revision、owner closing，guard 为 False；不变时为 True |
| `test_guard_does_not_repeat_gui_admission` | capture 后将 accepts 设为“调用即失败”，executor 中重复调用 guard 仍只读引用/标量；记录 capture 的 accepts 只在主线程执行 |
| `test_guard_preserves_admitted_request_semantics` | 仅清空 verified outcome、改变 current request 或 pairing 自身 closing 而不改变 owner/revision/owner closing，已有 guard 仍为 True；不把它写成新准入可以接受 |
| `test_callbacks_keep_optional_and_exception_behavior` | 回调缺失/不可调用无操作；`server_restart` 原样传递；provider/accepts/通知抛 RuntimeError 时原样传播；不转为空结果或成功 |

- [x] **2. 运行红灯。** `.\.venv\Scripts\python.exe -m pytest -q tests/test_device_connection_lifecycle.py`；预期缺少新模块，先排除测试自身错误。
- [x] **3. 实现两个模块。** guard 保留 owner/pairing 强引用和 outcome.context_revision，使用 `is` 比较引用；不调用 Qt 方法。按设计第 4 节写中文契约说明，不引入独立状态副本或额外锁。
- [x] **4. 运行同文件绿灯。** 预期退出码 0；本任务尚未接入 Controller，无需运行模型/GUI 宽集合。

## Task 2: Controller 消费接口，保持历史与重启语义

**Files:** `controllers/__init__.py`、`controllers/_base.py`、`controllers/_device.py`；新增 Controller 测试；修改历史与原重启测试文件。

**Interfaces:**
- Consumes: 任务 1 的两个协议及 QtDeviceConnectionLifecycle。
- Produces: `ADBController.__init__(self, log_service: LogService, *, load_device_history: bool = True, apk_picker: ApkFilePicker | None = None, device_lifecycle: DeviceConnectionLifecycle | None = None) -> None`。
- Produces: `_ADBControllerBase.__init__(self, log_service: LogService, *, apk_picker: ApkFilePicker, device_lifecycle: DeviceConnectionLifecycle, load_device_history: bool = True) -> None`；保存 `self.device_lifecycle`。
- Preserves: `accept_wireless_connection(self, outcome: PairingOutcome) -> None`、`restart_adb(self)`、`_process_restart_adb_result(self, result: dict)`。

- [x] **1. 补 characterization 与新接口失败测试。** 新文件构造真实 Controller 的节点使用 ui marker、Qt/设置隔离和 DeviceStore.load 替身，finally 在后台排空 Controller；其余使用明确 fake，不靠 Mock 自动生成缺失属性。

| 测试位置/新增场景 | 必须断言 |
| --- | --- |
| 新 Controller 文件：`test_explicit_falsey_lifecycle_is_preserved` | 保留假值注入对象；构造不调用其三个方法，不触发默认 adapter/provider |
| `test_default_lifecycle_is_lazy_and_resolves_late_owner` | 原构造仍有效；owner None/A/B 各阶段行为正确；旧 guard 在 owner 改变后为 False，APK picker 兼容测试保持 |
| `test_wireless_entry_uses_guard_without_window_access` | 显式 fake lifecycle，Controller 无可用 window_owner；合法结果仍按 fake guard 运行，None 拒绝且 falsey guard 不被误当 None；shutdown 时不调用 capture |
| 历史排队测试增加 owner_replaced 参数 | 即使新 owner 指向同 pairing、同 revision 也拒绝写入；保留原四种失效场景 |
| `test_history_rechecks_lifecycle_after_waiting_for_overview_write_lock` | Event 和可控锁覆盖 owner/pairing 替换、owner/controller closing、revision；锁前可接受，取得锁后不落盘 |
| `test_history_rechecks_lifecycle_after_reading_cache` | get_all 回调使同一组状态变化，写入前拒绝；保留原 revision 测试或等价参数覆盖 |
| `test_started_history_write_preserves_natural_completion` | 包装真实 add_device，在进入调用后改变 closing，再完成临时目录写入；原缓存/历史仍保存，不撤销连接、不发失败结果 |
| `test_history_guard_is_rechecked_on_submission_failure` | executor.submit 内使 guard 失效再抛 RuntimeError，不新增警告；guard 仍有效时保留原固定警告，不输出异常正文 |
| 原 CI Controller 成功测试 | 共用事件列表严格等于 notify→timer→成功反馈；timer 实参为 3000、同一 signals、refresh_devices；调用捕获回调只刷新一次 |
| 原 CI Controller 失败测试 | 不通知、不安排 timer，保留原失败反馈；缺失窗口回调的成功结果仍安排原 timer |
| `test_restart_failures_preserve_invalidation_and_propagation` | 失效异常不提交；model 提交异常仍先记录失效；失败结果不复活 pairing；成功通知异常不安排 timer或成功反馈，原分派层仍能结算失败 |
| `test_shutdown_rejects_late_restart_result_and_delayed_refresh` | 通过真实 `_handle_async_response` 在 shutdown 后投递成功结果：无通知/新 timer/反馈；已捕获的 refresh 回调在 shutdown 后执行不提交设备查询 |

- [x] **2. 运行红灯。** 先新增 Controller 文件，再运行新增/扩展的历史与重启节点。新接口未接入的测试应失败；旧行为 characterization 已通过属于基线，不能虚构红灯。
- [x] **3. 接入门面与 base。** 只在 `device_lifecycle is None` 分支创建同一适配器，用 `lambda: self.window_owner`；base 保存依赖，其余初始化不动。保留 APK picker 逻辑。
- [x] **4. 替换三处依赖。** 无线入口先保留 Controller shutdown 短路，再 capture，`guard is None` 才拒绝；局部 `_is_current` 保留所有调用位置，只改为 Controller shutdown 与 guard.is_current 的短路组合。重启仅替换两个窗口回调查找，原模型、timer、反馈与 catch 边界不动。
- [x] **5. 迁移测试替身。** 历史 fixture 显式注入真实适配器加 `lambda: controller.window_owner`，继续验证旧窗口状态/YAML/缓存；原 CI 重启 helper 使用明确 fake 接口。新接口业务测试使用 fake guard，适配器测试负责窗口结构，不在 mixin 增加无依赖 fallback。
- [x] **6. 运行直接与关联集合。** 直接覆盖变更过的 fixture 与整个 Controller 结果分派文件；关联只选配对屏障与 runtime 重探测消费者。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_device_connection_lifecycle.py tests/test_controller_device_lifecycle.py tests/test_wireless_connection_history.py tests/test_model_ci_controller.py tests/test_controller_apk_picker.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_qt_adb_pairing.py tests/test_wireless_pairing_flow.py tests/test_model_device.py::test_restart_adb_allows_slow_native_server_start tests/test_adb_runtime.py::test_external_server_restart_invalidates_capability_and_reprobes tests/test_model_shutdown_admission.py
```

预期退出码 0；不同重启结果不得改变设备历史协议。通过后无新改动不重复运行同一集合。

## Task 3: 主窗口装配、信号链与阶段交付

**Files:** MainFrame、三份启动/共享构造测试、环境集成与 ActionFeedback 测试、文件地图中的现状文档。

**Interfaces:**
- Consumes: `QtDeviceConnectionLifecycle(owner_provider)`、Controller 的 `device_lifecycle` 关键字。
- Preserves: 原 window_owner 赋值、APK picker、history 分支、MainFrame 三个 facade、signal map 与 ActionResults。

- [x] **1. 写启动失败测试并显式迁移工厂。** startup 与 build_main_frame 工厂接收并保存 `device_lifecycle`，不吞任意 kwargs；红灯阶段可暂设 None，接入后收紧为必填。新增 `test_mainframe_injects_distinct_lazy_device_lifecycles`，同步/分段 × history 预加载参数化；两窗口对象不同，构造无配对/通知调用，history 参数保持，后改 controller.window_owner 能改变通知目标并撤销旧 guard。原模型测试增加真实 adapter 构造实参断言。
- [x] **2. 运行红灯。** `.\.venv\Scripts\python.exe -m pytest -q tests/test_mainframe_startup.py::test_mainframe_injects_distinct_lazy_device_lifecycles`；预期 MainFrame 未传新依赖。
- [x] **3. 在原构造点接入。** 创建 `QtDeviceConnectionLifecycle(lambda: self.adb_controller.window_owner)`，两个 history 分支显式传入；不提前调用 provider，不移动随后 owner 赋值。只修正 note_adb_server_restarted 的 docstring，说明本方法通知 runtime/使 scan 失效，timer 仍归 Controller。
- [x] **4. 补窗口契约与真实信号链测试。** 下列均用合成数据、fake service/model，不访问设备。

| 位置/新增测试 | 必须断言 |
| --- | --- |
| 环境集成：`test_server_restart_facade_preserves_runtime_scan_order` | 真实 MainFrame 方法，events 为 runtime→scan；无 environment/scan 的情况兼容；closing 时不通知 environment，但仍保持原 scan 失效行为 |
| `test_pairing_invalidation_preserves_optional_and_closing_behavior` | pairing 未创建或窗口关闭时不调用；其余传入原 reason；原 recheck 的 invalidate→retire input→recheck 测试不变 |
| `test_wireless_forwarding_and_history_guard_preserve_window_close_boundary` | 真实 MainFrame._on_wireless_connected→真实 Controller mixin→真实 adapter；原 outcome 受理，copy/旧结果拒绝；只设置窗口 closing 而 Controller 尚未 shutdown 时，排队历史不写入；provider/guard 不创建资源 |
| ActionFeedback：`test_restart_signal_keeps_action_scope_and_reentry_guard` | 使用 result_frame 的真实 restart 信号和真实 mixin入口；fake model 边界捕获 ActionJob。失效回调内同 key 重入只产生一个请求/提交；成功/失败结果经 ActionEnvelope 路由归原 request，scope 退出无泄漏 |
| `test_restart_signal_rejects_closing_and_reports_hook_exceptions` | frame closing 时不触发 lifecycle/model；失效回调异常经原 dispatch 结算 failed，不提交模型、不留下 running 请求 |

- [x] **5. 运行 GUI 直接及共享消费者。** 新关键字影响共用 build_main_frame，因此纳入布局文件；runtime 适配层未改，只选关闭/排队通知节点，不因名字相关重跑所有外部环境用例。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_mainframe_startup.py tests/test_adb_environment_integration.py tests/test_action_feedback.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_main_window_layout.py tests/test_model_mainframe.py::test_main_frame_init_defers_adb_bootstrap_until_ui_is_built tests/test_model_mainframe.py::test_main_frame_signal_maps_keep_expected_coverage
.\.venv\Scripts\python.exe -m pytest -q tests/test_qt_adb_runtime.py::test_adapter_queued_notification_keeps_latest_manual_selection tests/test_qt_adb_runtime.py::test_adapter_discards_queued_notification_after_shutdown
```

- [x] **6. 同步文档。** ARCHITECTURE 说明依赖封装、动态 guard 和仍留的兼容 owner；MODULE_MAP 增加新模块；README/设计/本计划记录实施状态。DATA_FLOW 的既有持久化语义不变，不重复复制。核实日期只更新真正检查过的现状文档。
- [x] **7. 运行质量门禁与源码自检。** 只分析六个受影响生产文件，Ruff 覆盖实际修改的测试。Pyright 必须报告实际分析文件数；环境解析失败先记录原因，允许继承原规则的临时解释器路径配置，不允许降级或把零文件当通过。

```powershell
$lifecycleProduction = @("adblab/application/device_connection_lifecycle.py", "adblab/presentation/qt_device_connection_lifecycle.py", "controllers/__init__.py", "controllers/_base.py", "controllers/_device.py", "gui/main_frame.py")
$lifecycleTests = @("tests/test_device_connection_lifecycle.py", "tests/test_controller_device_lifecycle.py", "tests/test_wireless_connection_history.py", "tests/test_model_ci_controller.py", "tests/test_mainframe_startup.py", "tests/test_main_window_layout.py", "tests/test_model_mainframe.py", "tests/test_adb_environment_integration.py", "tests/test_action_feedback.py")
.\.venv\Scripts\python.exe -m ruff check @lifecycleProduction @lifecycleTests
.\.venv\Scripts\python.exe -m pyright @lifecycleProduction
.\.venv\Scripts\python.exe scripts/check_comment_language.py @lifecycleProduction
.\.venv\Scripts\python.exe scripts/check_source_text.py
.\.venv\Scripts\python.exe scripts/check_doc_links.py
.\.venv\Scripts\python.exe main.py --self-check packaging
git diff --check
```

- [x] **8. 主 agent 自检并独立审阅。** 审阅相对本阶段实施前快照的增量，按 Review Focus 检查；核实所有原有效断言保留，区分上一阶段资产。修复确认的问题后只重跑受影响集合。
- [x] **9. 交付记录。** 写实际命令/计数、既有失败、跳过、环境限制和人工边界；不把设计审阅当作代码通过，不自动提交/推送或关机。

## 验证范围与退出条件

规划时仅运行文档链接/frontmatter、路径/测试节点静态核对、源文本与 diff 检查；该记录不代表实施
验证结果。实施完成条件为三个任务落地、相关基线/回归有明确
结论、质量检查完成、独立代码审阅无未处理的重要问题，且前置资产保留。

全量 pytest 依[增量验证策略](../../guides/TESTING_GUIDE.md#增量验证策略)按触发条件另行决定；
本批不预设全量和 PyInstaller 构建。任何既有失败应列出复现/对照依据，不删测试或增加跳过来掩盖。

人工验收保持现有设置和设备数据：扫码/配对码成功后检查历史别名与属性、配对取消和环境重检、
ADB 重启成功/失败后的显示与刷新、关闭期间的队列历史和晚到结果。只在获准的实机环境操作；
没有做实机或产物验收时明确报告边界。

后续候选仍是独立生命周期状态/token 或 Controller 模型装配；本批先交付可验证的依赖边界，
不把这些候选的具体实施视为本计划授权。

## 规划时核对记录

- 主 agent 已逐项自检设计覆盖、接口名称/类型、三个任务的依赖和五项 Review Focus；未留下待定实现接口。
- 静态核对计划引用：21 个现有测试文件/节点有效，另 3 个引用明确属于待新增文件/节点；范围为 6 个生产文件、9 个测试文件。
- `check_doc_links.py`：57 个文档的链接/frontmatter 通过；`check_source_text.py`：707 个文件通过；`git diff --check` 通过。
- 对照规划开始时 36 个前置文件哈希，仅 `docs/README.md` 增加本阶段索引，其余既有资产未变。规划时新增设计与计划，未修改生产代码或测试，未执行 pytest、ADB、自检或构建。

## 实施与验证记录

2026-10-23，主 agent 串行实施；相对本阶段开始时的快照，修改范围为 6 个生产文件、9 个测试文件及
5 个文档。新增的协议和适配器不拥有线程、QObject 或 Timer；Controller 保留 shutdown 与历史复核点，
重启仍按失效→模型提交、成功通知→3 秒刷新→反馈执行。保留 `window_owner` 兼容装配、旧构造入口、
设备上下文及 APK picker 前置成果；没有修改模型、存储、配对状态机、配置或数据格式。

### 直接与关联验证

以下均使用仓库 `.venv`，GUI 设置 `QT_QPA_PLATFORM=offscreen`。日志和阶段前快照保存在忽略目录
`.superpowers/sdd/2026-10-23-device-connection-lifecycle/`，不包含真实设备数据。

| 命令/集合 | 实际结果 |
| --- | --- |
| 上文实施前基线命令 | 28 passed |
| Task 1 新协议/适配器文件 | 先因模块缺失 1 failed、22 errors；接入后 23 passed |
| Task 2 新接口及扩展历史/重启节点 | 接入前 13 failed、35 个既有行为 characterization passed |
| Task 2 第一条直接集合命令（含 APK picker 兼容） | 139 passed |
| Task 2 第二条配对/runtime/模型关闭关联集合命令 | 41 passed |
| MainFrame 注入的四个参数组合 | 接入前 4 failed，接入后 4 passed |
| Task 3 第一条 GUI 命令 | 初次 110 passed、3 failed；失败均为新增重启测试的 Timer 替身拦截了无关 GUI Timer，见下文 |
| `pytest -q tests/test_action_feedback.py tests/test_qt_adb_runtime.py::test_adapter_queued_notification_keeps_latest_manual_selection tests/test_qt_adb_runtime.py::test_adapter_discards_queued_notification_after_shutdown` | 修正测试隔离后 64 passed；startup 与 environment 两文件此前均通过，其后未改行为，不重复运行 |
| `pytest -q tests/test_device_connection_lifecycle.py::test_callbacks_preserve_exception_behavior` | Ruff 样式修正后 4 passed，原异常身份断言不变 |
| Task 3 布局及两个 model-mainframe 节点，最终以 `python -X faulthandler -m pytest -vv -ra` 运行 | 111 passed、1 failed、1 skipped，236.43 秒；正常退出码 1，失败与限制见下节 |

初次 GUI 失败定位为测试替换了共享 `QTimer.singleShot`，误计主窗口 500/30 ms 调度；改为仅替换
`controllers._device.QTimer`。随后发现 `build_main_frame` 构造期间的临时探测替身不能约束排队回调，
测试结束后曾逃逸到真实客户端版本探测并触发已删除 `_ProbeSignals` 异常。因此在 `result_frame`
fixture 整个窗口生命周期内禁用客户端探测，保留真实重启信号/ActionEnvelope 以及 fake model 边界。
四个新增信号节点和上述 64 项最终集合均无尾随探测输出或该清理异常。这些改动只修正测试隔离，
没有更改生产探测行为，也不把客户端探测列为这些结果展示测试的覆盖范围。

### 布局失败对照与原生退出

唯一断言失败为
`test_navigation_items_follow_font_settings_through_expand_and_collapse[Microsoft YaHei UI]`，
实际 `Sans Serif`，期望 `Microsoft YaHei UI`。当前版本单独运行该节点、末尾 performance/screenshot
首帧节点及两个 model-mainframe 节点为 1 failed、4 passed。

使用本阶段 `before/` 快照，在独立进程内替换 Controller 三模块、MainFrame 及两份对应测试源码，
相同五节点仍为 1 failed、4 passed；日志核对六模块 SHA256 与阶段前哈希一致，失败时字体值也完全相同。
对照命令为 `python run_before_layout.py --assert=plain -q <上述五节点>`，普通断言仍照常执行。
首次对照因 pytest 断言重写优先加载当前测试，导致旧生产代码与新工厂不匹配；该次结果无效，
没有当作前置失败。正确对照见 `layout-before-evidence.log`，字体根因未在本阶段修复。

第一次完整布局运行在汇总前退出，Windows 事件记录为 `Qt6Core.dll`、`0xC0000409`；
该次不能记作通过。上述五节点运行以及最终同一完整布局集合均未再出现原生退出。
`layout-final-verbose.log` 记录全部 113 项的最终状态；不能据一次成功完成的复跑认定原生异常已修复，
也没有证据将其归因于或排除本轮改造，保留为未定位的测试运行风险。

唯一 skip 是既有 `test_windows_apps_page_responsive_groups_fit_at_supported_widths` 的平台约束，
要求 Windows Qt platform plugin，而本次使用 offscreen；没有新增 skip、删除测试或放宽断言。

### 质量检查与环境

- 上文 Ruff 命令覆盖 6 个生产文件与 9 个测试文件，通过；中文注释检查通过。
- 默认 Pyright 出现 7 项错误，源于不能解析 `.venv` 实际通过 system-site-packages 使用的 Qt 依赖及其级联类型错误。
  使用忽略目录内 `pyright-runtime.json` 继承原 `pyrightconfig.json`，仅补充活动解释器的 `sys.path`
  为 `extraPaths`，以相对 include 和显式命令行路径分析六个生产文件：6 files analyzed、0 errors、0 warnings。
  没有修改仓库类型规则、降低诊断级别或把零文件分析记作通过。
- `check_source_text.py`：711 个文件通过；`check_doc_links.py`：57 个文档的链接/frontmatter 通过；
  最终 `git diff --check` 通过。
- `main.py --self-check packaging`：退出码 0，源码资源及运行时工具检查通过；未运行完整构建。
- 以 42 个阶段前文件哈希核对：26 个未变，16 个只产生本轮范围内增量；新增 4 个生产/测试文件，
  共 20 个阶段路径。共享文件的前置改动按快照差分和独立审阅核对，未覆盖此前设备上下文/APK picker 成果。

### 独立审阅与边界

独立审阅以阶段前快照为基线，核对 6 个生产文件、9 个测试文件以及五项 Review Focus；确认审阅补丁
与最终生产/测试文件一致。结论为没有 Critical、Important 或 Minor 问题，未要求代码修正。

审阅保留项及主 agent 裁定：

- 实机扫码/配对码、真实 ADB 重启和操作系统窗口关闭尚未验收，保留人工边界，不用 fake/offscreen 结果替代。
- guard 检查与落盘之间不新增原子事务，不引入独立 token 或取消协议；保留已开始写入的自然完成，符合批准范围。
- 前两阶段只核对本轮兼容接缝，不重新审阅全部既有脏工作树；未触发全量 pytest 条件。
- 布局字体失败与原生退出由主 agent 单独对照和报告，不能根据独立代码审阅结论记作测试通过。

没有提交、暂存、推送、更新依赖、改 CI、执行正式发布或关机；源码打包自检不等同于实际 PyInstaller
构建或打包产物验收。人工验收场景仍按上文执行，数据无需迁移。
