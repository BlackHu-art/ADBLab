# ADBLab 项目知识库

本知识库是 ADBLab 当前实现的长期维护入口，按四区组织：现状事实、决策、操作指南和过程归档。
结论以仓库代码、配置、测试和构建脚本为依据；不能由仓库确认的内容统一标记为"待确认"。修改代码时，
先从本页定位必读文档，再追踪入口、调用链、失败路径、线程/进程清理和现有测试。

## 四区说明

| 分区 | 目录 | 内容 | 更新规则 |
| --- | --- | --- | --- |
| 现状事实 | `docs/project-knowledge/` | 当前实现的架构、模块、流程、数据、依赖、术语和风险账本 | 代码/配置变化时同步更新 |
| 决策 | `docs/architecture/` | ADR 决策留痕 | 新增决策时追加，不回改历史 ADR |
| 操作指南 | `docs/guides/` | 已验证的构建、运行、测试命令与注释风格规范 | 命令/门禁变化时同步更新 |
| 过程归档 | `docs/archive/` | 阶段账本和历史卫生检查 | 只归档不更新 |

单源规则：每个事实只在一篇文档展开，其余文档用链接指回，不复述；风险条目只进
[project-knowledge/RISKS_AND_DEBT.md](project-knowledge/RISKS_AND_DEBT.md)。完整约定见
[CONTRIBUTING_DOCS](CONTRIBUTING_DOCS.md)。

## 快速阅读路径

| 场景 | 先读 | 再读 |
| --- | --- | --- |
| 快速理解项目 | [PROJECT_OVERVIEW](project-knowledge/PROJECT_OVERVIEW.md)、[glossary](project-knowledge/glossary.md) | [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md) |
| 修改启动、分层、线程或关闭逻辑 | [ARCHITECTURE](project-knowledge/ARCHITECTURE.md)、[MODULE_MAP](project-knowledge/MODULE_MAP.md) | [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md)、[TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 修改具体功能模块 | [MODULE_MAP](project-knowledge/MODULE_MAP.md) | 对应 [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md) 章节、[TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 修改 ADB/外部命令/平台服务边界 | [DEPENDENCY_MAP](project-knowledge/DEPENDENCY_MAP.md) | [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md) |
| 修改配置、持久化或用户数据 | [DATA_FLOW](project-knowledge/DATA_FLOW.md) | [BUILD_AND_RUN](guides/BUILD_AND_RUN.md) |
| 修改 Remote 或 MobilePerf | [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md)、[MODULE_MAP](project-knowledge/MODULE_MAP.md) | [DEPENDENCY_MAP](project-knowledge/DEPENDENCY_MAP.md)、[TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 修改日志、注释或文档字符串 | [ARCHITECTURE](project-knowledge/ARCHITECTURE.md)、[TESTING_GUIDE](guides/TESTING_GUIDE.md)（注释规范章节） | [TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 构建、打包、发布或 CI | [BUILD_AND_RUN](guides/BUILD_AND_RUN.md)、[TESTING_GUIDE](guides/TESTING_GUIDE.md) | [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md) |

## 文档地图

### 现状事实（project-knowledge/）

- [PROJECT_OVERVIEW](project-knowledge/PROJECT_OVERVIEW.md)：项目目标、用户、能力、技术栈、运行环境和当前实现边界。
- [glossary](project-knowledge/glossary.md)：项目专有名词及对应代码概念。
- [ARCHITECTURE](project-knowledge/ARCHITECTURE.md)：总体分层、运行时组件、初始化/关闭、线程/进程模型和架构边界。
- [MODULE_MAP](project-knowledge/MODULE_MAP.md)：模块位置、职责边界、主要入口和代表性测试。
- [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md)：启动、设备、应用、安装批次、Monkey、诊断、文件、Remote、MobilePerf 和关闭链路。
- [DATA_FLOW](project-knowledge/DATA_FLOW.md)：核心数据对象、来源、转换、存储、生命周期、状态变化，以及文件型存储、设置字段与无数据库结论。
- [DEPENDENCY_MAP](project-knowledge/DEPENDENCY_MAP.md)：内部依赖方向、第三方依赖、外部系统、外部边界与 ADB 命令接口、依赖治理建议。
- [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md)：仅保留尚未闭环的缺陷、安全风险和技术债。

### 决策（architecture/）

- [0001-incremental-vnext](architecture/adr/0001-incremental-vnext.md)：vNext 增量迁移决策。
- [0002-operation-contract](architecture/adr/0002-operation-contract.md)：OperationManager 契约决策。
- [0003-project-structure](architecture/adr/0003-project-structure.md)：项目结构优化的分阶段决策。
- [0004-services-package](architecture/adr/0004-services-package.md)：services/ 顶层包移动与 MobilePerf 内核实例化决策。
- [0005-exec-interface](architecture/adr/0005-exec-interface.md)：命令/进程执行接口迁移到 `core/exec.py` 的决策。
- [0006-appsettings-schema](architecture/adr/0006-appsettings-schema.md)：AppSettings schema 迁移与数据清理决策。

### 操作指南（guides/）

- [BUILD_AND_RUN](guides/BUILD_AND_RUN.md)：经仓库或实际执行验证的安装、启动、测试、PyInstaller 和 CI/CD 方法。
- [TESTING_GUIDE](guides/TESTING_GUIDE.md)：测试分层、目录、Mock 方式、验证命令、风险账本入口、提交前门禁，以及中文注释与文档风格规范。

## 维护与归档

- 修改代码时按“入口 → 调用链 → 失败/取消 → 清理 → 测试”追踪；模块入口见
  [MODULE_MAP](project-knowledge/MODULE_MAP.md)，未解决事项只记录在
  [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md)。
- 不在长期知识库保存分支、HEAD、提交数、测试数或临时工作树状态；版本以
  `utils/app_metadata.py` 为准，验证结果写入对应任务或发布记录。
- 写作、frontmatter、单源和陈旧检查规则见 [CONTRIBUTING_DOCS](CONTRIBUTING_DOCS.md)；文档修改后运行
  `.\.venv\Scripts\python.exe scripts/check_doc_links.py`。
- 阶段账本和历史检查见 [archive/](archive/README.md)。归档只用于追溯；当前事实以代码、测试和
  `project-knowledge/` 为准，ADR 只解释决策缘由。
