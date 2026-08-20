# ADBLab 项目知识库

本知识库是 ADBLab 当前实现的长期维护入口，按四区组织：现状事实、决策、操作指南和过程归档。
结论以仓库代码、配置、测试和构建脚本为依据；不能由仓库确认的内容统一标记为"待确认"。修改代码时，
先从本页定位必读文档，再追踪入口、调用链、失败路径、线程/进程清理和现有测试。

## 四区说明

| 分区 | 目录 | 内容 | 更新规则 |
| --- | --- | --- | --- |
| 现状事实 | `docs/project-knowledge/` | 当前实现的架构、模块、流程、数据、依赖、术语和风险账本 | 代码/配置变化时同步更新 |
| 决策 | `docs/architecture/` | ADR、实施计划等决策留痕 | 新增决策时追加，不回改历史 ADR |
| 操作指南 | `docs/guides/` | 已验证的构建、运行、测试命令与注释风格规范 | 命令/门禁变化时同步更新 |
| 过程归档 | `docs/archive/` | 阶段账本、评审、历史卫生检查 | 只归档不更新 |

单源规则：每个事实只在一篇文档展开，其余文档用链接指回，不复述；风险条目只进
[project-knowledge/RISKS_AND_DEBT.md](project-knowledge/RISKS_AND_DEBT.md)。完整约定见
[CONTRIBUTING_DOCS](CONTRIBUTING_DOCS.md)。

## 基线与状态

| 项目 | 当前记录 |
| --- | --- |
| 事实基线 | `dev` 分支 HEAD，扫描日期 2026-08-19 |
| 本次整理 | 2026-08-19，当前仓库 `dev`，版本 3.2.6 |
| 基线以来变更 | `dev` 自 main 基线 `8b84f8d`（3.1.14）重做：7 个实现提交（`70be33e` 卫生、`481175d` 安装批次 Gate C、`e36e3e6` Remote/MobilePerf 修复、`6ae6fea` 响应式框架控件、`3492159` 响应式面板/对话框/主窗口、`2f999eb` screen adapter 抽取与几何扫描提速、`d099b39` 知识库校准），以及随后的文档锚点同步提交 |
| 文档范围 | 根入口、`controllers/`、`core/`、`gui/`、`models/`、`utils/`、`adblab/`、`tests/`、`.github/workflows/`、`mobileperf/` 核心代码，以及资源和内置工具用途 |
| 文档 owner | 待确认；未指定具名维护人前，不把这些文档视为正式受控 SOP |
| 敏感信息规则 | 不记录密钥、Token、密码、私有证书、真实设备唯一标识、邮件正文或验证码 |

## 快速阅读路径

