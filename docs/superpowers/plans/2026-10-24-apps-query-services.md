# AppManager 查询服务提取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. 主任务选择执行方式；同一个 worker 由单一实施 owner 顺序修改。本草案不授权提交。

**Goal:** 把包解析、用户核验和完整只读查询从 AppManagerWorker 抽为可独立验证的服务，保持行为。

**Architecture:** package_details 拥有纯值解析；queries 拥有查询事务和策略。worker 原位显式注入执行、取消、预算、时钟、loader，并保留信号及写操作/归档。

**Tech Stack:** Python 3.11、PySide6、现有 pytest；不增依赖。

**Spec:** [设计](../specs/2026-10-24-apps-query-services-design.md)。设计中的函数签名、输出载荷、文案、时序均为本计划输入。

## Global Constraints

- 先读根与局部 AGENTS、docs/README、当前目标 diff；保留已有脏工作树。只处理本轮边界。
- 新服务不得导入 Qt/GUI/models/presentation，不直接执行 CommandRunner，不传 worker/self。
- 原包名、marker、fallback、用户准入、信号顺序不变；三个 batch 不新增 am get-current-user。
- models worker 原位；actions/archives/file operations、adapter 归位与 GUI 工厂不在本批。
- 不改依赖、CI、版本、用户数据格式；生产注释中文。无授权不 commit/push；本计划不含提交步骤。
- 实施 owner 仅直接/关联测试；主任务统一 Pyright、packaging 和 docs。没有全量触发条件不跑全量。

## Review Focus

- 完整空片段和被截断片段分流，前者不补查、后者只用余量（Task 1/2）。
- deadline 恰好耗尽但命令成功仍交付该条，下一条停止（Task 2）。
- 同步 Signal 回调取消发生在 user/details/metadata 条目之间，保持原发布门禁（Task 3）。
- batch 用户例外与无效 loaded user 准入、restore 再校验共用政策（Task 2/3）。
- 服务 import 无 Qt 不等于真实 executor 无 Qt；边界测试必须实际调用注入 fake 的完整服务（Task 3）。

## Task 1：冻结并提取纯解析

**Files:** 新 `services/apps/package_details.py`、`tests/test_app_package_details.py`；修改
`models/app_manager_worker.py` 的纯解析段。暂不改完整查询循环。

**Interfaces:** 产生设计中的 InstalledApp/PackageDetail/AppDetails 与六个纯函数；
worker `_safe_pkg` 同对象 alias，`_emit_package_detail/_emit_app_details` 保留现有调用方式。

- [x] 核对目标现有 diff，记录本轮边界；运行下面现有解析/批量/snapshot 代表节点作为基线，
  不执行混合文件全量。基线若失败，先定位是否既有，禁止删除断言。
- [x] 新增 `test_package_token_preserves_legacy_acceptance`：None/空/斜杠/空白拒绝，
  `android`、`com.Example_APP`、`.` 按既有规则接纳。
- [x] 新增 `test_sections_require_matching_end_and_keep_legacy_marker_rules`：完整/截断/错 end/
  重复 begin、相邻索引、marker 周围空白、正文行空白和 Unicode 值保持。
- [x] 新增 `test_batch_and_dialog_keep_distinct_label_and_version_defaults`：无 label 的
  com.example.myAPP → batch myAPP /详情 Myapp；无 versionName 时 batch 空版本、详情
  `? (code 7)`；单字符 label 不意外变为可匹配；字段 key 恰好六个，Path 尾空白保持。
- [x] 新增 `test_installed_rows_preserve_equals_paths_types_and_disabled_states`：路径含多个 =、
  四种分类优先级、重复行、空包、无 = 行、disabled 集合和名称下划线替换。
- [x] 运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_app_package_details.py`；
  预期新模块未实现导致明确 import/函数缺失的红灯，记录原因。
- [x] 实现冻结纯接口并接入 worker 解析 wrapper，不改变命令执行；移除仅重复的正则主体。
- [x] 重跑新测试及本任务现有节点，预期通过；不扩大到整份 UI 文件。

Task 1 现有节点（源码名称已核对）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_model_apps.py::test_app_manager_worker_load_detail_batch_uses_single_batched_shell tests/test_model_apps.py::test_app_snapshot_emits_details_and_permissions_from_one_query tests/test_model_apps.py::test_app_detail_complete_missing_package_section_is_not_retried_or_cached
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_visual.py::test_table_app_labels_render_on_one_line_without_losing_original_text
```

视觉 `_emit_package_detail` 消费位于 `tests/test_app_manager_visual.py` 约 670-715 行；
只运行该节点的全部现有参数，不猜测参数 ID、不执行整文件。

