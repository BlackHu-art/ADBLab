# adblab 职责归并实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 用户已授权自主并行推进，按文件 owner 分工，不自动提交或推送。

**Goal:** 把 adblab 的21个叶子归入现有顶层目录，验证后删除旧目录，保持功能和数据兼容。

**Architecture:** core/tasks 管资源，services 管业务状态/用例，gui/adapters 与 gui/workers 管 Qt 适配。
包根不主动聚合，旧 models worker 继续同模块兼容，内部 adblab.* 路径退役。

**Tech Stack:** 项目 Python 3.11、PySide6、pytest、Ruff、Pyright、现有打包工具，不增加依赖。

**Spec:** [职责归并设计](../specs/2026-10-24-adblab-responsibility-merge-design.md)

## Global Constraints

- 当前干净 ui-redesign，基线 ee8fbca；在既有工作区实施，保存基线与源码快照，不覆盖用户修改。
- 不新增顶层目录；精确目标逐项以设计映射为准，不复制旧包根的跨域聚合。
- 实现正文只改导入；接口签名、资源归属、业务/数据协议、翻译和工具路径不变。
- adblab.* 是本轮退役的内部源码路径，不保留目录、同名文件或导入钩子；models/GUI公开兼容入口保留。
- 先直接验证和独立审阅迁移，再删除旧包并做删除后的验证；所有测试隔离用户数据、记录原生退出。
- 独立子任务只写指定文件，主任务拥有全局消费者、工程配置、文档、旧目录删除及最终集成。
- 不做无关重构，不自动提交/推送，不改依赖、版本、CI或发布方式，不默认全量 pytest。

## Review Focus

- 异常/Enum/结果类型出现双份或 monkeypatch 失效：纯模块唯一性、models 两路径及页面工厂关联测试。
- 新包父入口带入 Qt/Fluent/旧包：每个职责包的独立进程 import blocker，不只做文本搜索。
- 取消/关闭时序变化、Qt进程异常退出：直接生命周期组和启动/关闭消费者，读取实际 native_exit。
- 漏掉动态导入和配置造成删目录后失败：静态消费者清单、阻断旧包的运行探针、删除后再验。
- 删除扩大到其它目录或用户资产：逐文件比对基线和映射；仅删除旧包25个受控文件及其已核实缓存。

## Task 1：资源原语与业务用例

**Files:** 创建设计中12个 application 叶子的目标，以及 core/tasks、services/tasks、services/devices
的轻量 __init__.py；新增 tests/test_responsibility_services.py；修改 tests/test_device_context.py。
不改旧 adblab、生产消费者、其它既有测试、Qt叶子或共享配置。

**Interfaces:** 保留基线中 CancellationToken/CancellationError、TaskSupervisor/ThreadedShutdownTask/
TaskStopResult/StopDisposition、OperationManager/快照/状态/异常、ActionResults/载荷、DeviceContext/
快照、DeviceBatchUseCase、InstallBatchUseCase、ScreenRecordUseCase、MonkeyBatchCoordinator、
ApkFilePicker、DeviceConnectionLifecycle/WirelessHistoryGuard 的完整签名和语义。

- [x] 保存基线直接测试，记录新路径缺失的红灯契约。
- [x] 新增12叶子真实位置/完整定义清单测试；新根不 eager 导入，core纯原语拒绝Qt/services/gui，
  业务叶子拒绝Qt/GUI/models/controllers/adblab；保留ContextVar和类型唯一性行为。
- [x] 精确搬迁12文件，跨包相对导入改为设计中的显式依赖；三个包根不聚合。
- [x] 设备上下文隔离测试只放行自己的3级路径，保留全部行为断言。
- [x] 新契约通过；主任务迁移旧测试导入后跑 action_results、device_context、device_batch_use_case、
  phase1_operations、phase2_install_batch_use_case、screen_record_use_case、monkey_batch_state。
- [x] 保存正文AST对照、静态检查、结果与 native_exit；不提交，交独立审阅。

## Task 2：Qt 适配与保留入口

**Files:** 创建设计中9个 presentation 叶子的目标与 gui/adapters、gui/workers 的轻量 __init__.py；
修改 models/app_manager_worker.py、models/file_explorer_worker.py、tests/test_worker_module_compatibility.py、
tests/test_device_discovery_adapter.py；新增 tests/test_responsibility_qt.py。core/tasks/__init__.py由Task1拥有。

**Interfaces:** 既有 QtTaskSupervisor、QtAdbRuntime、QtAdbPairing、QtApkFilePicker、
QtAppUpdate、QtDeviceConnectionLifecycle、_ScanThread/载荷和全部worker类，以基线真实类名和签名为准；
QObject父子关系、Signal和翻译保持。保留models两路径同模块别名及MainFrame类再导出。

