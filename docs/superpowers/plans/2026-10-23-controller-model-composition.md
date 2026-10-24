# Controller 模型创建与依赖装配 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development with the user's explicit parallel-execution preference. Steps use checkbox (`- [ ]`) syntax. One owner per file; main agent integrates and arranges independent reviews. No commits.

**Goal:** 把四模型创建从 Controller base 提取到可注入工厂，保留既有功能与数据兼容。

**Architecture:** `ControllerModels` 与无参默认工厂位于 Controller 装配模块；门面提供可选 factory，base 在原位置调用并保存到原属性。GUI、模型、信号和关闭实现保持不变。

**Tech Stack:** Python 3.11、PySide6、pytest、Ruff、Pyright；仓库 `.venv`，不新增依赖。

**Spec:** [模型装配设计](../specs/2026-10-23-controller-model-composition-design.md)

## Global Constraints

- 保持四模型创建顺序 Device→App→Testing→Advanced，settings→models→use cases→signals→executor→history 顺序不变。
- 只调用一次注入 factory；仅 `is None` 选默认值，异常原样传播、不回退、不重试。
- 保留四个原 `*_model` 属性，业务、信号、shutdown 继续读取它们，不增加第二份状态源。
- 不改变 Qt 线程、父子关系、八条信号接线、关闭顺序、首错传播、结果/关闭屏障。
- 不改 MainFrame、模型生产实现、设置、DeviceStore、ADB、数据格式、交互、依赖、CI 或发布流程。
- 不覆盖前置资产；不提交、暂存、推送、删除文件、执行真实设备命令或关机。
- 用户已授权持续改造，主 agent 决定常规细节；接口先冻结，独立文件并行，统一集成和独立审阅。

## Review Focus

1. falsey factory、异常工厂：不能误选默认值、重复创建或吞错。（任务 2）
2. 多个 Controller：模型不能缓存/共享或先于 settings 构造，模型线程归属不变。（任务 1、2）
3. 模型替换后关闭：shutdown 仍读取原属性，不能清理构造时另一份容器。（任务 3）
4. 每模型信号和晚到结果：恰好一路完成/进度投递，关闭后不再接受结果。（任务 3）
5. 前两种 UI 适配器与历史 preload：旧构造和默认值保持，工厂失败不启动后续 executor/history。（任务 2）

---

## 状态、基线与文件归属

用户最新授权覆盖持续全项目重构；本阶段采用多 agent 并行，替代此前主 agent 串行方式。
设计/计划由主 agent 制定，builder check 后推进。分支 `ui-redesign`，不得从缺少前三阶段成果的 HEAD
裸建工作树替代当前基线。46 个前置资产快照保存在忽略目录
`.superpowers/sdd/2026-10-23-controller-model-composition/`；ledger 是续作依据。

| 所有者 | 可写文件 | 与其他任务的依赖 |
| --- | --- | --- |
| Agent A | 新 `controllers/model_dependencies.py`、新 `tests/test_controller_model_factory.py` | 直接按设计中的冻结接口实现 |
| Agent B | `controllers/__init__.py`、`controllers/_base.py`、新 `tests/test_controller_model_injection.py` | 消费 A 的冻结接口；A 未完成时可先写红灯测试 |
| Agent C | 新 `tests/test_controller_model_wiring.py` | 测试公开注入与实际信号/关闭；A/B 完成后跑绿灯 |
| 主 agent | 设计/计划/路线图、`docs/README.md`；实现后更新 ARCHITECTURE、MODULE_MAP | 统一基线、类型/静态/集成验证，合并测试清单并独立审阅 |

只允许各组修改自己的文件，不共享 conftest 或测试 helper；小型本地 fake 优先于新增全局测试基础设施。
无关既有失败只记录证据，确实影响本阶段时才扩大范围。

### 实施前兼容基线

