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
