# Qt worker 目录归位实施计划

日期：2026-10-24。本阶段实施、任务独立审阅与全项目最终独立审阅均已通过。下文保留设计步骤与实际验收记录。以正式设计及前置验收后的当前源码为准。

前置记录：7个直接测试节点展开为8 passed，0 failed、0 skipped，真实exit 0；两份旧worker生产文件
Pyright为0 errors、0 warnings。基线子进程隔离全部六个数据环境变量并使用offscreen。
以服务阶段交付后的源码保存250个前置路径，保留246项已有脏资产；实施范围13生产与1新增测试，
root负责8份文档、类型、自检与集成。实现完成前不将本记录当作迁移后验收。

## 0. 前置验收与新基线

确认 root 已完成并验收 `services/apps/actions.py`、`archives.py`、`services/file_operations.py` 及对应 adapter。重新读目标 AGENTS、git status 与八个 GUI import 文件 diff。当前旧 app_manager_worker 有既有修改；不从 HEAD/git show 覆盖，不与前置 owner 同时改原文件。

在本忽略目录保存最终两个旧模块源码、SHA256 与 AST 基线；记录导入、顶层定义/赋值、所有 class 方法/Signal、构造参数、__file__ 用法。记录前置已迁走的私有符号，明确它们不是这次要恢复的兼容项。如果服务仍在提取，停止目录实施，仅保留本计划，不锁定现有旧正文。

重新 `rg` 两旧路径、`from models import ...`、patch 字符串、旧 GUI alias 本地工厂，确认当前生产直接消费者仍是设计列明八个文件；新增消费者按真实用途纳入。未发现 __file__ 资源计算方可整体移入；发现后必须核实原资源接口，而非调整 parent 层数猜测。

## 1. 最小直接基线与新红测试

执行前说明：本批边界为两个 Qt 模块位置及八处 import，直接验证身份/patch/导入，关联验证工厂与 Transfer 的完整生命周期；不把前置服务事务全部重新计作本轮。

新增一个专用 `tests/test_worker_module_compatibility.py`，不修改既有测试的旧入口来让它们绕过兼容层。新文件至少以下三种测试，参数矩阵覆盖两个模块：

1. `test_worker_module_import_order_preserves_identity`：old-first/new-first 共四子进程；比较 importlib 返回对象、sys.modules 两 key、models 包子属性、workers 包子属性、全部七类各自对应身份、基类和实际 __module__ 新归属。先验证新入口缺失导致明确红灯；不能把任意子进程失败当有效回归。
2. `test_new_worker_import_does_not_load_model_or_gui_aggregates`：package-only/app_manager/file_explorer 三个新进程。import 前用 MetaPathFinder 阻断 models、controllers、gui、qfluentwidgets 及子模块；允许 PySide6 和原 presentation/application 聚合。package-only 不加载两个 leaf；单 leaf 不加载另一 worker leaf。检查禁止前缀没有预载入。此测试不导入旧入口，否则会与边界自身矛盾。
3. `test_old_module_rebinding_reaches_new_worker_execution`：两个 leaf × 从 old/new 任一别名赋值。先从新类构造实例，再替换旧/新 module 的 load_app_icons 或整个 CommandRunner 绑定，执行真实 worker.run，用 fake 服务/执行器断言结果信号与调用参数。App 用 load_icon_batch 避免设备查询；File 用 ADBWorker。每个 mock 没有外部调用；构造前 patch 情形用参数扩展即可。不要只比较模块属性相等而不执行真实方法；只 patch CommandRunner.run 类方法不足以发现静态 reexport 的 module 分离错误。

子进程用 sys.executable 和临时环境，超时有界，输出失败 stderr；不复制仓库、不开真实设备。root 统一给所有子进程临时 LOCALAPPDATA/XDG_CONFIG_HOME 等当前数据目录、既有 legacy 设置路径隔离，检查实际设置读取源；仅改 cwd 或 QT_QPA_PLATFORM 不足以证明用户数据隔离。旧优先探针允许 models 聚合，绝不把它误标成新入口边界失败。

## 2. 单 owner 整体移动并保留 shim

