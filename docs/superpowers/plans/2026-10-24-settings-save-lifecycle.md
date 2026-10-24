# AppSettings 保存生命周期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 AppSettings.close 在返回前收回全部 Timer 和已准入保存，失败可重试，恢复测试路径后无旧写入。

**Architecture:** 保留 manager 为唯一状态与 I/O owner，登记全部 Timer并原子化启动、保存准入和关闭。现有后台 finalizer 调用 close，主窗口主题槽拒绝关闭后的通知，fixture 在恢复路径前排空 owner。紧耦合生产代码由单一实施 owner 顺序修改，独立 reviewer 审查；其他审计可并行。

**Tech Stack:** Python 3.11、threading、现有 PySide6/pytest 与项目 `.venv`，不新增依赖。

**Spec:** [保存生命周期设计](../specs/2026-10-24-settings-save-lifecycle-design.md)。状态：实施与独立任务审阅通过，最终集成审阅通过。

## Global Constraints

- 不搬 schema/migrations，不改 schema 版本、默认值、JSON/用户路径、迁移和未来版本保留规则。
- 保留 500ms 防抖、daemon Timer、写锁后快照和原子替换；close 不带内部 timeout。
- close 原子冻结已接受状态；关闭后 set/update/set_many/reset 抛 `RuntimeError("AppSettings is closed")`，get 可读，普通保存返回 False。
- close 失败只在全部工作排空后返回 False；重复 close 重试冻结快照，成功后幂等。
- 不在 GUI 主线程等待；不访问用户数据/设备；不提交、不推送；保留既有未提交修改。
- 本轮单 owner 文件：core/settings_manager.py、gui/close_controller.py、gui/main_frame.py（仅主题槽）、tests/test_settings_save_lifecycle.py（新）、tests/conftest.py、tests/test_settings_persistence.py、tests/test_typography_core.py、tests/test_phase2_mainframe_shutdown_gate.py、tests/test_run_library_integration.py、tests/test_test_collection.py，以及 Task 3 列出的事实文档和本计划。
- tests/test_test_collection.py、gui/main_frame.py 和事实文档已有其他阶段差异，实施前重新读 diff，按区块追加，不覆盖或重新验收此前无关工作。

## Review Focus

- Timer 回调返回与线程真正退出之间的窗口：Task 1 的 exit gate 回归必须证明 close 仍等待。
- 同步 reset/迁移写入在写锁前排队：Task 1 的参数化准入回归证明 close 不早退。
- close 的磁盘失败与第二次调用：Task 1 固定快照重试且无自动重开。
- 系统主题晚到和正常窗口：Task 2 用真实信号验证 guard 只影响 closing 窗口。
- 单个测试重建多个 owner：Task 3 的合成路径恢复探针必须等待所有旧 Timer，不能仅覆盖最后单例。

## Task 1：实现唯一保存 owner 与终止协议

**Files:** Modify core/settings_manager.py；Create tests/test_settings_save_lifecycle.py；Modify tests/test_settings_persistence.py、tests/test_typography_core.py。

**Interfaces:** Produces `AppSettings.close(self) -> bool`；保留 `_save_atomic(self, *, deferred_only: bool = False) -> bool` 和 `flush_deferred_save(self) -> bool`；不新增 flush。终止行为和锁顺序以设计为准。