- [x] 保存阶段前文件与哈希，核实目标增量及根目录规则。
- [x] 执行下列基线：**10 passed**，2026-10-23，`baseline.log`。

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests/test_controller_apk_picker.py::test_explicit_picker_is_kept_even_when_falsey tests/test_controller_apk_picker.py::test_default_picker_is_lazy_and_uses_late_window_owner tests/test_controller_device_lifecycle.py::test_explicit_falsey_lifecycle_is_preserved tests/test_controller_device_lifecycle.py::test_default_lifecycle_is_lazy_and_resolves_late_owner tests/test_mainframe_startup.py::test_controller_loads_history_by_default_and_honors_explicit_preload tests/test_model_shutdown_admission.py::test_controller_closes_every_model_admission_before_model_cleanup tests/test_model_shutdown_admission.py::test_controller_reports_cleanup_failure_only_after_waiting_for_every_model tests/test_model_shutdown_admission.py::test_model_shutdown_failure_does_not_skip_other_cleanup
```

## Task 1: 工厂与模型集合（Agent A）

**Files:** `controllers/model_dependencies.py`、`tests/test_controller_model_factory.py`。

**Interfaces:** Produces frozen `ControllerModels(device_model: ADBDevice, app_model: ADBApp, testing_model: ADBTesting, advanced_model: ADBAdvanced)`、`ControllerModelFactory = Callable[[], ControllerModels]`、`create_controller_models() -> ControllerModels`。

- [x] 编写工厂失败测试：`test_default_factory_creates_fresh_models_per_call`，四个构造器替身记录严格顺序，连续两次调用均有不同四实例、返回字段身份正确；`test_default_factory_propagates_model_creation_failure` 参数化四个失败位置，异常对象相同，后续构造器没有执行。
- [x] 运行新文件并记录因模块/接口缺失的红灯，不能把基础环境错误算红灯。
- [x] 实现简单 frozen dataclass、Callable 类型别名及顺序构造函数；模型类型直接沿用现有类，不缓存、不接线、不读设置/store。
- [x] 补真实构造契约 `test_real_factory_preserves_model_types_and_pool_ownership`：在 Qt 主线程构造两组，验证实际类型、不同模型/long_pool、共享 global pool、Advanced 录屏池 parent/双槽不变；禁止真实命令，finally 在后台有界等待模型清理。
- [x] `pytest -q tests/test_controller_model_factory.py` 通过；只检查本任务文件的 Ruff/中文注释，提交报告，不做 git commit。

## Task 2: 门面与 base 注入（Agent B）

**Files:** `controllers/__init__.py`、`controllers/_base.py`、`tests/test_controller_model_injection.py`。

**Interfaces:** Consumes 任务 1 的三符号。Produces 公开 `ADBController.__init__(self, log_service: LogService, *, load_device_history: bool = True, apk_picker: ApkFilePicker | None = None, device_lifecycle: DeviceConnectionLifecycle | None = None, model_factory: ControllerModelFactory | None = None) -> None`；base 在现有参数中增加必填 `model_factory: ControllerModelFactory`。

- [x] 新增红灯：`test_injected_factory_is_used_once_and_models_are_preserved`（参数化正常/falsey callable），断言一次调用、四属性身份、默认工厂不执行；`test_factory_failure_propagates_without_fallback`，断言原异常对象、无 executor/history；`test_default_factory_runs_between_settings_and_controller_services` 固定调用顺序。
- [x] 运行新文件红灯；A 尚未完成时等接口出现后确认失败是注入未接入，不把依赖缺失当本任务全部红灯证据。
- [x] 门面仅在 factory 为 None 时选默认函数并传给 base；base 在原四创建行调用一次再赋四属性，移除四个具体模型 import。其他初始化、方法和信号/关闭实现原样保留，不保存 bundle/factory 副本作为运行状态。
- [x] 验证既有适配器参数与 history 参数不变；工厂失败不进入后续 Controller 初始化。不设计新 rollback 机制。
- [x] `pytest -q tests/test_controller_model_injection.py` 通过；本任务 Ruff/注释通过。报告实际文件/红绿/例外，不提交。

## Task 3: 注入后的信号与关闭契约（Agent C）

**Files:** `tests/test_controller_model_wiring.py`，不改生产文件或共享夹具。

**Interfaces:** Consumes 任务 1、2 的公开构造与 `ControllerModels`；fake QObject 信号必须为 `Signal(str, object)` 和 `Signal(object, str)`。

- [x] 新增 `test_each_injected_model_routes_result_and_progress_once`，四模型逐个发实际 Qt 信号，经真实 Controller handler map/ActionResults 聚合观察一次结果/进度；禁止只断言 connect 次数或绕过真实分派。
- [x] 新增 `test_injected_models_keep_shutdown_order_and_first_error`，记录完整关闭时序，参数化正常/中途异常；异常后后续动作仍执行并保留首错。调用真实 Controller shutdown，fake 模型/全局 stop 隔离，finally 保证 executor 回收。
- [x] 新增 `test_shutdown_uses_current_model_attributes`：构造后替换一个模型属性，确认 shutdown 关闭替换对象而非旧 bundle。新增 `test_late_model_signals_are_ignored_after_shutdown`：真实分派拒绝关闭后的完成/进度。
- [x] 新测试使用 qt_application、isolated_app_settings 和本文件 DeviceStore 替身；模型不启动业务任务，关闭由后台线程执行；不修改全局 conftest、不调用真实 ADB。
- [x] A/B 完成后运行 `pytest -q tests/test_controller_model_wiring.py`，连同本文件 Ruff 通过并提交报告；先前收集失败仅标注依赖未就绪。

## Task 4: 集成、文档与阶段验收（主 agent）

- [x] 核对三个报告及分文件补丁，安排任务范围的独立审阅；无未处理重要问题后接入集成。
- [x] 一次集成运行三份新增测试 + 上文 10 项旧兼容基线；追加 `tests/test_model_shutdown_admission.py::test_controller_shutdown_waits_for_owned_queued_commands`、`tests/test_model_mainframe.py::test_main_frame_signal_maps_keep_expected_coverage`，分别确认真实池排空消费者和未改 GUI 信号映射。不重复完整布局。
- [x] 更新 ARCHITECTURE、MODULE_MAP、README 与本计划/路线图状态；DATA_FLOW 无新事实不改。
- [x] 对三个生产文件、三份新增测试运行 Ruff；三个生产文件运行 Pyright 和中文注释。若实际解释器路径解析失败，继承原规则临时补实际 sys.path，记录分析文件数，禁止降低级别。
- [x] 运行 `scripts/check_source_text.py`、`scripts/check_doc_links.py`、`git diff --check` 与 `main.py --self-check packaging`。不触发全量/完整构建/实机。
- [x] 安排阶段整体独立审阅，复核构造顺序、所有权、失败/关闭、前置资产哈希与跨组一致性；记录实际命令、计数、风险与修复结果。
- [x] 持续目标继续下一阶段审计，不能把本阶段完成记为全项目完成。保持当前工作树及忽略目录证据，不提交/推送。


## 实际验收记录（2026-10-24）

本阶段完成；全项目持续目标仍在执行，下一阶段为目录与功能模块归位。

| 验证 | 实际结果 |
| --- | --- |
| 旧公开构造/关闭基线 | 10 passed |
| Task 1 工厂直接测试 | RED 模块未定义；GREEN 6 passed，含真实模型/Qt 池归属 |
| Task 2 注入直接测试 | RED 7 failed（缺少关键字/未消费工厂）；GREEN 7 passed |
| Task 3 接线/关闭直接测试 | 接口未就绪时 8 setup errors；依赖就绪后 8 passed |
| 集成：三份新测试、上文 10 项基线、Task 4 两个关联节点 | 33 passed，1.23 秒；唯一警告为已安装 qfluentwidgets 的 SciPy 弃用提示 |
| Ruff：三个生产文件与三份新增测试 | 通过 |
| 中文注释：三个生产文件 | 通过 |
| Pyright：继承原配置，临时 extraPaths 来自本轮活动 .venv 的 sys.path | 3 files analyzed，0 errors，0 warnings；未修改仓库规则 |
| check_source_text.py / check_doc_links.py / git diff --check | 718 个文件通过 / 60 个文档通过 / 通过 |
| main.py --self-check packaging | 退出码 0，源码资源/运行时自检通过 |

三个任务分别完成规格与质量审阅。Task 3 的 ui 标记遗漏已补文件级 pytestmark 并独立复核：
`--collect-only -q -m ui` 选中 8 项，`-m 'not ui'` 排除 8 项（pytest 原生退出码 5，零选择），
修正后本文件 8 项通过；没有改全局 conftest。最终阶段独立审阅 Approved，无 Critical/Important/Minor。

阶段前 46 个资产中，41 个哈希未变，5 个为预定增量（两个 Controller 文件、三个现状文档）；
新增 7 个文件（工厂、三份测试、设计/计划/路线图）。六个生产/测试文件与最终审阅哈希完全一致。
原八条信号和 shutdown 实现按快照比较未变；没有修改 MainFrame、模型实现或历史数据协议。

主 agent 的关键裁定：在含前置成果的当前 checkout 工作，以快照审阅代替 HEAD；按用户要求将不同
文件并行实施；MainFrame 保留旧构造参数而由公开 Controller 选择默认工厂；不把部分构造回滚加入本批。
相应代价是需要额外范围核对、未来替代工厂由调用方显式传入，以及原有部分构造失败边界仍存在。
没有保存第二份运行时模型容器，关闭继续读取原模型属性。

未运行全量 pytest、完整 PyInstaller 构建、真实 GUI/设备或新增跨线程投递验收；未将 offscreen/fake
结果等同于这些场景。没有提交、暂存、推送、依赖/CI 修改或关机。日志、快照和审阅报告保留于本阶段
忽略工作区，供持续目标续作，不删除未提交成果的唯一证据。
