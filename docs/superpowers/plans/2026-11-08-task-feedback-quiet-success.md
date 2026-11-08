# 安静成功与任务内容整理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 成功不打断、失败有入口，清除任务表与侧栏的重复控件。
**Architecture:** 任务页原快照提供只读准入，协调器统一守门；原阅读器原位收敛呈现。业务 owner、任务身份与资源生命周期保持。
**Tech Stack:** Python3.11/PySide6 6.9.1/QWidget/现有Fluent。
**Spec:** ../specs/2026-11-08-task-feedback-quiet-success-design.md

## 全局约束

保留脏树、禁止Git写入/依赖/版本/CI/存储改动；root统一文档和项目记忆。普通QWidget可offscreen，macOS MainFrame必须Cocoa且root独占实际应用/CUA/ADB/录窗。每项先freshbase/manifest、明确RED→GREEN及直接/关联检查，再immutablepatch/report，独立评审。实现者不再派子agent；仅一位实现者写共享代码。

## 评审重点

- running已含失败子项但尚未终态，不得借失败提前打开。
- notes历史失败不得使新成功重开；手动仍可看全部事件。
- 单条结果的真实状态或设备名不同于请求，不能随无意义选择器一起丢失。
- 去掉图标列后键盘/AX、焦点归还及停止原版本不受影响。
- 正文去重复不能隐藏额外错误、破坏预算/附件或把共享阅读器换成新的。

### Task 1: 统一仅失败自动展示

**Files:** gui/pages/tasks_page.py, gui/task_feedback.py, gui/action_feedback.py；直接 tests/test_task_feedback.py, tests/test_action_feedback.py，必要失败夹具在 tests/test_task_feedback_review.py。
**Interfaces:** consumes _Entry.payload 的机器状态；produces TaskCenterPage.allows_automatic_details(key: str)->bool，manual选择契约不变。

- [x] 读取spec与 task6-feedback-policy-audit.md，freshbase。
- [x] 写慢截图、自动资格/notes/partial/重复提交回归并确认现代码失败。
- [x] 加唯一只读资格守门、删除running自动展示和pending自动打开；不加DTO或持久化。
- [x] 运行直接与上述关联检查，保留旧有效正文/身份/计数断言；不跑全量。
- [x] 静态及注释检查，冻结patch/manifest并报告exactcommands/output；root独立复审。

### Task 2: 五列表格与紧凑单结果侧栏

**Files:** gui/widgets/task_table.py, gui/widgets/action_result_view.py, gui/widgets/task_detail_drawer.py，必要 gui/pages/tasks_page.py/gui/task_feedback.py 的只读摘要和焦点入口；hosted文档表面若必须扩展，仅可在 gui/styles/reading_surface.py 增加局部只读开关，默认表现保持；只改直接受影响的table/inspector/reader/reading_surface tests。
**Interfaces:** consumes Task1最终源码；保留原TaskTable选择/单阅读器/TaskActionGesture key/revision和独立模式。

- [x] Task1冻结后移交，freshbase保留它的准入改动。
- [x] 写五列/无可见箭头、真实标题键盘/停止隔离、0/1job无chooser、多job不丢数据的回归。
- [x] 移除空列，迁移可见入口和焦点锚点；旧内部兼容状态不得成为可见假入口。
- [x] 整理必要元数据与正文，安全去重复，主题/字号/窄窗原位更新。
- [x] 直接及必要关联测试、实渲染深浅/字号图、静态检查；冻结patch/report并独立评审。

### Task 3: 整合与实际场景

- [x] 对实际停止后出现异常标记的代码分支补有界回归：主动停止且资源已收口的非零退出只进入诊断；非主动异常退出、停止失败和清理屏障保持。
- [x] 评审镜像工具窗修复、Task1/2与原身份/关闭契约。
- [x] root只运行当前受影响的Cocoa组合与尚未完成的Qt兼容尾部，不默认全量。
- [x] 实际截图/刷新成功、失败、手动查看、外侧点击、Tab/Esc、镜像稳定图标和资源清理；录窗逐帧核对。
- [x] 同步权威行为文档，按仓库 project-memory 追加当前事实与未验边界；不改Codex生成记忆。
