# Controller APK 文件选择依赖收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将三处 APK 文件选择改为显式接口依赖，保持现有 Controller 公共入口、任务作用域、功能和数据兼容。

**Architecture:** 纯 Python ApkFilePicker 定义同步选择契约，QtApkFilePicker 负责唯一的 Qt 文件框实现。MainFrame 显式注入，公开 ADBController 门面提供相同实现的兼容默认值；业务 mixin 只使用接口，沿用原执行流程。

**Tech Stack:** Python 3.11、PySide6、pytest、Ruff、Pyright；使用仓库 `.venv`，不引入新库。

**Spec:** [Controller 的 APK 文件选择依赖收敛设计](../specs/2026-10-23-controller-apk-picker-design.md)

## Global Constraints

- 本阶段保持 Python 3.11、PySide6 和现有依赖，不新增生产依赖。
- 保留现有界面、信号签名、功能路由、JSON/YAML 格式和存储路径。
- 不新增全局单例、线程、Timer、事件总线或持久化状态。
- 保留既有未提交修改，生产注释使用中文；本计划不授权 commit、push 或发布。
- 三个 Controller 公共方法与 signal map 不变；只增加可选仅关键字构造参数 `apk_picker`。
- 选择接口同步返回，不排序、去重、改写路径或吞掉异常；取消语义按设计第 5 节逐项保持。
- 不迁移 window_owner、模型装配、结果协议、安装 owner/generation、关闭流程或设备上下文。
- 本文已获用户批准，以下命令和测试是实施要求；实际执行结果在文末单独记录。

## Review Focus

1. 构造后才赋 window_owner、以及注入假值 picker：仍用正确对象和调用时父窗口。（任务 1、2）
2. 中文/繁体/英文、空选择、路径含空格或中文、重复路径：参数和原始值不能被改写。（任务 1、2）
3. 模态选择期间同 key 重入或改选设备：只有一个 request，提交仍归属点击时目标。（任务 3）
4. 选择异常、安装取消与解析取消：保留不同终态，无任务提交，scope 不泄漏。（任务 2、3）
5. 分段启动、历史已加载、窗口关闭前拒绝和关闭后空返回：不提前弹框、不重复加载、不复活结果。（任务 2、3）

---

## 状态、执行方式与文件地图

状态：2026-10-23 已完成代码实施与独立审阅；直接及 GUI 集成验证通过，布局关联集合保留一项经实施前源码对照复现的既有字体失败，详见文末。采用用户已选方式：**主 agent 串行实施，完成后独立审阅**。
实施前重新读取 AGENTS.md、docs/README.md、设计及局部规则，检查状态和目标差异。
撰写时分支为 `ui-redesign`，HEAD 为 `e0c0d04`；工作树包含上一阶段已经验收但未提交的改动，
执行基线是这些现有文件，不是只有 HEAD。复用合适工作区，不能因新建 worktree 丢失前置成果。

| 文件 | 责任 |
| --- | --- |
| `adblab/application/apk_selection.py`（新增） | 无 Qt 的 ApkFilePicker Protocol |
| `adblab/presentation/qt_apk_file_picker.py`（新增） | 文件框参数、翻译、父窗口及返回值适配 |
| `controllers/__init__.py`、`controllers/_base.py` | 公开兼容默认值、必填内部依赖保存 |
| `controllers/_app.py`、`controllers/_app_install.py` | 三处选择调用替换，保留业务分支 |
| `gui/main_frame.py` | 原构造点显式注入 |
| `tests/test_apk_file_picker.py`（新增） | Qt 适配器契约 |
| `tests/test_controller_apk_picker.py`（新增） | 构造、选择、取消、异常和请求顺序 |
| `tests/test_phase2_install_batch_gate.py`、`tests/test_model_apps.py`、`tests/test_dialog_languages.py` | 现有假对象接入、保留有效断言 |
| `tests/test_mainframe_startup.py`、`tests/test_main_window_layout.py`、`tests/test_model_mainframe.py` | 构造工厂与启动验证 |
| `tests/test_action_feedback.py` | 原信号调用链的模态重入和目标快照 |
| `docs/project-knowledge/ARCHITECTURE.md`、`MODULE_MAP.md`、`docs/README.md` | 实施完成后同步边界和导航 |

## 实施前基线