- [x] **写失败回归**：新增 `test_close_waits_replaced_running_timer`，用真实 Timer 与 Event 在第一个写锁前阻塞，第二 Timer 被取消；close 线程在放行前不得完成，返回后两线程均退出，合成新路径 sentinel 不变。
- [x] **写退出与启动竞争回归**：`test_close_waits_timer_thread_exit_after_callback` 使用真实 Timer 子类在 super().run 返回后等 gate，close 必须仍等待；`test_close_serializes_timer_start` 在 start handoff 暂停，以事件证明 close 不能对未启动线程 join 或返回后再启动；`test_timer_start_failure_retains_other_owners` 验证启动失败不丢旧线程、不保留不可 join 新对象。
- [x] **写同步准入回归**：`test_close_waits_admitted_synchronous_save` 参数化 `_save_atomic`、`flush_deferred_save`、`reset`，先证明调用已准入并停在写锁前，再 close；释放后所有调用结束，最终值正确。另测 OPEN 的 deferred 无 pending 不创建文件。
- [x] **写关闭语义回归**：`test_closed_settings_reject_mutations` 覆盖 set/update/set_many/reset、空 mapping 与 schema_version-only；断言 RuntimeError、数据/文件/Timer不变。`test_closed_save_entries_return_false_without_io` 覆盖 deferred无pending；`test_concurrent_close_is_idempotent` 验证并发成功仅一次最终写；`test_close_failure_retries_frozen_snapshot` 注入 dump/replace 失败，验证旧文件、temp清理、pending及成功后不再写。
- [x] **运行红灯**：`.\.venv\Scripts\python.exe -m pytest -q tests/test_settings_save_lifecycle.py`。预期为缺少 close 或真实未排空失败，不能接受仅 fixture/导入错误；所有 gate 在 finally 放行并 join，失败不能留挂起线程。
- [x] **实现**：在原 manager 初始化完整生命周期状态后才 `_load`；使用状态锁内 start、全 Timer 集合、Condition+活动保存计数、独立 close 串行锁。保存准入包装和磁盘 helper 分离；reset 修改与写入名额同锁，取消不移除登记。close 冻结快照、锁外 join/等计数、执行最后 I/O。禁止回调 finally 删除未退出线程登记。
- [x] **迁移直接测试隔离**：局部 fixture 与每个重建点关闭旧 owner，再切单例；adb_client round-trip 重建后的后续校验改用 reloaded。FakeTimer 补真实消费的线程协议，不放宽字体/防抖断言。不要用 no-op close 替身绕过资源清理。
- [x] **运行绿灯及关联集**：`.\.venv\Scripts\python.exe -m pytest -q tests/test_settings_save_lifecycle.py tests/test_settings_persistence.py tests/test_typography_core.py -k "settings or deferred"`；保留已有并发原子写和迁移失败回归。
- [x] **阶段审阅**：独立检查锁顺序、start失败、真正线程退出、失败重试和准入线性化；本任务不 commit。

## Task 2：接入关闭与晚到主题通知

**Files:** Modify gui/close_controller.py、gui/main_frame.py（仅 `_on_theme_changed`）、tests/test_phase2_mainframe_shutdown_gate.py、tests/test_run_library_integration.py。

**Interfaces:** Consumes Task 1 的 `close() -> bool`；Produces 原 finalizer FAILED/TIMED_OUT 语义和关闭后主题槽无操作；不修改 ThreadedShutdownTask。

- [x] **写失败回归**：真实 settings + 生产 `_flush_shutdown_state` 配合旧 Timer gate，证明 finalizer不早退；`test_closing_window_ignores_late_theme_signal` 连接真实 BaseStyles.theme_changed 到真实方法并传 closing 窗口，关闭 owner 后发信号，断言无异常和写入；配对 OPEN 控制用例证明正常主题保存仍执行。
- [x] **迁移 shutdown 替身协议**：假 settings 提供 `close`，删除消费者对 `_save_timer/_save_atomic` 的假契约；`_bind_settings_finalizer` 必须调用相同 owner接口。保存失败 mock 改为 close False；不改失败摘要/归档仍执行的断言。
- [x] **运行红灯**：选择以上新增节点和 `test_settings_failure_reaches_finalizer_and_is_saved_after_log_freeze`；确认旧关闭链/主题槽导致可解释失败。
- [x] **实现**：协调器仅调用 close，False 后照旧排空诊断和 library 并抛原 RuntimeError；主题槽入口只检查当前窗口 `_closing`。不移动 UI准备、布局保存、日志冻结顺序，不因close False提前跳出归档收尾。
- [x] **验证超时和重试**：真实阻塞 Timer 由最终 close 持有，GUI heartbeat 继续，TaskSupervisor 报 shutdown_finalizer 残留；放行后显式等最终线程退出。重复关闭不再启动第二个 finalizer；失败保存后显式 close 重试不重开 Timer。
- [x] **运行关联集**：设置 `$env:QT_QPA_PLATFORM = 'offscreen'`；`.\.venv\Scripts\python.exe -m pytest -q tests/test_phase2_mainframe_shutdown_gate.py tests/test_run_library_integration.py`。记录真实线程与mock各自证据；不以离屏通过宣称桌面/打包验收。

