# GUI Feature Packages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将 FileExplorer、AppManager、Performance 的页面及协作者归入各自功能包，完整保留旧入口和行为。

**Architecture:** 每簇拥有独立新包，旧 dialogs 模块通过静态导入和 `sys.modules` 指向同一实现。
包公开入口延迟加载页面，内部只使用新相对导入；模型、服务、生命周期和配置边界保持不变。

**Tech Stack:** Python 3.11、PySide6、现有 qfluentwidgets、pytest、Ruff、Pyright。

**Spec:** [GUI 功能包设计](../specs/2026-10-24-gui-feature-packages-design.md)。执行者须同时阅读设计和本计划。

## Global Constraints

- Python 3.11 + PySide6，使用现有 `.venv`，不增加依赖、不改 CI/发布、不提交或暂存。
- 保持公共入口、类/方法/信号、配置与数据格式、设备准入、视觉交互和平台兼容。
- 不移动 models、services、共享 dialogs 工具、用户数据、运行时工具或二进制资源；不操作真实设备。
- 现有未提交成果为前置资产，特别是 Performance 对 `services.performance.config/results` 的新导入。
- 用户已授权自主连续实施；不额外请求设计批准。主任务先完成快照与独立 builder check，再分配文件。
- 不批量改旧测试导入。不得通过跳过/减弱测试或移动替换点让兼容测试通过。

## Review Focus

1. 单独先导入协作者：不得经包入口强制加载 page；各任务新增 fresh-process 导入测试。
2. 旧路径 patch 与新入口组合：实际构造必须读取 patch；各任务新增调用行为测试，不只比较类名。
3. AppManager 详情页与主页面同时替换 worker：保持两处独立绑定；Task 2 覆盖各自调用及原用户快照测试。
4. Performance 旧代次结果与关闭重叠：仍先归档再释放、真正 join 后才撤销引用；Task 3 保留生命周期测试。
5. FileExplorer 失选后的取消/临时文件清理：保留原设备和清理 token；Task 1 保留传输/预览测试。

## 文件所有权和执行顺序

设计迁移表为精确生产文件清单：Task 1 独占其中 7 对 FileExplorer 文件，Task 2 独占 8 对 AppManager 文件，
Task 3 独占 6 对 Performance 文件；另分别独占对应旧 `gui/features/<feature>.py` 门面和新包 `__init__.py`。
新实现/旧 shim 总是由同一个 owner 同时修改。下面专属新测试也只归该 owner。

主任务独占本计划/设计、路线图、`docs/README.md`、`ARCHITECTURE.md`、`MODULE_MAP.md` 与忽略工作区记录。
`gui/features/__init__.py`、`gui/dialogs/__init__.py`、MainFrame、共享生命周期、`tests/conftest.py` 和
其余既有生产/测试文件不分配给 Task 1/2/3；发现必须修改时先报告主任务，不跨文件所有权编辑。
现有测试只运行；确需增补则优先写各簇专属兼容测试，不与前置成果冲突。

三任务无相互产物依赖，可在前置阶段验收后并行；独立测试命令不要同时操作同一持久化测试目录。
主任务负责收集基线、决定共享集成范围及独立审阅。本文编写时尚未运行本阶段 pytest 基线。

## 通用迁移与测试契约

三个新兼容测试文件各自定义设计表的 `MODULE_PAIRS`，参数化 `old_first=True/False`。
用现有 Logcat 兼容测试方式，在 `sys.executable` 启动的独立进程中断言：

```python
first_module = importlib.import_module(first_path)
second_module = importlib.import_module(second_path)
assert first_module is second_module
assert sys.modules[old_path] is sys.modules[new_path]
assert getattr(importlib.import_module("gui.dialogs"), old_leaf) is second_module
assert getattr(importlib.import_module(package_path), new_leaf) is second_module
```