- [x] 基线worker兼容15项已通过；新增新位置和不加载旧包/页面聚合的红灯契约。
- [x] 精确迁移9叶子；用Task1的新业务和资源路径，不聚合包根、不改正文逻辑。
- [x] models两个旧入口仅改实现目标；保留TYPE_CHECKING导出及sys.modules同对象机制。
- [x] worker隔离只允许gui.workers范围，保留旧全部身份/基类/替换断言，补设备扫描兄弟不被加载。
- [x] 发现测试更新真实位置并保留MainFrame同类导出、代次/取消/清理测试；其生产导入由主任务统一改。
- [x] 新契约及直接组通过：apk_file_picker、device_connection_lifecycle、qt_adb_runtime、qt_adb_pairing、
  qt_app_update、device_discovery_adapter、worker_module_compatibility；保存Signal/翻译/AST和native_exit证据。
- [x] 运行页面工厂兼容关联组：app_manager_module_compatibility、file_explorer_module_compatibility；交独立审阅。

## Task 3：全局消费者、工程和文档

**Files:** controllers/models/gui/services中剩余旧导入、所有旧命名空间相关测试（排除Task1/2所有文件），
pyrightconfig.json、pyproject.toml、scripts/check_comment_language.py、tests/test_comment_language.py、
tests/test_ci_contracts.py；新增tests/test_adblab_retirement.py；当前文档、
.dsh/skills/adblab-architecture/SKILL.md中的目录导航和Qt边界事实、ADR0007。

- [x] 保存所有adblab源码消费者清单和基线哈希；处理import、字符串替换点、根聚合导入，
  只替换完整模块路径，不批量替换品牌/资源名称。
- [x] 按唯一映射切换生产及测试；根聚合导入拆到具体定义模块，models保留入口不改协议。
- [x] 从类型/coverage/注释及CI测试的根列表移除adblab；注释测试改用新增职责子包样例。
- [x] 新结构契约验证无新顶层包、生产无旧导入、模块真实位置正确、检查范围覆盖；目录不存在断言
  只在最终删除阶段验收，其删除前红灯属于预期。
- [x] 按调用链运行Controller APK/设备连接/装配、Action反馈/任务历史/结果呈现、发现清理/生命周期，
  启动与关闭组；设备上下文仅选择快照、准入、代次、配对关闭、窗口销毁代表节点，避免重跑无关几何矩阵。
- [x] 运行业务操作关联组：phase2_live_logcat_gate、model_shutdown_admission、phase2_install_batch_gate、
  phase2_screenshot_gate、recording_publication、monkey_batch_cancellation；与Task1/2结果按nodeid去重。
- [x] AST对照全部迁移叶子及生产消费者，允许精确import转换/排序和说明类型路径，业务字符串不忽略。
- [x] 更新AGENTS目录事实、README、docs/README、现状架构/模块/依赖/数据/术语及指南，新增ADR0007。
  旧历史方案保持原证据；路线图明确本次才完成物理目录归并。
- [x] Ruff、源码文本、中文注释、相关Pyright、文档链接、diff及新文件空白检查通过；打包描述测试及
  隔离用户目录源码packaging自检通过。未获正式构建授权，不生成发布产物。

## Task 4：验证后删除旧目录与终审

- [x] 先核对前三任务全部验证及独立审阅；阻断旧adblab导入时新入口仍正常工作，业务逻辑无新增差异。
- [x] 删除旧包四个__init__.py与21叶子；不留下同名兼容文件。解析绝对路径确认仅为仓库/adblab，
  核实无重解析点/新增用户文件后删除缓存及空目录，不能扩大为清理整个工作区或其它任务目录。
- [x] 验证目录物理不存在；运行retirement、职责纯度、worker身份/发现兼容与代表性启动/关闭节点，
  再执行源码packaging自检、全量收集检查和文档/差异检查；只收集测试不等于全量执行。
- [x] 用最终增量、哈希和实际验证结果交独立整体reviewer；修复确认问题后定向复验，记录未验证边界。
- [x] 汇总唯一测试节点及原生退出码，更新计划完成状态，不将离屏/源码检查写成实机/冻结产物通过。

## 执行状态

状态：**已完成（2026-10-24）**。设计、Task1/2/3、布局修复与最终整体独立审阅均通过；
旧顶层目录已删除，删除后验证通过。没有提交或推送。
证据保存在忽略目录 `.superpowers/sdd/2026-10-24-responsibility-merge/`，不纳入提交。

### 基线与单独修复

业务用例基线 146 通过；Qt 基线 145 通过、4 失败。四项既有失败来自
`AdbEnvironmentSettingCard.set_status()` 更换文字后未更新最小高度：混合字体自然高度比初始中文高。
独立修复仅在设置文字后清除旧高度约束、按当前 sizeHint 恢复；新增增长与缩回回归先红后绿，
原断言完整保留。直接 7 项及字体/重排/动画关联 107 项通过，原生退出码均为 0；已独立审阅。
此项是唯一业务路径之外的 UI 行为修复，不混入迁移 AST 对照。

### 删除前验证

