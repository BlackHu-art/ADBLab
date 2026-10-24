# 设置 schema 与迁移边界 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 三个任务共享同一 manager，按顺序交给同一实施 owner；独立 reviewer 只读。

**Goal:** 抽出无设置 I/O 的 schema/migrations，使 i18n 直接消费纯语言规则，保留旧 manager 行为。

**Architecture:** 新增 `core/settings/` 的两个纯逻辑模块；manager 保留状态、I/O、线程生命周期和兼容 wrapper。迁移诊断显式注入 reporter；常量和迁移表只有单一真实来源。

**Tech Stack:** Python 3.11、现有 pytest/monkeypatch/subprocess、现有 PySide6 离屏语言测试；不新增依赖。

**Spec:** [设计](../specs/2026-10-24-settings-schema-boundaries-design.md)。实施、独立任务审阅及最终集成审阅均已通过；实际验证见末尾记录。

## Global Constraints

- 用户已授权自主推进；不再次询问执行方式，不 commit/push，不使用 git restore/reset/clean。
- 保留既有 dirty 内容；开始前为下列独占路径保存当前 bytes/hash，按阶段前快照比较增量，不能用 HEAD diff 冒充本批 patch。
- 单 owner 独占：`core/settings_manager.py`、新 `core/settings/` 三文件、`gui/i18n.py`、新测试 `tests/test_settings_schema.py`、`tests/test_settings_migrations.py`、`tests/test_settings_module_compatibility.py`。
- 需要补 manager 加载边界契约时只追加到 `tests/test_settings_persistence.py`；保留其既有 fixture/close 修改。新增测试不得在模块收集时构造 AppSettings。
- 不修改 `tests/conftest.py`、生命周期/关闭实现、main、依赖、资源、schema 版本、生产日志文案。docs 归 root。
- `__init__.py` 只放中文包说明；不得导出 AppSettings 或触发 manager 导入。
- 生产注释/docstring 中文；`CURRENT_SCHEMA_VERSION` 仍为 3；normalizer 返回类型/默认值不变。
- 先读取当前源码、基线报告和本文；历史 lifecycle audit 的缺陷已修复，不重复实施。

## Review Focus

1. 新旧 DEFAULTS 同值却不同对象，或 Monkey 嵌套默认/原始输入遭共享修改：任务 1 身份和深拷贝用例。
2. manager 导入时绑定旧 `_log_error`，后续 patch/sink 切换失效，或 migration 警告重复：任务 2 calltime 与精确顺序用例。
3. 未来版本被清键/降版本，legacy 未来版本又被误判为绝不写：任务 2 manager 加载测试。
4. 纯模块间接导入 Qt/LogService/manager 或调用配置路径：任务 1 独立解释器阻断；任务 3 i18n 消费者阻断。
5. 同包拆分不慎改变 owner、关闭冻结结果或 I/O patch 接缝：任务 2 旧入口契约、任务 3 当前生命周期直接回归；评审逐字核对类体不变。

## 任务 1：schema 与旧模块归一化门面

**Files:** Create `core/settings/__init__.py`, `core/settings/schema.py`, `tests/test_settings_schema.py`, `tests/test_settings_module_compatibility.py`; Modify `core/settings_manager.py` 顶部常量/normalizer 区块；不改 AppSettings 类体。

**Interfaces:** 新 schema 暴露 `DEFAULTS`、`SCRCPY_SETTING_DEFAULTS`、`UI_SCALE_OPTIONS`、`LANGUAGE_OPTIONS`、`normalise_language(value: Any) -> str`、`normalise_ui_scale(value: Any) -> str | float`、`normalise_setting(key: str, value: Any) -> Any`；内部 helpers 签名见设计。manager `_normalise_setting(key, value)` 委托 schema，常量与公开 normalise 函数显式同对象导入。