进程采用仓库 cwd、`QT_QPA_PLATFORM=offscreen`、30 秒 timeout、捕获并报告退出码/stdout/stderr。
检查公开名 `from gui.features.<feature> import X` 与新旧实现中的类为同一对象；未知包属性抛
`AttributeError`。在分别独立的进程中验证 package-only 和指定 leaf-first 的懒加载：
Task 1 用 `preview_tasks`，Task 2 用 `rows`、`details`，Task 3 用 `result_tasks`；访问公开页名前 page 不在
`sys.modules`，自身旧 shim 和另两簇的实现也不被加载。不要要求整个 Qt/Fluent 栈零导入。

每个 shim 使用静态实现导入、显式 `TYPE_CHECKING` 重导出和 module alias。按设计保留原属性面，
从迁移前快照的 AST 定义及消费者核对静态导出清单，包括 `_ImageRequest`、`PreviewIdentity`、
`_TransferThread`、`_QueuedTransfer`、`_ActivePerformanceRun` 等私有/类型名称，不以 `__all__` 推断。
新包入口定义 `__getattr__(name: str)`，准确返回设计指定公开类；不建立通用动态导入注册器。

### Task 1: FileExplorer 功能包

**Exclusive files:** 设计表的 7 对 FileExplorer 路径；`gui/features/file_explorer.py`；
`gui/features/file_explorer/__init__.py`；新增 `tests/test_file_explorer_module_compatibility.py`。

**Interfaces:** 消费现有 `FileExplorerPage`、`FileExplorerList`、`FileExplorerOps`、`FileExplorerView`、
`FileTransferCoordinator` 等原签名；产出同名类和方法的新实现，旧模块 alias 与原公开入口保持可用。
`_run_adb(self, *args, timeout: int = 30, _cleanup: bool = False, _device_ip=None)`、
`_run_transfer(self, *args, _device_ip=None)` 的准入及返回约定不变。

- [x] 读取上述文件当前 diff、相关测试及设计 FileExplorer 节；记录主任务快照标识。
- [x] 取得直接基线（迁移前）：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_file_explorer_transfers.py tests/test_file_explorer_preview.py tests/test_file_explorer_text.py`。
- [x] 在新测试文件实现通用契约；另加 `test_old_page_worker_patch_is_used_by_commands`，用禁止
  start 的实际 worker 子类替换旧 page 的 ADB/Transfer worker，从新入口页面调用两个工厂，断言
  返回对象是该子类、保留参数和设备、被页面追踪且 QObject parent 正确；测试结束关闭释放。
- [x] 加 `test_old_list_worker_patch_is_used_by_refresh`：替换旧 list 的 `DirectoryListWorker`，
  新入口页面刷新后断言活动 worker 是替换类型、携带请求路径/代次且 start 被调用，禁止真实 ADB。
  view/ops/preview_tasks 的完整模块身份已由通用契约验证；复用既有 text/preview/transfers 中
  的读取、保存、旧模块 LogService/QImageReader/文件框 patch 与清理回归，不新增四套同形 worker fixture。
- [x] 运行新测试确认新包缺失导致失败；不要将既有基线失败误认为预期红灯。
- [x] 按表移动唯一实现、建立 shim 与懒入口；更新包内、函数内和 TYPE_CHECKING 导入；
  保持 view/preview_tasks 的独立常量、transfers 模型类型引用及所有 worker 构造位置不变。
- [x] 重跑新测试与直接集合；随后关联验证目录事务、呈现和旧路径 patch：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_file_explorer_population.py tests/test_file_explorer_ordering.py tests/test_file_explorer_mutations.py tests/test_file_explorer_search.py tests/test_file_explorer_rename.py tests/test_file_explorer_focus.py tests/test_file_explorer_visual.py`。
- [x] 执行下述本簇静态检查，报告 diff、基线/结果及限制；不提交。

### Task 2: AppManager 功能包

**Exclusive files:** 设计表的 8 对 AppManager 路径；`gui/features/app_manager.py`；
`gui/features/app_manager/__init__.py`；新增 `tests/test_app_manager_module_compatibility.py`。

