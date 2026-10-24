# Media Feature Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 ScreenshotPage 和五个协作者归入 media 功能包，保留旧入口、globals 替换及所有图片会话行为。

**Architecture:** 页面实际定义从 `media.py` 迁至 `media/__init__.py`，保留 eager 入口；协作者归 sibling 模块。
五个旧 dialogs 以静态 import 和 `sys.modules` alias 指向唯一实现，不使用动态代理。

**Tech Stack:** Python 3.11、PySide6、现有 pytest/.venv；不新增依赖。

**Spec:** [Screenshot 功能包目录设计](../specs/2026-10-24-media-feature-package-design.md)。

## Global Constraints

- 保留公开入口、对象/Signal 身份、旧 patch 接缝、现有 UI、资源路径和平台行为。
- Python 3.11 + PySide6，使用仓库 `.venv`，不增加依赖，不改 CI、发布、版本或用户数据。
- 用户已授权目录调整、自主连续与并行；不重新问批准，不暂存或提交。
- 保留全部在途成果；不改 MainFrame、controllers/models、共享生命周期、tests/conftest.py 或既有测试入口。
- 代码只移位置并改包内 import，其他行为以设计不变量为准；生产注释/docstring 使用中文。
- 主任务先独立 builder check，再派单一 Media owner 实现；共享文档由主任务串行维护。

## Review Focus

1. 旧路径先导入时包 eager 初始化不得发生循环失败；Task 1 每对模块的双顺序子进程覆盖。
2. 旧 worker/reader patch 必须影响真实导航、添加与删除动作；Task 1 held worker 和 reader 参数覆盖。
3. 页面 globals 替换不得因 re-export 失效，关闭监督不能失去页面 worker；Task 1 shutdown factory 及原生 join 覆盖。
4. 同路径新图、权限失败、取消后晚到结果不得删除或追加错图；Task 1 直接 I/O 和页面回归覆盖。
5. 新目录不得丢失不受信图片格式限制、宿主延迟批次或静态打包可达性；Task 2 安全/宿主节点和 packaging 覆盖。

## 文件结构与独占范围

迁移全部精确源、目标、符号和静态导出见设计表，不复制第二份表维护。
Create: `gui/features/media/{__init__,actions,nav,tasks,ui,widgets}.py`、`tests/test_media_module_compatibility.py`。
Replace: `gui/dialogs/screenshot_viewer_{actions,nav,tasks,ui,widgets}.py` 为 shim。
Move: `gui/features/media.py` → 新包入口，完成后旧单文件不存在。
主任务维护本 spec/plan、`.superpowers/sdd/2026-10-24-media-feature-package/design-notes.md` 及共享知识库。

## Task 1: 兼容契约与完整截图簇迁移

**Files:** 上述 Media owner 的全部文件；测试仅新增 `tests/test_media_module_compatibility.py`。

**Interfaces:** 消费现有页面的 `activate(payload=None)`、`request_dispose(reason)`、`register_shutdown_tasks(supervisor, *, owner_id, task_prefix)`；
产出相同 `gui.features.media.ScreenshotPage`，方法签名与信号不变，五对模块 alias 身份不变。
worker 接口保持：Read `(generation, paths, cache, reader_factory, parent=None)`；
Delete `(paths, versions, parent=None)`；Validate `(paths, reader_factory, parent=None)`；
ShutdownTask 沿用 `QThreadGroupShutdownTask` 构造与监督接口。

- [x] **1. 取得范围快照和直接基线。** 读根与局部规则、当前六源 diff；记录哈希/差异，不覆盖用户资产。
  说明“目录/模块兼容 → 两份截图直接测试 → 后续只扩宿主和格式安全关联”。运行：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests/test_screenshot_page.py tests/test_screenshot_io.py