## Task 2：提取完整查询并保留窄适配

**Files:** 新 `services/apps/queries.py`、`tests/test_app_queries.py`；修改
`models/app_manager_worker.py` 对应 run/用户/list/detail/snapshot/metadata 方法。

**Interfaces:** 消费 Task 1 六个解析函数；产生设计中 QueryError、QueryExecutor、回调别名及
八个公开查询/用户函数。run 仍拥有 operation 分派；服务使用 explicit execute/cancelled/
query_budget/clock/metadata_loader，绝无隐式真实设备默认值。

- [x] 新增身份测试 `test_loaded_user_policy_rejects_bool_and_unknown_without_execution`、
  `test_current_user_parsing_never_guesses_zero`、`test_bind_keeps_expected_user_or_reports_change`：
  精确断言 invalid/unknown/changed 三种文案及取消不报告错误，callback 只读一次。
- [x] 新增列表/快照测试 `test_list_requires_both_queries_for_one_user`、
  `test_list_failure_and_cancel_never_return_partial_rows`、
  `test_snapshot_reads_once_and_rejects_missing_package`：检查完整 argv、cancellable、默认预算、
  成功空列表 [] 与取消 None，错误与缺包不返回可用快照。
- [x] 新增批量测试 `test_detail_fallback_shares_deadline`：clock 从 100，query_budget=5，
  batch 消耗 4.5 后无 marker，第一 fallback 用 0.5 秒并成功，timeouts 恰好 [5.0, 0.5]，
  只交付第一包，无第二 fallback；成功到 deadline 的第一包不丢弃。
- [x] 新增 `test_detail_default_budget_uses_original_package_count`：原始 3 包含无效包、budget=5，
  初始 batch timeout=6；重复合法包不去重，非法包日志只一次。
- [x] 新增 `test_detail_complete_missing_sections_are_not_retried` 和
  `test_detail_failure_cancel_and_expiry_stop_retries`：完整无版本、不完整、命令失败、
  batch/逐包中取消与过期分别验证命令数、结果及日志；已有成功条保留。
- [x] 新增 `test_metadata_fallback_uses_only_explicit_unsupported_and_remaining_time`：
  loader 后耗时 12→仅 18 秒；耗时 31→零 fallback；坏响应/非 unsupported 空值/
  unsupported 且有记录均零 fallback；metadata 成功不调用 query_budget。
- [x] 新增 `test_metadata_filters_user_per_record_and_cancels_between_callbacks`：错用户发
  failure 后继续正确用户，None expected_user 不取缺失 user_id 字段，回调取消后不交付下一条；
  只按原 records 数量判定缺失日志，不按接受条数改变它。
- [x] 运行 `.\.venv\Scripts\python.exe -m pytest -q tests/test_app_queries.py` 确认红灯。
  fake 使用真实 CommandResult 或字段契约完整的静态值，不执行真实 ADB。
- [x] 实现 queries 全部接口和私有一次 batch 协作者；预算和剩余包循环一起移动。
  不留 worker 副本，不把 metadata fallback 回调交回 worker 重启另一套事务。
- [x] worker 接入：初始身份校验委托，_read/_bind 保留明确 callable；保留 _adb；
  loader/monotonic 在调用点传入；发布适配只映射原信号；原非查询代码不动。
- [x] 列表 broad catch 保留原范围，新增专门 QueryError 分支以避免错误多出 `Error:` 前缀；
  snapshot/bind 只处理预期 QueryError，其余异常不新增吞错。
- [x] 确认旧私有 batch-once/has/split 实际引用消失后移除重复内部实现；保留有直接消费者的
  `_emit_package_detail`，不删除有效测试。重跑 Task 1+2 新文件，预期通过。
- [x] 运行精确 batch/快照关联节点（见 Task 3 清单），失败仅修本轮根因并重跑受影响集。

## Task 3：adapter 契约、导入边界与主任务交接

**Files:** 新 `tests/test_app_query_boundary.py`；按需增补
`tests/test_app_metadata_worker.py`、`tests/test_app_manager_worker_users.py` 的直接 adapter 节点。
不改变 conftest、不搬整份旧测试、不更改 GUI。

**Interfaces:** 公开 AppManagerWorker 与信号不变；旧模块 `_adb/_read_current_user/monotonic/
query_timeout/load_app_metadata` 替换入口仍由显式注入到达实际 service；真实 Signal 仍在 worker。

- [x] 增补 `test_query_signal_order_and_cancellation_boundaries`，在真实 Signal 观察
  user→apps、user→details→permissions；user 回调取消时列表仍按原两信号门禁发 apps，
  snapshot 不发详情/权限；details 回调取消时不发 permissions。