新增 workers/__init__.py 仅说明。将前置验收后模块完整复制到两个新 owner，保留所有实际 globals 名/导入和原类正文；旧文件替换为设计的 sys.modules alias。

对 shim 的 TYPE_CHECKING 导出，按最终 AST 列出需要静态可见的原绑定：至少 AppManagerWorker 与六文件类，及实际保留的 module 级依赖/类型、现存私有静态消费者；显式 `from new import name as name`。应保持原可见符号而非仅为 Pyright 当前报错补一点；不加 import *，不把前置已删的 os/shutil/_resolve_target 等重新引回来。新旧公开 __all__ 若前置有则按原契约处理，没有则不新建收紧 wildcard 范围的 __all__。

旧 alias 不改 module __class__、__name__、__module__、__spec__，不添加 get/set 转发。新 owner 不主动注册旧 sys.modules key，避免新导入隐式制造 models 子模块假象或跳过父包属性绑定。

仅替换以下 import 来源，所有使用处不改。来源变化后的目标 import 可按现有 Ruff I001 规则移动位置或换行；其余导入的相对顺序保持：

| GUI 文件 | 新来源/保留名字 |
| --- | --- |
| app_manager/page.py | adblab.presentation.workers.app_manager.AppManagerWorker；保留 F401 接缝注释 |
| app_manager/details.py | 同上，独立本地工厂 |
| app_manager/icons.py | TYPE_CHECKING 同上；运行时 `.page` 延迟导入不改 |
| file_explorer/page.py | file_explorer.ADBWorker、TransferWorker |
| file_explorer/list.py | file_explorer.ADBWorker、DirectoryListWorker |
| file_explorer/view.py | file_explorer.TextReadWorker |
| file_explorer/ops.py | file_explorer.LocalTextSaveWorker、TextSaveWorker |
| file_explorer/transfers.py | file_explorer.ADBWorker、TransferWorker |

models/__init__、presentation/__init__、gui/dialogs 兼容层、GUI batch 延迟工厂、services 全部不改。不要迁移测试文件或 conftest，也不迁移前置阶段已正确指向 service 的 patches。

## 3. 直接与关联节点

运行新增专用文件，然后运行以下已从现有源码核实的节点。实际命令 `.\.venv\Scripts\python.exe -m pytest -q <path>::<node>`；Qt 节点使用 offscreen，数据环境由 root 隔离。参数化节点不给具体 id，保留整组参数。以下旧文件均不整文件扩大。

直接 globals/旧类执行：

- `tests/test_app_detail_budget.py::test_detail_batch_has_backend_budget_without_retry_after_failed_command`
- `tests/test_app_metadata_worker.py::test_metadata_worker_publishes_unicode_without_dumpsys`
- `tests/test_app_metadata_worker.py::test_unsupported_fallback_spends_only_remaining_query_budget`
- `tests/test_app_icons_service.py::test_icon_worker_dispatches_packages_and_relays_png`
- `tests/test_app_icons_service.py::test_icon_worker_runs_in_background_and_abort_reaches_service`
- `tests/test_model_media_adb.py::test_file_explorer_worker_uses_command_runner_for_short_commands`
- `tests/test_model_media_adb.py::test_file_explorer_worker_passes_custom_timeout_to_command_runner`

GUI 工厂/页面 ownership 关联：

- `tests/test_app_manager_module_compatibility.py::test_old_page_worker_patch_reaches_collaborators`
- `tests/test_app_manager_module_compatibility.py::test_details_worker_patch_remains_independent`
- `tests/test_file_explorer_module_compatibility.py::test_old_page_worker_patch_is_used_by_commands`
- `tests/test_file_explorer_module_compatibility.py::test_old_list_worker_patch_is_used_by_refresh`
- `tests/test_file_explorer_visual.py::test_file_double_click_menu_reaches_transfer_or_inline_preview`（TextRead 来源及 args 消费）
- `tests/test_file_explorer_text.py::test_local_save_runs_off_gui_and_preserves_preview_bytes`（ops 保存 worker 新来源；前置 owner patch 应已迁好）
- `tests/test_action_feedback.py::test_app_manager_worker_feedback_reaches_page_before_worker_cleanup`（成功/失败 Signal 与 finished 清理顺序）