```

  记录实际结果；已有失败先定位和上报，不把前批全部脏工作树纳入本轮。

- [x] **2. 新增失败的兼容用例。** 新文件导入 Qt/页面放在函数内，GUI 用例显式 ui marker 并请求 `qt_application`；
  不修改 conftest。按以下精确测试名和断言实现，参数化用例可共用 helper：

| 新测试名 | 测试设置与必须断言 |
| --- | --- |
| `test_each_media_module_import_order_preserves_identity` | 五对 actions/nav/tasks/ui/widgets × old-first/new-first，每项独立子进程，`sys.executable`、仓库 cwd、offscreen、30 秒超时；`first is second`、sys.modules 两路径相同、两父包属性相同；全体原定义符号对象相同，包括 ImageKey、常量和私有 helper |
| `test_media_public_entry_keeps_real_globals` | `media.__all__ == ["ScreenshotPage"]`；`ScreenshotPage.__module__ == "gui.features.media"`；`_start_io_worker`、`_reap_io_workers`、`register_shutdown_tasks` 的 `__globals__ is vars(media)`；入口位于 `__init__.py` 且源码存在类定义 |
| `test_old_nav_worker_and_reader_patch_reaches_navigation` | 旧 nav 替换为真实 ReadWorker 的 held 子类（覆写 start 记录而不启动）、reader sentinel；空页 activate 临时图片；实际 nav worker 是 held 类型，reader_factory 是 sentinel，paths 当前图优先，worker 在 page._workers 且 start 被请求 |
| `test_old_actions_worker_and_reader_patch_reaches_add` | 旧 actions 替换真实 ValidateWorker 的 held 子类及 reader sentinel、文件框返回 tmp_path 图片；调用 page._add_images；实际 page._add_worker 为 held、reader_factory/paths/parent 正确且注册启动；重复动作不创建第二 worker |
| `test_old_actions_worker_patch_reaches_delete_snapshot` | 先完成真实临时图读取；旧 actions 替换真实 DeleteWorker 的 held 子类；调用 page._delete_all_files；实际 worker 路径为原 tuple、versions 为独立相等 dict、parent 为 page；后续到图和重复删除不扩大该快照 |
| `test_media_shutdown_factory_patch_is_used_at_registration` | 页面已构造后替换 `media.ScreenshotIOShutdownTask` 为记录参数的受控 factory；page._workers 有受控 worker；调用 register_shutdown_tasks，factory 收到当前 worker 快照，supervisor 注册 owner/kind 和其回调，返回 `<prefix>-screenshot-io`；不真正关闭系统资源 |
| `test_media_sources_keep_static_internal_imports_and_exports` | AST 检查五 shim 静态导入各自新模块并显式导出设计表名字；新包不导入旧 screenshot shim；页面只在 __init__ 定义一次；widgets 页面引用仅 TYPE_CHECKING；无新增动态模块代理或 __file__ 路径推导 |

  held worker 应继承真实类型，保留 page 的 isinstance 分派；不要用无关 Mock 替换 worker 后绕开生命周期。
  held start 不会令 QThread.isFinished 变真，finally 必须撤销 page._workers 与对应 `_worker/_add_worker/_delete_worker` 引用，
  取消/释放未启动对象后按 `close_screenshot_page`/deleteLater 清理，并处理 DeferredDelete；不让 held worker 造成 dispose 永久等待。
  不依赖 sleep 判断成功，不创建真实 ADB/文件管理器进程；真实图片只用 tmp_path。

- [x] **3. 运行新测试确认红灯来源。**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_media_module_compatibility.py
```

  预期双顺序、新源码结构测试因为 `gui.features.media` 目前不是包/目标不存在失败；旧行为用例可已通过。
  fixture 错误、错误测试签名或未清理线程不是有效红灯，先修正测试。

- [x] **4. 按设计迁移六份实现并写五个 shim。** 保留完整类体、globals、常量、注释与 `__all__`，只改精确内部 imports。
  保留 `gui.dialogs.lifecycle` 等共享绝对引用。静态导出逐名 `X as X`，不引入 `__getattr__`、ModuleType 子类或动态代理。
  不移动实际文件系统/运行时路径、修改旧测试入口或顺手格式化其他模块。

- [x] **5. 运行直接验收并检查测试选择。**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_media_module_compatibility.py tests/test_screenshot_page.py tests/test_screenshot_io.py
.\.venv\Scripts\python.exe -m pytest --collect-only -q -m ui tests/test_media_module_compatibility.py
```

  预期直接集合全部通过；所有 GUI patch 用例均被 ui 选择。两份原截图测试已覆盖失败/取消/重复启动、
  缓存预算/缩略图、设备控件归还、权限删除失败、同路径新批次及原生 join，不在本次通过后重复节点验收。

## Task 2: 定向消费者、静态质量与主任务交接

**Files:** 不新增生产范围；仅必要时修复 Task 1 范围内的回归。共享文档由主任务串行更新。

**Interfaces:** 消费 Task 1 原公开页面及旧 shim；产出实际测试记录、范围 diff 与未验证项，供独立审阅。

- [x] **1. 运行实际旧 ProcessRunner、缓存及宿主关联。** 前两节点证明旧 patch 与消费入口；后三节点证明后台批次和释放路由不变：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_model_media_adb.py::test_screenshot_page_opens_folder_via_process_runner tests/test_model_media_adb.py::test_screenshot_main_image_reuses_page_decode_cache tests/test_ui_delivery_order.py::test_media_batches_survive_disposal_without_navigation_change tests/test_ui_delivery_order.py::test_media_replay_preserves_inactive_host_and_pending_device_route tests/test_ui_delivery_order.py::test_deferred_media_payload_is_discarded_at_application_shutdown
```