- [x] **记录基线与预期**：运行 `git status --short`、目标 diff，保存阶段前文件。root 已确认复用本批刚验收的 persistence 72 项与 lifecycle 20 项作为当前前置基线，不为本次搬迁重跑基线；记录原日志路径与适用快照，不冒称本设计运行。仅对前批未覆盖的 i18n 三个语言选择节点和 console schema 节点补一次基线，使用任务3列明的真实节点。不重复227项代表组合或布局矩阵。
- [x] **先补语义测试，使用新入口**：`test_schema_preserves_normalization_contract` 参数至少包含：ui_scale True/1.5/`"150%"` -> Auto/1.5/Auto；language `"zh_HK"`/`"zh_TW"` -> zh_HK/Auto；save_directory `" path "` 保留空白；log_max_lines True/`"2500"`/0 -> 2000/2500/2000；console level `" error "`/None -> ERROR/DEBUG；theme `"auto"` -> System；accent `"#1a2b3c"` -> #1A2B3C；字体边界与原有比例 clamp；scrcpy None/False/过长文本回退或截为 128。未知 key 对普通 object 按身份透传。
- [x] **补共享与深拷贝契约**：`test_schema_monkey_copy_preserves_future_fields_and_defaults` 使用包含嵌套 future 的输入，断言 events `"12345"` -> 12345、throttle `" 60000 ms "` -> 60000、bool 非 bool 回退；结果中 future 值相等但嵌套不同对象，输入/defaults 未变。两次非法 Monkey 输入返回内容相等但非共享字典。`test_legacy_exports_share_schema_objects` 对 DEFAULTS/SCRCPY/options/normalise 函数用 `is`，调用旧 `_normalise_setting` 检查 console/Monkey 等结果。
- [x] **补 ADB 边界**：`test_schema_adb_preference_uses_shape_without_filesystem_lookup` 使用 tmp_path 构造不实际创建的绝对路径，输入首尾空白被剥离；路径 512 截断，source token 全部接纳；非法对象/相对路径回退 auto。不要用 Windows 绝对路径字符串假装跨平台测试，不检测文件存在。
- [x] **补纯导入子进程测试**：在 `test_settings_schema.py::test_pure_schema_import_has_no_settings_or_qt_side_effects` 内启动 `sys.executable -B -c`，cwd 仓库根，timeout=30，禁用插件并把 LOCALAPPDATA/APPDATA/XDG_CONFIG_HOME/XDG_CACHE_HOME/XDG_DATA_HOME/MOBILEPERF_LOG_DIR/TMPDIR 指到 tmp_path。导入安全的 utils.user_data/resource_path 后将 `user_config_path`/`resource_path` 替换为抛 AssertionError 的函数，再导入 schema。MetaPathFinder 拦截 core.settings_manager/core.log_service/PySide6/qfluentwidgets（含子模块），不能用 sys.modules 假模块绕过。调用 normalise_language/ui_scale/setting；检查无被禁模块、配置 sentinel 未改、无 app_settings.json。不要全局拦截 open 导致正常模块加载失败。
- [x] **RED**：运行 `P -m pytest -q tests/test_settings_schema.py tests/test_settings_module_compatibility.py`，预期新模块缺失而失败。保留 exit 与摘要；只把缺模块/契约断言作为需求红灯，先修 fixture 或脚本错误。
- [x] **迁移实现**：逐字移入原常量与字段逻辑，保留原导入依赖。manager 只增加 schema imports/必要 wrapper，移除重复函数体。不要改默认值，不把 DEFAULTS 变 immutable，不批量修改消费者。
- [x] **GREEN**：重跑本任务两个新文件；再运行 `P -m pytest -q tests/test_settings_persistence.py tests/test_console_log_level.py::test_settings_schema_registers_console_level`，保留旧私有导入的消费验证。通过后由只读 reviewer 检查阶段 patch，继续任务 2，不提交。

`P` 表示完整命令前缀 `.\.venv\Scripts\python.exe`；所有下述命令同此定义。

## 任务 2：显式 reporter 的字典迁移与 manager 兼容入口

**Files:** Create `core/settings/migrations.py`, `tests/test_settings_migrations.py`; Modify manager 的 legacy/version/migration 区块、`tests/test_settings_module_compatibility.py`；必要的新加载契约追加 `tests/test_settings_persistence.py`。

