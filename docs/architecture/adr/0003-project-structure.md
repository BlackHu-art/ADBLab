# ADR-0003：项目结构优化计划（四阶段渐进式）

- 状态：Proposed
- 日期：2026-08-19
- 基线版本：3.2.0

## 背景

知识库重组（2026-08-19）完成后，对代码仓库结构做了一次实测体检：

| 包 | 文件数 | 行数 | 观察 |
| --- | --- | --- | --- |
| `gui/` | 34 | 17,494 | `main_frame.py` 2,263 行、`dialogs/app_manager.py` 1,408、`panels/remote_panel.py` 1,372 |
| `tests/` | 42 | 19,683 | `test_model_execution.py` 3,957 行单文件承担大部分回归；无 pytest marker |
| `mobileperf/` | 24 | 5,418 | `androiddevice.py` 仍含三处 `shell=True` |
| `models/` | 26 | 4,681 | Model/Service/Worker/Store 四类角色混放同一层 |
| `controllers/` | 8 | 3,542 | `_app.py` 1,218 行；录屏/卸载等仍走共享 `_pending_ops`/`_batch_trackers` |
| `adblab/` | 9 | 1,826 | 只有 `application/` 与 `presentation/` 两个 vNext 子包 |
| `core/` | 6 | 896 | `log_service.py` 依赖 PySide6；`settings_manager.py` 反向创建 LogService |
| `utils/` | 12 | 534 | 杂货铺；`batch_tracker.py` 只剩 controllers 两个使用点 |

已确认的结构性问题（按严重度）：

1. 分层不纯：core 依赖 Qt（`core/log_service.py`），且 `core/settings_manager.py` 在错误路径创建
   `LogService`，初始化时序耦合。
2. 执行边界三套实现：主路径 `models/base/` ↔ `core/adb_bridge.py` 直接 Popen ↔
   `mobileperf/android/tools/androiddevice.py` 使用 `shell=True` 和 tasklist/taskkill。
3. 巨型文件：`gui/main_frame.py`（组合根 + 工具栏 + 二级窗口托管 + 关闭状态机）、
   `controllers/_app.py`、`tests/test_model_execution.py`。
4. 状态治理半迁移：Screenshot（Gate A）与安装批次（Gate C）已进 `adblab/application/`，
   录屏/卸载/清数据/重启/当前 Activity 仍走共享字段。
5. 顶层包碎片化：新代码落位 `adblab/`，旧代码分散在 `controllers/models/gui`，命名哲学不一致。
6. 测试无分层 marker，全量约 11 分钟，几何扫描类测试是主要耗时来源。
7. 资源遗留：`resources/app_settings.json`（含本机路径的旧种子）、
   `resources/connected_devices.yaml`（含历史设备标识）仍作为迁移种子。

## 决策

遵循 ADR-0001 的渐进原则，本计划前三个阶段只做包内拆分、新代码落位和执行层收敛，
**不做目录搬家**；物理包重排作为独立第四阶段，执行前需单独决策。

### Phase 0：立规约（本 ADR 生效即为完成）

1. 新用例只落位 `adblab/application/`；新 Qt 适配只落位 `adblab/presentation/`。
2. controllers 只做 Qt 信号协调与结果聚合，不再新增业务状态。
3. 新增 pytest marker：`unit`（无 Qt）、`ui`（轻量 Qt）、`integration`（进程/外部边界）；
   CI 增加 unit + integration 快速子集，全量门禁保留。
4. 大文件拆分的通用边界：`gui/` 单文件目标 < 800 行；拆分只移动代码与内部导入，不改变
   Qt 信号签名和公共接口。

### Phase 1：执行层统一（对齐风险清单 High #1）

1. 新增 `core/process_utils.py`：纯函数 PID 查找/进程树终止（psutil、参数数组、无 Qt）。
2. `mobileperf/android/tools/androiddevice.py` 删除三处 `shell=True`，改用
   `core/process_utils.py`；`killOccupy5037Process` 禁止拼接 PID。
3. `core/adb_bridge.py` 的 Popen 显式注册到 ProcessRunner tracking，消除"统一执行边界"的
   文档与实现漂移。
4. 完成第 3 步后移除 `ruff.toml` 中 `mobileperf/**` 的 E402/UP031 豁免。

### Phase 2：大文件拆分（不动导入面，纯内部提取）

1. `gui/main_frame.py` 拆出：`gui/main_frame_toolbar.py`（工具栏构建/溢出/保存路径省略）、
   `gui/secondary_windows.py`（二级窗口托管与事件过滤器）、`gui/close_controller.py`
   （Gate B2 异步关闭状态机）；MainFrame 只保留组合根接线。
2. `controllers/_app.py` 拆出 `_app_install.py`、`_app_monkey.py`。
3. `tests/test_model_execution.py` 按主题拆为约 8 个文件，与 Phase 0 marker 同步落地。
4. 每步以现有 930 项测试守护，拆分本身不改变任何行为。

### Phase 3：状态治理收口（正确性优先）

1. 录屏/卸载/清数据/重启/当前 Activity 的 `_pending_ops`/`_batch_trackers` 迁入
   OperationManager（延续 vNext Gate 模式，每门独立回滚）。
2. `BatchOperationTracker` 退役：最后一个使用点迁走后删除 `utils/batch_tracker.py` 及对应测试。
3. 对话框 worker 统一接入 TaskSupervisor：App Manager、File Explorer、Remote、MobilePerf。
4. core 无 Qt 化：`settings_manager` 的错误日志改为注入的日志 sink 接口（MainFrame 启动时注入
   LogService 实现），使 `core/` 可无 Qt 单测。

### Phase 4：包布局渐进归一（长期，执行前单独决策）

1. 新增顶层 `services/` 承接纯服务类（`file_explorer_service`、`models/remote/`、
   `models/mobileperf/runner`），`models/` 只留 ADB model 与存储。目录移动需同步
   PyInstaller spec、`pyproject` pythonpath 与知识库，并先提交一份专门的移动 ADR。
2. `adblab/` 继续作为新代码唯一落点，旧包只出不进。
3. MobilePerf 内核中期重构（实例化 RuntimeData、去 `os.chdir`/`os._exit`、统一执行接口）
   与 Phase 1 同步规划。

## 优先级

Phase 1（安全）> Phase 2（可读性与评审成本）> Phase 3（并发正确性）> Phase 4（布局归一）。

## 后果

优点：

- 每阶段独立可验证、可回滚；
- 安全项（shell=True）最先处理，降低命令注入面；
- 大文件拆分不改变行为，回归风险低；
- 与 vNext Gate 迁移共用同一套 operation/supervision 机制，不引入第二套架构。

代价：

- Phase 1–3 期间新旧执行路径/状态路径并存，与 ADR-0001 相同的兼容成本；
- Phase 2 拆分要求严格的信号语义守护，需要 QSignalSpy 级契约测试；
- Phase 4 的目录移动是高风险操作，必须与打包/CI 变更绑定在独立提交并实机验证。

## 与既有文档的关系

- 风险条目同步进 `docs/project-knowledge/RISKS_AND_DEBT.md`（High：shell=True；Medium：
  main_frame 2,500 行、批次 tracker 遗留、全量测试耗时）。
- 各阶段落地后更新 `MODULE_MAP.md`、`ARCHITECTURE.md` 与 `TESTING_GUIDE.md`。
