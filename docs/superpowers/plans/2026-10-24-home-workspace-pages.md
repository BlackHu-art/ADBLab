# Home / Workspace 页面目录归位 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本阶段由一个实施 owner 串行完成代码任务；主任务调度独立审阅与集成，禁止自动 commit。

**Goal:** 把首页协作簇与工作区容器放入两个真实模块，保持旧导入、界面及设置替换边界。

**Architecture:** 7 个 QWidget 类完整迁移，旧聚合模块静态导出相同 class 对象。设置与辅助类继续真实定义于 `fluent_pages.py`，MainFrame 和 WorkspaceFeatureHost 保持不动。

**Tech Stack:** Python 3.11、PySide6、当前已安装 qfluentwidgets、pytest；使用仓库 `.venv`。

**Spec:** [设计](../specs/2026-10-24-home-workspace-pages-design.md)。证据补充见 本阶段忽略目录中的 design-notes.md。

## Global Constraints

- 当前授权是持续自主重构和实际目录调整；不增加批准/commit/push 步骤。先检查差异，保留其他 owner 和用户的在途修改。
- 仅一个实施 owner 写 `home.py`、`workspace_containers.py`、`fluent_pages.py` 和新专属测试文件；文档与 packaging 自检交主任务。
- 完整类迁移，不改类内逻辑/签名/文案/父子关系，不使用方法 mixin 或动态模块代理。
- 保留旧 10 项 `__all__` 和 settings 原方法 globals；`pages/__init__.py` 与 MainFrame 不改。
- 不重跑此前已验收功能簇，不整跑设置已知 8 个布局失败矩阵；全量仅按当前增量策略由主任务裁定。
- 任何本批新增 subprocess 检查用临时 `LOCALAPPDATA`/`XDG_CONFIG_HOME`；不运行真实 ADB、不写用户数据。

## Review Focus

- 新模块先导入时的循环/半初始化：Task 1 的导入顺序测试覆盖旧优先、home 优先、workspace 优先。
- Settings 替换 globals 因清理 imports 失效：Task 1 原方法 globals 契约及既有 preference/mica 行为节点覆盖。
- Gallery 的传入滚动区/已隐藏 content 重挂后不可见或脱离父对象：Task 1 参数化所有权测试覆盖。
- 迁移改变语言或无障碍文本：Task 1 新路径英文首页及 workspace 具体路由文本测试覆盖。
- MainFrame 的延迟首页/Gallery 构造替换和取消边界丢失：Task 2 精选 startup 节点覆盖，不改组合根。

## Task 1：单 owner 完整迁移并冻结兼容契约

**Files:**
- Create: `gui/pages/home.py`、`gui/pages/workspace_containers.py`
- Modify: `gui/pages/fluent_pages.py`（原 86–864 行七类与所需 import；保留设置类体）
- Create: `tests/test_home_workspace_module_compatibility.py`

**Interfaces:**
- Consumes: 原七个类的完整公开签名；`WorkspaceFeatureHost`、`WorkspaceRoute` 原类型；MainFrame 现有 `_open_workspace_feature(section, feature)`、`_on_nav_requested(route)`、`_request_device_refresh()`、`_open_cmd()`、`_on_save_path_clicked()` callbacks。
- Produces: `gui.pages.home.{ActionCard,ActionCardView,DeviceContextCard,HomePage}`、`gui.pages.workspace_containers.{GalleryPage,WorkspaceSectionPage,WorkspaceAreaPage}`；旧路径相应符号 `is` 新符号，Settings 仍原位。

