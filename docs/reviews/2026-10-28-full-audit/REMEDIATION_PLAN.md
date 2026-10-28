# ADBLab 审查问题修复方案与实施计划

> **For agentic workers:** 后续获得实施授权后，使用 superpowers:executing-plans 逐项推进；如用户选择独立任务并行，再使用 superpowers:subagent-driven-development。以下复选框均为待办，不代表已经实施或验证。

**Goal:** 闭环本次审查确认的缺陷，优先保护历史数据和资源退出，保持现有功能、数据格式及兼容入口。

**Architecture:** 沿用 controllers/services/models/core/gui 现有职责分层，各资源由原有 owner 登记、停止、确认退出。业务结果、资源活性和清理错误分别判断；本次不新增顶层目录，不整体重写监督框架。

**Tech Stack:** 项目现有 Python 3.11、PySide6、pytest、Ruff、Pyright 和仓库 `.venv`；不新增或升级生产依赖。

**Spec:** [审查发现与证据](FINDINGS.md)、[后续处理建议](FOLLOW_UP.md)、[验证记录](VALIDATION.md)。本方案整理修复决策与验收任务，不替代原始审查报告。

## 状态与范围

2026-10-28 核对：工作区 `S:\CodeSpaces\PyCharm\ADBLab`，分支 `ui-design`，提交 `574f0d2b39ae55ce126cb60db58cfefaa0d64a5e`。没有已跟踪文件改动；原有截图、`docs/design/`、本次 `docs/reviews/` 未跟踪内容均保留。

本方案覆盖 **15 条已确认缺陷、1 条条件性风险 F11、2 条规范差异 D01/D02**。本轮只新增方案文档，未开始修复。实施前重新核对目标文件差异；基线变化时先复验问题，不机械套用旧行号。

推荐采用“按风险分批、每个根因独立验收”的路线。一次统一重构生命周期框架会扩大兼容风险；只修可见 UI 问题又会留下数据和退出缺口。下面的实现选择是推荐方案，不记作用户已经批准的产品决定。

## 全局约束

- 保留设备历史 YAML、设置键与迁移、APK ZIP 布局、性能报告和归档格式；不引入用户数据迁移。
- 保留旧导出、模块身份、Qt 回调与测试替换入口，目录调整仅在具体修复确有需要时另列依据。
- 保留设备目标快照、Android 用户复核、owner/generation、取消与旧结果拒收约束。
- 保留安装不重放、COMMIT、nonce、父进程身份及摘要校验；不得把所有 helper 一律终止。
- 所有等待有预算；超时后仍活跃的资源继续有 owner。不能用强制销毁 QObject 或吞掉异常制造退出成功。
- 保留 ZIP 防护、命令输入校验和现有测试断言强度；不靠增加 sleep、skip 或放宽断言通过验收。
- 本地修复不改版本，不执行 commit/push、真实 ADB、安装器、正式构建或发布。这些动作按后续明确授权和独立环境安排。

## 批次和依赖

| 批次 | 问题 | 交付目标 | 前置条件／相对规模 |
| --- | --- | --- | --- |
| A：验证基础 | F14、F10 | UI 探测全生命周期隔离；等待真实提交点 | 最先准备后续 Qt 验收；中 |
| B：数据保护 | F01、F08 | 未读历史不丢失；新备份满足恢复准入 | 可与 A 独立推进；中 |
| C：进程与错误终态 | F03、F02、F04 | 清理失败不被洗掉，活客户端和失败 helper 不失去归属 | C 内先 F03；涉及共享关闭链，串行集成；中至大 |
| D：页面与采集收尾 | F05、F06、F07 | Logcat 导出进入关闭屏障；全部代次 reader 可排空 | A、C 的相关验收完成；中至大 |
| E：功能一致性 | F09、F12、F15、F13 | 多用户 FPS 目标、数值格式、Monkey 计数及跨平台置顶 | Qt 用例依赖 A；F13 平台验收单列；各小至中 |
| F：工程收口 | F16、F11、D01、D02 | 完整枚举 Actions；构建来源校验；规范与实现一致 | F11 先复现再决定修复；各小 |

规模表示相对改动与验证复杂度，不是工时或性能收益承诺。A 不应阻塞 B 的 F01 数据保护。F09、F16 等独立文件可与其他修复并行；Qt、共享设置和线程／进程验证统一安排串行窗口。

## 重点复核场景

