# 任务抽屉精细化 Implementation Plan

> **For agentic workers:** 使用superpowers:subagent-driven-development，按当前脏工作区快照保留用户资产。

**Goal:** 完成紧凑精细抽屉和不误触业务的外侧收起。

**Architecture:** Drawer只呈现固定reader；Coordinator拥有本主窗口的有限outside-dismiss监听，
reader的可选hosted呈现模式只约束可见结构，不改数据、资源和动作资格。

**Tech Stack:** 项目.venv Python/PySide6/Fluent、pytest、Ruff、Pyright。

**Spec:** [设计与明确边界](../specs/2026-11-08-task-drawer-refinement-design.md)。

## Global Constraints

- 现有所有dirty资产保留，基线位于本轮.sdd/base；不提交、推送、新worktree、依赖、版本或CI。
- 外壳390逻辑像素与280ms位置动画不变；FontRole/UI_SMALL/TITLE、SELECTION_BG/TEXT等现有tokens。
- 不更改session owner或停止算法；单例reader不重建，原TaskActionGesture/ReaderInteraction撤销链保留。
- Mac MainFrame/FluentWindow仅Cocoa；所有Spy先count，mapTo仅真实祖先，不制造native crash。

## Review Focus

1. 接管手势尾部不能在panel关闭/显式重开后触发背景或新任务。
2. popup/模态对话框的逻辑归属与窗口chrome不得被按矩形误判。
3. 简化只针对严格单条成功，不能把partial/失败或多step伪装成全部成功。
4. 长同名recent/大字/窄窗仍可区分、Tab可达，停止/来源按钮不被裁剪。
5. app filter及短期timer完整清理，背景更新及关闭末帧继续被保护。

## Task 1：一个可独立验收的抽屉细化

**Files:** gui/widgets/task_detail_drawer.py、gui/task_feedback.py、gui/pages/tasks_page.py、
必要的gui/widgets/action_result_view.py；直接tests及UI_IMPLEMENTATION/OPERATION_RESULTS。
可增加单一职责的私有outside-filter协作者；不扩大MainFrame或resources owner。

**Interfaces:** 原public信号、opened/selected_key、open/close/shutdown均保持；
ActionResultView可新增可选hosted compact呈现开关（默认False），TaskCenterPage.reader_for_drawer启用。
Outside listener只调用现有dismiss链，不执行cancel，不创建/重选设备。

- [ ] 先补面板外首击、release/dblclick/快速reopen、popup/modal/drag与清理的失败回归；
  直接测试新observable行为，不依靠直接button.click伪装命中。
- [ ] 基于审计实现有限范围的outside-dismiss与完整手势吞噬；保留内侧和原关闭状态屏障。
- [ ] 实现紧凑header/title/status/recent/footer及hosted-only重复信息收敛；独立reader正例不变。
- [ ] 直接/关联测试、Ruff、受影响生产Pyright/中文注释、docs/diff；报告真实退出码与边界。
- [ ] 冻结相对此轮base的patch/hash，fresh reviewer按spec/质量独立评审并定向修正。
- [ ] root集成Cocoa测试、main.py实际外侧/双击/inside菜单/快速开合与窗口-only录像；正常退出。

## 验证范围

本轮4个生产呈现/协调文件→drawer/input/reader direct＋外侧新回归→coordinator/external details及
字体/附件代表节点；只有出现新调用链疑点才扩大。前一轮已验收的owner/backend与540节点不重当本轮。
无全量触发条件，旧记录不冒充本次验证。