- [x] **Step 1：记录当前目标差异和基线。** 运行 `git status --short` 与 `git diff -- gui/pages/fluent_pages.py gui/pages/__init__.py`，确认没有重叠编辑；读取根规则、测试指南和 Spec。主任务已有同代码基线可复用；否则先跑 Step 5 的直接集合中现有三文件，记录真实结果，不把基线失败修进本任务。
- [x] **Step 2：新增兼容测试。** 新文件包含下列精确测试契约：
  - `test_page_import_order_preserves_class_identity`，`first` 参数为 `fluent_pages/home/workspace_containers`；每种用新子进程依序 import 三模块，断言 7 对类 `is` 相同、各 `__module__` 为设计的新路径，`ActionCard.activated`/`WorkspaceAreaPage.routeChanged` 通过同一类对象可访问。子进程不构造 UI，`env` 复制父环境后设置 offscreen、临时 LOCALAPPDATA/XDG_CONFIG_HOME，带 timeout/capture；不在父进程删除 sys.modules。
  - `test_aggregate_exports_and_settings_globals_remain_compatible`：断言旧、新模块 `__all__` 与设计逐项一致，`gui.pages.__all__ == ["TaskCenterPage"]`；`SettingsPage.__init__`、`_apply_adb_client`、`prepare_shutdown` 的 `__globals__ is vars(fluent_pages)`，原 settings helper/class 仍能通过旧模块访问。只锁兼容承诺，不断言无关内部实现。
  - `test_gallery_reparents_hidden_content_without_replacing_owner`：通过新容器入口构造，用 `scroll=False/True` 参数；True 分支传预先创建的 SmoothScrollArea，content 先挂临时旧 parent 且 hide。show page 后断言 content `isVisibleTo(page) is scroll`（旧类刻画确认 False 分支保留隐藏）、content 的 parent 为 page.body（False）或 page.body.widget()（True）、True 分支 `page.body is supplied_scroll`、`page.body.parentWidget() is page`；关闭由既有 Qt fixture 收尾。保留旧 parent 引用，确认归属转移没有复制 content。
  - `test_new_page_paths_keep_application_translation_context`：使用 `qt_application`、项目 `install_translators(...,"en_US")` 和合成 frame callbacks，通过新路径建 HomePage，断言 `accessibleName()=="Home"`、应用卡标题是翻译后的 `tr("应用管理")` 且不等于中文源文案。为 WorkspaceArea 提供 QObject fake host（具备 `route_changed=Signal(object)`、`section_key="apps"`、`current_feature="overview"`、`current_device_id=""`、空 `deactivate`、`is_overview_feature` 返回 True、`feature_label` 返回 "Manager"、`feature_requires_device` 返回 False）；page 的 content 使用另一个 QWidget，验证不强制 host/content 相同。调用 `_set_route_presentation(WorkspaceRoute("apps", "manager"))` 后 description 等于 `"Manager · " + tr("使用顶部设备栏中勾选的操作目标")`，且该 tr 结果不等于中文原文。不要创建 MainFrame 或设备工作线程；finally 先销毁页面并投递 DeferredDelete，再移除/销毁 translators 并投递 DeferredDelete。
- [x] **Step 3：确认新增测试红灯是新路径尚不存在。** 运行 `python -m pytest -q tests/test_home_workspace_module_compatibility.py`；预期缺少 `gui.pages.home/workspace_containers`，不是环境/用户数据错误。命令中的 python 均替换为 `.\.venv\Scripts\python.exe`。
- [x] **Step 4：完整搬迁及静态导出。** 按 Spec 搬 7 个 ClassDef；原类 body 不改，新增模块只导入实际依赖（完整清单见 notes，类型注解名也须保留）。旧模块清理确实只被迁移类使用且无旧替换消费者的 imports，显式重导出类；设置仍原字典。新模块保留 Gallery 来源与许可说明，两个新 `__all__` 精确写入。不修改现有消费者导入。
- [x] **Step 5：运行直接测试。** 本轮边界是类位置/导出 → 以下直接页面/路由测试 → 不扩大到所有设置或主窗布局。设置 `$env:QT_QPA_PLATFORM = "offscreen"` 后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_home_workspace_module_compatibility.py tests/test_home_banner.py tests/test_page_layout.py tests/test_workspace_route_payload.py
```

预期全通过；若失败先区分导入、迁移遗漏与已有环境/布局问题，不放宽断言。

## Task 2：相关边界与集成收口（同一代码 owner，主任务负责文档/自检）

**Files:** 不预设新增生产改动；只有 Task 1 发现的本范围缺陷回到原四文件修复。主任务最小更新 `docs/project-knowledge/MODULE_MAP.md`、`docs/project-knowledge/UI_IMPLEMENTATION.md`、阶段设计/计划与路线图/README 链接。

**Interfaces:** Consumes Task 1 的旧、新同一类对象；Produces 已核实的兼容、行为结果及清晰验证边界，不引入新 runtime API。

- [x] **Step 1：运行直接关联节点。** 每组只执行一次；如失败有针对性地重跑失败节点与其污染组合。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_workspace_feature_host.py::test_overview_category_switch_resets_inner_scroll_position tests/test_workspace_feature_host.py::test_workspace_suspends_and_resumes_feature_across_navigation tests/test_workspace_feature_host.py::test_inactive_deep_route_activates_target_without_resuming_old_session tests/test_workspace_feature_host.py::test_unknown_workspace_feature_does_not_change_section_or_route
.\.venv\Scripts\python.exe -m pytest -q tests/test_accessibility_contract.py::test_home_action_card_has_accessible_name_and_keyboard_focus tests/test_cached_icons.py::test_action_card_reuses_renderer_in_actual_icon_paints tests/test_model_mainframe.py::test_main_frame_workspace_route_is_forwarded_without_top_level_window tests/test_model_mainframe.py::test_main_frame_unknown_workspace_route_does_not_switch_page
.\.venv\Scripts\python.exe -m pytest -q tests/test_mainframe_startup.py::test_stage_failure_preserves_exception_and_cleans_partial_children tests/test_mainframe_startup.py::test_task_page_is_owned_when_its_gallery_constructor_fails tests/test_mainframe_startup.py::test_auxiliary_pages_yield_between_construction_and_allow_cancellation
.\.venv\Scripts\python.exe -m pytest -q tests/test_qt_adb_runtime.py::test_adb_client_selection_applies_preference_and_rechecks tests/test_settings_typography.py::test_mica_setting_gates_unsupported_systems_without_overwriting_preference
```