1. 读历史失败且备份失败，稍后 I/O 恢复时不能覆盖未读旧内容；B1 负责。
2. 业务已失败但资源仍存活，不能释放 owner 或误判 idle；C2、C3、D1、D2 负责。
3. 模态文件框期间开始关闭，返回后不能接纳新任务；D1 负责。
4. 旧代 reader 未排空而新代已经启动，资源统计不能漏旧代，结果也不能串代；D2 负责。
5. 成功提示之前发生取消、校验失败或平台拒绝，不能发布文件或显示虚假成功；B2、C3、E2、E4 负责。

## A：先保证验证可信

### A1 — F14，隔离延迟客户端探测

**文件：** `tests/test_qt_adb_runtime.py`、`tests/test_main_window_layout.py`，以及复用窗口 helper 的 `test_live_logcat_visual.py`、`test_file_explorer_visual.py`、`test_workspace_consolidation.py`、`test_navigation_rendering.py`、`test_workspace_feature_host.py`。仅在确有共享需要时调整 `tests/conftest.py`，不得以全局禁用掩盖检测功能覆盖。

- [ ] 迁入审查反例：构造设置页并处理延迟事件，断言非检测测试不解析真实客户端、不创建改名副本、不执行 native version。
- [ ] 将替身寿命覆盖构造、定时回调、后台任务和 teardown；检测专用测试显式使用合成候选与脚本化 runner，保持真实 Qt 投递。
- [ ] 先跑直接节点，再按上述 helper 消费者扩大；每个后台任务实际结束后才能恢复补丁和临时路径。

**验收：** 所有外部调用均由受控替身接管，关闭后无待运行探测；不改变生产自动检测功能。

### A2 — F10，修复两个测试域的同步点

**文件：** `tests/test_model_ci_controller.py`、`tests/test_phase2_live_logcat_gate.py`。

- [ ] 用可控门闩固定“查询开始但结果未发布／PID 未提交”的时序，保留当前业务断言。
- [ ] metadata 测试等待首次 emit 的可观察事件后再断言或使 topology 失效；Logcat 测试等待当前 package/generation 对应 PID 提交后再发送唯一目标行。
- [ ] 覆盖先阻塞、再提交、随后失效／切包的顺序，确保 finally 释放并等待所有线程；运行两文件的直接及关联节点。

**验收：** 合法线程调度不能令测试误报；不修改生产代码来迎合原有错误同步点。

## B：保护用户已有数据

### B1 — F01，DeviceStore 未读原文件写保护

**文件／接口：** `models/device_store.py` 的读取、备份、`_persist_snapshot` 路径；保持 `load/save/add_device/upsert_devices` 的调用接口。测试入口 `tests/test_device_store_concurrency.py`。

- [ ] 增加读失败且备份失败后再次保存的回归，覆盖冷启动空内存、热加载旧内存、正常并发保存、取消、来源路径切换。
- [ ] 记录原文件尚未安全读取或保全的保护状态，所有持久化入口统一拒绝覆盖。内存展示可继续，写入拒绝沿现有错误通道表达，不能报告保存成功。
- [ ] 推荐最小策略：只有成功重新加载原文件，或确认原文件已完整备份后，才解除相应保护。本批不把过时的全量内存快照直接合并回磁盘，也不新增隐式自动恢复／迁移；重读后的新修改沿既有保存路径处理。
- [ ] 验证保护期间原文件字节不变、正常恢复后可保存、备份失败不被当成功、临时文件被清理。对照既有带附加扫描块的容错加载及 IP/USB 持久化规则。

**验收：** 未读且未保全的内容不会丢失；文件格式、地址过滤和正常保存行为兼容。若后续要求故障期间的编辑自动重放，须另设计变更日志与删除语义，不在本批偷偷加入。

### B2 — F08，备份发布与恢复使用同一准入规则

**文件／接口：** `utils/archive.py`、`services/apps/archives.py`；保留 `safe_extract_zip(zip_ref, target_dir)`。推荐在同模块抽取不解压的 `validate_zip_archive(zip_ref, target_dir) -> None`，由提取和发布前检查共用。测试 `tests/test_app_archives.py`，新增 `tests/test_archive_validation.py` 专门覆盖共用边界。

- [ ] 增加正常/split APK 往返、大小／成员数／压缩比超限、路径逃逸和取消反例，断言校验失败时旧备份原样保留、安装调用为零。
- [ ] 抽出当前准入判断，保留 512 MiB、10,000 成员、现有压缩比判定及路径检查的精确语义；不改变阈值计算方式。
- [ ] staged ZIP 发布前调用同一验证器，检查后再次核对取消，再执行原子替换；失败沿原错误通道返回。
- [ ] 直接测试通过后检查共用 ZIP 函数的其他调用方并选择关联测试；不执行真实下载或解压用户归档。