**Interfaces:** `Reporter = Callable[[str, str], None]`；`stored_schema_version(stored: dict) -> int`、`legacy_panel_ratio(left_width: Any, right_width: Any) -> float`；`migrate_1_to_2(stored: dict, report: Reporter) -> None`、`migrate_2_to_3(stored: dict, report: Reporter) -> None`、`run_migrations(stored: dict, from_version: int, report: Reporter) -> None`、`prune_unknown_keys(stored: dict, report: Reporter) -> None`。迁移表签名和旧 wrapper 见设计，report 无默认值。

- [x] **版本与迁移 RED**：新增 `test_stored_version_contract` 参数 missing/True/False/None/`"3"`/0/-1/1/2/3/99 -> 1/1/1/1/1/1/1/1/2/3/99。`test_v1_migration_mutates_in_place_without_stamping_version` 使用 widths 300/900、events 5000、未知键，断言同一 dict、ratio=.25、用户值保留、defaults 补齐并非共享、schema_version 不被步骤盖章；完整链再清掉未知键。直接 v1 步不清未知键。
- [x] **精确诊断 RED**：`test_pruning_reports_sorted_top_level_then_monkey_once` 输入顶层 zeta/alpha、Monkey zeta/alpha，捕获期望两行：`('WARNING', 'Ignored 2 unknown settings key(s): alpha, zeta')` 和 `('WARNING', 'Ignored 2 unknown monkey_params key(s): alpha, zeta')`。第二次 prune 不增加消息；run v1→3 后再 prune 同样只有两条。报告对象只用局部 list.append adapter，不在新模块挂全局。
- [x] **调用时绑定 RED**：`test_legacy_migration_wrappers_resolve_reporter_at_call_time` 在 imports 完成后先 patch manager `_log_error` 为 first，调用旧 `_migrate_2_to_3` / `_run_migrations` / `_prune_unknown_keys`；再 patch second 用全新输入调用，分别收到同样 warning。`test_migration_reporters_are_not_shared` 两个独立 reporter 连续调用，消息不串。`test_error_sink_replacement_stays_in_manager` monkeypatch 原 `_error_sink` 后使用 set_error_sink(first/second) 调用同一旧 wrapper，确保恢复旧 sink，不永久设 None 污染上层。
- [x] **纯导入 RED**：`test_pure_migrations_import_has_no_settings_or_qt_side_effects` 沿任务 1 子进程模式实际导入 migrations、调用 run/prune 并检查无路径解析/禁止模块；脚本独立、不依赖纯 schema 测试先执行。
- [x] **manager 加载保真**：复用现有 future 与 deferred 测试；追加 `test_future_legacy_copy_keeps_unknown_fields_and_seen_version`，分别 defer False/True，legacy 合成 JSON 含版本99、规范化所需 known 值、嵌套 future top 与 Monkey future；用户目标原本不存在。False 构造后已有用户文件；True 构造后未写，flush 后写。均保留99和未知值、已知值按原规则规范化，无 unknown-key warning。`test_current_schema_normalization_does_not_rewrite_source_on_load` 验证 v3 输入非法已知值和未知键，内存规范化/清键但构造后原 bytes 不变。`test_runtime_unknown_keys_and_reset_preserve_future_metadata` 验证 update 未知键仍进内存，future owner reset 后版本和 extra 保持；更新调度在测试内禁用，owner 关闭在恢复 patch 前。
- [x] **执行 RED**：新 migration/兼容节点应因新模块或新 reporter 委托缺失失败；manager 原行为的新契约可能已经通过，这是有效保真基线，不为制造红灯改断言。运行命令 `P -m pytest -q tests/test_settings_migrations.py tests/test_settings_module_compatibility.py tests/test_settings_persistence.py`。
- [x] **迁移实现**：按原体搬迁；唯一表放 migrations，v1 接受 report 但不使用。旧纯 helper 保持别名，四个诊断相关旧 wrapper 在函数体内读取 `_log_error`。不改 `_load` 和其锁域、不改保存类体。避免默认参数 `report=_log_error`、import时绑定回调、第二张 dispatcher 或新的 sink。
- [x] **GREEN**：重跑任务 2 命令；对比阶段前后的 AppSettings AST/源码应相同，paths/sink 定义与 __all__ 保持。检查同对象常量、版本3、旧私有函数签名；`_MIGRATIONS` 私有条目新的两参协议须在报告声明。通过后进行局部只读审阅，不提交。

