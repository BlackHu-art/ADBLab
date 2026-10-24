# 文件事务纯服务实施计划

日期：2026-10-24。实施与最终独立审阅均已完成；下文保留原步骤，实际结果见末尾验收记录。范围与接口以[正式设计](../specs/2026-10-24-file-operation-services-design.md)为准；初始静态审计记录保留于忽略工作区。

## 执行规则

实施前重新 `git status --short`、检查目标 diff，与 root 确认当前文件 owner 没有并行冲突；已有脏工作树不回退、不暂存、不提交。原设计任务仅作静态核实；后续实施与验证结果已记录在末尾。正式实施只触及两个生产文件、两个新增专用测试文件、两个旧测试的必要 patch；主任务统一 docs、类型、packaging，不重复其他批次门禁。

先保留一份实施前 `models/file_explorer_worker.py` 源码快照于本忽略目录，供 AST/源码 parity；不可用 HEAD 代替当前脏工作树基线。AST 读取使用 Python 标准库，不导入目标模块。当前读取基线 SHA256 为 `0FF311674C636AFDB0AB2699F79B47D41C131195A05EA1C59B49C69937E1AB09`，只标识本次审计快照，若 root 另有修改则更新。

## 第一步：取得直接基线并固定有风险的旧行为

说明“本轮修改边界为四个同步文件事务，直接测试覆盖协议/取消/清理/信号，关联节点覆盖页面收尾与构造参数”，再运行下方已有直接节点。不要整跑混合的 test_file_explorer_text.py、test_file_listing_security.py、test_file_explorer_visual.py。

新增 `tests/test_file_operation_adapters.py`，先在旧 worker 上建立以下行为表征（应先绿，若红先判断现有事实，不把修 bug 混进抽取）：

- `test_constructor_preserves_marker_and_command_timing`：Directory 非法路径构造不立即建命令，run 才给原失败；TextRead 命令 builder 抛出的异常在构造期原样传播；marker 为 bytes 且 args 在 run 前具有 head/printf，run 不再生成 marker；构造后、run 前 patch CommandRunner 仍生效。
- `test_decoded_direct_cancel_still_publishes_raw_inside_capture_scope`：Qt DirectConnection 接收 decoded 时断言 flag=True 并 abort；记录 decoded/raw 顺序，raw 仍出现；随后清理；不得在 worker 新增取消 gate。
- `test_four_workers_keep_event_only_cancellation`：四类使用 requestInterruption 而不置 Event 仍按旧规则执行；Event 已置位则不执行/发结果。纯 fake 读写目标，Local 使用 tmp_path。ADBWorker 的联合规则只做源码 parity，不改成这个规则。
- `test_worker_signals_keep_payloads_and_decoded_flag`：目录 listing、正文原始 bytes、保存 str 与 bool、decoded 值和标志保留；失败和不可解码路径保留。

这些是既有行为表征，不宣称“旧代码失败”的回归。真正用于提取的红测试见下一步，失败原因应是新边界缺失或 Qt 依赖，不能凭任何异常当作红灯。

## 第二步：新增服务测试，再整体搬迁事务

创建 `tests/test_file_operations.py`，新服务尚未存在时先运行 `test_pure_service_import_and_fake_transactions_without_qt`，预期因明确缺失 services.file_operations 失败；实现后同一节点必须完成四个事务，不能止于 import 成功。

独立子进程用 import hook 拒绝 PySide6/PyQt5/PyQt6/qfluentwidgets、gui、models、adblab.presentation、core.log_service（包括子模块），先检查它们没有预载入。用父进程传入的临时目录和隔离数据环境；只加仓库到导入路径，不加载应用入口。使用 CommandResult 与 fake capture/run，直接执行目录读取、正文读取、root 远端保存、同目录本地保存；capture 写带完整 marker 的 bytes、resolve 写 framed target、run 只记录参数，绝不执行命令。真实 runner 的 run/run_to_file 可设为触发即失败，确认新服务确实使用注入项。断言命令顺序、原始 bytes、结果、目录销毁、逆序非取消 cleanup、无 Qt 导入。不能仅凭 AST 没有 PySide6 名称宣称无 Qt。

其余新节点均在同一专用文件，以假执行器/局部 tempfile 为边界：

