# 服务与 Logcat 功能目录归位实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development，按独占文件并行实施，主任务集成并安排独立审阅。

**Goal:** 落实 apps/performance 服务功能包和 Logcat UI 功能包，保持旧入口及行为兼容。

**Architecture:** 配置、结果和 helper 从无关实现中分离；Logcat 页面及协作者归入同一功能目录。
旧模块保留显式兼容入口，业务和生命周期算法不随目录迁移改变。

**Tech Stack:** Python 3.11、PySide6、pytest、Ruff、Pyright，复用项目 `.venv`。

**Spec:** [设计](../specs/2026-10-24-feature-directory-boundaries-design.md)。

## Global Constraints

- 保持现有功能、公共入口、UI、平台兼容和用户数据路径/格式；不访问真实设备。
- 保留前置未提交资产，不暂存、commit/push，不增依赖、不改 CI/发布或二进制。
- 生产注释中文；只用 `.venv`；Qt 测试离屏，测试设置和文件使用临时目录。
- 各任务仅修改自己的文件；共享文档、集成与审阅由主 agent 负责。
- 用户已授权持续并行实施及自主决策，不重复发起阶段批准请求。

## Review Focus

- helper 大载荷、取消与清理失败不能造成重复设备查询或错误发布结果：任务 1 保留直接回归。
- 新旧入口必须使用同一数据类型，配置序列化保持字段和值：任务 2 增加身份及固定配置字节回归。
- 结果查询不得抢占后一次运行或掩盖部分 I/O 错误：任务 2 保留元数据和结果加载回归。
- 新旧 Logcat 模块按任意顺序导入不能产生重复 QObject 类型或破坏旧替换点：任务 3 子进程回归。
- 包迁移不能破坏取消、关闭与晚到回调，或变更运行器 cwd：任务 2/3 保留直接生命周期回归。

## Task 1: apps helper 独立服务

**Files:** 创建 `services/apps/__init__.py`、`helper.py`；修改 `services/app_icons.py`、
`services/app_metadata.py`；测试 `tests/test_app_helper_boundary.py` 及现有 `test_app_icons_*.py`、
`test_app_metadata.py` 中必要的 transport 私有 patch 目标。

**Interfaces:** 原样移动 `HelperResult`、`run_app_helper(device_id, packages, cancelled, *, output_limit,
metadata=False, icon_metadata=False)`、`_run_inline_helper` 及传输常量。
app_icons 重导出公开对象，业务级替换点保留；helper 不导入两个业务模块。

- [x] 运行基线：`python -m pytest -q tests/test_app_icons_service.py tests/test_app_icons_inline.py tests/test_app_icons_metadata.py tests/test_app_metadata.py`。
- [x] 新增失败测试：新旧公开 helper/结果对象 `is` 相同；隔离子进程导入元数据不会加载图标模块；新 helper 不加载两个业务模块。
- [x] 运行新测试确认因目标模块缺失失败，记录原始输出。
- [x] 移动通用传输实现，修改业务模块依赖；保留命令、异常、取消与补偿清理算法；私有 patch 移到实际所有者并保留原断言。
- [x] 运行新增与直接集，并增加 `tests/test_app_metadata_worker.py`，原因是 worker 通过元数据服务消费 helper。
- [x] 运行修改文件 Ruff、生产注释；自查 diff，记录报告并交独立审阅，不提交。

## Task 2: performance 配置/结果边界

**Files:** 创建 `services/performance/__init__.py`、`config.py`、`results.py`；修改
`services/mobileperf_runner.py`；可修改配置/结果消费者 `gui/dialogs/performance_launcher_form.py`、
`performance_library.py`、`performance_result_tasks.py`、`performance_launcher_run.py`、`performance_launcher.py`。
新增 `tests/test_performance_service_boundaries.py`，必要时更新自己的旧私有 patch 目标。

**Interfaces:** config 原样提供 `MobilePerfMonkeyConfig`、`MobilePerfRunConfig`、`normalize_local_path`
和三个分号/包名辅助函数；results 提供 `PerformanceArtifacts`、`PerformanceResultQuery`、
`path_key(path: Path) -> str`；旧 runner 公开类/函数身份保持，`MobilePerfRunner._path_key` 委托新函数。

