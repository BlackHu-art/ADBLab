# 应用动作与归档服务提取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. 一个实施 owner 顺序修改 worker；完成下述步骤后做一次独立 review，不把每个步骤拆为互相竞争的 owner。

**Goal:** 独立承载应用写操作和备份恢复完整事务，保持命令、反馈、取消、用户和清理行为。

**Architecture:** actions/archives 使用显式执行器与窄同步回调，worker 保留 Qt 与准入。
service 内保留原 try/with/计数位置，绝不把通知积累后移到返回点播放。

**Tech Stack:** Python 3.11、现有 pytest、PySide6 adapter、标准库 ZIP/临时目录；无新依赖。

**Spec:** [设计](../specs/2026-10-24-apps-actions-archives-design.md)。接口、固定文案、回调顺序和异常范围以该设计为准。

## Global Constraints

- 以查询阶段最终工作树为前置，先核对主任务快照与目标 diff；不从 HEAD 回退已有服务/worker。
- 只改单一 owner 的 actions/archives/worker 与直接测试；不改 GUI factories、查询实现、CI、版本或依赖。
- 不强中断已开始写命令；备份取消位置的静默/info 差异、恢复逐次核验及计数保持。
- 生产中文注释；服务不得依赖 Qt/GUI/models，真实命令只经显式注入 executor。
- 不提交/推送；主任务统一 docs、Pyright 和隔离 self-check；无全量触发不跑全量。

## Review Focus

- 同步回调抛错、取消或改变后续状态时，旧 try 范围和通知顺序不漂移（步骤 1/2/3）。
- backup 失败与取消优先级、内外 temp cleanup、replace 后失败与旧 ZIP 保留（步骤 2）。
- restore 以 None 表示核验失败，用户 0 有效；切换/取消后不再写，失败不得自动改绑（步骤 3）。
- restore 最后成功安装的计数、Restored 日志异常导致 succeeded/failed 同时计入（步骤 3）。
- 归档私有 patch 改真实 owner 后仍通过真实 worker，服务 fake 完整执行确实不加载 Qt（步骤 4）。

## 步骤 0：确认快照与最小基线

- [x] 读根/局部 AGENTS、docs/README、主任务最终查询阶段记录与本设计；记录 git status、目标 diff。
  核对四个 action/backup/restore 的 AST 与 design-notes 记录；若发生实质变化，先更新设计对应契约。
- [x] 以下“现有精确节点”均已通过 ast.parse 确认定义名；先运行与当前步骤直接相关的组作基线。
  启用 QT_QPA_PLATFORM=offscreen；使用项目 .venv。只读本草案阶段不执行这些命令。

## 步骤 1：完整 action 服务与 adapter

**Files:** 新 services/apps/actions.py、tests/test_app_actions.py；改 worker 四个 action wrapper，
新增 _report_clear_permission_denied；暂时 `_command_error` 留给尚未迁移的 archives。

**Interfaces:** 精确实现 design 中 command_error/modify_app/launch_app/clear_app/modify_permission；
QueryExecutor、CommandResult 只 TYPE_CHECKING；服务无需新的 result DTO 或 cancel 参数。

- [x] 写新测试 `test_modify_actions_preserve_argv_and_feedback_order`：参数化四动作，断言
  显式 --user、timeout 默认、不传 cancellable；成功 log→done，失败 log→feedback 且无第二 log。
- [x] 写 `test_action_validation_rejects_before_execute`：包名/动作/权限失败命令数为 0，
  校验优先顺序与中文提示固定，Unicode/$/- 合法权限使用 shlex.split 验证是单个字面参数。
- [x] 写 `test_launch_error_output_and_warning_keep_existing_semantics`：非零/零退出 Error 都失败，
  Warning 成功；argv 末尾 2>&1，精确 am start 顺序；无重试。
- [x] 写 `test_clear_denial_logs_before_lazy_hint_callback`：output/error 原序去重，log 完整诊断，
  后调用 permission_denied 一次，无 done；普通失败不调用该 callback，成功保留 stdout。
