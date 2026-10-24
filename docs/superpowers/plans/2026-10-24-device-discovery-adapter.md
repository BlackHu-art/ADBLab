# 设备发现 Qt 适配器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans when implementation is authorized. 本文为待审阅草案，不是本子任务实施授权；沿用主任务协作方式，不自行提交。

**Goal:** 完整扫描类归入Qt适配层，旧类同对象重导出，保持功能/数据/类级使用。

**Architecture:** 新模块实际定义原名_ScanThread及两个token载荷类；main_frame只作静态同对象导出。扫描私有globals patch迁到实际owner，窗口组合/定时器/关闭/工具根原地；不增加callback/dependencies或兼容子类。

**Tech Stack:** Python 3.11、PySide6 QThread/Signal、现有core执行器与pytest/unittest.mock。

**Spec:** [设计](../specs/2026-10-24-device-discovery-adapter-design.md)。root预审后决定实施；正式方案与文档由root管理。

## Global Constraints

- 原六方法、两载荷构造、SCAN_CALL_TIMEOUT_S=15.0、Signal(object)、命令/timeout/快照/取消/清理次序不改。
- 新旧_ScanThread与载荷为同一个类对象；不新增__new__/__init__/start/msleep wrapper。
- 允许迁移私有globals patch；仅扫描用途，不能全文件替换gui.main_frame。
- 不增加依赖对象、薄子类、默认factory、反向import、ModuleType/sys.modules/globals代理。
- MainFrame所有方法、CloseController、presentation包__init__、_open_cmd与__file__根保持。
- 不覆盖前置脏成果，不改依赖/版本/CI/用户数据，不commit/push。

## Review Focus

- 扫描构造前后patch新owner的runtime/runner/clock/lock都生效，旧类调用仍命中它们（Task1新测试与迁移旧测试）。
- 旧类identity、class-level start/msleep与MainFrame工厂替换仍有效（Task1identity/类级测试、Task2窗口节点）。
- queued Signal(object)不丢token；stale/恢复/invalidate不变（Task1queued测试，Task2delivery/runtime）。
- admission和native共享deadline，drain/close异常仍准确实例release（Task1清理测试，Task2生命周期）。
- 非扫描ProcessRunner patch保留旧位置；新模块导入无MainFrame/Fluent（Task1导入测试，Task2_open_cmd节点及parity）。

## 文件 owner

同一实施owner独占 `adblab/presentation/qt_device_discovery.py`、`gui/main_frame.py` 的imports/三个扫描类区块、新 `tests/test_device_discovery_adapter.py`，以及五个既有测试文件中设计表指定的扫描patch：`test_model_mainframe.py`、`test_qt_adb_runtime.py`、`test_device_scan_cleanup.py`、`test_device_scan_lifecycle.py`、`test_ui_delivery_order.py`。

root串行协调main_frame/tests的前置改动；独占正式设计计划、`docs/project-knowledge/{ARCHITECTURE,MODULE_MAP,DATA_FLOW}.md`、README/路线图及root类型/packaging验收。未列出的文件只读，不删/放宽测试。

## Task 1：完整类迁移与私有替换点归位

**Interfaces:** 新模块保留原 `_ScanThread(QThread)` 和两个载荷原名/完整签名，见设计接口表；旧模块显式 `from ... import _ScanThread as _ScanThread`（两个载荷同样），无新构造参数或生产API。

- [x] **Step 1：核对前置状态和基线。** git status/target diff，保存当前工作树三个扫描类、所有MainFrame方法AST。扫描6方法，载荷各1构造；以当前文件而非HEAD为迁移源。先跑两专项扫描文件和Task2的算法/runtime关联节点取得原行为基线；不先迁patch导致旧实现误跑真实边界。
- [x] **Step 2：增加 `tests/test_device_discovery_adapter.py`，定义下列可观察边界。** 新模块import在相应函数/子进程内，旧入口类与工厂调用仍来自main_frame。先确保fake ProcessRunner/CommandRunner全部封住，测试不得触及真实ADB。

