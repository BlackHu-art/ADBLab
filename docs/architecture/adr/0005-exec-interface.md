# ADR-0005：执行接口统一（core/exec.py 契约与落位）

- 状态：Accepted（Step A–D 全部落地，全量测试守护通过）
- 日期：2026-08-20
- 前置：ADR-0003（分层与物理包）、ADR-0004（services/ 归一）

实施进度：Step A–D 已全部落地，垫片清零完成——`core/exec.py` 承载
`CommandResult`/`CommandRunner`/`ProcessRunner`/`ExecHandle`/`resolve_command`/创建标志；
`core/adb_bridge.py`、`services/*`、`models/*`、`gui/*`、`controllers/*` 与全部测试的导入
均直连 `core.exec`，`models/base/command_runner.py` 与 `models/base/process_runner.py`
两个垫片文件已删除（2026-08-21），core → models 反向依赖解除。Step C：`ProcessRunner`
树杀路径统一委托 `core/process_utils.kill_process_tree`（psutil，支持共享绝对截止时间），
内联 taskkill 路径删除。Step D：`ExecHandle` 协议含 stdio 结构面，`MobilePerfRunner`/
`ScrcpyService`/`ADBInputSession` 已面向协议标注。全量测试守护通过。

## 背景

当前进程/命令执行面有两条主路径，但存在三类结构性问题：

1. **分层倒挂**：`core/adb_bridge.py` 依赖 `models/base/command_runner.py` 与
   `models/base/process_runner.py`（`CommandResult`、`CommandRunner`、`ProcessRunner`），
   而 ADR-0003 约定依赖方向是 `gui → controllers → models/services → core/utils`，
   `core` 不应反向依赖 `models`。这两个 runner 本质是进程基础设施，物理落位应在
   `core`，而非 `models/base`（`models/` 的定位是 ADB model、存储与 Worker）。
2. **关注点重复**：
   - ADB 可执行路径解析三处重复：`command_runner._get_adb_path`、
     `process_runner._resolve_cmd`（仅替换命令首位 `"adb"` token）、
     `core/adb_bridge.py` 直接调用 `utils.adb_resolver.adb_path()`；
   - Windows 创建标志重复：`command_runner.CF` 与 `process_runner` 内
     `CREATE_NO_WINDOW` 的重复派生；
   - 进程树终止两套实现并存：`process_runner` 内联 `taskkill /T /F` 两条路径
     （无界 5s 与按截止时间有界），与 `core/process_utils.kill_process_tree`
     （psutil 实现、无 shell、ADR-0003 Phase 1 产物）语义重叠；
   - 慢命令日志内联在 `command_runner`，阈值读取绕经 `core.settings_manager`。
3. **无类型契约**：`MobilePerfRunner`、`ScrcpyService`、`ADBInputSession` 均面向
   `subprocess.Popen` 直接编程（`poll/wait/terminate/kill/returncode` 裸用），
   没有统一的进程句柄协议，替换执行后端或做测试替身时需要逐处适配。

目标：在 `core/exec.py` 定义统一执行契约与共享工具，把两类 runner 物理移入 `core`，
消除分层倒挂与重复关注点；**执行语义零变化**，现有调用方经兼容垫片继续工作。

## 决策

1. 新建 `core/exec.py`，承载：
   - `CommandResult`：短命令归一结果（由 `models/base/command_runner.py` 原样迁入，
     单一物理定义，不再有别名副本）；
   - `CommandRunner`：同步短命令执行（`run`/`run_to_file`，语义与现状一致）；
   - `ProcessRunner`：长进程执行（`start`/`spawn`/`stop`/`request_stop`/`force_stop`/
     `poll`/`stop_all`/全局登记兜底，语义与现状一致）；
   - `ExecHandle` Protocol：`poll() -> int | None`、`wait(timeout) -> int`、
     `terminate()`、`kill()`、`returncode`、可选 `stdin/stdout/stderr`——描述
     `subprocess.Popen` 与测试替身共同满足的结构面，供 `MobilePerfRunner`、
     `ScrcpyService`、`ADBInputSession` 做类型标注；
   - `resolve_command(cmd)`：唯一的 ADB 路径替换入口（首位 `"adb"` token → 解析路径，
     带缓存），替换 `_get_adb_path` 与 `_resolve_cmd`；
   - `CF` / `CREATE_NO_WINDOW`：唯一创建标志定义，`models/base` 侧删除重复派生。