- [x] 保存本轮前状态/差异，明确上阶段文件不可覆盖；确认上述目标没有新增的冲突修改。
- [x] 先运行选择和入口直接基线，再执行对应任务；不重跑上一阶段全部设备上下文验收。

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests/test_dialog_languages.py::test_apk_choosers_translate_titles_and_filters_without_submitting_on_cancel tests/test_model_apps.py::test_parse_apk_info_accepts_existing_apk_case_insensitively tests/test_model_apps.py::test_parse_apk_info_rejects_missing_file tests/test_phase2_install_batch_gate.py::test_single_apk_entry_uses_same_operation_identity_for_every_device tests/test_phase2_install_batch_gate.py::test_install_batch_partial_maps_to_compat_failure_and_reports_counts tests/test_mainframe_startup.py::test_controller_loads_history_by_default_and_honors_explicit_preload
```

预期退出码 0；失败先定位并记录，不能把基线问题包装成本轮回归，也不能放宽断言。

## Task 1: 定义选择接口与唯一 Qt 适配器

**Files:** 新增 `adblab/application/apk_selection.py`、`adblab/presentation/qt_apk_file_picker.py`、`tests/test_apk_file_picker.py`。

**Interfaces:**
- Consumes: `Callable[[], QWidget | None]`；现有 `QCoreApplication.translate` 和 QFileDialog API。
- Produces: `ApkFilePicker(Protocol).select_one(self) -> str | None`、`select_many(self) -> tuple[str, ...]`。
- Produces: `QtApkFilePicker.__init__(self, parent_provider: Callable[[], QWidget | None]) -> None`，实现上述两个方法。

- [x] **1. 新增适配器失败测试。** 测试标记 `pytest.mark.ui`，使用既有 `qt_application`；Qt 静态方法用 Mock，不打开真实系统文件框。测试名称和关键断言如下：

| 新增测试 | 输入与必须断言 |
| --- | --- |
| `test_selection_protocol_import_does_not_load_qt_or_controllers` | 使用项目解释器启动新子进程，只导入 `adblab.application.apk_selection`；`assert not any(name == "controllers" or name.startswith("PySide6") for name in sys.modules)`，不把父测试进程已加载的 GUI 算入 |
| `test_construction_is_lazy_and_parent_is_resolved_per_selection` | 构造后 `provider.assert_not_called()`、两个 chooser 未调用；更换 provider 返回的两个 QWidget 后逐次选择，`chooser.call_args.args[0] is current_parent`；兼容 `None` 父窗口 |
| `test_single_and_multiple_preserve_dialog_parameters` | 本用例替换 translate 为原文返回并断言 context 为 `ADBLab`；单选/多选分别 `assert_called_once_with(parent, title, "", "APK Files (*.apk);;All Files (*)")`，标题按设计第 4.2 节；三语言验证留在原语言测试 |
| `test_selection_preserves_paths_order_and_duplicates` | Qt 返回 `"目录/demo one.APK"`、`["b.apk", "目录/demo one.APK", "b.apk"]`；断言单选原样，`select_many() == ("b.apk", "目录/demo one.APK", "b.apk")` |
| `test_cancel_returns_none_or_empty_tuple` | Qt 返回 `("", "")` / `([], "")`；断言 `select_one() is None` / `select_many() == ()` |
| `test_picker_exceptions_propagate` | chooser 或 provider 抛 `RuntimeError("picker failed")`；`pytest.raises(RuntimeError, match="picker failed")`，不转为空选择 |

- [x] **2. 运行红灯。** `python -m pytest -q tests/test_apk_file_picker.py`（使用 `.venv` 完整路径）；预期缺少新增模块，确认不是 Qt 环境错误。
- [x] **3. 实现接口和适配器。** 按 Interfaces 签名，使用设计固定的三条翻译原文；构造不调用 provider；两方法分别取 Qt 返回的首项并归一为 `None` / tuple。生产契约用中文说明同步调用、异常及资源归属。
- [x] **4. 运行绿灯。** 同一测试文件应全部通过；本任务不改变 Controller 或 GUI 路由，不需要扩大到安装/关闭测试。

## Task 2: 将 Controller 接入选择接口并保留默认构造

**Files:** 修改 `controllers/__init__.py`、`controllers/_base.py`、`controllers/_app.py`、`controllers/_app_install.py`；新增 `tests/test_controller_apk_picker.py`；修改 `tests/test_phase2_install_batch_gate.py`、`tests/test_model_apps.py`、`tests/test_dialog_languages.py`。

**Interfaces:**
- Consumes: 任务 1 的 `ApkFilePicker` 与 `QtApkFilePicker`。
- Produces: `ADBController.__init__(self, log_service: LogService, *, load_device_history: bool = True, apk_picker: ApkFilePicker | None = None) -> None`。
- Produces: `_ADBControllerBase.__init__(self, log_service: LogService, *, apk_picker: ApkFilePicker, load_device_history: bool = True) -> None`，属性 `apk_picker: ApkFilePicker`。
- Preserves: `install_apk(self, devices: list) -> str | None`、`batch_install_apk(self, devices: list) -> str | None`、`parse_apk_info(self)` 以及 `_start_install_batch` 契约。

- [x] **1. 补充构造和业务失败测试。** 新文件中需要构造真实 Controller 的测试标记 `pytest.mark.ui`，使用 Qt/设置隔离；DeviceStore.load 使用 Mock，模型不提交真实命令，并在 finally 排空 Controller。业务测试使用显式 picker 假对象、真实 `_emit_operation` 和受控模型，不能只 Mock 消息发送却声称验证了 ActionResults 终态。

| 新增测试 | 必须断言 |
| --- | --- |
| `test_explicit_picker_is_kept_even_when_falsey` | 假 picker 的 `__bool__` 返回 False；`controller.apk_picker is picker`；构造期间 chooser 未调用 |
| `test_default_picker_is_lazy_and_uses_late_window_owner` | 省略 picker 构造不弹框；随后设置/更换 window_owner；调用原入口时 Qt chooser 的 parent 是最新 owner，默认适配器与显式 Qt 适配器为同一类 |
| `test_missing_devices_never_opens_install_picker` | 对两个安装入口参数化；空列表导致 picker 两方法均未调用，`_start_install_batch.assert_not_called()`；保留原无设备反馈 |
| `test_cancel_preserves_each_entry_result` | 三入口参数化，在真实 ActionResults.run 中调用；安装 `result.state == "failed"`，消息含 `APK selection canceled`；解析 `result.state == "cancelled"` 且未发该消息；模型/批次未提交 |
| `test_batch_request_order_and_paths_are_unchanged` | 设备 `["device-a", "device-b"]`，文件 `("b.apk", "目录/demo one.APK", "b.apk")`；`[(r.apk_path, r.device_id) for r in requests] == [(p, d) for p in paths for d in devices]` 共 6 项，返回值仍为原 operation id |
| `test_picker_exception_creates_no_job_and_releases_scope` | picker 抛 RuntimeError；ActionResults.run 对外继续抛错，request 为 failed，无模型/批次调用，作用域外 `capture_action_job("probe") is None` |

- [x] **2. 运行红灯。** `.\.venv\Scripts\python.exe -m pytest -q tests/test_controller_apk_picker.py`；预期为构造参数/选择依赖尚未接入的断言失败。
- [x] **3. 实现依赖装配。** 门面只在 `apk_picker is None` 分支内导入 Qt 适配器，传入调用时读取 `self.window_owner` 的 provider；再调用原 super 构造。Base 保存传入实例，其余初始化顺序不变。
- [x] **4. 替换三次选择调用。** 业务方法只调用 `self.apk_picker.select_one/select_many`；删除两文件不再使用的 Qt 选择/翻译导入，保留无设备检查、解析校验、原消息及批次构造顺序。不得在 mixin 内做 fallback。
- [x] **5. 迁移原测试的依赖替身。** 安装 gate 的 `_controller()` 显式提供 picker，各用例替换自身 picker 方法，不再 patch 全局 Qt。`test_model_apps` 保留大小写/缺失文件断言；语言测试构造真实 QtApkFilePicker 并注入，保留三语言×三入口、父窗口、过滤器和取消断言。原 gate 的 `parent is None` 断言迁入适配器/默认构造测试，不丢失该覆盖。
- [x] **6. 执行直接与关联验证。** 完整安装 gate 覆盖变更过的测试替身及下游 operation 协议；解析模型和 ActionResults 验证取消/异常没有改动结果归属。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_apk_file_picker.py tests/test_controller_apk_picker.py tests/test_phase2_install_batch_gate.py tests/test_model_apps.py tests/test_dialog_languages.py::test_apk_choosers_translate_titles_and_filters_without_submitting_on_cancel
.\.venv\Scripts\python.exe -m pytest -q tests/test_apk_analysis_results.py tests/test_action_results.py tests/test_mainframe_startup.py::test_controller_loads_history_by_default_and_honors_explicit_preload
```