| 测试名称 | 精确行为与断言 |
| --- | --- |
| `test_scan_classes_are_identical_through_legacy_entry` | 三个旧导出分别is新定义，_ScanThread.__module__为新模块；parent QObject传入后parent()同对象，interval_ms=1规范为3000，默认15000；不额外手工调用未初始化QThread方法验证__new__ |
| `test_adapter_import_does_not_load_main_frame_or_fluent_widgets` | 独立Python子进程只import新模块，assert gui.main_frame/qfluentwidgets不在sys.modules；禁止实例启动/ADB。core.exec存在是允许的，不造“无执行器”指标 |
| `test_legacy_entry_uses_new_runtime_and_runners_after_patch` | 参数化before_construct/after_construct；旧_ScanThread构造，新owner整个adb_runtime/CommandRunner/ProcessRunner替换；fast runtime、None admission、一轮run返回唯一mock-device列表，fast命令含-l，native guard不调用；cancelled在scan.stop后变True |
| `test_legacy_entry_uses_new_clock_and_client_lock_after_patch` | 同两时机；新owner整time对象monotonic=100、runtime=None、CommandRunner.active_count=0、ProcessRunner fake；fake _run_devices_scan必须收到deadline=115与同runner；新owner acquire和lock.release各一次，不碰真实锁 |
| `test_legacy_class_start_and_msleep_patches_remain_effective` | before/after构造patch旧class.start与msleep；scan.start只命中Mock不启动线程；_sleep_interruptibly(250)产生[100,100,50]，stop后立即True无新sleep；新旧类指向同对象 |
| `test_scan_payload_keeps_token_through_queued_delivery` | 新/旧同类真实信号，queued connection接收，pump现有qt_application；从run产生list子类与unavailable的str子类，分别携带(7,0)/(8,0)；不先转成list/str，断言原载荷token到达 |
| `test_native_cleanup_attempts_all_finally_steps_for_exact_process` | 新owner patch cleanup helpers，fake communicate抛OSError；参数化drain失败/close失败/均正常，_run_devices_scan均返回None，顺序drain(proc,timeout=0.5)→close(proc)→runner.release_finished('device_scan',proc)，同一proc，未退出对象不移除 |

- [x] **Step 3：确认结构红灯。** `.\.venv\Scripts\python.exe -m pytest -q tests/test_device_discovery_adapter.py`：新模块尚不存在，要求失败是ModuleNotFoundError，而非真ADB/设置环境异常。旧行为基线通过不表示修复了bug；这是新职责入口的结构需求。
- [x] **Step 4：完整搬移三个类。** 新模块正常imports原执行边界，类名/方法/签名/常量/控制流均原样。parse_connected_devices/capture保留原位置延迟import；新模块不得引用gui.main_frame。
- [x] **Step 5：替换旧定义为三个显式同对象import。** 删除main_frame中移走后无消费者的扫描专用imports（设计列明）；ProcessRunner/time/threading/Callable/Signal保留。MainFrame所有方法不动，_ScanThread工厂查找仍旧模块全局，_open_cmd/__file__不动。
- [x] **Step 6：原子迁移五文件的扫描patch。** 对照设计表，扫描ProcessRunner/CommandRunner/runtime/time/lock改新模块；tests仍通过旧_ScanThread调用。cleanup/lifecycle fixture可新增 `from adblab.presentation import qt_device_discovery as discovery` 并仅将扫描setattr改discovery，保留旧main_frame._ScanThread实例入口。transport.lock/time、execution.ProcessRunner/popen_native等原patch保持。

特别冻结：`test_model_mainframe.py::test_main_frame_open_cmd_launches_terminal_via_process_runner` 的 `gui.main_frame.ProcessRunner` 不改；`test_main_frame_starts_scan_thread_with_debounced_refresh` 的整个gui.main_frame._ScanThread替换不改；所有旧类start/msleep patch不改。不得简单全文件replace `gui.main_frame.ProcessRunner`。

- [x] **Step 7：parity和绿灯。** 三个类AST（去行号）应完全相同，不需任何callback lookup归一化；MainFrame全部方法AST同样相同。测试diff只迁import/patch地址，原断言/失败语义完整；新增测试另审。运行新文件及Task2直接集合后再关联；任何真实外部边界调用视为隔离失败。
- [x] **Step 8：局部静态检查及审阅。** 对改动Python运行Ruff/注释检查，审阅者核查同对象导出、五文件精确patch、窗口终端旧patch、Signal(object)、原native finally；root统一类型与最终集成，不提交。

## Task 2：关联验证与 root 集成

**Interfaces:** 消费 Task 1 的同对象别名与原样扫描实现；没有新的生产接口。验证范围从线程→runtime准入→MainFrame排队/关闭，不能把整个主窗混合测试文件都算本轮。