第一组证明容器路由/滚动/激活；第二组证明快捷卡公共入口及组合根路由；第三组证明旧构造替换和 partial startup 所有权；第四组仅证明原 globals 替换仍实际生效，不扩展设置布局矩阵。

- [x] **Step 2：静态质量与一次性迁移审计。** 对照实施前暂存于忽略目录的源文本，用 AST 比较 7 个迁移 ClassDef 以及 6 个原位设置 ClassDef（忽略属性/行号）等价，若不是完全一致逐项解释并拒绝无关行为变化。运行：

```powershell
.\.venv\Scripts\python.exe -m ruff check gui/pages/fluent_pages.py gui/pages/home.py gui/pages/workspace_containers.py tests/test_home_workspace_module_compatibility.py
.\.venv\Scripts\python.exe scripts/check_comment_language.py gui/pages/fluent_pages.py gui/pages/home.py gui/pages/workspace_containers.py
.\.venv\Scripts\python.exe -m pyright gui/pages/fluent_pages.py gui/pages/home.py gui/pages/workspace_containers.py
git diff --check
```

Pyright 若报告既有错误，按迁移前后具体诊断对比，不改宽类型或宣称已通过。新文件未跟踪时 diff 不覆盖其正文，另用脚本检查 UTF-8/行尾空白。保留项目已有源码文本检查接口的正常使用，不默认 compileall。

- [x] **Step 3：提交主任务独立审阅与集中验收。** 提交实际文件列表、节点结果、AST 差异、未运行边界，禁止自行 commit。主任务检查文档最小同步后跑 `scripts/check_doc_links.py`；集中一次源码 packaging 子进程，环境隔离示例：