**验收：** 本工具新报告成功的备份满足恢复的安全准入；不承诺设备安装必然成功，不放宽大 APK 的安全限制。支持更大归档属于另行产品决策。

## C：进程所有权与清理错误

### C1 — F03，保留已经发生的清理失败

**文件／接口：** `core/tasks/supervision.py` 的 `stop/_stop_selected`，复用已有 completion error 与 `StopDisposition.FAILED`；消费者为关闭控制器。新建直接测试 `tests/test_task_supervision_completion.py`，关联 `tests/test_phase2_mainframe_shutdown_gate.py`、`tests/test_qt_supervisor_shared.py`。

- [ ] 参数化验证 stop/owner/all 对预先失败任务返回 FAILED；另测首次 FAILED 后再次 stop，以及无错误的正常已停止对照。
- [ ] 已停止分支读取完成错误并保留失败记录，保持与运行中等待结束分支一致；重复停止不洗掉错误，也不重新执行已经结束的资源操作。
- [ ] 验证升级关闭门禁仍拒绝清理失败；不得把错误记录数直接宣称为存活线程数。

### C2 — F02，默认 native 路径保留残留客户端

**文件／接口：** `core/native_process.py`、`core/exec.py`，结合 `core/adb_runtime.py` 的 `native_capture/native_cleanup_count/wait_for_native_cleanup` 机制；检查 `gui/close_controller.py` 的 `active_count/wait_for_idle` 消费。

- [ ] 在 `tests/test_native_process.py`、`tests/test_native_capture_cleanup.py` 添加 kill/wait 失败后客户端仍活跃的回归；业务结果必须失败，同时 idle 不得为真。
- [ ] 默认执行路径在无法确认退出时转交明确的残留 owner；后续检查／关闭继续处理，确认退出且身份匹配后才释放。复用已有机制，不新建无界轮询线程。
- [ ] 覆盖自然迟到退出、重复清理、已退出句柄、并发调用与总等待预算；关联 `tests/test_command_outcomes.py`、`tests/test_native_command_scope.py` 和主窗关闭测试。

**验收：** 失败返回不丢进程归属；安装仍不可重放且保持原取消契约；只收口本次直接客户端，不终止独立 ADB server 或其他应用进程。

### C3 — F04，失败升级 helper 与正常交接分开收口

**文件／接口：** `core/installer_handoff.py`、`gui/adapters/installer_handoff.py`；保留 `reset_attempt/prepare` 业务入口及安装协议。

- [ ] 在 `tests/test_installer_handoff.py` 添加握手失败且 helper wait 超时的反例：句柄仍被持有、reset 被拒绝；模拟迟到退出后允许重试。
- [ ] 保留失败尝试的活 helper，并将其资源状态纳入 Qt 适配器／关闭监督；检查必须有界，不能在 GUI 线程等待进程。
- [ ] 分别验证取消、握手失败、重复开始、窗口关闭和正常授权路径，关联 `tests/test_installer_update_ui.py`、`tests/test_qt_installer_update.py` 及主窗关闭门禁。

**验收：** 失败 helper 未退出时不能重试叠加；正常准备并授权的 helper 仍能等待父应用退出。不得为了“无残留”等待或终止本应跨父进程退出运行的 helper。全部使用假进程，不启动安装器。

## D：页面与采集资源收尾

### D1 — F05/F06，Logcat 导出加入关闭屏障并封闭准入

**文件／接口：** `gui/features/logcat/stream.py`、`page.py`、`lifecycle.py`，沿 `gui/features/base.py` 的现有 shutdown 注册协议接入；不新增第二套关闭协调器。

- [ ] 在 `tests/test_live_logcat_render_batches.py` 和 `tests/test_phase2_mainframe_shutdown_gate.py` 迁入受控真实 QThread 探针：导出未 join 时不得 close_ready。
- [ ] 将导出资源登记到现有 owner；自然结束与关闭取消均以实际线程退出作为解除条件，导出失败保留原用户反馈。
- [ ] 文件框打开前和返回后均检查对象有效性、页面关闭状态及忙碌状态；dispose 后返回路径不得创建线程。
- [ ] 覆盖成功、失败、重复导出、取消文件框、模态期间 dispose、单页释放和全局退出；再关联 `tests/test_window_lifecycle.py`。另用隔离子进程验证真实窗口销毁退出码与致命 Qt 输出。

**验收：** 导出线程不会漏出关闭监督；已关闭页面不接纳新任务。替身测试通过不等于已经证明所有平台原生退出安全。