**Interfaces:** 保留 `AppManagerPage`、`AppSortProxy`、`AppDetailsPage` 原签名、信号和行为；
协作者继续消费原 page 对象。details `_rw(self, op, *, _generation=None, _finished_part=None, **kw)`
使用 details 模块 worker；主页面协作者晚绑定 page 模块 worker，不共享新的工厂状态。

- [x] 读取当前 diff、设计 AppManager 节及 worker 替换测试，记录快照标识。
- [x] 取得直接基线：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_selection.py tests/test_app_manager_user_context.py tests/test_app_manager_icon_lifecycle.py`。
- [x] 新测试实现通用契约及 `test_old_page_proxy_patch_is_used_by_form`：旧 page 的 `AppSortProxy`
  替换为可记录子类，从新入口构造页面，断言 `page.proxy` 使用该子类。
- [x] 加 `test_old_page_worker_patch_reaches_collaborators`：从新入口创建页面，旧 page patch 后分别
  触发 views 列表查询、batch 操作、icons 图标批次；断言 fake 收到原 operation、包名及 Android
  用户参数。沿 population/user_context/icons/batch_budget 的受控快照前置条件，禁止真实 worker。
  加 `test_details_worker_patch_remains_independent`：对旧 page/details 赋不同 fake 工厂，通过
  新 `AppDetailsPage._rw` 和主页面加载分别断言只命中各自工厂，结果保留用户和代次。
- [x] 运行新测试确认缺少新包的失败后迁移；form/views/batch 方法中用 `from . import page as
  _app_manager`，icons 方法内从 `.page` 获取 worker；details 保留原模型 worker 顶层绑定。
  把其余内部 imports 改为新路径，懒入口按公开名分别导入 page/details；保留 rows 常量。
- [x] 新测试、直接集合通过后，扩大到协作、布局和渲染消费者：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_population.py tests/test_app_manager_metadata.py tests/test_app_manager_icons.py tests/test_app_manager_batch_budget.py tests/test_app_manager_visible_scan.py tests/test_app_manager_material.py tests/test_app_manager_column_fill.py tests/test_app_manager_header_sort.py tests/test_app_manager_status_layout.py tests/test_app_manager_visual.py`。
- [x] 执行本簇静态检查并报告；models 的恢复/设备测试不是本次迁移默认扩围范围，不提交。

### Task 3: Performance 功能包

**Exclusive files:** 设计表的 6 对 Performance 路径；`gui/features/performance.py`；
`gui/features/performance/__init__.py`；新增 `tests/test_performance_module_compatibility.py`。

**Interfaces:** 保留 `PerformancePage`、`CurrentPackageWorker`、`PerformanceLauncherRun`、
`PerformanceResultLoader` 等签名；`PerformanceResultLoader.submit(self, query, *, active=None,
exit_code=None, had_config=True, cancelled_run=False, present_result=True)` 不变。
输入服务对象必须仍是前置 `services.performance.config/results` 中的原类，运行器保持原位置。

