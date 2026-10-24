# Controller 媒体职责边界 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. 本子任务仅交付草案；主任务沿用用户已授权的执行方式，不重复批准、不 commit。

**Goal:** 将截图、录屏、设备诊断协调实现归入职责模块，保持旧 ADBMediaMixin 入口与全部业务语义。

**Architecture:** 三个新 mixin 继承同一基础类，旧类按 Screenshot、Recording、Diagnostics 顺序组合。注册表只存在实际职责类，不改反射注册和安装 super 链。

**Tech Stack:** Python 3.11、PySide6、现有 pytest/unittest.mock、项目 `.venv`。

**Spec:** [设计](../specs/2026-10-24-controller-media-boundaries-design.md)。正式执行前由主任务把审阅后的设计/计划放入现有 docs/superpowers 目录；本目录仍是忽略的协作草案。

## Global Constraints

- 不改命令、标识、信号、文案、状态机、取消/关闭顺序、数据格式、校验、GUI、模型或用例。
- 旧 `controllers._media.ADBMediaMixin` 入口、直接 `.__new__`、非绑定替身调用保持。
- 三职责类和组合类不定义 `__init__`；包 `__init__.py` 仅中文说明。
- 私有 datetime/QTimer patch 地址明确迁移；禁止反向导入旧聚合、通用代理或 sys.modules 替换。
- 只有三个录屏显式类引用允许更名；全部业务方法 AST parity，其余不顺手重写。
- 不修改任何前置脏资产，不跑设备、不做正式构建、不 commit/push。

## Review Focus

- 完整 Controller 先经过截图再经过安装协议校验；install/generic 不被截图分支吞掉（Task 1 协议路由测试与 Task 2 关联门禁）。
- 残留/重复注册键不会导致方法覆盖或同一结果重复交付（Task 1 唯一注册与实际调用测试）。
- 私有 patch 的新位置控制实际 globals，旧公开方法仍执行受控时间/回调（Task 1 现有命名与批次测试）。
- 录屏失败后同批次只重试一次，SimpleNamespace 非绑定调用仍可完成，关闭后不再提交（Task 1 录屏 Controller 精确节点）。
- 新包静态导入可达，真实数据目录不受 self-check 影响（Task 2 root 类型检查、隔离源码 packaging，冻结与真机限制单列）。

## 文件 owner

**同一个实施 owner（Task 1，不能按三模块并行改 `_media.py`）：** 新增 `controllers/media/{__init__,screenshot,recording,diagnostics}.py`；修改 `controllers/_media.py`；新增 `tests/test_controller_media_boundaries.py`；仅迁移 `tests/test_phase2_screenshot_gate.py`、`tests/test_diagnostic_artifact_identity.py`、`tests/test_diagnostic_artifact_names.py`、`tests/test_model_media_adb.py` 中设计表列出的私有 patch。

**主任务/集成 owner（Task 2）：** 设计计划正式稿、`docs/project-knowledge/ARCHITECTURE.md` Controller 小节、`docs/project-knowledge/MODULE_MAP.md` Controller 行、`docs/README.md` 当前设计索引、`docs/superpowers/plans/2026-10-23-project-refactor-roadmap.md` 阶段进度。只更改这次归属事实，与其他 agent 对这些文档的更新串行合并。

**只读关联文件：** `controllers/__init__.py/_base.py/_app.py/_app_install.py`，模型工厂/信号、operation/recording 用例、所有非 patch 消费者测试。遇到真问题另报告，不扩大本次重构。

## Task 1：职责归位与兼容边界

**Interfaces:** 新增 `ADBScreenshotMixin(_ADBControllerBase)`、`ADBRecordingMixin(_ADBControllerBase)`、`ADBDiagnosticsMixin(_ADBControllerBase)`；旧 `ADBMediaMixin` 组合三者。所有方法签名由现状 AST 保持；设计文件的方法范围和下列注册字典是完整迁移清单，不另创接口。

- [x] **Step 1：核对前置状态和保存源码基线。** 执行 `git status --short`、`git diff -- controllers/_media.py`，检查更近规则；将当前 `_media.py` 的方法 AST/handlers 快照保存到此任务忽略目录的执行记录中（不得用 HEAD 替代未提交现状）。记录 46 个类方法、2 个函数、17 普通键、1 operation 键；先校验实际计数，变化则停下重核设计。
- [x] **Step 2：取得行为基线。** offscreen 下运行下文直接集合；本轮边界是 Controller 协调归位，不是模型命令或 UI 重写。失败先定位并记录，不能用迁移删除/放宽断言。
- [x] **Step 3：增加 `tests/test_controller_media_boundaries.py` 的可观察边界用例。** 使用无构造器的对象与 Mock/真实纯用例；不创建真实模型/进程、不跨测试导入私有 fixture。

