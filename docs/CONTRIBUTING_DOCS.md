# 知识库文档约定

本文件固化 ADBLab 知识库的组织与写作规则，适用于 `docs/` 下全部 Markdown 文档。入口与分区导航见
[README.md](README.md)。

## 四区

| 分区 | 目录 | 主要写入者 | 更新规则 |
| --- | --- | --- | --- |
| 现状事实 | `project-knowledge/` | 修改代码/配置的人 | 与代码同步更新；必须带 frontmatter |
| 决策 | `architecture/` | 架构决策者 | 追加 ADR，不回改历史决策 |
| 操作指南 | `guides/` | 修改命令/门禁的人 | 只记录已验证命令；未验证标"待确认" |
| 过程归档 | `archive/` | 阶段收口时 | 只搬移不更新；入口见 [archive/README.md](archive/README.md) |

## 单源规则

1. 每个事实只在一篇文档展开；其他文档用相对 Markdown 链接指回，不复述细节。
2. 风险条目只进 `project-knowledge/RISKS_AND_DEBT.md`，其他文档引用其条目而不是复制。
3. 术语定义只进 `project-knowledge/glossary.md`。
4. 同一事实需要在多处出现时，用短句引用 + 链接，禁止成段复制。

## Frontmatter

`project-knowledge/` 文档必须带 YAML frontmatter：

```yaml
---
status: current
last_verified: 2026-08-19
related: [glossary.md, ARCHITECTURE.md]
---
```

- `status`：`current`（与代码一致）或 `under-review`（正在校准，暂时不要当作事实来源）。
- `last_verified`：最近一次对照代码核实的日期（YYYY-MM-DD）。
- `related`：同分区或跨分区的相关文档相对路径列表，支持流式 `[a, b]` 或块式 `- a` 写法。
- `RISKS_AND_DEBT.md` 额外要求 `owner` 字段；未指定具名维护人时填"待确认"。

`guides/`、`architecture/`、`archive/` 的文档不强制 frontmatter，但推荐至少标注 `last_verified`。

## 链接规范

- 一律使用标准相对 Markdown 链接，不使用 `[[wikilink]]`，不依赖 Obsidian 插件语法。
- 移动文件必须同步更新所有指向它的链接，并用 `scripts/check_doc_links.py` 验证。

## 陈旧检查

- 每次文档提交前运行 `py -3.11 scripts/check_doc_links.py`，校验链接与 frontmatter。
- 每季度执行一次卫生检查：把超过 365 天未 `last_verified` 的现状文档列为陈旧页，人工校准或
  归档；检查报告写入 `archive/hygiene/`，不写在入口页正文。

## 归档条件

满足以下任一条件的文档移入 `archive/` 对应子目录，且不再修改正文：

- 阶段实施账本在阶段收口、结论已并入当前知识文档后；
- 阶段性评审/调研报告失去指导意义后；
- 历史卫生检查报告。