- [x] 写 `test_command_error_preserves_priority_and_stripping` 与
  `test_action_callback_exception_propagates_without_later_notification`：检查 error→output→fallback，
  log 抛错后无后续 callback。modify 的结果判定仍在 log 后，不提前缓存用于重放。
- [x] 运行新 test_app_actions.py，确认因入口缺失红灯；实现最小服务与四个 wrapper，重跑为绿。
- [x] 运行现有 action/clear/用户节点组，确认真实 worker 的 lazy 翻译与 operation_done 自带
  success feedback 没有被服务再次发送；没有在执行中取消后抹去成功。

## 步骤 2：备份事务整体迁入 archives

**Files:** 新 services/apps/archives.py、tests/test_app_archives.py；改 worker._backup_app；
改 restore_cancellation 中两处 make_archive patch 到 archives owner。

**Interfaces:** backup_app 完整签名见设计；共用 actions.command_error；callbacks 同步就地执行。

- [x] 新增 `test_backup_success_publishes_once_after_all_serial_pulls`：fake pm/pull 写 tmp_path
  所需文件，断言进度顺序、串行命令、ZIP 内容、同目标目录 staging、replace 后才 log→done。
- [x] 新增 `test_backup_rejects_invalid_package_and_failed_or_empty_path_query`：非法包无 progress/
  命令；pm path 失败或空路径只发原 failure、不创建拉取/压缩临时目录，不发 done。
- [x] 新增 `test_backup_pull_failure_is_aggregated_after_remaining_pulls`：首 pull 失败仍执行后续，
  聚合错误仅一次、无 zip/done；failed+最后取消优先报失败，failed+下一 pull 前取消静默返回。
- [x] 新增 `test_backup_cancellation_keeps_phase_specific_feedback`：参数化 progress、pull 间、
  最后 pull、压缩中四位置；前两类不发 aborted info，后两类先 log 后 info；全都无 done。
  progress 取消后 pm path 仍执行但无 pull；旧 ZIP 字节始终不变。
- [x] 新增 `test_backup_apk_count_and_case_rules_are_preserved`：递归 .apk/.APK 都计数，
  expected/found 不符不压缩；paths 不去重，不按名称修复碰撞。
- [x] 新增 `test_backup_exception_scope_and_cleanup_order`：受控 temp context/fake callback
  在拉取阶段、内层 cleanup、外层 cleanup 注入异常，验证设计中的传播/失败转换。
  replace 后内层 cleanup 失败时文件已换、failure 且无 done；外层 cleanup 失败时 done 已发。
- [x] 新增 `test_backup_cancel_callback_error_inside_compression_is_reported_as_failure`：
  压缩后的取消 log/info callback 抛错会进入原 try 的 failure；pull 后同类 callback 抛错传播。
- [x] 运行上述新节点确认红灯；提取完整 with/try/聚合/发布逻辑并接 worker，保持原位置。
- [x] 重跑新归档测试及现有 backup 组；清理所有新临时文件，仅使用 tmp_path，不操作真实保存目录。

## 步骤 3：恢复事务整体迁入 archives

**Files:** 扩展 services/apps/archives.py、tests/test_app_archives.py；改 worker._restore_apps，
新增 _restore_target_user；迁旧 restore_cancellation 的 safe_extract_zip import/patch 到 archives。

**Interfaces:** restore_apps 不接收 worker 或 Signal，只接 confirm_user()->int|None；
adapter 调原 _bind_current_user 后返回当前 user_id。用户政策不复制，不接受新目标自动改绑。

- [x] 新增 `test_restore_uses_safe_extraction_and_exact_split_basename`：小型临时 ZIP，
  ordinary/base.apk 路径误导/split 正例；.APK 被排除；无 APK 为原失败，无 install。
  一条 traversal ZIP 由现有 safe_extract 拒绝，不绕过安全工具或复制它的整套测试。