### D2 — F07，分离 MobilePerf 可重启状态与全部资源活性

**文件／接口：** `services/mobileperf_runner.py`、`gui/features/performance/page.py`、`run.py`。保留现有 `is_running()` 供原业务启动判断；推荐增加 `has_active_resources() -> bool`，涵盖全部未排空代次的进程、mode thread、stdout/stderr reader。

- [ ] 在 `tests/test_mobileperf_runner_concurrency.py` 加入旧代双 reader 延迟、新代已启动的受控场景，断言业务可重启时资源仍活跃。
- [ ] 按代次保留资源上下文，确认真实线程退出后才移出；停止与等待使用同一截止时间，禁止每个 reader 重新获得完整预算。
- [ ] 页面监督、dispose 和等待排空的消费者改用资源谓词；本次报告完成仍按本次代次判断，不能误等新一轮采集或接收旧代结果。
- [ ] 关联 `tests/test_performance_start_lifecycle.py`、`test_performance_package_lifecycle.py`、`test_performance_result_loading.py` 和关闭门禁，覆盖取消、迟到回调、写出收尾及重复停止。

**验收：** 允许重启的既有契约保留；资源统计含旧代 reader；结果、日志和报告归属不串代。长时间设备采集与远端排空另列实机验收。

## E：用户可见功能

| 任务／文件 | 推荐实现与兼容约束 | 必须新增的验收／直接测试 |
| --- | --- | --- |
| E1，F09：`mobileperf/android/tools/androiddevice.py`；消费链 `mobileperf/android/fps.py` | 将 u0 特判改为识别可选合法 u<数字> 字段并提取组件；保留无用户字段的旧格式和缺样语义 | `tests/test_mobileperf_parsers.py`：u0/u10、空/null、短行、重复空格、旧格式；fake gfxinfo 验证使用真实组件匹配。关联 sampling/metric 测试 |
| E2，F12：`gui/panels/base_panel.py`、`system_panel.py` | 推荐针对 ADB 协议数值字段显式使用 C locale 并拒绝分组符，提交规范 ASCII；后端 `utils/adb_values.py` 严格校验不变。先检查工厂全部消费者，普通本地展示不被强制改格式 | `tests/test_responsive_panels.py`、`test_adb_values.py`：de_DE/en_US/zh_CN，端口、坐标、小数、PID、分组符、正负号、边界值；实际 SystemPanel 信号收到预期文本，非法输入不发命令 |
| E3，F15：`gui/panels/app_panel.py` | 单台完成后刷新展示，不修改 Monkey 运行状态机、目标集合或停止逻辑 | `tests/test_monkey_batch_state.py`：2→1→结束、部分失败、重复结果、旧代结果；标签与实际剩余目标一致 |
| E4，F13：`gui/main_frame.py`、必要时 `gui/pages/fluent_pages.py` | 仅非 Windows 走受控 Qt 置顶 flag 路径，保留窗口可见性、几何、状态和合理焦点；Windows 原生分支及失败时不重建窗口规则不变 | `tests/test_model_mainframe.py`：开/关、启动已置顶后关闭、隐藏/最小化窗口；Windows 回归。Linux/macOS 实际窗口管理器单独验收，不能用 Windows 模拟平台结果冒充 |

各任务独立执行以下步骤：

- [ ] 先补直接反例并确认它因原问题失败。
- [ ] 实施表中最小修改，检查真实调用方及旧接口。
- [ ] 运行直接测试，再按受影响控件或消费链扩大。
- [ ] 记录平台未覆盖范围；如新增提示文案，同步项目词库及语言测试。

E2 是对现有后端可接受格式的前置对齐；支持 locale 自然数字输入的解析／规范化可作为另一产品方案，本批不同时支持两种歧义格式。E4 若实际平台无法可靠即时生效，应记录受阻并提出重启生效提示方案，不能继续显示已生效；该交互变更需单独确认。

## F：工程与规范收口

### F1 — F16，Actions 引用完整枚举

**文件：** `tests/test_ci_contracts.py`；使用现有 YAML 依赖，不修改 workflow 或 CI/CD 流程。

- [ ] 临时夹具加入无注释、列表内 inline uses、`.yml`、非 SHA、未知来源和混合合法／非法引用，证明旧门禁漏检。
- [ ] 先枚举 `.yaml/.yml` 中所有 steps/job 层 uses，再按现有来源和固定 SHA 规则逐个检查；本地 action、容器 action、可复用 workflow 显式分类，未支持类型明确拒绝，不能悄悄忽略。
- [ ] 保留当前合法工作流通过和反例拒绝断言；运行该文件，无需触发 CI。