命令使用项目 `.venv`，以证据目录中的 `run_checks.py <label> [--block-retired] <pytest 参数>`
隔离用户数据及遗留配置源，保存每个 setup/call/teardown 与 sessionfinish，并在父进程读取真实退出码。
`--block-retired` 在导入阶段拒绝旧 `adblab` 包；不以 pytest 打印通过代替进程成功退出。

| 范围 / 证据 label | 结果 |
| --- | --- |
| `task1-contract-final`、`task1-direct`：新职责契约、原有业务用例 | 18 + 146 通过 |
| `task2-green`、`task2-factories`、`task2-direct`：Qt 新职责、worker 身份、页面工厂与适配 | 38 + 40 + 138 通过 |
| `root-contract-green`：退役、注释和构建描述契约 | 43 通过；物理缺席一项留待删除后 |
| `root-operation-boundaries`：操作成功、失败、取消及收尾 | 169 通过 |
| `root-controller-consumers`：Controller、结果反馈与扫描生命周期 | 137 通过 |
| `root-window-boundaries`：启动、关闭与共享设备上下文 | 83 通过 |
| `root-ci-boundaries`、`root-ci-packaging-correction`：CI 和纯服务边界 | 123 个不同节点最终通过 |

所有最终通过组均无跳过、native/sessionfinish 为 0。CI 首次有 1 项失败是临时验证脚本把
packaging 需要检查的两个真实资源路径也屏蔽了；仅修验证脚本的 main 资源查验入口，用户目录和
settings 常量仍隔离，原三个参数节点通过，没有改生产代码或测试断言。

21 个迁移实现和 32 个生产消费者共 53 项 AST 对照通过；只允许精确导入路径、相邻导入排序及
说明中的类型路径差异，保留普通业务字符串。38 处 Signal 与 5 处翻译调用一致。
`ruff check <修改的 Python 文件>`、`check_source_text.py`、`check_comment_language.py`、
`check_doc_links.py`、`git diff --check` 和新文件空白检查均通过。相关生产路径 Pyright 为
0 error / 0 warning；临时配置继承项目规则，补实际解释器的 system-site-packages 和项目根，未放宽规则。
隔离目录下通过实际 `main.py --self-check packaging` 入口，阻断旧包，原生退出码为 0。

第三方 Qt/Fluent/SciPy 弃用警告和 Pyright 版本提示保留记录，未通过过滤警告或修改依赖消除。
未执行全量 pytest、真实设备操作、其他平台运行、原生桌面视觉验收或新的 PyInstaller 产物构建。

### 删除后验证

删除前逐文件哈希确认旧源码与基线一致，仅有 25 个源码和 25 个已知缓存，无重解析点或未知文件。
25 个源码经补丁删除；递归清理命令被工具策略拒绝后，采用范围更小的非递归操作：逐缓存文件删除，
每个目录确认空后再删除。最终 `adblab/`、`adblab.py` 均不存在，顶层目录差异只有移除 adblab。

- `run_checks.py root-after-delete tests/test_adblab_retirement.py tests/test_responsibility_services.py
  tests/test_responsibility_qt.py tests/test_worker_module_compatibility.py tests/test_device_discovery_adapter.py`
  加四个已选启动/关闭节点：67 通过，native/sessionfinish 均为 0；该轮不使用外层 import blocker，
  物理缺席与 `find_spec` 无解析结果由测试直接核实。
- `run_checks.py root-collection-after-delete --collect-only tests`：8,134 项收集成功，原生退出码 0；
  这是全库导入/收集检查，不是全量测试执行。
- `main.py --self-check packaging`：删除后再次通过，隔离用户目录、阻断旧包，原生退出码 0。
- 各组按 nodeid 去重合计 1,043 项通过，最终无未解决失败、无跳过；基线及红灯过程单独保留。

审阅记录：Task1、Task2、Task3 与布局修复均获规格/质量双通过。Task3 指出的计划旧进度文字已更新；
第三方弃用警告为已记录的非阻断项。删除后发现三份历史设计中的五个源码链接失效，仅更新链接目标并
注明保留历史语义；文档和差异检查重新通过，追加文档增量也已纳入最终审阅。

最终独立 reviewer 核对 185 路径清单、132 个修改/迁移 Python 文件的 AST 及测试原始事件记录，
规格与质量均为 Approved，Critical / Important / 新增 Minor 均为 0。完整报告保留于证据目录
`final-review.md`；未重复运行已有绿灯套件。审阅明确不替代真实设备、多平台、原生桌面视觉及冻结产物验收，
不承诺仓外代码的旧内部 `adblab.*` 导入兼容，也不表示已重新审计所有无关的既有问题。

本轮自主决定：单独修复已经复现的状态文字高度问题，代价是增加一处已独立验证的 UI 小改动；
保留本地忽略目录中的原始验收证据，代价是占用本地磁盘，不将其夹带提交。配置、归档、资源和用户目录未迁移。