- [x] 新增 `test_restore_confirms_user_before_every_write_and_accepts_zero`：普通两 APK 每次确认，
  split 一次确认；None 后不 install/不 complete，0 必须实际写 --user 0；无新增用户查询策略。
- [x] 新增 `test_restore_cancellation_preserves_installed_and_completed_counts`：解压后/首安装/
  最后安装/split 后/归档之间参数化；最后成功安装后 installed 和 succeeded 均按原路径增加，
  Restored 日志先于最终 cancel warning；无 done，不回滚已安装。
- [x] 新增 `test_restore_partial_failure_continues_next_archive_without_completion`：失败档后继续下一档；
  ordinary 第一 APK 成功第二失败时 installed=1，succeeded 不增加；摘要级别按成功档数决定。
- [x] 新增 `test_restore_user_probe_cancellation_returns_without_extra_cancel_warning`：confirm_user
  内把 cancelled 置真并返回 None；直接返回，没有补发最终 cancel/incomplete。
- [x] 新增 `test_restore_callback_and_cleanup_exceptions_keep_original_try_scope`：Restored log
  抛错时 succeeded/failed 都增加；temp cleanup 失败前不增加 succeeded；归档前取消 callback
  抛错传播，解压后取消 callback 抛错进入 per-archive failure；except 内 failure 再抛错传播。
- [x] 新增 `test_restore_last_failure_then_cancel_prioritizes_cancel_summary`：先失败反馈后 warning
  cancel，不能再发 incomplete/done。
- [x] 新增 `test_restore_empty_and_all_failed_have_distinct_terminal_states`：空 files 无 callback，
  全失败仍逐档处理，最后 log incomplete→error feedback，不误发 complete/done。
- [x] 运行新节点确认红灯，按设计实现完整计数/try/with/安装；重跑新文件及现有 restore 组。
- [x] 检查全部 `_command_error`/`_safe_pkg` 消费迁出后移除 worker 无用私有实现与导入，
  不新增旧 globals 的动态转发；查询区及 _adb/_bind 保持既有实现。

## 步骤 4：无 Qt 完整执行与独立 review

**Files:** 新 tests/test_app_write_boundary.py；必要时补 tests/test_app_actions.py / test_app_archives.py。
**Interfaces:** 既有 AppManagerWorker 类/Signal/GUI 工厂不变；服务导入和 fake 执行均不依赖 Qt。

- [x] 写 `test_write_services_import_and_execute_without_qt_or_models`：独立子进程在 import 前
  通过 MetaPathFinder 拒绝 PySide6/qfluentwidgets/gui/models/adblab.presentation，导入两服务；
  fake executor 返回结构完整的 success/stdout/output/error，调用四 action 及 backup/restore，
  使用 TemporaryDirectory 的合成文件验证实际成功、取消、失败流程及禁止模块未进入 sys.modules。
  不使用真实 CommandRunner；不得只验证 import 后声称完整事务无 Qt。
- [x] 新测试先红后绿；跑两新服务文件、边界测试和未重复验收的现有精确关联节点。成功后不无故重复。
- [x] 实施 owner 对实际修改 Python 文件运行 Ruff，生产新服务和 worker 跑中文注释检查，记录结果。
- [x] 提交主任务做一次独立 review：比对 try/with/callback/计数和用户命令、私有 patch、取消反馈；
  reviewer 不仅看测试数量，还按原 AST 核对异常范围。review 修复只重跑直接/关联节点。
- [x] 主任务统一 Pyright：`services/apps/actions.py services/apps/archives.py models/app_manager_worker.py`；
  若共享已验收 queries 的协议未改，不额外重跑整个查询套件。新增问题按真实依赖扩大。