- [x] 刻画 metadata 身份读取时与 detail 解析期间触发取消的旧行为：本条仍按旧时点交付，后续条目停止。
  取消政策属于服务；纯发布 adapter 不新增检查，detail 仍在解析前保留旧 `_emit_package_detail` 的门禁。
- [x] 增补 `test_batch_operations_skip_current_user_query` 参数化三种 batch：通过真实 run
  与 fake loader/icon/executor 断言没有 am get-current-user；无效显式 user_id 仍在准入处拒绝。
- [x] 新增独立解释器边界测试，在 import 前安装 MetaPathFinder 拒绝 PySide6/qfluentwidgets/
  gui/models/adblab.presentation；导入新两模块并用 fake executor、时钟和 metadata loader
  执行列表/详情/快照/metadata fallback。子进程不用 tests.conftest，不生成真实设备命令。
  断言禁用模块不在 sys.modules；真实 executor/loader 不纳入此无 Qt 保证。
- [x] 先运行新测试确认尚未实现的契约缺失会失败，再完成必要的 adapter 接缝；
  已满足的既有行为只补特征测试，不人为破坏代码制造红灯。
- [x] 运行以下直接/关联选择，QT_QPA_PLATFORM=offscreen；现有 user 文件是共同身份政策的
  直接调用者，metadata 文件是共同 deadline/loader 接缝，允许整文件。test_model_apps 是混合
  套件，只跑列出的节点；不把其他此前阶段纳入本轮。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_package_details.py tests/test_app_queries.py tests/test_app_query_boundary.py tests/test_app_metadata_worker.py tests/test_app_manager_worker_users.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_model_apps.py::test_app_manager_worker_load_detail_batch_uses_single_batched_shell tests/test_model_apps.py::test_app_detail_batch_failed_command_does_not_fallback_or_publish_empty_details tests/test_model_apps.py::test_app_detail_batch_parse_fallback_uses_remaining_budget_and_stops_at_deadline tests/test_model_apps.py::test_app_detail_batch_keeps_completed_sections_and_only_retries_unfinished_package tests/test_model_apps.py::test_app_detail_complete_missing_package_section_is_not_retried_or_cached tests/test_model_apps.py::test_app_detail_query_failure_or_missing_package_does_not_publish_success tests/test_model_apps.py::test_app_snapshot_emits_details_and_permissions_from_one_query tests/test_model_apps.py::test_app_snapshot_discards_both_parts_when_cancelled_during_read tests/test_model_apps.py::test_app_manager_read_queries_cancel_in_flight_without_publishing_results tests/test_model_apps.py::test_app_manager_cancelled_disabled_query_does_not_publish_partial_app_states