- [x] 读取当前 diff（这些旧模块已有前置服务抽取修改），按当前工作树迁移，不从 HEAD 取旧版本。
- [x] 取得直接基线：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_performance_start_lifecycle.py tests/test_performance_package_lifecycle.py tests/test_performance_result_loading.py tests/test_performance_library.py`。
- [x] 新测试实现通用契约及 `test_old_page_package_worker_patch_is_used`：旧 page 替换
  `CurrentPackageWorker`，从新入口查询包名，断言 `_package_worker` 是替换类型且查询按钮锁定。
  使用不启动线程的子类，按既有 lifecycle 清理路径释放。
- [x] 加 `test_old_run_and_result_worker_patch_is_used`：分别替换旧 run 的 `PerformanceStartWorker`
  和旧 result_tasks 的 `PerformanceResultWorker`，通过新控制器 start_mobileperf/submit 断言使用替换对象、
  config/query/代次不变、拥有正确 QObject parent；禁止真实进程。保留原生命周期测试的 join 验证。
  加 `test_performance_service_types_keep_identity`：比较新 page/form/library/run/result_tasks 引用的
  配置/结果类与服务定义 `is` 相同；`CONFIG_HINTS`、`MONKEY_PERCENT_FIELDS` 在新旧模块为同一对象。
- [x] 新测试确认红灯后按表迁移、建立兼容 shim 与懒入口；保留服务新导入和 page 对运行器的导入。
  page 内结果加载器导入改 `.result_tasks`，library 的类型引用改 `.page`，不改归档/停止逻辑。
- [x] 新测试、直接集合通过后扩大到表单与会话消费者：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_model_performance_launcher.py tests/test_performance_inline_fields.py tests/test_performance_compact_layout.py tests/test_performance_responsive.py tests/test_performance_sessions.py tests/test_performance_progress.py`。
- [x] 执行本簇静态检查并报告；已稳定且未改的 services 配置/结果隔离测试不重跑，服务类身份由
  新兼容测试覆盖；不重复整个 MobilePerf runner 集、不构建产物、不提交。

## 各 owner 的验证约定

Qt 测试先设置 `$env:QT_QPA_PLATFORM = 'offscreen'`。先明确“本簇迁移 → 上述直接集合 → 关联消费者”
再执行；记录命令、退出码、通过/失败/跳过数量，不把环境失败或源外字体差异表述为通过。

- `.\.venv\Scripts\python.exe -m ruff check <本簇新包、旧shim和新测试>`。
- 各 owner 不重复运行 Pyright；将新包与旧 shim 清单交主任务，由主任务统一使用当前解释器
  实际 `sys.path` 生成忽略工作区中的临时配置后验证，避免已知 missingImports 环境噪声。
- `.\.venv\Scripts\python.exe scripts/check_comment_language.py <本簇新包和旧shim>`。
- 定向检查本簇新实现无回导自身旧 dialogs 路径（共享 lifecycle/fluent_dialog 允许）。
- `git diff --check`；静态检查路径展开为本任务精确所有权集合，不能以整个脏树代替。

### Task 4: 主任务集成、文档与独立审阅

**Exclusive files:** 本计划/设计、路线图、`docs/README.md`、
`docs/project-knowledge/ARCHITECTURE.md`、`docs/project-knowledge/MODULE_MAP.md`、阶段忽略记录。
不修改共享生产文件，除非实际失败表明确有需要且另行冻结边界。

**Interfaces:** 消费 Task 1/2/3 的兼容入口、新包和验证记录；产出同一工作树集成结论和目录现状文档。

- [x] 实施前保存所有目标文件及工作树差异快照，独立 builder check 后才派发；记录三组排他所有权。
- [x] 收齐每组直接、关联、静态结果及独立代码审阅；失败先区分新增、前置和环境原因，不放宽断言。
- [x] 共享宿主只运行真实页面创建、设备切换、关闭重建节点（包含 MainFrame 实际组合）：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_workspace_feature_host.py::test_all_pages_device_selection_and_reopen_without_transient_windows`。
- [x] 设备准入选择调用本次页面实现的节点：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_file_app_device_admission.py::test_fixed_page_rejects_new_operations_without_selected_online_target tests/test_file_app_device_admission.py::test_fixed_page_uses_only_its_selected_device_in_multi_selection tests/test_file_app_device_admission.py::test_root_pull_stops_next_transfer_but_cleans_prepared_file tests/test_file_app_device_admission.py::test_started_transfer_finishes_on_original_device_without_refresh_after_deselection tests/test_file_app_device_admission.py::test_finished_app_batch_does_not_schedule_unselected_device_refresh tests/test_file_app_device_admission.py::test_embedded_pages_wait_for_host_selection_before_initial_load`。
- [x] 语言检查只选择三个功能页相关呈现与稳定值节点：
  `.\.venv\Scripts\python.exe -m pytest -q tests/test_dialog_languages.py::test_business_pages_and_error_toast_render_english tests/test_dialog_languages.py::test_translated_file_type_keeps_directory_navigation_key tests/test_dialog_languages.py::test_permission_submission_uses_raw_names_after_translation tests/test_dialog_languages.py::test_app_filter_uses_stable_values_with_english_labels`。
  不重跑整个 mainframe_startup/dialog_languages/workspace_host；已验收 Controller/APK/partial-startup、
  未改变的 registry 契约和共享 window_lifecycle 实现不属于本轮。各 owner 已通过且之后未改的专属
  集合不默认重跑；需要组合污染复现时记录具体原因与最小集合。