| 新节点 | 可观察断言，必须防止的回归 |
| --- | --- |
| `test_directory_success_publishes_after_temporary_cleanup` | 回调发生时捕获文件已不存在；raw marker/上限不改变 |
| `test_directory_failure_precedes_cleanup_and_preserves_cleanup_error` | 命令失败回调发生时文件仍在；清理包装器真正清理后抛 OSError，按旧规则收到第二固定错误；取消可抑制第二条 |
| `test_text_callbacks_precede_cleanup_and_preserve_synchronous_cancel` | decoded->raw->cleanup；decoded 设置取消后 raw 仍有；未取消的 cleanup OSError 在成功后追加错误 |
| `test_text_read_preserves_marker_read_bound_and_decode_failure` | 以记录 read(n) 的窄文件假对象/包装器断言 n=limit+1+marker 长；无 marker 拒绝；decode 原异常仍给 raw；结果 error 不按 Directory 分类 |
| `test_resolve_target_cleans_before_parse_and_wraps_cancel` | tempfile 清理后解析；8192/8193、前后框、UTF-8、绝对路径、空白与 NUL/CR/LF；InterruptedError cause 被包装且外层取消静默 |
| `test_remote_save_registers_before_prepare_and_cleans_in_reverse` | use_root 两态，prepare 取消/失败仍 cleanup 已登记目标；失败阶段矩阵 resolve/prepare/push/publish；device 固定、正文不进 argv、timeout30/120/15、cleanup cancelled=None |
| `test_remote_cleanup_warning_preserves_result_and_exception_boundary` | 返回失败仅固定 warning 且原 OK 不变；cleanup 或 warning 抛异常原样传播，不能继续新清理或伪造终态；主体非 OSError 可先在 finally 发布再传播，单独表征不修复 |
| `test_local_save_preserves_replace_cleanup_and_error_precedence` | 同目录 mkstemp、取消保留旧 bytes、replace 后 unlink、unlink 失败补 error、已有 error 优先、终态在 finally 中 |

按 design 中五个服务函数与两个私有辅助移入完整事务。只做 self 属性参数化、执行器注入、emit 替换同步回调、LogService 替换 warning 的必要结构改写；保留 try/except/with/finally 嵌套，不提取一个“统一失败/完成”帮助器。`text_read_arguments` 原样复用 explorer_service 构造器，在 worker 构造期调用。

适配器 run 仅转交 snapshot 字段/执行/取消/值回调；decoded 适配方法先置 flag 再 emit；warning 适配方法在需要时才调用 LogService().log。不要把日志对象构造提前到 worker ctor/run 无条件路径。移除旧 TextSave `_resolve_target/_shell`，不用兼容 wrapper 继续暴露业务实现。

更新三个实际私有 patch 位置：

1. listing security 的 TemporaryDirectory patch 改 service owner。
2. text cleanup failure 节点的两个 worker 私有方法 patch 改 `_resolve_text_target/_text_shell`，fake 签名加入 device/注入参数；保持断言和 worker 调用。
3. text 本地异步保存节点的 os.replace 取值与 patch 改 service owner。

其他 CommandRunner patches 继续原样通过 worker 注入；marker、args、GUI/信号消费者不改。

## 第三步：直接与关联验证

PowerShell 基础命令为 `.\.venv\Scripts\python.exe -m pytest -q <nodes>`。需 Qt 的节点先设 `$env:QT_QPA_PLATFORM = "offscreen"`。执行者应使用项目既有临时数据环境隔离约定；不能写真实用户配置/日志。

直接：完整运行新增的两个专用文件，然后只选择下列现有节点；节点名已从当前 AST 核实，省略参数后缀会保留其全部参数矩阵。

`tests/test_file_explorer_text.py`：

- `test_text_reader_preserves_raw_bytes_and_removes_local_temporary_file`
- `test_text_reader_preserves_mixed_newlines_on_legacy_shell`
- `test_save_uses_bounded_arguments_and_cleans_only_owned_staging`
- `test_cancel_during_remote_reservation_still_attempts_owned_cleanup`
- `test_target_resolution_failure_stops_before_staging_and_cleans_capture`
- `test_text_reader_failed_or_cancelled_capture_discards_output_and_cleans`
- `test_text_reader_rejects_success_status_without_remote_completion`
- `test_local_save_preserves_bytes_and_cancellation_preserves_old_file`
- `test_text_save_rejects_unrepresentable_target_without_touching_similar_file`
- `test_text_save_cleanup_failure_keeps_success_result`
- `test_text_save_preserves_unicode_and_trailing_spaces_in_link_target`