- [x] 主任务同步真实职责变化的 ARCHITECTURE/MODULE_MAP，再运行 check_doc_links 与 git diff --check。
- [x] 主任务独立 child env 设置临时 LOCALAPPDATA/XDG_CONFIG_HOME、offscreen，核对 legacy
  读取路径隔离后运行一次 `.\.venv\Scripts\python.exe main.py --self-check packaging`。
  父环境和真实配置不改；明确只是源码自检，不执行 PyInstaller 构建/设备/真实恢复。

## 已经 AST 确认的现有精确节点与命令

下列各组按步骤执行一次；此前已经通过且无新变化的组不再重复。新测试文件名是本计划拟新增。

```powershell
# 动作直接与准入：不执行整个 phase0 / clear / model_apps 文件
.\.venv\Scripts\python.exe -m pytest -q tests/test_phase0_failure_semantics.py::test_app_manager_simple_command_failure_never_reports_success tests/test_phase0_failure_semantics.py::test_app_manager_pre_aborted_worker_does_not_run_dangerous_command tests/test_clear_app_data.py::test_clear_worker_reports_actionable_denial_but_logs_complete_diagnostic tests/test_model_apps.py::test_app_manager_write_commands_keep_existing_completion_contract
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_worker_users.py::test_mutations_use_the_loaded_user_after_revalidation tests/test_app_manager_worker_users.py::test_user_change_rejects_old_snapshot_before_operation tests/test_app_manager_worker_users.py::test_mutation_without_valid_loaded_user_never_queries_or_writes tests/test_app_manager_worker_users.py::test_launch_uses_explicit_user_instead_of_implicit_monkey_target tests/test_app_manager_worker_users.py::test_invalid_permission_is_not_sent_to_device tests/test_app_manager_worker_users.py::test_custom_permission_name_reaches_device_as_one_literal_argument tests/test_app_manager_worker_users.py::test_two_device_workers_keep_separate_user_targets tests/test_app_manager_worker_users.py::test_launch_error_output_never_reports_success tests/test_app_manager_worker_users.py::test_launch_zero_exit_stderr_failure_is_retained_at_command_boundary tests/test_app_manager_worker_users.py::test_launch_existing_task_warning_still_reports_success
# backup 所有直接取消/发布场景
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_restore_cancellation.py::test_backup_cancellation_does_not_start_remaining_pulls tests/test_app_manager_restore_cancellation.py::test_backup_last_pull_cancellation_preserves_old_zip_and_emits_no_success tests/test_app_manager_restore_cancellation.py::test_backup_cancel_during_compression_preserves_old_zip tests/test_phase0_failure_semantics.py::test_app_manager_backup_pull_failure_does_not_create_success_zip tests/test_phase0_failure_semantics.py::test_app_manager_backup_all_pulls_success_creates_zip_and_completion
# restore 的选择/取消/用户/部分失败与实际 Signal
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_restore_cancellation.py::test_restore_chooses_split_mode_only_from_exact_apk_basename tests/test_app_manager_restore_cancellation.py::test_restore_cancellation_stops_new_installs_and_success tests/test_app_manager_worker_users.py::test_restore_targets_loaded_user_and_stops_after_user_changes tests/test_phase0_failure_semantics.py::test_app_manager_restore_partial_failure_does_not_emit_completion tests/test_phase0_failure_semantics.py::test_app_manager_restore_all_success_emits_completion_once
# 仅扩大到调用这些 worker 的单个忙碌预算节点
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_batch_budget.py::test_backup_and_restore_share_busy_budget
```

完整新增服务测试命令为 `.\.venv\Scripts\python.exe -m pytest -q tests/test_app_actions.py tests/test_app_archives.py tests/test_app_write_boundary.py`。
四类已有混合套件不整文件执行；不新增全量要求，不把用户既有工作树改动全部归为本轮。

## 完成报告

分别报告动作/归档提取、测试实际命令及结果、独立 review 处理、静态/源码自检、未验证实机与
产物范围。不把“worker 业务已抽出”表述为已完成 presentation 目录归位；后者另行设计。
以上保留最初设计步骤；实际执行与验收结果见下文。

## 主任务预审与执行裁定