预期全部通过；保留安装成功、部分失败、提交异常、取消、失败重试、重复/晚到结果的既有断言。
本任务不修改这些生命周期实现。检查通过后没有新变更就不重复运行相同集合。

## Task 3: 主窗口显式注入与原信号链集成验收

**Files:** 修改 `gui/main_frame.py`；修改 `tests/test_mainframe_startup.py`、`tests/test_main_window_layout.py`、`tests/test_model_mainframe.py`、`tests/test_action_feedback.py`；更新文件地图中的三份现状/导航文档。

**Interfaces:**
- Consumes: `QtApkFilePicker(parent_provider)`、`ADBController(..., apk_picker=picker)`。
- Preserves: MainFrame 两种启动方式、`load_device_history` 条件、两个 APK signal map、ActionFeedbackPresenter.dispatch 与 ActionResults.run。
- Produces: 每个窗口独立注入一个 picker，原 Controller 入口在原 request scope 内执行。

- [x] **1. 给主窗口构造替身增加显式参数。** `test_mainframe_startup.controller_factory` 和 `test_main_window_layout.build_main_frame` 内的工厂均显式接收 `apk_picker` 与 `load_device_history`，记录实例供断言；不使用任意 `**kwargs` 隐藏漏传。先以可辨识的缺省值保持旧调用可运行。
- [x] **2. 新增启动注入失败测试。** `test_mainframe_injects_one_picker_without_opening_dialog` 对同步/分段、历史预加载 True/False 参数化；断言捕获的 picker 为 QtApkFilePicker、不同窗口实例不同、构造与启动均未调用 chooser，history flag 沿用原分支。增强 `test_main_frame_init_defers_adb_bootstrap_until_ui_is_built` 的构造实参断言。
- [x] **3. 运行红灯。** `.\.venv\Scripts\python.exe -m pytest -q tests/test_mainframe_startup.py::test_mainframe_injects_one_picker_without_opening_dialog`；应因 MainFrame 尚未注入失败。
- [x] **4. 实现主窗口注入。** 原 Controller 构造点创建 `QtApkFilePicker(lambda: self)`，两个 history 分支都传 `apk_picker=picker`；不改后续 window_owner 赋值、刷新定时器或 signal map。构造替身收紧为必填 picker。
- [x] **5. 在 `test_action_feedback.py` 补充同步选择回调集成测试。** 沿用 result_frame 和真实 SidePanel 信号；Mock Controller 的入口 side_effect 调用真实 mixin 方法，设置 `_shutting_down=False` 并绑定真实 `_require_devices`、`_emit_operation`。picker 使用可编排的同步假对象；安装提交边界 `_start_install_batch` 的替身记录 InstallRequest 并逐项调用 `capture_action_job("install_apk_async", request.device_id)`，解析模型替身调用 `capture_action_job("parse_apk_info_async", path)`。解析有效文件用 tmp_path 创建。测试重点是选择前后 scope 和路由；完整批次执行由任务 2 的安装 gate 覆盖，不在替身复制业务分支。