`tests/test_file_listing_security.py`：

- `test_directory_reader_keeps_protocol_and_link_bytes_on_legacy_transport`
- `test_directory_reader_reports_safe_failure_category`
- `test_directory_worker_reads_raw_names_and_links_without_text_normalization`
- `test_worker_rejects_names_that_could_become_another_existing_file`
- `test_directory_worker_failure_or_cancel_never_delivers_usable_rows`

关联范围因服务仍经原 worker 驱动页面，选择关闭/迟到/保存快照与 ctor args，避免扩大到传输或其他 feature 的完整大文件：

- `tests/test_file_explorer_text.py::test_page_reads_raw_text_on_worker_and_discards_late_preview`
- `tests/test_file_explorer_text.py::test_context_change_cancels_loading_text_without_stuck_spinner`
- `tests/test_file_explorer_text.py::test_save_deduplicates_clicks_and_does_not_change_new_preview`
- `tests/test_file_explorer_text.py::test_cancelled_save_waits_for_cleanup_without_publishing`
- `tests/test_file_explorer_text.py::test_local_save_runs_off_gui_and_preserves_preview_bytes`
- `tests/test_file_listing_security.py::test_refresh_preserves_directory_identity_and_rejects_legacy_text_results`
- `tests/test_file_listing_security.py::test_closing_directory_reader_cancels_and_waits_without_delivering_late_rows`
- `tests/test_file_explorer_visual.py::test_file_double_click_menu_reaches_transfer_or_inline_preview`

Windows 上 local_shell 的既有 POSIX skip 保留并明确报告。现有 `test_real_shell_publish_preserves_link_and_target_permissions` / `test_real_shell_cleanup_refuses_unowned_directory` 是原命令构造器契约，不是本批强制扩大项；仅构造器、命令内容或异常证据显示受影响才追加。parser/TextPreview 纯函数实现不变，不无条件重跑全部纯函数测试。

## 第四步：源码 parity 与 root 集成

1. 对基线/现状 AST：ADBWorker、TransferWorker 两个 ClassDef（忽略行号）逐节点完全相等；六类构造签名/Signal 赋值保持；Directory/Text marker 构造顺序不变；TextRead command 表达式搬到 builder 仅表达式位置变化，仍在 super 前调用。不要把整个 worker 文件相等作为目标。
2. 六业务方法（四 run 加原 TextSave 两 helper）逐一对照新函数；列出允许替换表：self字段->同义实参、self._aborted.is_set->cancelled、CommandRunner调用->run/capture、result_ready.emit->publish、decoded flag/signal->decoded、LogService调用->warning。循环次序、read(n)、命令 helper 参数、timeout、异常类型/文本与上下文位置均不变；不忽略 finally 中 publish。
3. 新模块只使用旧 explorer_service 函数；检查 import graph 未反向依赖 models/gui/log；全仓搜索旧 `_resolve_target/_shell` 消费、旧 tempfile/replace patch 不遗漏。`os` 仍供 TransferWorker 用，`uuid` 仍供 marker 用，避免误删。
4. root 对两个生产文件、四个测试文件执行 Ruff；对改动生产文件执行 source-text/中文注释检查与 `git diff --check`。root 统一 Pyright `services/file_operations.py models/file_explorer_worker.py`（必要时扩大既有 GUI 具体消费者），不改类型标准，不用 ignore 掩盖回调不匹配。
5. 新静态 import 应可被当前 PyInstaller 收集；本阶段不改 spec/hook。root 统一在隔离临时用户数据环境运行 `main.py --self-check packaging`，按本轮实际 import 边界记录结果；不运行完整 PyInstaller、不宣称产物已验证。
6. root 根据事实更新 MODULE_MAP/必要架构说明，精简反映服务所有权、旧 worker 原位，不重复用户流程。只在实际更新正式 docs 后跑 doc links/frontmatter。设计 agent 不接管这些写入。

通过条件：新纯服务导入与全部 fake 路径可执行；原协议/发布/取消/cleanup 断言保持；旧 worker 类和公开构造/信号兼容；无额外线程/进程/用户数据入口。失败须归因到本轮、既有问题或环境限制；未运行不是通过。

## 主任务预审与执行裁定


