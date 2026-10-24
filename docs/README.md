# ADBLab 项目知识库

本知识库描述当前实现。代码、配置与可执行测试是事实来源；实机、许可或部署条件无法从仓库
确认时标记为“待确认”。历史 ADR 和验收记录只供追溯，不作为当前实现或门禁要求。

## 按任务查阅

| 需要了解或修改 | 文档与维护边界 |
| --- | --- |
| 项目用途与能力 | [PROJECT_OVERVIEW](project-knowledge/PROJECT_OVERVIEW.md) |
| 功能在哪、从哪里测试 | [MODULE_MAP](project-knowledge/MODULE_MAP.md) |
| 分层、对象归属、并发与关闭 | [ARCHITECTURE](project-knowledge/ARCHITECTURE.md) |
| UI 组合、材质字体、控件、布局与滚动动画 | [UI_IMPLEMENTATION](project-knowledge/UI_IMPLEMENTATION.md) |
| 导航、设备目标、业务成功/失败/取消路径 | [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md) |
| 数据对象、配置字段、存储与保留 | [DATA_FLOW](project-knowledge/DATA_FLOW.md) |
| 依赖、外部工具及命令边界 | [DEPENDENCY_MAP](project-knowledge/DEPENDENCY_MAP.md) |
| 未闭环问题与验证缺口 | [RISKS_AND_DEBT](project-knowledge/RISKS_AND_DEBT.md) |
| UI 尚未统一的实现与候选优化 | [UI 优化账本](project-knowledge/RISKS_AND_DEBT.md#ui-一致性与体验优化) |
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
- [0007 按职责统一目录](architecture/adr/0007-responsibility-directory-consolidation.md)

历史阶段与验收索引见 [archive/README](archive/README.md)。

## 重构设计与验收索引

- Windows 安装版与免安装版并行交付：[设计](superpowers/specs/2026-10-24-windows-installer-design.md)、
  [实施与验收记录](superpowers/plans/2026-10-24-windows-installer.md)。已实现并推送 PyInstaller
  onedir + Inno Setup 双产物构建和维护协议；[构建与恢复指南](guides/BUILD_AND_RUN.md#windows-安装版与免安装版)
  记录接口和兼容边界。四平台 CI 构建、Windows 独立升级 fixture 与正式产品自动安装验收已通过，
  产物可从实施记录链接的 Actions 运行下载，尚未正式发布；标准用户、旧真实应用跨版本及
  人工设备验收等未执行项见实施记录。
  [应用内安装包升级](superpowers/plans/2026-10-24-windows-installer-update.md)目前仅规划，未实现。
- adblab 按职责合并到现有目录：[逐模块设计](superpowers/specs/2026-10-24-adblab-responsibility-merge-design.md)、
  [实施与验证记录](superpowers/plans/2026-10-24-adblab-responsibility-merge.md)。业务、基础设施和 Qt 实现分别归入
  services/core/gui，不新增顶层目录；旧内部命名空间在验证后退役，原 models/GUI 兼容入口与数据保持。
- [重构后目录、架构与兼容性复审](superpowers/plans/2026-10-24-post-refactor-audit.md)：记录现有入口与调用链复核、APK 关闭取消反馈及测试清理协议修复。
- [字体、布局与 Qt 退出验证记录](superpowers/plans/2026-10-24-ui-stability.md)：记录重构后遗留失败的根因、兼容修复和独立审阅。
- [全项目持续重构路线图](superpowers/plans/2026-10-23-project-refactor-roadmap.md)记录前期整体范围、保留依据与阶段验收；后续顶层目录统一由上述职责合并计划单独记录。
  Controller 模型创建与装配已完成并行实施与独立审阅：[设计](superpowers/specs/2026-10-23-controller-model-composition-design.md)、
  [计划与验收](superpowers/plans/2026-10-23-controller-model-composition.md)；相关项目目录与功能模块归位亦已完成。
- 服务与 Logcat 功能目录归位：[设计](superpowers/specs/2026-10-24-feature-directory-boundaries-design.md)、
  [实施计划与验证](superpowers/plans/2026-10-24-feature-directory-boundaries.md)。应用 helper、性能配置/结果和
  Logcat 页面协作者按职责归包，保留旧公开入口，已完成验证与最终独立审阅。
- FileExplorer、AppManager、Performance 功能包：[设计](superpowers/specs/2026-10-24-gui-feature-packages-design.md)、
  [实施计划](superpowers/plans/2026-10-24-gui-feature-packages.md)。已完成并最终审阅，保留旧入口和worker替换点。
- 设置保存生命周期：[设计](superpowers/specs/2026-10-24-settings-save-lifecycle-design.md)、
  [实施计划](superpowers/plans/2026-10-24-settings-save-lifecycle.md)。已完成并最终审阅，保存线程与同步写入由owner统一关闭。
- 截图功能包：[设计](superpowers/specs/2026-10-24-media-feature-package-design.md)、
  [实施计划](superpowers/plans/2026-10-24-media-feature-package.md)。六份实现已归包并最终审阅，保留旧入口及实际globals。
- 设置规则与历史迁移分包：[设计](superpowers/specs/2026-10-24-settings-schema-boundaries-design.md)、
  [实施计划](superpowers/plans/2026-10-24-settings-schema-boundaries.md)。已完成并最终审阅；保持持久化owner和数据协议。
- Remote窗口平台分包：[设计](superpowers/specs/2026-10-24-remote-windowing-package-design.md)、
  [实施计划](superpowers/plans/2026-10-24-remote-windowing-package.md)。已完成并最终审阅；保留原跟踪策略和工厂入口。
- 首页与工作区页面分包：[设计](superpowers/specs/2026-10-24-home-workspace-pages-design.md)、
  [实施计划](superpowers/plans/2026-10-24-home-workspace-pages.md)。已完成并最终审阅，完整类归位且保留旧导出与设置替换边界。
- 应用查询服务提取：[设计](superpowers/specs/2026-10-24-apps-query-services-design.md)、
  [实施计划](superpowers/plans/2026-10-24-apps-query-services.md)。已完成并最终审阅，保留身份、查询预算和信号发布契约。
- Controller媒体职责归包：[设计](superpowers/specs/2026-10-24-controller-media-boundaries-design.md)、
  [实施计划](superpowers/plans/2026-10-24-controller-media-boundaries.md)。已完成并最终审阅，保留旧组合入口、注册与安装协议链。
- 设备发现Qt适配器：[设计](superpowers/specs/2026-10-24-device-discovery-adapter-design.md)、
  [实施计划](superpowers/plans/2026-10-24-device-discovery-adapter.md)。已完成并最终审阅，窗口保留扫描资源所有权和旧同对象类入口。
- 应用动作与归档服务：[设计](superpowers/specs/2026-10-24-apps-actions-archives-design.md)、
  [实施计划](superpowers/plans/2026-10-24-apps-actions-archives.md)。已完成并最终审阅，保留用户核验、写命令、归档格式及通知时序。
- 文件事务服务：[设计](superpowers/specs/2026-10-24-file-operation-services-design.md)、
  [实施计划](superpowers/plans/2026-10-24-file-operation-services.md)。已完成并最终审阅，保留原始字节、取消、原子发布及清理归属。
- 应用与文件 Qt worker 目录归位：[设计](superpowers/specs/2026-10-24-worker-directory-boundaries-design.md)、
  [实施计划](superpowers/plans/2026-10-24-worker-directory-boundaries.md)。已完成并通过全项目独立终审；保留旧模块身份及页面工厂。
- Controller 的设备连接生命周期依赖收敛：[设计](superpowers/specs/2026-10-23-device-connection-lifecycle-design.md)与
  [实施计划](superpowers/plans/2026-10-23-device-connection-lifecycle.md)已完成代码实施与独立审阅；
  无线配对历史准入与 ADB 重启通过生命周期接口接入，保留现有行为和数据兼容。阶段验证及限制见实施计划。
- Controller 的 APK 文件选择依赖收敛：[设计](superpowers/specs/2026-10-23-controller-apk-picker-design.md)与
  [实施计划](superpowers/plans/2026-10-23-controller-apk-picker.md)已完成代码实施与独立审阅；
  选择接口与 Qt 适配器已接入 Controller 和主窗口。阶段验证、既有字体测试失败及人工边界见实施计划。
- 设备上下文独立化：[设计](superpowers/specs/2026-10-22-device-context-design.md)与
  [实施计划](superpowers/plans/2026-10-22-device-context.md)已完成第一阶段代码迁移、自动回归与
  独立审阅；当前实现见架构与数据流文档，阶段验证记录及人工验收边界见实施计划。

## 保留的历史方案

`superpowers/` 中以下历史设计与计划保留原位置及当时状态，供理解实现缘由，不作为待执行任务或
当前验收要求：

- 无线配对：[设计](superpowers/specs/2026-09-25-wireless-adb-pairing-design.md)、
  [交互方案](superpowers/specs/2026-09-25-wireless-adb-pairing-interaction.md)、
  [实施计划](superpowers/plans/2026-09-25-wireless-adb-pairing.md)。
- 页内连接：[实施计划](superpowers/plans/2026-09-25-inline-device-connection.md)。

当前连接行为以 [BUSINESS_FLOW](project-knowledge/BUSINESS_FLOW.md#2-连接设备与读取信息) 为准，
历史验证边界见归档中的[无线配对](archive/ledgers/2026-09-25-wireless-pairing.md)和
[页内连接](archive/ledgers/2026-09-25-inline-device-connection.md)验收记录。

## 文档验证

文档修改后运行 `.\.venv\Scripts\python.exe scripts/check_doc_links.py` 和 `git diff --check`；
链接/frontmatter 校验不能替代正文与代码的核对。
