# 归档区

本目录只保存历史过程和当时的验证结论，不作为当前实现依据。发生冲突时，以当前代码、测试和
[project-knowledge](../project-knowledge/PROJECT_OVERVIEW.md) 为准；ADR 只解释决策缘由。

## 规则

1. 归档正文不回改；必要的纠正在当前知识文档中说明。
2. 临时任务计划不进入现状文档。完成后只有具备审计价值的材料才归档。
3. 阶段编号、测试数量、路径和结论都只代表记录当时，不能直接套用到当前工作树。

## 索引

| 类型 | 文档 | 说明 |
| --- | --- | --- |
| 实施账本 | [Phase 0](ledgers/PHASE0_LEDGER.md)、[Phase 1](ledgers/PHASE1_LEDGER.md) | 早期安全与 Operation 契约实施记录 |
| 实施账本 | [Screenshot Gate](ledgers/PHASE2_GATE_A_LEDGER.md)、[LiveLogcat Gate](ledgers/PHASE2_GATE_B_LEDGER.md) | 当时的组件与生命周期验证；页面形态后来已变化 |
| 卫生检查 | [2026-08-18](hygiene/2026-08-18.md) | 当时的文档结构快照 |
| 卫生检查 | [2026-09-22 项目与文档核对](hygiene/2026-09-22-project-doc-audit.md) | 文件保留与清理依据、文档校准范围、历史材料归档及当时验证边界 |
| 实施验收 | [2026-09-05 质量与 UI 改进](ledgers/QUALITY_UI_2026_09_05.md) | 本地工作树的业务、生命周期、导航布局、完整测试与 Windows 打包验收 |
| 实施验收 | [2026-09-05 第二轮界面整合](ledgers/QUALITY_UI_CONSOLIDATION_2026_09_05.md) | 全局多选设备栏、功能归并、列表与采集布局、QObject 归属及最终软件验收 |
| 执行测量 | [2026-09-07 ADB 快速路径](ledgers/ADB_FAST_2026_09_07.md) | 从使用指南移入的当时测量原文；耗时与验收范围只代表记录时的环境 |
| 实施验收 | [2026-09-08 ADB 执行链](ledgers/2026-09-08-adb-execution-gaps.md) | 已完成的查询取消、能力验证、截图 I/O 与 MobilePerf 采样记录；不作为待执行计划或当前测试快照 |
| 平台实施 | [2026-09-22 多系统兼容性](ledgers/2026-09-22-cross-platform-compatibility.md) | 保留已实施改动及当时 Linux 验证；Windows/macOS、实机设备等未验收项继续由当前风险账本跟踪 |
| UI 检查 | [2026-09-24 体验检查与修复](ledgers/2026-09-24-ui-experience-audit.md) | 界面源码扫描、字号与窄窗修复、输入状态及菜单生命周期验证 |
| 实施验收 | [2026-09-25 无线 ADB 配对](ledgers/2026-09-25-wireless-pairing.md) | 三页连接交互、配对身份与取消、翻译布局、冻结产物验收及实机验证边界 |
| UI 验收 | [2026-09-25 页内设备连接](ledgers/2026-09-25-inline-device-connection.md) | 紧凑等高页签、工具栏断开、收起与离页取消、三语言和 DPI 增量验证 |
| 工具迁移 | [2026-09-22 Windows 工具包](ledgers/2026-09-22-windows-tool-bundle-migration.md) | 保留工具目录迁移、清理范围与验证证据；原生 Windows 产物及设备验证仍以风险账本为准 |