| 场景 | 先读 | 再读 |
| --- | --- | --- |
| 快速理解项目 | [PROJECT_OVERVIEW](project-knowledge/PROJECT_OVERVIEW.md)、[glossary](project-knowledge/glossary.md) | [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md) |
| 修改启动、分层、线程或关闭逻辑 | [ARCHITECTURE](project-knowledge/ARCHITECTURE.md)、[MODULE_MAP](project-knowledge/MODULE_MAP.md) | [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md)、[TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 修改具体功能模块 | [MODULE_MAP](project-knowledge/MODULE_MAP.md) | 对应 [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md) 章节、[TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 修改 ADB/HTTP/外部命令边界 | [DEPENDENCY_MAP](project-knowledge/DEPENDENCY_MAP.md) | [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md) |
| 修改配置、持久化或用户数据 | [DATA_FLOW](project-knowledge/DATA_FLOW.md) | [BUILD_AND_RUN](guides/BUILD_AND_RUN.md) |
| 修改 Remote 或 MobilePerf | [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md)、[MODULE_MAP](project-knowledge/MODULE_MAP.md) | [DEPENDENCY_MAP](project-knowledge/DEPENDENCY_MAP.md)、[TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 修改日志、注释或文档字符串 | [ARCHITECTURE](project-knowledge/ARCHITECTURE.md)、[TESTING_GUIDE](guides/TESTING_GUIDE.md)（注释规范章节） | [TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 构建、打包、发布或 CI | [BUILD_AND_RUN](guides/BUILD_AND_RUN.md)、[TESTING_GUIDE](guides/TESTING_GUIDE.md) | [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md) |

## 文档地图

### 现状事实（project-knowledge/）

- [PROJECT_OVERVIEW](project-knowledge/PROJECT_OVERVIEW.md)：项目目标、用户、能力、技术栈、运行环境、当前状态与关键术语入口。
- [glossary](project-knowledge/glossary.md)：项目专有名词、通用缩写和对应代码概念。
- [ARCHITECTURE](project-knowledge/ARCHITECTURE.md)：总体分层、运行时组件、初始化/关闭、线程/进程模型和架构限制。
- [MODULE_MAP](project-knowledge/MODULE_MAP.md)：模块职责、接口、上下游、配置、数据、测试与风险。
- [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md)：启动、设备、应用、安装批次、Monkey、诊断、文件、Remote、MobilePerf 和关闭链路。
- [DATA_FLOW](project-knowledge/DATA_FLOW.md)：核心数据对象、来源、转换、存储、生命周期、状态变化，以及文件型存储、设置字段与无数据库结论。
- [DEPENDENCY_MAP](project-knowledge/DEPENDENCY_MAP.md)：内部依赖方向、第三方依赖、外部系统、外部边界与 ADB 命令接口、依赖治理建议。
- [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md)：按严重程度排序的缺陷、安全风险、技术债、历史热点和修复优先级。

### 决策（architecture/）

- [0001-incremental-vnext](architecture/adr/0001-incremental-vnext.md)：vNext 增量迁移决策。
- [0002-operation-contract](architecture/adr/0002-operation-contract.md)：OperationManager 契约决策。
- [0003-project-structure](architecture/adr/0003-project-structure.md)：项目结构优化四阶段计划（3.2.0 基线）。
- [0004-services-package](architecture/adr/0004-services-package.md)：services/ 顶层包移动与 MobilePerf 内核实例化决策。
- [IMPLEMENTATION_PLAN](architecture/IMPLEMENTATION_PLAN.md)：vNext 实施计划。
- [agent_contract](architecture/agent_contract.md)：统一技能调用契约。

### 操作指南（guides/）

- [BUILD_AND_RUN](guides/BUILD_AND_RUN.md)：经仓库或实际执行验证的安装、启动、测试、PyInstaller 和 CI/CD 方法。
- [TESTING_GUIDE](guides/TESTING_GUIDE.md)：测试分层、目录、Mock 方式、已验证命令、覆盖缺口、提交前门禁，以及中文注释与文档风格规范。

## 维护热点

修改以下区域前，优先按"入口 → 调用链 → 失败路径 → 清理路径 → 测试"的顺序追踪：

- `gui/main_frame.py`：主窗口（约 2,500 行）、设备扫描、工具栏溢出、面板懒加载、信号接线和关闭清理。
- `adblab/application/`：`operations.py`（OperationManager 单元接口）与 `install_batch.py`（安装批次 Gate C 用例）。
- `controllers/`：批次状态与所有权/generation 边界、异步结果分派、截图/录屏共享状态和危险操作入口。
- `models/base/`、`core/adb_bridge.py`：短命令、长进程和持久 shell 边界。
- `gui/widgets/responsive_controller.py`、`gui/widgets/responsive_layout.py`、`gui/screen_adapter.py`：响应式重排协调器、语义布局和屏幕适配协议。
- `gui/dialogs/app_manager.py`、`models/app_manager_worker.py`：批量应用操作、备份恢复和失败传播。
- `gui/panels/remote_panel.py`、`services/remote/`：scrcpy 预检、输入映射、会话所有权/watchdog 和关闭清理。
- `services/mobileperf_runner.py`、`mobileperf/android/`：隔离子进程、采样线程、报告落盘和遗留 ADB 实现（`shell=True` 已移除，独立 Popen 生命周期仍待统一）。

## 知识库维护规则

1. 修改架构、对外接口、配置键、数据结构、主要业务链路、构建或测试命令后，同步更新对应主题文档和本页导航。
2. 代码与文档冲突时，以当前可执行代码和测试为准；修正文档，不把推测写成事实。
3. 新增功能时至少更新 [MODULE_MAP](project-knowledge/MODULE_MAP.md) 和相关业务/数据/边界文档；新增风险时同步 [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md)。
4. 新增术语或缩写时同步 [glossary](project-knowledge/glossary.md)，避免同一词在不同文档中漂移。
5. `APP_VERSION` 仅在推送到远端时递增一次（默认补丁 +1），本地提交不修改版本号且不得复用历史版本。
6. 提交前至少运行 `py -3.11 -m pytest -q`（全量约 930 项、约 11 分钟）、`py -3.11 main.py --self-check packaging`、`ruff check .`、`git diff --check`；修改打包/资源/ADB/Remote/MobilePerf 时按 [TESTING_GUIDE](guides/TESTING_GUIDE.md) 扩展验证。
7. 文档类提交前运行 `py -3.11 scripts/check_doc_links.py`，确保链接与 frontmatter 通过。

## 归档

过程记录与历史检查已移入 [archive/](archive/README.md)：Phase 0/1/2 实施账本、Agent 技能评审和
2026-08-18 知识库卫生检查。归档文档不再更新，现状事实一律以 `project-knowledge/` 与
[architecture/](architecture/) 的 ADR/实施计划为准。

## 明确排除

- `.git/`：版本数据库，不属于运行时代码。
- `.idea/`、`.pytest_cache/`、`__pycache__/`、`logs/`：IDE、缓存或运行产物。
- `resources/icons/`：大量图标资源，只验证加载机制与打包关系。
- `scrcpy-win64-v3.3.1/`：第三方可执行文件、DLL 和脚本，只验证调用与打包关系。
- `mobileperf/extlib/xlsxwriter/`：随项目携带的第三方实现，只验证报告模块对它的依赖。
- `mobileperf/android/tools/` 内各平台 ADB 二进制，以及仓库中的 JAR、图片、GIF、日志和其他媒体/生成文件：只验证调用位置与用途，不作为核心源码分析对象。
- `pyright_output.json`：静态分析输出产物，不作为实现事实来源。