TransferWorker 位置改变虽方法不变，仍需覆盖 QThread 与 ProcessRunner 身份和关闭耦合：

- `tests/test_file_explorer_transfers.py::test_cancel_only_requests_stop`
- `tests/test_file_explorer_transfers.py::test_cancel_before_run_never_launches`
- `tests/test_file_explorer_transfers.py::test_force_stop_keeps_residual_until_actual_process_exit`
- `tests/test_file_explorer_transfers.py::test_cancel_during_start_reissues_stop_and_preserves_live_process`
- `tests/test_file_explorer_transfers.py::test_cancel_unblocks_stdout_reader`
- `tests/test_file_explorer_transfers.py::test_natural_completion_join_race_retries_terminal_without_abort`
- `tests/test_file_explorer_transfers.py::test_start_failure_delivers_terminal_and_cleanup_once_despite_callback_failure`
- `tests/test_file_download_security.py::test_pull_worker_cancel_unblocks_raw_download_without_publishing`

以上足以覆盖改动 import 指向与实际生命周期，默认不重跑整个应用/文件业务服务矩阵、不跑全量。若 alias 导入顺序影响 GUI feature 的既有懒加载，再追加两份 module_compatibility 中 `test_each_module_import_order_preserves_identity` 与各自懒加载节点；没有证据不重复每个旧 GUI alias 的全部组合。

前置新 adapter 文件的测试名不能假定今日草案即最终实现。实施前读取实际 AST；若已有一个节点覆盖本批新来源未覆盖的构造/信号，选择该节点并记下理由，不把未存在名称写成已执行命令。

## 4. 静态 parity、类型与集成

对两个原最终模块与新 owner 做 AST 完整比较（忽略位置信息，最多允许 module docstring 文本变化）；尤其完整 TransferWorker、QThread Signal/构造/装饰器必须一致。GUI 八文件分别核对目标 import 的名称/alias/作用域不变，仅来源及合规排序位置变化；移除该条 import 后，其余完整 AST 及导入顺序必须相同，不将所有 import 无序化掩盖差异。shim 仅固定 imports/TYPE_CHECKING 导出/sys.modules 替换；workers 包 docstring-only。搜索所有生产旧 worker import，应该只剩 shim 无新增反向依赖；tests 保留旧路径是预期。

root 统一 Ruff（两个新模块、三个新/旧包入口或 shim、八个 GUI 文件和新测试），中文注释与源码文本检查、git diff --check。没有新增运行依赖/资源/spec/CI。必要 Pyright 最小范围明确为：

```text
adblab/presentation/workers
models/app_manager_worker.py
models/file_explorer_worker.py
gui/features/app_manager/page.py
gui/features/app_manager/details.py
gui/features/app_manager/icons.py
gui/features/app_manager/batch.py
gui/features/file_explorer/page.py
gui/features/file_explorer/list.py
gui/features/file_explorer/view.py
gui/features/file_explorer/ops.py
gui/features/file_explorer/transfers.py
```

batch 未修改，但动态读取 page.AppManagerWorker 是真实类型消费者；所以列为关联类型范围。若旧 gui/dialogs TYPE_CHECKING 指向的再导出出现类型错误，按具体错误扩大对应 shim，不能无理由全树重查，也不能降低标准。

root 在隔离临时用户数据环境统一 `main.py --self-check packaging`，检查现有工具/资源边界；新路径静态可达性由导入对照确认，旧/新入口可导入由兼容测试确认。源码自检不证明 PyInstaller 已收集全部 worker，不为此新增 hiddenimports，不默认完整构建。root 按最终事实同步 MODULE_MAP/必要架构归属并跑相应 docs 门禁。源码自检、fake/离屏结果不能证明真实设备、桌面关闭或 PyInstaller 产物。

完成报告须区分：迁移的两个实现、保留的旧同模块入口、GUI import 八处、实际节点及结果、旧入口 eager 成本、前置阶段私有 patch 已迁而未恢复、未验证环境。不 commit、不动 userdata，不将设计静态核实写作运行通过。

## 主任务预审与执行裁定


2026-10-24：设计及计划 PASS；执行依赖是 actions/archives 与 file_operations 两阶段验收，尚未允许并发迁移其 worker。
用户已授权目录结构和架构持续重构，无须重复批准。此处是技术依赖，不是用户授权等待。