新测试精确定义：

| 测试名称 | 核心断言与准备 |
| --- | --- |
| `test_media_facade_routes_each_registered_result_once` | 对 `ADBMediaMixin.__new__` 注入 log Mock；在实例上将设计表全部 17 个普通 handler 名设为 Mock，调用真实 `_build_handler_map()`，逐个取出 map 中的 handler 并传入 payload 调用，每个 Mock 恰好一次且收到同一 payload；operation `take_screenshot` 同法以 payload/metadata 两参调用；map 键严格为 17+1，无 collision 日志 |
| `test_full_controller_keeps_media_and_install_registration_without_collisions` | `ADBController.__new__` + log Mock 调真实注册；媒体 17 键绑定 self；operation 键恰为 install_apk/take_screenshot，分别指向原业务方法；扫描 classdict 键计数全部为 1，assert 无 collision；不把 77 写成永久全项目计数断言（前后临时快照验证非媒体映射） |
| `test_screenshot_protocol_still_reaches_install_and_base` | 使用真实完整类 `__new__`，对 `_operation_metadata_matches` 直接参数化调用：缺 generation 的 screenshot=False；同代 screenshot 且 claim=None=True；带 claim 且 op_type!=install_apk=False；install_apk 同代 claim=True；错 generation/method/kind=False；合法 generic 无 generation + claim=None=True。每项用真实 OperationMetadata 与 manager.begin 返回 snapshot |
| `test_protocol_failure_reaches_correct_terminal_owner` | 完整类对象，截图 `_fail_screenshot_operation` Mock、安装 use_case.fail_snapshot Mock 回 `(True, owner, terminal)` 与 `_publish_install_terminal` Mock、base 的真实 manager；依次调用 screenshot/install/batch_install/generic；截图仅本门面、安装仅 fail_snapshot+publish、generic 真实 FAILED，互不串路 |
| `test_new_screenshot_owner_preserves_old_entry_delivery` | 参数化新 Screenshot 类与旧 Media 类的 `__new__`；注入 signals Mock，调用 `_emit_screenshot_batch(["", "image.png"])` 恰好 emit(["image.png"])，设置 `_shutting_down=True` 后不增加调用；不启动 GUI |
| `test_new_recording_owner_preserves_old_entry_retry` | 参数化新 Recording 类与旧 Media 类的非绑定方法；用 ScreenRecordUseCase 建 mock-device/batch-1/owned.mp4 的已拉取会话，处理 retryable 失败后重复 stop；pull_recorded_video_async 只一次、stop 不调用、路径/批次不变；成功返回后清空会话且 finished/legacy 各一次 |
| `test_new_diagnostics_owner_preserves_old_entry_admission` | 参数化新 Diagnostics 与旧 Media，使用 SimpleNamespace；`kill_process` 多设备与 Unicode PID 均不下发；单设备 ASCII 1234 恰好下发一次；`gfxinfo` 非法包名不下发；`battery_set` level=101 不下发；保留各错误操作名，直接覆盖边界而非仅检测方法存在 |

- [x] **Step 4：确认红灯。** `python -m pytest -q tests/test_controller_media_boundaries.py`；只因新模块尚不存在失败属于结构需求红灯。独立旧组合的行为表征应通过；如其失败，先调查，不把测试期待强行套到现有行为。建议新模块 import 放入对应测试函数以便观察其他表征结果。
- [x] **Step 5：实施三模块和组合门面。** 移动设计清单的方法与 helper，保留三个录屏显式调用仅改所属类名。Screenshot 唯一 operation 表；Recording 三键；Diagnostics 十四键；旧聚合无字典/方法。分文件必要 import，不写额外抽象或构造器。`controllers/__init__.py` 不改。
- [x] **Step 6：同步迁移四个测试文件的精确 patch。** 地址以设计表为准；保留旧 `ADBMediaMixin` imports 和所有业务断言。`test_diagnostic_artifact_names.py` 额外导入 diagnostics 仅用于 monkeypatch，旧类调用不换。
- [x] **Step 7：源码 parity 检查。** 对比移动前 AST 与新所属类方法：忽略行号，类名引用只允许那三个 `ADBMediaMixin → ADBRecordingMixin` Name 节点变化；按方法名比对参数、装饰器、返回注解和完整函数体；helper 原样。核对完整 Controller 非媒体映射与此前快照一致、媒体映射键值相同；以差异列表记录，禁止用行数/测试通过替代源码核对。
- [x] **Step 8：绿灯和直接验证。** 运行新边界文件及下列直接集合，Ruff/中文注释针对生产新包/旧门面与修改测试。记录实际结果；不声称未执行项通过。
- [x] **Step 9：任务审阅。** 审阅者重点检查 C3、classdict 注册唯一、两处 super、三个显式录屏调用、4 个测试文件 patch 地址、旧构造/非绑定调用；不提交。