### F2 — F11，先验证图标 helper 来源竞态

**文件：** `scripts/build_app_icon_helper.py`；新建 `tests/test_build_app_icon_helper.py`，源码及产物均在临时目录。

- [ ] fake 编译器在读取源码后修改临时源文件，验证旧编译结果是否被新摘要认可；若无法复现，保留风险，不按已确认缺陷宣称修复。
- [ ] 确认后优先沿同类 helper 构建器的编译前摘要／发布前重核方式，拒绝本次源码变化并保留旧产物；若需抵抗修改后又恢复的 ABA 窗口，应编译不可变快照，不能宣称两次摘要彻底消除任意并发变化。
- [ ] 验证稳定源码成功、源码变化拒绝、编译失败和校验失败保留旧产物；不调用真实 javac/d8，不重建仓库 JAR。

### F3 — D01/D02，更新当前事实和规范入口

**文件：** `docs/project-knowledge/RISKS_AND_DEBT.md`、`.dsh/skills/adblab-verify/SKILL.md`、`.dsh/skills/adblab-ui-i18n/SKILL.md`。

- [ ] UI-05 改为已分批构建，保留最终排序／绘制未测量风险；不要直接标记性能问题全部闭环。
- [ ] 将工作区路径提示改为动态核对规则，DEFAULTS 的定义指向 `core/settings/schema.py`，保留 `settings_manager` 兼容导出说明。
- [ ] 逐批修复验收后才更新风险账本的闭环状态，链接实施证据；原始 FINDINGS/COVERAGE 保留审查时状态。
- [ ] 运行文档检查；若修改技能说明中的命令或路径，核实其真实存在，不执行正式构建验证文字修改。

## 实施调度与验证记录

推荐由主 Agent 统一集成和测试排期；如果后续采用多 Agent，最多三个实施子任务并行且文件边界不重叠。C 的共享监督与关闭接口先串行稳定，D 再接入；共享 `base_panel.py`、窗口 helper、关闭门禁测试不得同时改写。独立复核者在每个高影响批次后重新检查实现、调用方、防护和测试，最后复核跨模块链路。

每个任务先读其领域 skill 和目标局部规则。回归可以从 [EVIDENCE.md](EVIDENCE.md) 转为仓库测试，但不能照搬临时探针的假接口；使用项目真实依赖协议和失败语义。

测试命令使用项目解释器，例如 B1：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_device_store_concurrency.py
```

其他任务用各节列出的直接文件／节点替换范围；Qt 需要时设置 `$env:QT_QPA_PLATFORM = "offscreen"`。执行前隔离设置、历史、归档、导出、客户端候选、子进程及网络，临时缓存和日志写入专用目录。不能以 `not ui` 作为无副作用或并行安全证明。

每批记录：变更文件与基线、回归失败证据、实际命令及退出码、直接／关联结果、资源清理结果、独立复核意见、未验证场景。完成条件是反例失败转通过、既有契约未退化且无新增残留；不是只有 pytest 输出通过。

Lint 检查修改的 Python 文件；共享接口变化时对相关生产模块运行 Pyright；生产注释与文档按项目现有工具检查。全量测试仅在[增量验证策略](../../guides/TESTING_GUIDE.md#增量验证策略)触发条件成立时，由 Lead 说明原因并集中执行一次。源码 packaging self-check 按实际触及的启动／资源／运行时路径边界选择，不把正式构建绑定到每个修复。

## 单列的真实环境验收与可选优化

- Android：副用户／工作资料 FPS、厂商焦点格式、签名 APK/split APK 备份恢复、长时间采集停止后远端资源。
- Windows：真实主窗口销毁、原生文件框期间退出、失败升级 helper 的实际父子进程交接；安装／升级／卸载仍使用一次性授权环境。
- Linux/macOS：置顶开启和关闭、窗口状态恢复、具体窗口管理器与 Qt 原生退出。
- 构建／发布：仅在另行安排产物验收时执行，不能引用审查前历史成功结果替代当前版本证明。

这些项目在实际完成前保持“待验证”，不阻止明确限定范围的本地修复验收，也不允许因此宣称全部平台已验收。

目录结构维持现状。可选结构优化仅在上述修复稳定后评估资源状态接口是否值得统一；不以文件长短为拆分理由。文件列表性能先以 1k/10k 合成数据测量首批时间、完成时间、事件循环最大间隔和内存，再决定排序或模型调整，本方案不承诺未经测量的性能收益。
