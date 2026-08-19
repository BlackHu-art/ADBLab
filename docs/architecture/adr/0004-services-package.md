# ADR-0004：物理包归一（services/ 顶层包）与 MobilePerf 内核实例化

- 状态：Accepted
- 日期：2026-08-19
- 前置：ADR-0003 Phase 1–3

实施进度：包移动（决策 1–3）已完成——`services/file_explorer.py`、
`services/remote/`、`services/mobileperf_runner.py` 落位，全部导入点已改向，
`models/mobileperf/` 包已删除；MobilePerf 内核实例化（决策 4）待实施。

## 背景

ADR-0003 Phase 2 完成大文件拆分后，`models/` 仍混装四类角色：ADB model（`adb_*.py`）、
存储（`device_store.py`）、Worker（`app_manager_worker.py`、`file_explorer_worker.py`）与
纯服务（`file_explorer_service.py`、`remote/`、`mobileperf/runner.py`）。实测导入面很小：

- `models/file_explorer_service.py`：仅 `gui/dialogs/file_explorer.py` 与 1 个测试文件导入。
- `models/remote/`：仅 `gui/panels/remote_panel.py` 与 1 个测试文件导入。
- `models/mobileperf/runner.py`：仅 `gui/dialogs/performance_launcher.py` 与 4 个测试文件导入。

另外 MobilePerf 内核仍使用类级 `RuntimeData`、`os.chdir` 与 `os._exit(0)`，停止/落盘边界脆弱
（RISKS_AND_DEBT Medium 项，靠子进程隔离兜底）。

## 决策

1. 新建顶层 `services/` 承接纯服务（低 Qt 耦合、可独立单测的业务/外部工具适配）：
   - `services/file_explorer.py` ← `models/file_explorer_service.py`
   - `services/remote/` ← `models/remote/`（整体）
   - `services/mobileperf_runner.py` ← `models/mobileperf/runner.py`
   `models/` 保留 ADB model、存储与 Worker（`base/`、`adb_*.py`、`device_store.py`、
   `app_manager_worker.py`、`file_explorer_worker.py`）。
2. 移动一律使用 `git mv` 保留历史；直接更新全部导入点（导入面已量化，共 3 个生产文件与
   若干测试），**不留 re-export 垫片**；完成后用 grep 验证旧路径零残留。
3. PyInstaller 收集无需改动：`services/` 是一方 Python 代码，跟随 import 自动收集；
   CI 的 `--collect-submodules mobileperf` 与 `--add-data mobileperf` 不涉及本包。
4. MobilePerf 内核实例化（独立提交）：
   - `RuntimeData` 类级全局 → 运行级实例上下文（`StartUp` 创建一次运行 context，注入各
     monitor 与 `androiddevice.ADB`）；
   - `os.chdir` 改为显式目录参数（配置/结果路径解析不再依赖进程工作目录）；
   - `os._exit(0)` 改为正常 return，由 `MobilePerfRunner` 以退出码收口，保留现有
     "退出码 0 且存在本次报告才 Completed/100" 语义。

## 后果

优点：

- `models/` 职责纯化，服务边界清晰；`services/` 与 `adblab/application/` 平行命名，新代码
  落位规则更直观；
- 内核实例化后 MobilePerf 可脱离 `os.chdir`/`os._exit` 依赖，停止/落盘可测试性提升。

代价与风险：

- 目录移动触碰 PyInstaller 与测试的 import 路径；需打包自检与全量测试守护；
- 内核实例化改动面大（monitor 全程），需按模块小步迁移并在授权设备做最小实机验证
  （当前无授权设备，实机项标记待确认）。

回滚：

- 三个 `git mv` 各自独立提交，可单独回滚；内核实例化按文件分步提交，
  失败时保留子进程隔离兜底路径。

## 与既有决策的关系

- 延续 ADR-0001"物理包重排放在核心迁移完成后"的次序（Phase 4 是收尾阶段）。
- 执行层统一（ADR-0003 Phase 1 的 `core/process_utils`）为内核实例化提供无 shell 的
  进程工具基础。