直接集合（命令中的 Python 均为 `.\.venv\Scripts\python.exe -m pytest -q`；分行可分批，避免全部混合文件）：

```text
tests/test_phase2_screenshot_gate.py
tests/test_diagnostic_artifact_identity.py::test_log_exports_same_second_get_unique_paths
tests/test_diagnostic_artifact_names.py::test_log_export_names_are_bounded_and_hide_connection_identifiers
tests/test_recording_publication.py::test_recording_controller_preserves_identity_and_existing_stop_retries_once
tests/test_recording_publication.py::test_recording_controller_ignores_old_retry_failure_after_new_capture
tests/test_recording_publication.py::test_recording_retry_submission_error_preserves_retry_entry
tests/test_recording_publication.py::test_recording_shutdown_never_resubmits_retry_or_retains_save_state
tests/test_recording_publication.py::test_recording_retry_capacity_eviction_finishes_original_ui_target
tests/test_model_media_adb.py::test_recording_start_submits_background_save_once_without_duration_timer
tests/test_model_apps.py::test_kill_process_rejects_unicode_digit_pid_without_raising
tests/test_multi_device_network.py::test_pid_operation_rejects_multiple_devices_before_submitting_any_command
tests/test_multi_device_network.py::test_single_device_forward_and_pid_keep_existing_submission_path
```

## Task 2：完整 Controller 协议集成、事实文档与验收

**Interfaces:** 消费 Task 1 的稳定三职责结构；不改运行行为，只验证共享继承链及更新当前事实。失败若来自本次迁移，回 Task 1 最小修复；不并行覆盖共同文件。

- [x] **Step 1：关联验证。** 扩大理由是插入 MRO 节点会影响完整 Controller 的截图/安装协议与模型信号接线；action 消费者需确认只收到正确归属的结果。执行下表，不整跑 `test_phase1_operations.py/test_phase2_install_batch_gate.py/test_action_results.py/test_model_media_adb.py`。
- [x] **Step 2：文档更新。** ARCHITECTURE 说明三个职责 owner、旧组合门面与 classdict 注册；MODULE_MAP 增新模块路径和新边界测试；README/路线图记录本阶段与最终验证限制；不改不受影响的业务流程。
- [x] **Step 3：静态/类型与链接。** `.\.venv\Scripts\python.exe -m ruff check controllers/_media.py controllers/media tests/test_controller_media_boundaries.py tests/test_phase2_screenshot_gate.py tests/test_diagnostic_artifact_identity.py tests/test_diagnostic_artifact_names.py tests/test_model_media_adb.py`；`.\.venv\Scripts\python.exe scripts/check_comment_language.py controllers/_media.py controllers/media`；`.\.venv\Scripts\python.exe -m pyright`（root）；`.\.venv\Scripts\python.exe scripts/check_doc_links.py`；`git diff --check`。root 类型检查由主任务执行一次，区分本轮新增与前置问题。
- [x] **Step 4：源码 packaging 自检。** 标准库包装脚本创建 TemporaryDirectory，复制进程环境并仅覆盖 LOCALAPPDATA/XDG_CONFIG_HOME 为临时目录、QT_QPA_PLATFORM=offscreen，用仓库 Python 子进程执行 `main.py --self-check packaging`；cwd 保持仓库，工具和资源仍真实定位。完成后自动清理，仅临时数据隔离，无机器级环境修改。不得修改运行时工具、版本、spec 或屏蔽自检项。
- [x] **Step 5：最终差异和独立审阅。** 主任务集中审阅 diff/源码 parity/直接及关联结果；失败不跳过，重复验证仅针对新改动或不确定边界。报告公开入口不变、内部 patch 迁移、未运行冻结构建/真机/真实桌面交互，不把源码自检当这些已通过。依据增量策略决定是否有全量触发项；无则不跑全量。

关联集合：