- [x] 主任务以 `.venv` 实际 `sys.path` 生成阶段忽略目录内临时 Pyright 配置（不修改仓库类型配置），
  include 仅为三组新包和旧 shim，保留项目严格规则；运行
  `.\.venv\Scripts\python.exe -m pyright --project <临时配置路径>`，将前置诊断与新增诊断分别报告。
- [x] 核对源码静态导入可达性及三组全模块双顺序 probes，运行
  `.\.venv\Scripts\python.exe main.py --self-check packaging`。该命令只给源码打包清单自检结论。
- [x] 更新模块地图的结果库/功能页/性能条目、架构的功能包边界、README 索引与路线图阶段状态；
  保留服务/Logcat 前置成果。运行 `.\.venv\Scripts\python.exe scripts/check_doc_links.py`、
  `.\.venv\Scripts\python.exe scripts/check_source_text.py`、`git diff --check`。
- [x] 最终独立审阅须检查双顺序模块身份、真实 worker 替换、AppManager 回读时机、Performance 服务
  imports、配置和生命周期未变；审阅修复只重跑受影响的直接/关联集合。
- [x] 在本计划追加真实验收结果和限制，说明未做冻结构建/真实 GUI/设备验证。未触发测试指南全量条件
  时不全量 pytest。阶段收口后按总路线图继续，不将此阶段等同整个持续目标完成。


## 验收记录

2026-10-24 已完成：21个实现模块归入FileExplorer/AppManager/Performance功能包，旧模块同身份
兼容及原替换点保留。三路独立Spec/Quality审阅和最终综合审阅均PASS，无新增findings。

不重复用例：FileExplorer279通过、23平台跳过；AppManager247通过、1既有失败；Performance204
通过；主任务宿主/准入/语言20通过，合计750通过、1既有失败、23跳过。兼容重复执行和基线不叠加。
性能结果/库迁移前基线复用上一阶段未变代码证据，新增启动/包查询基线20通过；未回退性能服务依赖。

AppManager唯一失败为status layout [340-22]：选择计数宽109小于minimumSizeHint119。将迁移前
八模块快照与迁移后实现置于同一解释器、offscreen、字体及原测试/fixture下，均复现同一断言。
保留原断言、未增加skip；该证据说明本批迁移未引入，不确定布局根因、历史HEAD或真实桌面表现。
FileExplorer跳过均为既有平台契约，22项POSIX文件名/模式/symlink、1项Windows dangling-link。

45生产文件Pyright为0错误/0警告；各owner Ruff与中文注释检查通过。源码packaging self-check
退出0；源码文本762文件、文档链接/frontmatter64文档及git diff --check通过。审阅冻结51个路径，
116份前置快照经独立核对；忽略工作区保存原始命令、日志、固定补丁及审阅报告。

文档所有权扩展到UI_IMPLEMENTATION与RISKS_AND_DEBT，先补2份快照再改实现链接，并登记UI-09。
未执行全量pytest、完整PyInstaller构建、冻结产物验证、真实GUI/DPI视觉或设备验收；源码清单、
离屏和类型通过不代表这些行为通过。没有提交、暂存或清理既有成果。持续目标继续下一阶段。