2. 物理搬迁（`git mv` + 保留历史）：`CommandResult`、`CommandRunner`、`CF` 迁入
   `core/exec.py`；`ProcessRunner` 及全局登记表迁入 `core/exec.py`。
   `models/base/command_runner.py` 与 `models/base/process_runner.py` 变为**兼容垫片**
   （re-export，docstring 指向 `core.exec` 并标注 deprecated），导入面零破坏；
   `core/adb_bridge.py` 改从 `core.exec` 导入，分层倒挂解除。
3. 测试补丁目标随物理位置更新：`tests/test_model_processes.py` 等对
   `models.base.process_runner.subprocess.Popen` / `models.base.command_runner.subprocess.run`
   的 patch 改指向 `core.exec.subprocess.*`（行为断言不变）；全量测试守护等价性。
4. 进程树终止收敛：`ProcessRunner` 的 `_kill_process_tree*` 与 `_stop_proc` 统一委托
   `core/process_utils.kill_process_tree`（psutil、无 shell、先子后父），删除内联
   `taskkill` 路径；`stop` 的 terminate→wait→树杀→kill 顺序与超时值保持不变。
   若回归测试暴露 psutil 与 taskkill 的边界差异（权限、无 psutil 环境等），保留
   taskkill 作为 `kill_process_tree` 的 Windows 兜底并在 ADR 补充说明。
5. `ExecHandle` 仅用于类型标注与结构约束，**不引入**新的包装类：`Popen` 天然满足
   协议，避免额外对象层与性能/GC 语义变化。
6. 不迁移 MobilePerf 内核自身的 `subprocess` 调用（`mobileperf/android/tools/`）：
   内核在独立子进程中运行，属另一执行边界，维持现状。

## 实施步骤（每步独立提交、跑全量门禁）

- Step A：`core/exec.py` 新建（`CommandResult`/`CommandRunner`/`CF`/`resolve_command`/
  `ExecHandle`），`models/base/command_runner.py` 转垫片，`adb_bridge` 改导入；
  测试 patch 目标同步更新。
- Step B：`ProcessRunner` 迁入 `core/exec.py`，`models/base/process_runner.py` 转垫片；
  `adb_bridge`/`services/*`/`controllers` 导入点更新或维持垫片导入（垫片期内
  行为等价，可零散迁移）。
- Step C：树杀收敛到 `core/process_utils`（决策 4），删除重复标志定义。
- Step D：`MobilePerfRunner`/`ScrcpyService`/`ADBInputSession` 面向 `ExecHandle`
  类型标注（纯类型层，不改变运行时行为）。

## 后果

优点：

- `core` 不再依赖 `models`，分层方向与 ADR-0003 一致；执行基础设施集中在
  `core/exec.py`，新边界（如未来的 MobilePerf 扩展入口）有唯一落位；
- ADB 解析、创建标志、树杀、慢命令日志各自单一实现，消除三处重复的漂移风险；
- `ExecHandle` 协议让进程句柄可注入、可伪造，`MobilePerfRunner` 等适配器的
  单元测试不再强依赖真实 `Popen` 行为。

代价与风险：

- 物理搬迁触碰大量测试的 patch/import 目标（`test_model_processes.py` 等），
  需全量测试守护；垫片保留期间新旧路径并存，完成后用 grep 验证
  `models.base.*runner` 的残留导入并给出清零计划；
- 树杀从 taskkill 切到 psutil 属行为等价迁移，但进程树终止的边界行为
  （权限、僵尸进程）可能产生回归，Step C 需单独跑进程管理相关测试并复查；
- `ExecHandle` 为纯协议，不强制运行时校验，约束力靠类型检查与评审。

回滚：

- Step A/B/C/D 各自独立提交；垫片保留 `models/base` 旧入口，任一 Step 回滚后
  调用方仍可工作；树杀收敛单独成 Step，可独立回退到 taskkill 路径。

## 与既有决策的关系

- 延续 ADR-0003 Phase 1（`core/process_utils` 无 shell 进程工具）与 ADR-0004
  （`services/` 归一后 `models/` 只留 ADB model/存储/Worker）——本 ADR 是执行
  基础设施从 `models/` 剥离的最后一步；
- 与 ADR-0006（AppSettings schema 版本化）无耦合，可并行实施。