- [x] 基线运行 `tests/test_model_mobileperf.py tests/test_performance_metadata.py tests/test_performance_result_loading.py tests/test_mobileperf_runner_concurrency.py`。
- [x] 新增失败测试：新旧类/函数身份相同；新配置/结果模块在干净子进程中不加载 runner/core.exec/core.owned_process；固定配置输出字节与原有输出一致。
- [x] 确认新测试因目标模块缺失失败；记录使用原配置类得到的固定字节期望，不能迁移后自证同一实现。
- [x] 按设计提取配置/结果并改消费者，运行器原位置保留，进程/锁/reader/清理算法不变。
- [x] 运行新增与直接集，GUI 消费者有改动时增加 `tests/test_performance_library.py tests/test_model_performance_launcher.py`。
- [x] 运行 Ruff/生产注释，自查 diff 并报告；主任务完成类型与源码打包检查，不提交。

## Task 3: Logcat 功能目录归位

**Files:** 将 `gui/features/logcat.py` 转换为 `gui/features/logcat/__init__.py`；创建设计表中的八个实现模块，
将原 `gui/dialogs/live_logcat*.py` 八文件改为模块身份兼容入口。新增 `tests/test_logcat_module_compatibility.py`。
不修改 MainFrame、共享 dialogs/lifecycle、其他功能模块或现有 Logcat 行为测试。

**Interfaces:** `from gui.features.logcat import LiveLogcatPage` 继续成立；旧新对应模块 `is` 相同。
包入口延迟静态导入 page，内部只用新相对导入；stream 晚绑定 page 的 worker 替换点保留。

- [x] 取得基线：`tests/test_phase2_live_logcat_gate.py tests/test_live_logcat_render_batches.py`。
- [x] 新增双导入顺序子进程回归：八个旧/新模块身份一致，公开 Page 身份一致；旧 stream.CurrentPackageWorker 与旧 page.LogcatWorker patch 仍被实际启动路径消费。
- [x] 确认新测试因目标包缺失失败，再按迁移表移动实现；保留类方法和信号行为，旧模块仅显式兼容。
- [x] 运行新增与基线测试，并扩大到 `test_live_logcat_feedback.py test_live_logcat_empty_state.py test_live_logcat_material.py test_live_logcat_visual.py`，验证页面导入、视觉构造和关闭。
- [x] 运行 Ruff/中文注释，自查迁移前后算法一致并报告，独立审阅，不提交。

## 集成与收口

- [x] 三项独立审阅完成；主任务核对前置资产和目录迁移表，修复实质问题。
- [x] 受影响生产路径 Pyright（使用当前 `.venv` 路径）、源文本、文档链接、`git diff --check`。
- [x] `python main.py --self-check packaging`；无完整冻结产物或真实设备结论。
- [x] 只有集成失败/污染证据才重跑已通过的测试集合；全量条件按测试指南决定。
- [x] 更新架构、模块地图、索引和总路线图；最终独立审阅本阶段增量，继续后续项目结构阶段。


## 实际验收记录（2026-10-24）

三个独占实现任务及各自独立审阅已完成；最终综合审阅 PASS / APPROVE，无 Critical、Important 或 Minor 问题。

| 验证边界 | 实际结果 |
| --- | --- |
| 应用 helper、图标、元数据与 worker | 172 passed |
| 性能配置/结果、运行器及 GUI 消费者 | 182 passed |
| Logcat 新旧模块、渲染、worker 与关闭 | 78 passed |
| Logcat 反馈、空状态与视觉构造 | 119 passed |
| 主窗口同步/分步构造、五页切换重开与释放 | 5 passed |
| 受影响30个生产文件 Pyright | 0 errors / 0 warnings |
| Ruff、中文注释、源文本、文档链接、diff | 通过；源文本736文件、链接/frontmatter62文档 |
| 源码 packaging 自检 | exit 0 |

合计556个不同用例通过；不重复累计320项迁移前基线和最终11/18项边界复查。
完整命令、原始日志、各任务审阅与资产哈希位于忽略工作区
`.superpowers/sdd/2026-10-24-feature-directory-boundaries/`。
类型检查通过临时配置继承原规则并加入实际解释器依赖路径，未降低检查标准；子任务初次依赖缺失诊断已解决。

本阶段只迁移实现和依赖方向，配置序列化固定字节、旧公共类型/模块身份及实际替换点已有回归。
未修改用户数据格式/路径、设备操作、版本、依赖或 CI，未暂存/提交/推送。
未运行全量 pytest、完整冻结构建、真实设备与桌面手工验收；本次影响范围可按调用链界定，
没有触发测试指南的全量条件。源码自检不能代表完整冻结产物兼容。

下一批继续 FileExplorer、AppManager、Performance 功能包归位；另将已复现的设置 Timer
关闭归属列入独立生命周期修复阶段，不把行为修复夹带到本次目录迁移。