```

- [x] 实施 owner 对实际变更 Python 文件运行 Ruff，对新两服务/worker 运行中文注释检查。
  不跑整仓 Ruff。保存实际命令、结果、已通过范围和未验证项后交接主任务。
- [x] 主任务审核 diff：确认 actions/archives 没有语义变化，旧 patch 仍作用真正 owner，
  纯函数没有更严格校验/不同默认值，metadata/列表/快照信号级别及顺序保持。
- [x] 主任务仅一次运行：

```powershell
.\.venv\Scripts\python.exe -m pyright services/apps/package_details.py services/apps/queries.py models/app_manager_worker.py
.\.venv\Scripts\python.exe scripts/check_comment_language.py services/apps/package_details.py services/apps/queries.py models/app_manager_worker.py
git diff --check
```

- [x] 主任务同步 ARCHITECTURE/MODULE_MAP 中实际变化的服务归属后运行 check_doc_links；
  按需要更新 BUSINESS_FLOW 仅当当前事实描述确实变化，不制造新的行为承诺。
- [x] 主任务在独立子进程/临时环境中运行一次源码 `main.py --self-check packaging`：使用
  Python 标准库 TemporaryDirectory，复制 os.environ，在 child env 设置 LOCALAPPDATA 和
  XDG_CONFIG_HOME 为新临时根，QT_QPA_PLATFORM=offscreen，再 subprocess.run 同一 .venv
  解释器和参数、cwd 项目根；保持父进程环境不变，退出后由 TemporaryDirectory 清理。
  开始前核对自检路径没有读取/迁移真实 legacy 配置；若会触及则再隔离实际边界，不直接运行。
- [x] 记录此为源码工具/资源自检，不能证明 frozen archive 已收集服务；不运行 PyInstaller
  构建、设备/外网或真实用户配置。没有全量触发条件就结束，不追加整仓测试。

## 自检与交接

设计的解析、身份、事务、预算、回调、private patch、导入边界分别映射 Task 1/2/3；
没有运行期新 DTO 或未定义的共享服务。当前只读草案阶段不执行以上验证。
实施完成时报告新增文件和职责、真实运行命令、失败/跳过/未跑边界；actions/archives 和
Qt adapter 目录归位仍为后续阶段，不能宣称 AppManagerWorker 已成为纯 Qt adapter。

## 主任务预审与执行裁定


2026-10-24，root。已读设计、计划、notes及现有worker查询/身份/批量实现，设计PASS，执行时以下裁定优先。

- 同一owner完整持有worker与两服务、三新测试和两个可追加的旧测试；所有任务完成后统一独立审阅，不逐步重复review。
- 保留取消检查的实际位置与次数效果。列表在解析完成后仍先记录Loaded，再执行原单一门禁，user与apps之间无新增门禁；服务不能因更严格取消而提前省略已有日志。
- QueryError仅表示原已处理错误；列表原try范围和回调异常处理保持，snapshot/bind不新增broad catch。不要引入通用事件系统。
- 新int注解不授权额外运行时校验；private直接调用过去允许None的路径不额外拒绝，run继续拥有既有准入。
- 所有原模块monotonic/query_timeout/load_app_metadata及实例_adb/_read_current_user接缝晚绑定显式注入；write/restore继续共享身份政策。
- metadata/deadline/逐包结果与取消以现有实现为准，成功恰好到deadline仍发布。既有完整但无版本片段不fallback。
- root先跑精确代表节点与users/metadata直接基线、现存worker类型基线；owner复用基线，禁止重复未变化集合。
- root集中最终类型、正式docs与隔离packaging。子进程所有用户数据环境按上一阶段已核验包装脚本隔离，不只设置两个变量；临时清理先确认路径。
- 不改GUI、服务聚合入口、conftest、写操作及归档主体；旧重复私有函数仅在实际调用迁出且核实无其他消费者后移除。
- 保留同一worker类与所有信号；当前只保证新服务及fake注入无需Qt，不扩大到真实CommandRunner/真实设备无Qt承诺。

当前仅预审通过，未实施；正式发布与before证据由root完成。

root集中Pyright与源码packaging；owner不重复执行这两项。最终自检子进程的LOCALAPPDATA、APPDATA、
XDG_CONFIG_HOME/XDG_CACHE_HOME/XDG_DATA_HOME和MOBILEPERF_LOG_DIR均指向经边界校验的临时目录。

## 实施验证记录（2026-10-24）

八代码/测试路径已冻结：纯解析与完整查询事务归services/apps，旧worker保留类、信号及显式注入接缝。
10个未触及方法完整源文/AST、11个Signal声明与写操作/归档整段均保真，旧两测试文件仅追加契约。
迁移后去重151实例：当前直接集合126（初次122加后补4项回归）、精确模型关联21、视觉参数4。
其中初次122、关联21已有通过证据；新增列表异常范围1与取消时点3分别失败→通过，最终受影响69项通过。
69与上述集合有交集，不重复相加；新parser/queries模块缺失各有真实结构红灯。
旧源码探针确认身份读取或解析期间取消仍发布当前条，后续停止；服务保留原loop/preparse门禁，
纯Qt发布不再次检查。列表QueryError在原broad try内部处理，报告回调异常仍沿原路径。
独立解释器阻断Qt/GUI/models后实际执行fake查询，未使用真实设备；不推广成真实执行器无Qt保证。
root三生产Pyright无错误/警告，owner八文件Ruff、三生产中文注释、文本/空白及限定diff通过。
独立任务审阅与最终集成另记，原方法/错误/预算与信号审阅均以本阶段before为准，不使用HEAD覆盖前置资产。
与Home统一源码packaging采用临时数据环境，exit0；不代表冻结构建、实机多用户/OEM/取消行为。
未跑全量、真实用户数据、真实设备/外网或完整构建。精确命令、日志与退出码见本阶段owner-delivery.md。

## 最终审阅与交付

2026-10-24，独立任务与最终综合审阅均PASS，无P0–P3 findings。两阶段211个不同用例通过，
6生产文件类型无诊断，76文档链接/frontmatter、801源码文本与diff检查通过。最终审阅独立核对
22固定路径、12代码/测试路径与10文档增量；208前置路径中22授权变化、186未变，无范围外漂移。
原integration-hashes保留，收尾后另存delivery-hashes；未重跑已通过测试/类型/自检。
已知UI-09/UI-10未修复或重验，实机/真实桌面/冻结产物仍未验收；全项目后续阶段继续推进。