- 单 owner 负责两个实现整体归位、两个同模块 shim、docstring-only 包入口、八个 GUI import 与一个新增测试。
  前置服务必须稳定后重新读取源码、符号表及现有消费者；不能从 HEAD 或本次设计时的快照搬正文。
- 整模块 alias 沿用已验收 GUI 兼容方案；新 owner 不主动注册旧 key，不导入 models，不伪造 __module__。
  TYPE_CHECKING 显式导出最终实际绑定，既保证静态可见，也不复活前一阶段已删除的私有业务符号。
- 七个类完整正文/Signal/构造和全部真实 globals 原样移动；TransferWorker 仅迁目录，不再拆解其生命周期。
  GUI 八处只改 import，尤其 page/delayed batch/icons 与 details 独立工厂关系保持。
- 独立子进程分别覆盖新/旧优先、父包属性、模块与类身份、真实 globals 重绑定执行；构造前后替换用少量参数覆盖。
  package-only 不加载 leaf，新入口不加载 models/GUI；允许原 presentation/application 聚合，旧入口 eager 成本如实说明。
- 基线与迁移后仅计划22个旧节点及新兼容文件；按真正重叠nodeid去重。若前置新增adapter提供缺失覆盖，按证据选择一个节点，
  不重跑已验收全部事务。root类型范围包括八个GUI与未修改但真实依赖page工厂的batch，以及两个shim和新包。
- root统一文档、类型、自检、最终审阅；实现owner执行自己的lint/注释/parity与直接关联测试即可。
  全部子进程数据入口和源码packaging用临时环境隔离；未验证的实机/桌面/冻结产物保持未验证。
- 本次仅预审草案和当前依赖证据，未运行此阶段测试或生产导入，也未修改生产。


## 实施验证记录（2026-10-24）

状态：实施、任务独立审阅及全项目最终独立审阅均已通过。
13生产与1新测试已冻结。两个新worker模块和前置验收源码逐字节、完整AST相等；七类与全部真实globals原样移动。
八处GUI目标import保留名称、alias与作用域，仅来源及合规排序/换行调整；移除该条后其余完整AST与导入顺序相等。
旧两个models入口是同模块alias并提供全部实际绑定的显式静态导出；新workers包仅说明，不主动注册旧key。

新兼容矩阵先取得15项明确缺入口RED，迁移后15 passed；旧7直接节点展开8 passed，15关联节点展开26 passed。
三组无交集，最终49个不同用例，0 failed、0 skipped。Ruff首轮发现新来源的排序/长行问题，仅整理目标import与
新shim/test；完成后新15和关联26重跑通过，未改变的worker正文对应direct8不重复。不得累计重复GREEN次数。
Ruff14文件、中文注释13生产、范围差异及parity通过；root实际14生产Pyright为0 errors、0 warnings。
全部子进程使用六数据环境变量临时隔离，新导入探针额外隔离legacy入口，不创建真实设备命令。
源码packaging隔离执行exit 0、无.self_check残留且临时目录清理；只证明现有工具/资源边界，不证明冻结收集。
具体命令、退出码、nodeids、哈希及对照证据见本阶段忽略目录owner-report与root-validation。
以上为送审时的实施验证记录；独立审阅后的最终状态见下节。

## 最终独立审阅与交付

任务Spec/Quality及全项目独立终审PASS，无待解决的新增finding。本阶段49个不同用例通过，
14生产文件Pyright无诊断；Ruff、中文注释、文档、源文本和差异检查通过。源码packaging使用六个数据环境变量隔离，
真实exit 0且无探针残留。固定范围14代码/测试和8文档，其余前置资产保持；最终状态另存delivery清单，
不覆盖integration或全项目终审快照，不重复未变的测试/类型/自检。
完整迁移七类和实际globals，旧两模块保持同身份兼容；八个GUI仅改目标import来源及合规排序。
必要架构与目录阶段现已全部完成，保留模块依据及仍未验证边界见[路线图](2026-10-23-project-refactor-roadmap.md)。
未运行全量pytest、实机、真实桌面关闭或冻结构建；没有提交或推送。