2026-10-24：PASS，可与应用动作/归档服务并行实施；当前 Controller/设备发现批次先完成集成收尾。
已阅读当前 worker 四事务与两 helper、设计/计划、实际消费者记录；用户已有持续重构授权，草案“不是实施授权”
只表示设计 agent 未实施，不代表需要再次向用户询问。正式计划由 root 发布并确定 owner 后即执行。

- 范围固定两生产文件、两个新增测试、两个旧测试必要 patch；ADBWorker/TransferWorker 完整类源码与 AST 不变。
- TextSave/Local 的终态在 finally 内；Directory 失败在 with 内而成功在其外；TextRead decoded 后同步取消仍发 raw。
  必须保留这些通知与异常捕获位置，不能改成统一返回 DTO。远端 cleanup 逆序、独立取消、15 秒时限保持。
- 仅移动三个实际私有 patch owner，CommandRunner 类替换和 marker/args/decoded_available 保持。
  不为无消费者的旧 _resolve_target/_shell 增加代理；服务内部 helper 是唯一实现。
- service 接收每次 run 当时的执行器、Event 与输入快照；不增加 Qt interruption 判断，不引入真实设备或路径探测。
  参数/命令表达式迁移按原 AST 对照，原类构造/信号与 Transfer 生命周期不得混改。
- 已有 POSIX fixture skip 在 Windows 如实列出，不删除/放宽；只运行计划精确节点和两个新增专用文件。
  新无 Qt 子进程必须实际 fake 执行完整四事务。旧行为表征先绿；真正 RED 应确认为新服务缺失。
- root 统一两生产文件类型、正式文档与隔离源码 self-check。使用验证过的 wrapper 隔离所有数据环境变量，
  不仅 LOCALAPPDATA/XDG_CONFIG_HOME；不构建安装产物、不访问真实用户配置。
- 本预审未运行本阶段测试/生产导入，也不代表设备、真实桌面或冻结产物验收。


## 前置基线与执行状态（2026-10-24）

16个精确旧node展开38passed、23原POSIX环境skip，真实exit0；旧worker单生产类型0errors/0warnings。范围2生产4测试；ADBWorker/TransferWorker原文保持，root集中文档/类型/自检/集成。
前一批媒体/设备发现已最终审阅通过，当前按独占owner并行实施；无须重复用户确认。

实施裁定：旧代码表征证明TextRead的head_command/shell_quote不以NUL路径抛错，
新增测试改为让命令builder明确抛错以验证原构造时点；不新增路径校验或改变生产行为。

## 实施验证记录（2026-10-24）

六代码/测试路径已冻结。四读写事务与构造期命令builder归file_operations，原worker只适配Signal、Event、
decoded标志和日志。ADBWorker/TransferWorker完整类源码和AST不变；四run/两helper按受限依赖替换逐body AST一致。
六类构造/Signal、两个marker与TextRead命令表达式保持。三个实际私有patch owner迁移，原断言与平台skip保持。
旧worker行为表征12通过，新服务缺失RED明确；最终新测试67通过，16旧直接和8GUI关联展开57通过、23原POSIX跳过。
147不同节点中124通过、23跳过；POSIX字节文件名20项及shell3项保留原fixture，不计入通过数。
初次TextRead NUL构造抛错预期不符合现有实现，仅改为明确builder异常传播表征，未新增路径校验。
无Qt子进程完整fake执行四事务；callback、cleanup与finally原有非理想时序保留。root两生产Pyright无诊断，
owner六文件Ruff、两生产中文注释及源码parity通过。精确命令、退出码、nodeid/skip原因见owner-report.md及关联证据。
最终综合审阅已通过；未运行真实设备/真实桌面或冻结产物。

统一源码packaging使用六个数据环境变量隔离到已校验临时目录，exit0且无.self_check残留；
这包含工具执行和临时探针写删，不是完全只读或冻结产物验收。既有UI-09/UI-10未修复或重验，未触发全量pytest。

## 最终审阅与交付

两个任务Spec/Quality及最终综合审阅均PASS，无P0–P3 findings。130+124=254个不同用例通过，
另23项原POSIX平台跳过；5生产文件类型无诊断，84文档链接/frontmatter、824源码文本及diff通过。
独立核验23固定路径，包括13代码/测试和10文档；244前置路径中23授权变化、221未变。
原integration-hashes保留，状态收尾后另存delivery-hashes；未重复已通过测试/类型/源码自检。
既有UI-09/UI-10、实机/真实桌面/冻结产物仍未验收；全项目持续目标进入Qt worker目录归位。