| 新增测试 | 必须断言 |
| --- | --- |
| `test_apk_picker_reentry_keeps_one_request_and_original_targets` | 准备在线 `device-a/device-b` 并选择 A；picker 内再次发同一批量安装信号，改写原输入列表并用 `left_panel.set_selected_devices(["device-b"])` 改选；进入 picker 时 `state == "running"` 且尚无批次提交；最终 picker 调用 1 次、批次提交 1 次、request 数为 1、`targets == ("device-a",)`、InstallRequest.device_id 仍为 A，至少一个 job 且全部 request_id 同属该 request |
| `test_apk_parse_picker_reentry_uses_original_signal_scope` | 解析信号同 key 重入只选一次；返回有效文件后模型只提交一次，job 归属选框前 request，选框内无 job |
| `test_apk_signals_preserve_cancel_and_exception_results` | 真实批量安装/解析信号分别取消或抛异常；终态和任务数量按任务 2，dispatch 记录异常而不额外创建 request，`capture_action_job("probe") is None` |
| `test_apk_signal_is_rejected_when_frame_is_closing` | `_closing=True` 后分别发两信号；picker、模型均未调用，结果列表不增长 |
| `test_apk_picker_empty_return_after_results_close_does_not_revive_request` | picker 回调执行 store.close 后返回 None/()；两入口均无模型提交，`store.recent() == ()`，scope 退出无异常；不把该测试解释为非空返回的关闭安全证明 |