2026-10-24：PASS，可在当前 Controller/设备发现批次收尾后取得最新快照与直接基线并实施。
已逐项对照 worker 当前六事务、查询服务已验收边界、设计/计划及节点证据；用户已有全项目持续重构授权，无须再次批准。

- 一个 owner 独占 worker、两服务、三个新增测试与 restore_cancellation 的三处私有依赖迁移。
  查询服务、GUI、用户政策、执行协议与发布流程不修改。
- action 同步通知、备份内外临时目录、恢复逐写用户核验及异常计数位置是兼容条件；不借提取修正罕见旧语义。
- implementation 前保存当前 worker；验收需逐方法确认 run、取消、_adb、_read/_bind 与查询区正文不变。
  旧 _command_error/_safe_pkg 只在确认全部消费者迁出后清理。不能以整个脏工作树对 HEAD 的差异作为本轮差异。
- 新服务先取得缺少入口导致的 RED，再完整 fake 执行；旧行为表征先验证旧代码，不能因猜测预期失败而改生产。
  最终按 nodeid 去重计数，阶段内不同组或 review 重验不得相加。
- root 负责三份生产模块类型、正式文档、整合审阅；package self-check 使用现有已验证 wrapper，隔离
  LOCALAPPDATA、APPDATA、XDG_CONFIG_HOME、XDG_CACHE_HOME、XDG_DATA_HOME、MOBILEPERF_LOG_DIR 全部入口，
  不仅草案简写的两项。记录实际退出码、临时 probe 是否残留与清理验证。
- 本预审不代表测试、真实 Android、桌面或冻结产物验收。尚未运行本阶段基线或修改生产。


## 前置基线与执行状态（2026-10-24）

24个精确旧node展开50passed，真实exit0；旧worker单生产类型0errors/0warnings。直接验证为4动作、备份与恢复，关联仅单worker忙碌预算。范围3生产4测试；root集中文档/类型/自检/集成。
前一批媒体/设备发现已最终审阅通过，当前按独占owner并行实施；无须重复用户确认。

## 实施验证记录（2026-10-24）

七代码/测试路径已冻结。四动作与备份/恢复完整事务归actions/archives，Qt worker保留run、用户准入、
Signal和延迟翻译。22个未动方法逐源码一致，七迁移方法经明确参数/回调映射后AST正文一致。
旧恢复测试仅一import和三patch路径变化；查询区、执行和用户政策未改。旧私有错误/helper无消费者后清理。
旧worker上77个新行为表征通过，新服务缺失RED明确；最终新三文件78通过，旧24节点加单busy节点展开52通过，
合计130不同用例，0skip/0fail。两次错误样例分别为权限分段不允许$开头、Windows大小写文件同名，均只改样例。
独立子进程阻断Qt/GUI/models后完整fake执行动作与归档成功/失败/取消，六数据环境变量隔离。
root三生产Pyright无诊断；owner七文件Ruff/文本/差异、三生产中文注释及parity通过。
精确命令、真实退出码、唯一nodeids与hash见忽略目录owner-report.md和对应证据；最终综合审阅已通过。

统一源码packaging使用六个数据环境变量隔离到已校验临时目录，exit0且无.self_check残留；
这包含工具执行和临时探针写删，不是完全只读或冻结产物验收。既有UI-09/UI-10未修复或重验，未触发全量pytest。

## 最终审阅与交付

两个任务Spec/Quality及最终综合审阅均PASS，无P0–P3 findings。130+124=254个不同用例通过，
另23项原POSIX平台跳过；5生产文件类型无诊断，84文档链接/frontmatter、824源码文本及diff通过。
独立核验23固定路径，包括13代码/测试和10文档；244前置路径中23授权变化、221未变。
原integration-hashes保留，状态收尾后另存delivery-hashes；未重复已通过测试/类型/源码自检。
既有UI-09/UI-10、实机/真实桌面/冻结产物仍未验收；全项目持续目标进入Qt worker目录归位。