```text
tests/test_phase2_install_batch_gate.py::test_generic_operation_with_opaque_owner_token_routes_through_full_controller_mro
tests/test_phase2_install_batch_gate.py::test_install_operation_protocol_failure_uses_application_terminal_facade
tests/test_phase2_install_batch_gate.py::test_install_protocol_identity_mismatch_fails_closed
tests/test_phase2_install_batch_gate.py::test_cancel_screenshot_cannot_cancel_shared_manager_install_operation
tests/test_phase2_install_batch_gate.py::test_old_screenshot_protocol_failure_cannot_finish_reused_install_generation
tests/test_phase2_install_batch_gate.py::test_released_install_owner_token_disguised_as_generic_is_stale_dropped
tests/test_phase1_operations.py::test_controller_routes_metadata_only_to_registered_vnext_handler
tests/test_phase1_operations.py::test_controller_drops_stale_metadata_instead_of_falling_back_to_legacy_handler
tests/test_phase1_operations.py::test_controller_handler_exception_fails_and_cleans_operation_once
tests/test_screenshot_action_admission.py
tests/test_action_results.py::test_automatic_recording_pull_creates_one_media_result_per_device
tests/test_controller_model_wiring.py
tests/test_controller_model_injection.py
```

## 自审记录

所有方法/注册/patch/协议/生命周期/源码与类型自检要求均有 Task 1 或 Task 2 对应步骤；没有另造新的 public API 或状态机。三个职责共享同一旧文件，按一个实施 owner 完成，避免交错移动。此草案只规定要运行的测试，不表示任何 pytest、Pyright、packaging 已执行。

## 主任务预审与执行裁定


2026-10-24，root。已读取三草案、现有媒体类 imports/注册/方法、base 注册与协议、安装协议和根类组合；设计PASS。

- 三职责对应真实独立协调链，沿用App组合模式；一个owner完整持有旧源、四新源与五测试文件。
- 旧门面不得复制注册表；按完整classdict计数，super必须继续可达安装与base。旧类__new__和非绑定替身路径保留。
- 仅三个录屏显式类引用更换为实际owner，业务函数其余AST必须保真。类型所需注解可保留，但不制造新state初始化。
- datetime/QTimer私有patch明确迁移到实际owner，不保留假的重导出或反向代理；公开类和controller不变。
- 新边界用例不得把草案中的假设当新功能：旧类行为表征若失败，先核实原行为再修测试期待，不改生产迁就。
- root取得直接基线和现存_media类型基线；owner复用。实现和关联测试完成后一次独立任务review，root最终集成。
- root仅对受影响生产路径做Pyright（不采用计划里无路径全项目命令），集中packaging采用已验证的全部临时数据环境变量。
- 子进程与临时清理先校验路径。禁止真实设备、发布、依赖/CI/版本变更与commit/push。

正式文档发布、实施前快照和基线尚待当前Home/Apps批稳定；本文件不表示已实施或验证通过。

root集中Pyright与源码packaging；owner不重复执行这两项。最终自检子进程的LOCALAPPDATA、APPDATA、
XDG_CONFIG_HOME/XDG_CACHE_HOME/XDG_DATA_HOME和MOBILEPERF_LOG_DIR均指向经边界校验的临时目录。

## 实施验证记录（2026-10-24）

十代码/测试路径已冻结。截图、录屏、诊断各自归入controllers/media；旧ADBMediaMixin只组合职责，
保留完整Controller的77普通与2operation处理器。46方法与2helper源码/AST保真，只有三处批准的
录屏显式类引用变更；完整MRO继续到安装和base。四旧测试仅迁移批准的私有datetime/QTimer patch。
25新增、36旧直接、34精确关联全部通过，实际收集集合无交集，共95个不同用例。
结构RED为新模块缺失；错误的新增终态保留预期按原OperationManager事实修正，未改生产。
Ruff发现迁移时遗漏recording的re导入，4个新增提交用例确认NameError后恢复import，红绿闭环；方法体未改。
root五生产Pyright无错误/警告，owner Ruff、中文注释、parity及空白/diff检查通过。
报告、精确命令/真实退出码、节点集合和冻结hash在本阶段忽略目录implementation-report.md及关联记录。
最终综合审阅已通过；不把源码/fake/离屏结果推广为真实录屏或冻结产物验收。

root统一集成：全部数据环境变量隔离后的源码packaging exit0、临时.self_check无残留；
812源码文本检查及diff通过。文档检查初次把计划中的调用语法误识别为链接，改为等义描述后80文档通过；
未修改检查器或生产代码，不重复已通过测试、类型或自检。既有UI-09/UI-10未重验或修复。

## 最终审阅与交付

两个任务Spec/Quality及最终综合审阅均PASS，无P0–P3 findings。95+57=152个不同用例通过，
7生产文件类型无诊断，80文档链接/frontmatter、812源码文本及diff通过。独立核验28固定路径，
包括18代码/测试和10文档；228前置路径中28授权变化、200未变，无范围外漂移。
保留原integration-hashes，状态收尾后另存delivery-hashes；未重复已通过测试/类型/源码自检。
既有UI-09/UI-10、实机/真实桌面/冻结产物仍未验收；全项目持续目标推进下一批服务及worker目录调整。
