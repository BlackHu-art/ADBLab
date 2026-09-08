# ADBLab 项目知识库

本知识库描述当前实现。代码、配置与可执行测试是事实来源；实机、许可或部署条件无法从仓库
确认时标记为“待确认”。历史 ADR 和验收记录只供追溯，不作为当前实现或门禁要求。

## 按任务查阅

| 需要了解或修改 | 文档与维护边界 |
| --- | --- |
| 项目用途与能力 | [PROJECT_OVERVIEW](project-knowledge/PROJECT_OVERVIEW.md) |
| 功能在哪、从哪里测试 | [MODULE_MAP](project-knowledge/MODULE_MAP.md) |
| 分层、对象归属、并发与关闭 | [ARCHITECTURE](project-knowledge/ARCHITECTURE.md) |
| 导航、设备目标、业务成功/失败/取消路径 | [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md) |
| 数据对象、配置字段、存储与保留 | [DATA_FLOW](project-knowledge/DATA_FLOW.md) |
| 依赖、外部工具及命令边界 | [DEPENDENCY_MAP](project-knowledge/DEPENDENCY_MAP.md) |
| 未闭环问题与验证缺口 | [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md) |
| 项目专有术语 | [glossary](project-knowledge/glossary.md) |
| 环境、运行、翻译资源、打包与版本 | [BUILD_AND_RUN](guides/BUILD_AND_RUN.md) |
| ADB 执行环境自动适配与独立快速命令 | [ADB_FAST](guides/ADB_FAST.md) |
| 操作结果归属、全文与附件交互、应用诊断 | [OPERATION_RESULTS](guides/OPERATION_RESULTS.md) |
| 测试选择、隔离、质量工具与注释规范 | [TESTING_GUIDE](guides/TESTING_GUIDE.md) |
| 协作、授权与修改范围 | [AGENTS.md](../AGENTS.md) |
| 文档组织、事实核实与清理 | [CONTRIBUTING_DOCS](CONTRIBUTING_DOCS.md) |

快速入门先读概览和模块地图；修改具体行为时再读对应流程、架构或数据章节，沿代码调用链
核对失败、取消和清理路径。仅阅读知识库或修改文档不触发全量测试，验证按测试指南选择。

## 分区

| 分区 | 内容与更新方式 |
| --- | --- |
| `project-knowledge/` | 当前事实；与代码同步，带核实日期 |
| `guides/` | 运行和维护方法；命令及规则变化时更新 |
| `architecture/adr/` | 决策缘由；保留历史，不维护当前进度 |
| `archive/` | 有追溯价值的阶段材料；不回改正文 |

每项事实只在一处展开，其他页面链接引用；界面局部排版和已修复问题不逐条堆入架构页。
未闭环事项集中在风险账本，临时分支、测试数量和验收结果不进入现状文档。

## 决策索引

- [0001 增量迁移](architecture/adr/0001-incremental-vnext.md)
- [0002 Operation 契约](architecture/adr/0002-operation-contract.md)
- [0003 项目结构](architecture/adr/0003-project-structure.md)
- [0004 Services 与 MobilePerf 隔离](architecture/adr/0004-services-package.md)
- [0005 命令/进程执行接口](architecture/adr/0005-exec-interface.md)
- [0006 设置 schema](architecture/adr/0006-appsettings-schema.md)

历史阶段与验收索引见 [archive/README](archive/README.md)。

文档修改后运行 `.\.venv\Scripts\python.exe scripts/check_doc_links.py` 和 `git diff --check`；
链接/frontmatter 校验不能替代正文与代码的核对。