```python
with tempfile.TemporaryDirectory(prefix="adblab-home-workspace-check-") as root:
    env = dict(os.environ)
    env.update(LOCALAPPDATA=root, XDG_CONFIG_HOME=root, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "main.py", "--self-check", "packaging"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

使用 `.venv` Python 启动该包装脚本，具体 timeout 可按现有耗时调整；临时目录只在子进程完成后释放。若主任务同期阶段已有同等隔离的最终自检，可集中复用一次，不为本批重复运行。

- [x] **Step 4：完成报告。** 明确完整类归位、旧入口及设置替换保持、实际测试结果、没跑全量/完整构建/真实 UI 的边界。人工可检查首页窄宽/字体切换/一次快捷操作与工作区来回导航；这不是自动测试通过的组成部分。

## 计划自审

设计每个保护点分别落到导入 identity、settings globals/既有行为、直接 Home/Workspace 测试、startup 关联、AST 和包装自检；未重新打开已完成功能包。一个 owner 拥有共享源文件，主任务独占正式 docs/自检。翻译测试已经明确为项目 translator 加轻量 QObject fake host，不加载完整窗口或执行设备操作。

## 主任务预审与执行裁定


2026-10-24，root。设计/计划PASS，纳入下方测试与执行裁定后可发布。已读取草案/notes、旧模块import、
Gallery与WorkspaceArea构造、七类边界与__all__、当前i18n固定context及已有消费者检索。

| 边界 | 结论 |
| --- | --- |
| 完整类归位 | 首页4类与容器3类责任可分；不增mixin、不改组合根；两个新模块不回导旧聚合 |
| 同对象兼容 | 旧10项导出顺序保持，7类静态同对象；Settings及5个实际globals接缝原地 |
| Qt归属 | Gallery wrapper和传入scroll重用、host/content独立、路由pending及晚到回调不随移动改变 |
| 翻译 | tr固定ADBLab context；新路径轻量实例验证有意义，无需重生成词库或遍历全部导航 |
| Task1/2 | 单owner原子持有fluent_pages，13个关联节点有实际消费者证据，不扩大8项布局矩阵 |
| 并行边界 | 当前Settings修改i18n import但不改tr语义；正式执行等当前批稳定，避免把中间态作为基线 |

Ruling: 两个新GUI测试（Gallery参数化和翻译）必须显式pytest.mark.ui并消费qt_application，
运行collect-only -m ui确认实际3参数项被选；纯导入子进程不为凑数标UI，不模块顶层创建控件。
Ruling: 新兼容测试是保真测试，不改类体迎合新断言。若隐藏content/假host断言不符合旧实现，
先在before原类确定实际行为再修测试；不能把已有行为修复夹入目录迁移。
Ruling: root集中3生产类型基线/最终与临时数据环境packaging；owner仅限定lint/comment及行为测试。
Ruling: 所有TemporaryDirectory递归清理必须先核实绝对路径位于指定临时base，不跨shell移动/删除。
Ruling: root拥有正式docs和before快照；未来发布时转换草案/notes链接，不把忽略目录相对引用当正式链接。
Ruling: 完成两步后一个独立任务review与主任务最终集成；不自动提交、不为每小步重复review。

当前未实施，也未运行本批测试。仅预审通过不代表UI或冻结产物验证。

root集中Pyright与源码packaging；owner不重复执行这两项。最终自检子进程的LOCALAPPDATA、APPDATA、
XDG_CONFIG_HOME/XDG_CACHE_HOME/XDG_DATA_HOME和MOBILEPERF_LOG_DIR均指向经边界校验的临时目录。

## 实施验证记录（2026-10-24）

四文件已冻结：七个完整类分别归入home/workspace_containers，旧fluent静态导出同一对象。
迁移七类与原位六设置类完整源码和AST均一致，旧__all__顺序与设置globals保留。
新测试7实例先因新路径缺失失败，直接绿灯44实例；13个关联函数展开16实例，共60个不同用例通过。
Qt marker收集3/7，仅两GUI函数及其参数消费qt_application；导入四例不标UI。
旧Gallery隐藏内容刻画确认False分支不显示、True分支显示；仅修设计及保真断言，未更改原类行为。
独立任务审阅Spec/Quality PASS，复核4路径hash、完整patch、13类源文/AST和实际globals。
root三生产Pyright无错误/警告，owner四文件Ruff、三生产中文注释、文本/空白及diff均通过。
此前设置UI-10及应用UI-09布局失败不在本阶段，不宣称已修复或重验。
源码packaging用全部数据环境变量隔离到已校验临时目录，exit0且无残留.self_check；不是冻结产物验证。
未跑全量、真实桌面/高DPI、真实设备或完整构建。精确命令及真实退出码在本阶段忽略目录implementation-report.md。
最终综合审阅已通过；全项目持续重构仍在推进。

## 最终审阅与交付

2026-10-24，独立任务与最终综合审阅均PASS，无P0–P3 findings。两阶段211个不同用例通过，
6生产文件类型无诊断，76文档链接/frontmatter、801源码文本与diff检查通过。最终审阅独立核对
22固定路径、12代码/测试路径与10文档增量；208前置路径中22授权变化、186未变，无范围外漂移。
原integration-hashes保留，收尾后另存delivery-hashes；未重跑已通过测试/类型/自检。
已知UI-09/UI-10未修复或重验，实机/真实桌面/冻结产物仍未验收；全项目后续阶段继续推进。