- [x] **6. 运行 GUI 集成集合。** 先新测试所在文件，再扩展启动及共享构造工厂的代表性消费者；范围扩大原因是 MainFrame 构造关键字和共用 build_main_frame 已改变。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_action_feedback.py tests/test_mainframe_startup.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_main_window_layout.py tests/test_model_mainframe.py::test_main_frame_init_defers_adb_bootstrap_until_ui_is_built tests/test_model_mainframe.py::test_main_frame_signal_maps_keep_expected_coverage
```

- [x] **7. 同步文档事实。** ARCHITECTURE 只增加选择接口、Qt 适配、兼容默认值及仍保留的 window_owner 边界；MODULE_MAP 只增加模块职责；README 标明本阶段完成状态。更新受影响现状文档核实日期，不复制本计划测试计数。
- [x] **8. 执行修改范围的质量检查和启动自检。** 预期退出码均为 0。Pyright 必须实际分析列出的 7 个文件；若 venv 解析错误，先记录环境诊断，临时配置只能继承原检查级别并修复真实解释器路径，不能降级规则或把 0 文件结果算通过。

```powershell
$apkProduction = @("adblab/application/apk_selection.py", "adblab/presentation/qt_apk_file_picker.py", "controllers/__init__.py", "controllers/_base.py", "controllers/_app.py", "controllers/_app_install.py", "gui/main_frame.py")
$apkTests = @("tests/test_apk_file_picker.py", "tests/test_controller_apk_picker.py", "tests/test_phase2_install_batch_gate.py", "tests/test_model_apps.py", "tests/test_dialog_languages.py", "tests/test_mainframe_startup.py", "tests/test_main_window_layout.py", "tests/test_model_mainframe.py", "tests/test_action_feedback.py")
.\.venv\Scripts\python.exe -m ruff check @apkProduction @apkTests
.\.venv\Scripts\python.exe -m pyright @apkProduction
.\.venv\Scripts\python.exe scripts/check_comment_language.py @apkProduction
.\.venv\Scripts\python.exe scripts/check_source_text.py
.\.venv\Scripts\python.exe scripts/check_doc_links.py
.\.venv\Scripts\python.exe main.py --self-check packaging
git diff --check
```

- [x] **9. 主 agent 自检并交独立审阅。** 审阅本阶段增量及与前置工作树的集成，重点检查取消差异、scope、构造兼容、导入方向和有效测试覆盖；不把所有未提交修改误算为本阶段新增。修复发现后只重跑实际受影响集合。
- [x] **10. 记录实际结果与人工边界。** 交付变更范围、测试命令/结果、未运行项、已知限制和独立审阅结论。不自动 commit/push、不生成发布产物、不宣称全项目重构已完成。

## 验收边界与后续路线

全量条件按[测试指南](../../guides/TESTING_GUIDE.md#增量验证策略)判断；当前影响可沿三入口与构造消费者界定，不预设全量。
规划阶段只检查文档链接/frontmatter、路径/节点存在性和 diff；实施阶段的实际 pytest 与源码自检结果见下文。

人工验收：在可用环境中验证三语言文件框的父窗口、标题、过滤器；取消后再次打开；中文/空格路径；
真实设备单 APK/批量安装与本地解析。选框中关闭主窗口并返回非空路径需要专项生命周期验证，
不能用本计划的空返回测试替代；保持设计第 7 节的已知边界。

本阶段验收后，下一候选是把无线配对接纳/ADB 重启通知的 window_owner 访问收敛为明确契约；
届时单独分析 revision、关闭和后台读取时序，再制定范围。模型装配、执行器、持久化和目录归并仍分批推进。

## 实际执行记录（2026-10-23）

主 agent 按任务 1 → 2 → 3 串行实施，随后由独立审阅者检查相对于实施前快照的阶段增量。
本阶段涉及 7 个生产文件、9 个测试文件和 5 份文档；保留上一阶段设备上下文改动。
三个业务入口、signal map、安装批次协议、配置与用户数据格式均未改变；公开构造增加可选的
`apk_picker` 关键字，省略时仍使用同一个 Qt 适配器。没有新增生产依赖或后台资源。

### 测试与质量结果

下列计数属于本次工作树，不是互斥测试集合，不能直接相加作为唯一用例数。
pytest 均使用项目 `.venv`，GUI 使用 `QT_QPA_PLATFORM=offscreen`。

| 检查 | 实际结果 |
| --- | --- |
| 实施前基线命令 | 15 passed |
| 任务 1 适配器 | 新模块缺失时 10 failed；实现后 10 passed |
| 任务 2 新入口测试 | 未接入时 9 failed、2 passed；实现后 11 passed |
| 任务 2 直接集合（上文第一条命令） | 155 passed，1 条已有 SciPy 弃用警告 |
| 任务 2 关联集合（上文第二条命令） | 27 passed，1 条已有 SciPy 弃用警告 |
| 任务 3 启动注入 | 未注入时 4 failed；实现后 4 个参数在下述 GUI 集合中通过 |
| `test_action_feedback.py` + `test_mainframe_startup.py` | 使用 `-vv -o faulthandler_timeout=45`：92 passed，405 条 Qt/SciPy 弃用警告，179.14 秒 |
| 任务 3 布局集合（上文第二条命令，追加 `-o faulthandler_timeout=45`） | 111 passed、1 failed、1 skipped，详见下节；不记作全绿 |
| 独立审阅者运行两个新增测试文件 | 21 passed，1 条 SciPy 弃用警告 |
| Ruff（7 个生产 + 9 个测试文件） | 通过 |
| 中文注释（7 个生产文件） | 通过 |
| `scripts/check_source_text.py` | 705 个文件通过 |
| `scripts/check_doc_links.py` | 55 份文档通过，含交付前文档收尾检查 |
| `git diff --check` | 通过，含交付前文档收尾检查 |
| `main.py --self-check packaging` | 源码环境自检通过，未构建 PyInstaller 产物 |
| Pyright 默认配置 | 实际分析 7 个文件，8 个错误：7 个 Qt 相关导入解析错误及 1 个派生类型错误 |
| Pyright 解释器路径对照 | 临时配置继承原规则，仅加入实际解释器的 `sys.path`，同样 7 个文件，0 errors、0 warnings；未修改仓库配置或降低规则 |

Pyright 对照使用上文 `$apkProduction` 文件列表，并指定
`--project .superpowers/sdd/2026-10-23-controller-apk-picker/pyright.runtime.json --outputjson`。
该忽略目录保存执行前快照、阶段 diff、原始命令日志和临时诊断配置，不作为新的产品依赖。

### 既有失败、跳过与诊断边界

布局集合唯一失败是
`test_navigation_items_follow_font_settings_through_expand_and_collapse[Microsoft YaHei UI]`：
字体返回 `Sans Serif`，期望 `Microsoft YaHei UI`。单独运行该函数两个参数仍为 1 failed、1 passed。
随后在独立进程中，通过只读源码加载器使用实施前保存的四个 Controller 模块、MainFrame 和原测试文件，
相同两个参数同样 1 failed、1 passed，失败表达式和字体值完全一致；六个指定模块均确认加载了前置源码。
这是当前离屏环境下可复现的既有失败，根因未在本阶段修复；没有放宽断言、增加 skip 或修改字体实现。

原有跳过来自 `test_windows_apps_page_responsive_groups_fit_at_supported_widths`：
该用例要求 Windows 原生 Qt 平台插件，本轮为 offscreen。没有新增跳过条件。

首轮 GUI quiet 运行输出长时间没有追加后被中断，未取得栈证据；随后相同 92 节点改用 verbose
和 45 秒单用例栈诊断全部通过，期间未改产品代码。输出没有追加不等同于死锁，不能声称发现或修复了死锁。
新增集成测试曾把真实 Qt 信号误当 Mock 使用，已改用 QSignalSpy 检查零次发射，保留原断言语义。

### 执行裁定与独立审阅

- 复用当前 `ui-redesign` 工作树及其前置改动，不用仅含 HEAD 的新工作树替代；本阶段外的原有文件按实施前哈希核对。
- 计划中的 `SidePanel.set_target_devices` 经代码核实不存在，改为现有 `set_selected_devices`；没有新增或改变运行时接口。
- 遵循仓库增量验证策略，未触发全量 pytest 或完整打包；未经要求不 commit、push 或发布，保留源码与执行记录。
- 独立审阅覆盖阶段增量、七个生产模块、测试及文档，Critical / Important / Minor 均无发现；结论为未发现本阶段引入的可报告缺陷。
- 字体失败在审阅后完成实施前源码对照，按既有问题记录；不因该问题扩展本阶段架构改造范围。

独立审阅未判定的边界分别处理如下：窗口关闭后选框返回**非空路径**仍需专项生命周期验证；
原生对话框的视觉、焦点、高 DPI 和平台模态行为仍需人工检查；真设备安装、真实 APK 工具执行及
PyInstaller 产物未验证；被中断运行的原因没有栈证据；布局集合结果及其对照如上；上一阶段
DeviceContext 仅检查本批衔接与改动保留，不重复宣称对其全部行为做了新一轮验收。
