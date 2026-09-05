# 知识库文档约定

本文件固化 ADBLab 知识库的组织与写作规则，适用于 `docs/` 下全部 Markdown 文档。入口与分区导航见
[README.md](README.md)。

## 四区

| 分区 | 目录 | 主要写入者 | 更新规则 |
| --- | --- | --- | --- |
| 现状事实 | `project-knowledge/` | 修改代码/配置的人 | 与代码同步更新；必须带 frontmatter |
| 决策 | `architecture/` | 架构决策者 | 只追加 ADR，不在 ADR 中维护实施进度 |
| 操作指南 | `guides/` | 修改命令/门禁的人 | 只记录已验证命令；未验证标"待确认" |
| 过程归档 | `archive/` | 阶段收口时 | 只搬移不更新；入口见 [archive/README.md](archive/README.md) |

## 单源规则

1. 每个事实只在一篇文档展开；其他文档用相对 Markdown 链接指回，不复述细节。
2. 风险条目只进 `project-knowledge/RISKS_AND_DEBT.md`，其他文档引用其条目而不是复制。
3. 术语定义只进 `project-knowledge/glossary.md`。
4. 同一事实需要在多处出现时，用短句引用 + 链接，禁止成段复制。
5. 当前协作约束以 [AGENTS.md](../AGENTS.md) 为入口，测试范围只在
   [TESTING_GUIDE](guides/TESTING_GUIDE.md) 展开。ADR 的历史实施命令和 archive 的快照不是当前门禁。

## Frontmatter

`project-knowledge/` 文档必须带 YAML frontmatter：

```yaml
---
status: current
last_verified: YYYY-MM-DD
related: [glossary.md, ARCHITECTURE.md]
---
```

- `status`：`current`（与代码一致）或 `under-review`（正在校准，暂时不要当作事实来源）。
- `last_verified`：最近一次对照代码核实的日期（YYYY-MM-DD）。
- `related`：同分区或跨分区的相关文档相对路径列表，支持流式 `[a, b]` 或块式 `- a` 写法。
- `RISKS_AND_DEBT.md` 额外要求 `owner` 字段；未指定具名维护人时填"待确认"。

`guides/` 不强制 frontmatter；ADR 和 `archive/` 是不可回写的历史记录，不维护滚动
`last_verified`。

## 链接规范

- 一律使用标准相对 Markdown 链接，不使用 `[[wikilink]]`，不依赖 Obsidian 插件语法。
- 移动文件必须同步更新所有指向它的链接，并用 `scripts/check_doc_links.py` 验证。

## 陈旧检查

- 每次文档提交前运行 `.\.venv\Scripts\python.exe scripts/check_doc_links.py`，校验链接与 frontmatter。
- 每季度执行一次卫生检查：把超过 365 天未 `last_verified` 的现状文档列为陈旧页，人工校准或
  归档；检查报告写入 `archive/hygiene/`，不写在入口页正文。

检查器覆盖根 README/AGENTS、docs、第三方说明和 MobilePerf 移植说明，校验相对文件目标、
`status` 合法值、真实日历日期及风险账本非空 `owner`。它不核实正文中的代码行为、符号引用或
标题锚点，因此“链接检查通过”不能表述成“文档与实现全部一致”。

## 匹配度检查与清理

1. 从现状文档给出的入口定位当前定义和消费者，再对照配置、失败/取消/清理路径及代表性测试。
2. 已被替代的说明改成当前事实；重复约束移除正文并指回单一来源；过期风险在确认闭环后从活动
   账本移除。不能只更新 `last_verified` 或仅凭文件存在就认定已核实。
3. 无剩余用途且没有审计价值的整份文档，在已获得清理授权且同步修复引用后才删除。ADR、许可和
   有价值的历史验收记录不因日期旧或实现已变化而删除。
4. 死代码候选须检查直接引用、信号槽、重写方法、字符串/反射注册、包导出、打包和兼容迁移。
   只有测试仍调用旧入口时，先将有效行为回归迁到真实入口，再清理失效实现和实现细节断言。

## 归档条件

只有具备审计价值的完成材料才移入 `archive/`，且不再修改正文：

- 阶段实施账本在阶段收口、结论已并入当前知识文档后；
- 阶段性评审/调研产生了实际决策或能解释历史实现时；
- 历史卫生检查报告。