## Task 3：共享 fixture 关闭屏障及事实文档

**Files:** Modify tests/conftest.py、tests/test_test_collection.py；按需要完善 Task 1/2 已拥有的手工fixture；Modify docs/project-knowledge/ARCHITECTURE.md、docs/project-knowledge/DATA_FLOW.md、docs/project-knowledge/RISKS_AND_DEBT.md、docs/guides/TESTING_GUIDE.md、docs/README.md、本计划。

**Interfaces:** Consumes `close()` 是资源屏障（False也已排空）；保留先销毁 QObject/恢复主题、后关闭settings、最后恢复路径的 fixture 依赖顺序。

- [x] **写失败探针**：在 test_test_collection.py 现有独立解释器框架添加 `test_settings_fixture_drains_replaced_timer_before_restoring_storage`。所有环境目录先指向 tmp；在fixture测试内让第一Timer已进入、第二替换，独立受控释放者等待teardown close开始后放行，下一用例断言所有捕获Timer已退出且模拟用户sentinel不变。清理失败也必须放行gate。
- [x] **运行红灯**：单独运行上述节点；旧fixture仅join最新Timer时应确定性失败，不依赖固定sleep抢时序。
- [x] **实现 fixture**：共享settings teardown调用owner.close，保留UI销毁顺序；不得仅清空单例、遍历全局线程或绑定旧路径绕过实际生命周期修复。确保持有并关闭本用例所有替换owner。故障测试的close False不是资源残留，不新增“必须落盘成功”的fixture断言。
- [x] **运行直接及代表组合**：`.\.venv\Scripts\python.exe -m pytest -q tests/test_test_collection.py tests/test_settings_persistence.py tests/test_typography_core.py tests/test_settings_typography.py tests/test_phase2_mainframe_shutdown_gate.py tests/test_run_library_integration.py tests/test_gui_startup.py`。新增主题guard后追加 main_window_layout 中既有主题/关闭节点；按实际收集结果选择，不运行全部布局矩阵。启动关联只覆盖deferred消费者，不修改main启动接线。
- [x] **同步事实**：DATA_FLOW维护close及终止接口，ARCHITECTURE维护后台finalizer资源屏障，TESTING_GUIDE更新fixture owner清理说明；RISKS只在真实回归通过后关闭对应已复现风险，README增加阶段链接。保留其他阶段已修改的事实和日期，不复制所有设计细节。
- [x] **静态验收**：对本轮Python文件执行 Ruff；对 core/settings_manager.py、gui/close_controller.py、gui/main_frame.py 执行中文注释检查和 Pyright（共享接口改变）；执行 `.\.venv\Scripts\python.exe scripts/check_doc_links.py`、`git diff --check`。若Pyright出现既有错误，提供与本轮差异证据，不能表述全通过。
- [x] **独立最终审阅**：仅当前生命周期差异，重点核对关闭后入口、全部Timer真实退出、fixture路径切换、真实主题槽及失败摘要。主任务决定是否需要额外集成范围；没有全量触发条件不跑全量、构建或实机。
- [x] **记录交付**：写实际命令/结果/限制及最终diff范围；未运行不写通过；不commit。

## 设计阶段验证记录

设计阶段未执行实施任务；以下为当时基线记录。主任务完成迁移前消费者基线：test_phase2_mainframe_shutdown_gate.py、test_run_library_integration.py、test_test_collection.py、test_typography_core.py，51 passed、2个既有warnings、16.98s，日志 `.superpowers/sdd/2026-10-24-settings-save-lifecycle/baseline-consumers.log`；不重复启动相同基线。settings_persistence原代码未改，复用此前审计72项通过记录，共123项相关原实现基线，但它不替代实施后的红绿回归。

