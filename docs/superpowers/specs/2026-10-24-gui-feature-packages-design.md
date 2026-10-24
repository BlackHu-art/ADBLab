# FileExplorer、AppManager、Performance 功能包设计

状态：已实施并通过最终独立审阅。延续[持续重构路线图](../plans/2026-10-23-project-refactor-roadmap.md)
的自主连续实施授权；不另设批准等待，不提交。实际验收、既有失败与未验证边界见
[实施计划](../plans/2026-10-24-gui-feature-packages.md#验收记录)。

## 目标与方案选择

三个内嵌 QWidget 功能的页面与协作者目前分散在 `gui/features/*.py` 门面和 `gui/dialogs/`。
将其按功能归包，使一次功能评审可在同一目录检查页面、操作、视图和关闭协作；不拆新的业务层。
依据是当前源码、GUI 结构审计和[首批目录设计](2026-10-24-feature-directory-boundaries-design.md)。

采用与已实施 Logcat 一致的“单份实现 + 旧模块同身份 alias”，但按各簇的真实替换点保留导入时机。
单纯重导出类会让旧模块 monkeypatch 无法影响新类 globals；直接切断旧路径会破坏现有消费者。
通用动态迁移注册器会隐藏静态打包依赖，因此不采用。此选择由架构负责人依据持续授权裁定。

Python 3.11 + PySide6，使用现有 `.venv`，不增加依赖、不改 CI/发布、不提交或暂存。
保持公共入口、类/方法/信号、配置与数据格式、设备准入、视觉交互和平台兼容。
不移动 models、services、共享 dialogs 工具、用户数据、运行时工具或二进制资源；不操作真实设备。
现有未提交成果为前置资产，特别是 Performance 对 `services.performance.config/results` 的新导入。

## 精确迁移表

下表源路径均在 `gui/dialogs/`，源文件保留为兼容 shim；目标为唯一实现。
三个原 `gui/features/<feature>.py` 门面转成对应目录的 `__init__.py`，公开模块路径不变。

| 原文件 | 新实现路径 |
| --- | --- |
| `file_explorer.py` | `gui/features/file_explorer/page.py` |
| `file_explorer_image.py` | `gui/features/file_explorer/image.py` |
| `file_explorer_list.py` | `gui/features/file_explorer/list.py` |
| `file_explorer_ops.py` | `gui/features/file_explorer/ops.py` |
| `file_explorer_transfers.py` | `gui/features/file_explorer/transfers.py` |
| `file_explorer_view.py` | `gui/features/file_explorer/view.py` |
| `file_explorer_preview_tasks.py` | `gui/features/file_explorer/preview_tasks.py` |
| `app_manager.py` | `gui/features/app_manager/page.py` |
| `app_manager_details.py` | `gui/features/app_manager/details.py` |
| `app_manager_batch.py` | `gui/features/app_manager/batch.py` |
| `app_manager_form.py` | `gui/features/app_manager/form.py` |
| `app_manager_icons.py` | `gui/features/app_manager/icons.py` |
| `app_manager_views.py` | `gui/features/app_manager/views.py` |
| `app_manager_rows.py` | `gui/features/app_manager/rows.py` |
| `app_manager_material.py` | `gui/features/app_manager/material.py` |
| `performance_launcher.py` | `gui/features/performance/page.py` |
| `performance_launcher_form.py` | `gui/features/performance/form.py` |
| `performance_launcher_log.py` | `gui/features/performance/log.py` |
| `performance_launcher_run.py` | `gui/features/performance/run.py` |
| `performance_library.py` | `gui/features/performance/library.py` |
| `performance_result_tasks.py` | `gui/features/performance/result_tasks.py` |

包公开名严格保留：FileExplorer 为 `FileExplorerPage`；AppManager 为 `AppDetailsPage`、
`AppManagerPage`、`AppSortProxy`；Performance 为 `PerformancePage`。不扩张包级 worker 导出。
各包 `__all__` 列出原公开名，`TYPE_CHECKING` 显式导入对应类型；`__getattr__(name: str)` 按名称
在函数内静态导入并返回对象，未知名称抛 `AttributeError`。不在包加载时提前导入 page。
`gui/features/__init__.py`、MainFrame 的现有懒导入和 registry 工厂保持不动。

## 模块兼容和依赖方向

每个旧 shim 静态 `from gui.features.<feature> import <module> as _implementation`，
然后 `sys.modules[__name__] = _implementation`。旧/新路径必须是同一个模块对象；经父包属性访问
也一致。类、Signal、dataclass 和可变常量只定义一次，不保留第二份实现。

shim 的 `TYPE_CHECKING` 块采用显式 `from ... import X as X`，至少覆盖原模块定义的所有类/函数/
类型别名/常量及当前生产、测试直接导入或替换的依赖；包括私有名称。核对 AST 顶层定义与实际消费者，
不使用星号导入或仅靠动态 `__getattr__` 掩盖静态类型缺口。运行时 alias 保留完整原模块属性面。

新实现内部只导入新相对路径；含函数内导入及 `TYPE_CHECKING` 引用，不回导自身旧 shim。
`gui.dialogs.lifecycle`、`gui.dialogs.fluent_dialog` 是未迁移的共享工具，继续显式引用。
不能为消除所有 `gui.dialogs` 字符串而移动这些共享模块。

### FileExplorer：分散的替换点

- `page._run_adb/_run_transfer` 分别读取 page globals 的 `ADBWorker/TransferWorker`。
  `list.FileExplorerList._refresh` 读取 list 的 `DirectoryListWorker`；view 的文本/图片读取分别
  读取 `TextReadWorker/PreviewReadWorker`；ops 的保存读取 `TextSaveWorker/LocalTextSaveWorker`。
  保留这些不同归属，不将 worker 工厂集中到 page。
- transfers 还直接使用模型 worker 类型进行 `isinstance`；原 worker 类型及 stop/join 行为不变。
  页面/协作者的旧模块 patch 要作用于相同的新 globals；测试 fake 优先继承实际类型并禁止真实 start。
- 保留 view 的 `MAX_TEXT_VIEW_BYTES = 2 * 1024 * 1024`、view 和 preview_tasks 各自的
  `MAX_IMAGE_PREVIEW_DIMENSION = 2048`。二者原本独立，归包不顺手合并常量或改默认参数绑定时机。
  保留 `PreviewIdentity`、缓存预算、临时路径清理 token、请求代次与失选后的原设备清理。
- transfers 的 page 类型引用改为 `.page`，view 对 preview_tasks 的引用改为 `.preview_tasks`。

### AppManager：晚绑定回读和独立详情页

- form 在创建排序器时回读 `AppSortProxy`；views 的列表/详情批次、batch 的六处操作构造、icons
  的可见图标批次均在方法内读取 page 的 `AppManagerWorker`。改为方法内 `.page` 模块/名称导入，
  保留晚绑定时机，不能提升至模块顶层而产生环或冻结旧 worker 引用。
- details 的 `_rw` 独立读取 details globals 的 `AppManagerWorker`；仍是独立替换点，不能统一为
  page worker。现有 `test_app_manager_user_context.py` 同时 patch 两个模块，证明此区别有消费者。
- `AppDetailsPage` 从 `.details` 延迟导出；details → form、form → rows/material、icons → views/rows
  的模块依赖可先加载协作者，再按需加载 page。保留 rows 的 `STATUS_ROLE`、`VERSION_ROLE` 值及身份。
  不调整当前用户快照、批次预算、图标 epoch、可见区扫描、选择状态、材质事件过滤器和 Qt 所有权。

### Performance：保留服务分层及结果归档

- page 保留从 `services.mobileperf_runner` 导入 `MobilePerfRunner`，从 `services.performance.config`
  导入 `MobilePerfRunConfig`；form 保留 `MobilePerfMonkeyConfig`；library 保留 `MobilePerfRunConfig`；
  run/result_tasks 保留从 `services.performance.results` 导入 `PerformanceArtifacts`。
  不回退前置配置/结果抽取，不移动运行器，不复制 dataclass。
- page 的 `CurrentPackageWorker`、`detect_current_package`、`MobilePerfRunner` 保留模块替换点。
  run 的 `PerformanceStartWorker` 仍由 `PerformanceLauncherRun.start_mobileperf` 读取；result_tasks 的
  `PerformanceResultWorker` 仍由 `PerformanceResultLoader.submit` 读取；`load_result_metrics`
  仍属于 result_tasks globals。library 的 `os.path.getsize` patch 仍作用于真实归档代码。
- page 构造中的结果加载器函数内导入改为 `.result_tasks`；library 的类型引用改为 `.page`。
  不把结果加载器改成包入口 eager 导入。form 的 `CONFIG_HINTS`、`MONKEY_PERCENT_FIELDS` 原值和
  page 导入引用不变。保持设置键、参数快照、run id、归档顺序、取消、进程退出和线程 join 屏障。

## 文件深度、打包与验证边界

当前 21 个迁移实现未使用 `__file__`、`Path.parents` 或相对文件深度解析资源。
图标仍经既有 icon_loader，服务/用户数据路径工具留在原位；禁止新增根据新目录深度推断项目根的逻辑。
shim 与懒入口使用静态导入以便 PyInstaller 分析；不改 spec、不新增 collect_submodules 清单。

每簇迁移前取得直接基线；新增每个模块双导入顺序、父包属性、公开类身份和实际旧 patch 行为回归，
并检查独立协作者导入不加载 page、其他两簇或对应旧 shim。保留现有旧路径测试，避免批量改测试导入。
每簇直接通过后运行其关联测试，主任务统一验证共享宿主、关闭和语言边界。
具体集合、exclusive files 和命令见[实施计划](../plans/2026-10-24-gui-feature-packages.md)。

主任务负责实施前快照、独立 builder check、共享文档及最终审阅；各实施任务只修改自己的文件。
源码 import probe 与 `main.py --self-check packaging` 不代表冻结产物、真实 GUI 或设备验收。
本阶段没有视觉/业务改动，不默认完整构建或全量 pytest；新增失败先与迁移前基线比较再决定扩围。