## 任务 3：i18n 接入、关联验证与交付

**Files:** Modify `gui/i18n.py:10`，新增依赖契约放 `tests/test_settings_module_compatibility.py`；root 负责 DATA_FLOW/MODULE_MAP 的少量事实更新。

**Interfaces:** 消费任务 1 的 `schema.normalise_language`；`resolve_language` 等 GUI 接口不变。

- [x] **消费者 RED**：`test_i18n_language_resolution_does_not_import_settings_owner` 在独立解释器/临时环境中禁止 core.settings_manager/core.log_service，允许真实 Qt/qfluentwidgets，导入 gui.i18n 并调用 `resolve_language('zh_HK') == 'zh_HK'`、`resolve_language('Auto', QLocale('en_US')) == 'en_US'`。旧 import 会触发 blocker，证明不是仅测试新函数存在。检查无 manager、无 app_settings.json。不得把该测试做成模块顶层 Qt 导入；该子进程无需 QWidget/QApplication。
- [x] **实现和 GREEN**：只修改 i18n 的 import。运行该节点与 `P -m pytest -q tests/test_i18n.py::test_auto_language_selects_a_supported_locale tests/test_i18n.py::test_explicit_language_is_independent_of_system_locale tests/test_i18n.py::test_auto_and_invalid_language_use_the_real_system_locale`。
- [x] **明确关联验证范围**：本轮修改边界是 schema/migration 与 i18n import；以下节点检查 shared normalizer、diagnostic 注入、冻结 default 数据与消费方式，未触及关闭 UI 或布局，不运行那组已知8失败的布局用例。
- [x] **运行最终直接及关联组合一次**（若任务2之后仅 i18n import改变且直接结果已覆盖，可复用已有稳定结果并只运行新增关联集合；记录实际选择，不为了凑一条大命令重复）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_settings_schema.py tests/test_settings_migrations.py tests/test_settings_module_compatibility.py tests/test_settings_persistence.py tests/test_settings_save_lifecycle.py tests/test_typography_core.py::test_settings_update_validates_fonts_and_schedules_one_save tests/test_typography_core.py::test_settings_atomic_writes_cannot_overwrite_newer_snapshot tests/test_typography_core.py::test_settings_load_migrates_legacy_panel_widths_to_ratio tests/test_typography_core.py::test_settings_loads_and_validates_device_log_split_ratio tests/test_console_log_level.py::test_settings_schema_registers_console_level tests/test_startup_diagnostics.py::test_gui_failure_before_application_is_persisted tests/test_startup_diagnostics.py::test_failure_report_write_error_does_not_mask_startup_error tests/test_i18n.py::test_auto_language_selects_a_supported_locale tests/test_i18n.py::test_explicit_language_is_independent_of_system_locale tests/test_i18n.py::test_auto_and_invalid_language_use_the_real_system_locale
```

- [x] **最小静态检查**：Ruff 仅本轮生产与新/追加测试文件；中文注释仅 manager、新 settings 包、i18n；因为提取共享函数与 Reporter 类型，定向 Pyright 为 `core/settings core/settings_manager.py gui/i18n.py`，有既有错误需保存前后结果，不能降规则。`git diff --check -- <本轮已跟踪路径>`；新增未跟踪文件另查尾空白/源码文本，不认为 git diff 已覆盖。需要时调用现有 check_source_text.py 的真实参数，先查其 CLI，不发明路径选项。
- [x] **scope审阅**：对比阶段前 patch/hash；确认类体、sink、paths、main、close/finalizer/fixture未改；确认两个新模块能独立导入、实际 i18n消费者收益、无第二owner。让独立 reviewer 审 implementation patch；修复只重跑受影响节点。
- [x] **root事实文档**：更新 DATA_FLOW 的 DEFAULTS 真源和迁移来源、MODULE_MAP 的两个新入口，必要时 ARCHITECTURE 一句依赖说明；不改 ADR。root运行 check_doc_links.py 与文档 diff 检查。设计 agent 不越界编辑这些文件。
- [x] **交付报告**：分别列 applied/files、RED/GREEN命令和数字 exit、关联/静态结果、未验证项；保留既有8布局失败的历史归属，不声称本轮修复或验证它们。无全量触发条件；不跑正式构建、真实用户文件、设备或桌面。若范围仍无 main/resource/runtime/packaging 变化，不要求源码 packaging self-check。

## 执行前自检

- 三个任务顺序共享 manager，禁止让两个 implementation agents 并写；reviewer只读。
- 表与 reporter 类型一致；旧函数wrapper原签名保留，旧 _MIGRATIONS 条目内部签名变化显式标注。
- future legacy、v3不回写、runtime未知键与deepcopy都有测试位置，不把纯迁移测试代替owner加载测试。
- 不依赖当前进程先前import状态证明“纯模块”；隔离子进程设置路径环境在第一次项目import之前。
- 计划未实施；本次编写计划未运行任何pytest、用户设置import、packaging或Git写操作。

## 主任务预审与执行裁定

主任务独立builder check PASS，三个/两个紧耦合步骤各由单owner顺序实施，完成后统一独立任务审阅；
两阶段按不相交生产/测试并行。root保管全部正式文档与集成，不重复每小步review或全量测试。
Pyright基线/最终由root按实际.venv搜索路径集中执行。packaging也由root稳定后集中执行，
子进程LOCALAPPDATA/XDG_CONFIG_HOME指向临时目录，保留原main自检入口和工具行为；
该命令会写删.self_check探针，不描述为只读或冻结构建验收。owner不重复自检。
精确裁定与before证据在本阶段忽略目录builder-check.md和progress.md。

## 实施验证记录（2026-10-24）

已完成9文件增量：schema/migrations实际归入core/settings，i18n消费新规则，旧manager仍唯一owner。
完整AppSettings、路径表达式、sink定义及__all__与阶段before源码一致，persistence仅追加4项保真用例。
旧常量/公开normalizer同对象，旧私有函数签名保持；私有迁移表条目改为stored/report两参数，
唯一表与当前版本3不变。无已知外部表消费者，不声称所有私有重绑定行为完全兼容。

去重182项通过：schema32、migrations23、compatibility7、persistence76、console1、i18n17、
lifecycle20、typography4、startup2。无本阶段失败或skip，不把此前8布局失败称已修复或重验。
新增测试经历schema缺模块33fail、migration缺模块24fail、实际i18n旧依赖1fail的红绿链。
最终规则集合62pass、关联26pass；其他稳定消费者结果复用，不重复累计。所有pytest保存数字exit，
绿色命令exit0，警告为既有scipy导入弃用。精确命令见忽略目录implementation-report.md及对应日志。

限定Ruff、中文注释、diff及未跟踪文本/空白检查通过；root使用实际解释器搜索路径运行5生产Pyright，
0错误/0警告。root集中运行原main.py --self-check packaging，子进程数据目录环境隔离到已校验的
临时目录，exit0、无残留.self_check，完成后回收临时目录；自检包含工具执行及探针写删，不是纯静态。
与Remote一起的305项通过只是两阶段去重合集，不是全项目测试。当前独立审阅与最终集成状态见阶段记录。

未跑全量、真实用户配置、设备、真实GUI、高DPI或冻结构建；数据路径/JSON/schema/未来字段规则不变。
完整证据在`.superpowers/sdd/2026-10-24-settings-schema-boundaries/`，审阅以before固定增量为准。

## 最终审阅与交付

2026-10-24，独立最终审阅 PASS，无 P0–P3 findings。审阅固定30路径与20代码路径，
核对两个完整补丁、关键源段和实际验证记录；305项通过、13生产文件类型无诊断。
审阅未重跑测试；1项真实native排除，既有UI-09/UI-10未修复或重验，未验收实机或冻结产物。
原integration-hashes保留，状态收尾后的delivery-hashes另存；全项目持续目标仍在推进。