本轮 `.\.venv\Scripts\python.exe scripts/check_doc_links.py` 通过（66个项目知识文档），`git diff --check` 通过（其他既有文件有LF/CRLF提示）。三份新文档另行逐行检查尾部空白通过，因为普通git diff不覆盖未跟踪文件。未运行全量、真实桌面、构建或设备验证。

## 实施与集成验收记录（2026-10-24）

已完成三个紧耦合步骤，独立 reviewer 的 Spec/Quality 均 PASS，无分级缺陷。
最终集成审阅PASS，无未解决新增分级缺陷。仅本批3生产与7测试文件，保留 main_frame 和收集测试的前置差异。
新增20项核心回归覆盖真实 Timer 退出、start 前后异常、同步保存准入、并发关闭、严格终止、
冻结重试、冻结失败排空以及锁外 warning sink；关闭消费者和多 owner fixture 接入同一 close。

实际执行命令使用仓库 `.venv`。Task 3 的代表组合额外包含新生命周期测试及 main_window_layout 的
`test_shutdown_flush_captures_visible_window_size_and_theme_without_resize_transaction`、
`test_system_color_scheme_change_reapplies_system_theme` 两节点：226 passed、8 failed。
随后新增 start-after 参数并运行最终核心加原并发写节点：21 passed；其中只有1项为新增，
故设置范围去重为 **227 passed、8 failed，共235项**，不能把重复节点累加为覆盖数。
最终真实主题和超时3节点再次通过。早期包装命令未单独保存 pytest 数字退出码，以完整摘要判定，
不把 shell0 当作 pytest 通过；最终直接/主题/静态命令显式 exit0。

8项失败属于未改动的 settings_typography 两函数×4参数的布局恢复断言。使用相同环境与脚本装载
阶段前/当前四模块（manager、close_controller、main_frame、conftest），核验源码hash与真实函数/fixture
身份后，before/after各复现同样8项、相同3或6像素差。独立审阅已核对原日志和来源证据。
它们在本阶段前已存在，仍保留失败，不推断字体原因或历史引入提交；见风险账本UI-10。

主任务为新共享fixture与截图目录的交叉影响追加
`pytest -q tests/test_workspace_feature_host.py::test_all_pages_device_selection_and_reopen_without_transient_windows`：
Light/Dark **2 passed**，3842个既有依赖/Qt弃用warning，35.74s，exit0。
截图包自身77项通过，故本批两个阶段加此宿主交叉检查共 **306 passed、8既有failed**，不重复统计。
本批无skip；此前其他阶段的平台skip不移入本批。

限定Ruff与中文注释通过；Pyright按实际解释器sys.path生成临时配置，设置3生产文件前后均0错误/0警告。
源码packaging由截图归包阶段集中执行，exit0。该自检在默认数据目录临时写入并删除`.self_check`，
不能称完全只读或未访问数据目录；没有发现读取/改写用户设置或历史的证据。日志含本机路径，交付不展开。
完整日志/固定增量/来源对照与审阅报告在忽略目录`.superpowers/sdd/2026-10-24-settings-save-lifecycle/`。

没有全量触发条件，未跑全量或PyInstaller构建；未验证真实桌面、高DPI、冻结产物或设备。
永久阻塞I/O仍由finalizer持有并由监督器报告超时残留；冻结失败的终止owner不能原地重试，
成功冻结后的磁盘失败才重试同一快照。不改变配置路径、JSON、schema版本、未来字段和正常交互。

最终综合审阅已独立核对35范围路径、23代码路径、完整移动AST与失败对照，PASS。
文档链接/frontmatter 68项、源码文本773项与diff空白检查通过；134项前置快照完全未变。
最终review保留packaging探针访问和8项既有失败的限制，未扩大为整库或发布验收。