- [x] **2. 运行迁移 worker 的格式安全关联。** 测试仍经旧 tasks 路径使用同一 reader，覆盖内容签名、扩展名不匹配及 TOCTOU：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_security_boundaries.py::test_all_external_image_boundaries_reject_non_raster tests/test_security_boundaries.py::test_raster_without_matching_extension_remains_supported tests/test_security_boundaries.py::test_imported_image_replaced_by_svg_is_not_decoded tests/test_security_boundaries.py::test_file_replaced_after_signature_cannot_change_decoder
```

  不整份运行混合 `test_model_media_adb.py` 或安全套件。`test_screenshot_action_admission.py` 仅出现宿主准入改动/证据才扩大。

- [x] **3. 运行限定静态质量及源码打包自检。**

```powershell
.\.venv\Scripts\python.exe -m ruff check gui/features/media gui/dialogs/screenshot_viewer_actions.py gui/dialogs/screenshot_viewer_nav.py gui/dialogs/screenshot_viewer_tasks.py gui/dialogs/screenshot_viewer_ui.py gui/dialogs/screenshot_viewer_widgets.py tests/test_media_module_compatibility.py
.\.venv\Scripts\python.exe -m pyright gui/features/media gui/dialogs/screenshot_viewer_actions.py gui/dialogs/screenshot_viewer_nav.py gui/dialogs/screenshot_viewer_tasks.py gui/dialogs/screenshot_viewer_ui.py gui/dialogs/screenshot_viewer_widgets.py
.\.venv\Scripts\python.exe scripts/check_comment_language.py gui/features/media gui/dialogs/screenshot_viewer_actions.py gui/dialogs/screenshot_viewer_nav.py gui/dialogs/screenshot_viewer_tasks.py gui/dialogs/screenshot_viewer_ui.py gui/dialogs/screenshot_viewer_widgets.py
.\.venv\Scripts\python.exe main.py --self-check packaging
git diff --check
```

  Pyright 用于新共享模块及静态 shim 出口；既有诊断要和源基线区分，不削弱类型或改其他阶段文件。
  检查静态可达链 MainFrame → media 入口 → 五 siblings → 共用生命周期/reader；不添加 hiddenimports/collect_submodules。

- [x] **4. 主任务串行集成文档并运行文档检查。** 核对 MODULE_MAP、ARCHITECTURE 的 media 位置和 eager 例外，
  只更新受影响事实；路线图/阶段状态由主任务更新。运行 `.\.venv\Scripts\python.exe scripts/check_doc_links.py`。
  新增未跟踪文档另做空白和节点引用核对，不能仅以 git diff --check 覆盖它们。

- [x] **5. 独立审阅与交接。** 报告本阶段改动清单、基线/红灯/通过结果、已有失败、跳过项与无修改文件范围。
  无新变更/失败/疑点不重复已通过集合；不全量、不构建、不提交。真实 GUI、高 DPI、剪贴板平台与冻结产物待人工或独立发布阶段验收。

## 当前记录

本计划编写时仅做源码/调用者读取及文档检查；设计随后通过主任务 builder check，实施与独立任务审阅已通过，最终集成审阅通过。实际验证见下方记录，不能将计划命令本身视为通过。

## 实施与集成验收记录（2026-10-24）

六份实际实现已归入 `gui/features/media/`，旧五个dialogs模块通过静态同模块alias兼容；
公开页面实际定义在包入口，保留eager与真实globals。独立reviewer的Spec/Quality均PASS，无分级缺陷。
六对完整AST仅规范化约定imports及排序后相同，tasks正文逐字相同；未修改原截图测试。
最终集成审阅PASS，无未解决新增分级缺陷。

迁移前44项通过。新兼容测试红灯12 failed、4个既有行为passed；最终直接+格式安全命令70 passed，
定向ProcessRunner/cache/宿主消费者7 passed，合计 **77个不同用例通过，无失败或skip**。
`pytest --collect-only -q -m ui tests/test_media_module_compatibility.py`选择全部4个GUI用例。
所有held worker有明确未启动对象清理，验证实际动作及参数，不只检查导出名字。

限定Ruff、中文注释、UTF-8/空白检查通过。主任务按实际解释器搜索路径执行11份生产文件Pyright：
0错误/0警告；`main.py --self-check packaging` exit0。该自检在默认数据目录临时写删`.self_check`探针，
不是纯静态或完全只读验证；没有发现读取/改写用户设置或历史的证据，日志中的本机路径不在交付展开。
后续自检先使用临时数据目录隔离。本次不为纠正文案重复执行。主任务另外执行真实宿主所有页选择与重开
Light/Dark两参数：2 passed，计入本批交叉检查，未重复计入上述77项。
具体命令、原输出、固定patch/hash和独立审阅在忽略目录
`.superpowers/sdd/2026-10-24-media-feature-package/`；不是用HEAD差异代替本阶段before快照。

保留旧导入身份、worker/reader晚绑定、原生join、图片格式限制、64MiB缓存与删除版本快照。
协作者类的实现模块路径随迁移改变，旧路径仍解析到同一类；不改变数据或用户交互。
未运行全量、PyInstaller构建、冻结产物、真实GUI/高DPI、平台剪贴板或Android实机验证。

最终综合审阅已独立核对35范围路径、23代码路径、完整移动AST与失败对照，PASS。
文档链接/frontmatter 68项、源码文本773项与diff空白检查通过；134项前置快照完全未变。
最终review保留packaging探针访问和8项既有失败的限制，未扩大为整库或发布验收。