- [x] **Step 1：执行直接集合。** 下面两文件都是扫描专项，允许整文件；其生命周期测试包含**合成 Python 客户端/独立后代**，不是设备命令，清理必须在fixture/finally中完成。只读设计阶段未执行。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_device_discovery_adapter.py tests/test_device_scan_cleanup.py tests/test_device_scan_lifecycle.py
```

- [x] **Step 2：执行算法与窗口精确关联节点。** `.\.venv\Scripts\python.exe -m pytest -q` 后接以下节点，可分批运行；原因是扫描实现globals归属变化，仍需验证类级patch、结果语义和原窗口owner。已有新测不代替这些原路径测试。

```text
tests/test_model_mainframe.py::test_scan_thread_uses_command_runner_for_device_polling
tests/test_model_mainframe.py::test_scan_thread_skips_polling_while_command_runner_is_busy
tests/test_model_mainframe.py::test_scan_thread_rechecks_shortly_after_command_runner_becomes_idle
tests/test_model_mainframe.py::test_scan_thread_emits_when_device_set_changes_with_same_count
tests/test_model_mainframe.py::test_scan_thread_republishes_same_snapshot_after_unavailable
tests/test_model_mainframe.py::test_scan_thread_republishes_same_snapshot_after_external_invalidation
tests/test_model_mainframe.py::test_scan_thread_treats_nonzero_adb_exit_as_unavailable
tests/test_model_mainframe.py::test_scan_thread_stop_terminates_inflight_scan
tests/test_model_mainframe.py::test_main_frame_open_cmd_launches_terminal_via_process_runner
tests/test_model_mainframe.py::test_main_frame_starts_scan_thread_with_debounced_refresh
tests/test_model_mainframe.py::test_main_frame_shutdown_disconnects_scan_callbacks_without_warning
tests/test_model_mainframe.py::test_main_frame_stop_scan_thread_uses_short_ui_wait
tests/test_model_mainframe.py::test_main_frame_stop_scan_thread_uses_blocking_wait_on_close
tests/test_model_mainframe.py::test_scan_thread_finish_restarts_after_fast_disable_enable_toggle
tests/test_model_mainframe.py::test_main_frame_scan_refresh_debounce_collapses_bursts
tests/test_model_mainframe.py::test_manual_refresh_failure_invalidates_continuous_scan_snapshot
tests/test_qt_adb_runtime.py::test_fast_scan_runs_while_other_commands_are_busy
tests/test_qt_adb_runtime.py::test_scan_waits_for_host_without_opening_another_native_client
tests/test_qt_adb_runtime.py::test_scan_admission_and_native_process_share_one_deadline
tests/test_qt_adb_runtime.py::test_scan_requests_recovery_before_busy_gate_or_failed_native_scan
tests/test_qt_adb_runtime.py::test_fast_scan_failure_preserves_last_snapshot
tests/test_qt_adb_runtime.py::test_superseded_scan_keeps_snapshot_and_state_and_waits_normally
tests/test_ui_delivery_order.py::test_manual_refresh_result_discards_older_debounced_scan
tests/test_ui_delivery_order.py::test_scan_state_from_older_generation_does_not_revoke_manual_success
tests/test_ui_delivery_order.py::test_scan_republishes_same_devices_after_manual_generation_changes
tests/test_gui_audit_regressions.py::test_device_scan_drains_pipes_before_waiting_for_exit
tests/test_gui_audit_regressions.py::test_device_scan_cancellation_and_failed_exit_do_not_publish_output
```

- [x] **Step 3：root更新事实文档。** ARCHITECTURE区分线程实现、旧构造门面和窗口owner；MODULE_MAP补新适配器/专项测试；DATA_FLOW图中的 `_ScanThread` 可标注为旧兼容入口对应新实现，不改现有代次/快照语义；README/路线图记录阶段和验证限制。保留前置文档改动。
- [x] **Step 4：root集中类型与静态验证。** `.\.venv\Scripts\python.exe -m ruff check gui/main_frame.py adblab/presentation/qt_device_discovery.py tests/test_device_discovery_adapter.py tests/test_model_mainframe.py tests/test_qt_adb_runtime.py tests/test_device_scan_cleanup.py tests/test_device_scan_lifecycle.py tests/test_ui_delivery_order.py`；`.\.venv\Scripts\python.exe scripts/check_comment_language.py gui/main_frame.py adblab/presentation/qt_device_discovery.py`；root `.\.venv\Scripts\python.exe -m pyright`；`scripts/check_doc_links.py`；`git diff --check`。类型错误按实际移动边界修复，不新增Any/忽略或更改QThread API。
- [x] **Step 5：root运行源码packaging。** 子进程复制环境，仅把 LOCALAPPDATA/XDG_CONFIG_HOME（及项目现有隔离约定所需 APPDATA/MOBILEPERF_LOG_DIR）指向 TemporaryDirectory，QT_QPA_PLATFORM=offscreen；执行项目 Python `main.py --self-check packaging`。不改工具搜索/真实资源、不改机器环境或用户配置。不要把self-check等同PyInstaller产物包含新模块。
- [x] **Step 6：报告和最终审阅。** 记录实际命令/结果、源parity、仅扫描私有patch迁移、窗口终端旧patch保留、静态新入口收益；说明未验证真实设备取消/恢复、实际桌面关闭与冻结产物。没有新证据不重复跑已通过集合；没有增量策略全量触发项不跑全量。设计任务本身不执行以上步骤。

## 自审

推荐方案不再包含十callback/薄子类；原方法AST可完全保持，测试改动边界有具体五文件和一处必须保留的非扫描ProcessRunner patch。所有现有节点均从当前AST核对，新增测试均有假依赖和可观察结果。root的窗口/类型/packaging/docs工作与只读设计交付区分，设计草案不表示已经执行测试或获准立即实施。

## 主任务预审与执行裁定


2026-10-24，root已读三草案、现有完整三类、原生finally与两专项扫描夹具/合成客户端测试，设计PASS。

- 采用最终同对象别名方案；不采用十callback/子类方案。私有patch不是用户功能契约，按五文件精确迁移到实际owner。
- 主窗全部方法与三类完整source/AST保真，old_ScanThread及两个载荷同对象；保留窗口ProcessRunner终端patch和time/threading用途。
- 根包无GUI导入是实际可验证边界；不要宣称无Qt/models。新导入测试先隔离全部数据环境再import，并用timeout，禁止启动真实ADB。
- 新清理测试的outer except确实会在尝试全部finally步骤后返回None；与源码相符。run的runtime探测位于try外，不能改变异常范围。
- QObject/QThread实例都要在测试退出前释放；需要QApplication事件泵的queued测试按项目marker规范显式标记并collect-only核验。
- 原专项生命周期测试启动合成Python进程并保持独立后代；保留其精确PID/fixture清理，不改为设备命令，不误计真实ADB覆盖。
- root取得专项/算法/runtime直接基线和现存main_frame类型基线；owner复用。实现完成后一次独立任务审阅。
- root只对受影响生产文件做Pyright，不运行计划里无参数全项目命令；集成按临时全部数据环境的原packaging入口。
- 限定root正式docs与before快照；当前Home/Apps批完成后再发布和快照，不把并行中间态当迁移前基线。

未实施，未运行本阶段pytest/type/self-check；预审不代表线程或实机验收。

root集中Pyright与源码packaging；owner不重复执行这两项。最终自检子进程的LOCALAPPDATA、APPDATA、
XDG_CONFIG_HOME/XDG_CACHE_HOME/XDG_DATA_HOME和MOBILEPERF_LOG_DIR均指向经边界校验的临时目录。

## 实施验证记录（2026-10-24）

八代码/测试路径已冻结。三个完整类移入adblab/presentation/qt_device_discovery.py，旧MainFrame模块
静态导出同一对象；三类以及MainFrame整类/153方法的源码字节和AST一致，窗口继续拥有线程与关闭。
五旧文件251条断言的AST及顺序保持，私有扫描globals patch转向实际owner，终端ProcessRunner patch不变。
12新适配、10扫描专项、35精确关联共57个不同nodeid通过；ui选择1/12，其他11不标ui。
新模块缺失RED后，导入探针把Popen类替成函数导致既有子类定义失败；仅改为拦截构造函数，最终新文件12通过。
root两生产Pyright无错误/警告，owner八文件Ruff、两生产中文注释及空白检查通过。
source-text CLI不支持文件参数的失败未算通过，改用同一check_file API对八文件检查，无问题。
报告、实际命令/退出码、57节点和冻结hash见本阶段忽略目录owner-report.md及关联证据。
原合成Python客户端/独立后代清理fixture仍执行，结果不代表真实ADB设备；最终综合审阅已通过。

root统一集成：全部数据环境变量隔离后的源码packaging exit0、临时.self_check无残留；
812源码文本检查及diff通过。文档检查初次把计划中的调用语法误识别为链接，改为等义描述后80文档通过；
未修改检查器或生产代码，不重复已通过测试、类型或自检。既有UI-09/UI-10未重验或修复。

## 最终审阅与交付

两个任务Spec/Quality及最终综合审阅均PASS，无P0–P3 findings。95+57=152个不同用例通过，
7生产文件类型无诊断，80文档链接/frontmatter、812源码文本及diff通过。独立核验28固定路径，
包括18代码/测试和10文档；228前置路径中28授权变化、200未变，无范围外漂移。
保留原integration-hashes，状态收尾后另存delivery-hashes；未重复已通过测试/类型/源码自检。
既有UI-09/UI-10、实机/真实桌面/冻结产物仍未验收；全项目持续目标推进下一批服务及worker目录调整。
