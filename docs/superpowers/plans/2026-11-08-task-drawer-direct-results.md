# 任务抽屉完整阅读实施计划

Spec: docs/superpowers/specs/2026-11-08-task-drawer-direct-results-design.md

用户新增反馈继续当前任务。使用superpowers:subagent-driven-development；单生产writer避免共享
reader/footer/主题冲突，独立审计与审阅并行。当前ui-design脏checkout是授权工作区，不创建分支，
不提交/推送/暂存/回退、不删除旧证据，评审用捕获基线与不可变补丁而非新增commit。

## Task 1: 完整阅读、Fluent滚条、页脚和设置热更新

Read spec first; it is the authority. Read both theme-followup-audit.md and full-result-followup-audit.md
copied into this plan workspace before implementation. Read repo AGENTS/docsREADME/UI_IMPLEMENTATION/
OPERATION_RESULTS/TESTING_GUIDE and closest instructions; use .venv only.

生产范围以gui/widgets/task_detail_drawer.py、action_result_view.py、run_results.py和
gui/pages/tasks_page.py为主。只有确有证据的最小共享控件改动才可扩展，先报root；不改
TaskFeedback外侧过滤器、TaskActionGesture/ReaderInteraction/资源owner等上一阶段已审阅链路。
新增tests/test_task_drawer_reading.py；若旧测试依赖已被新需求移除的hosted toggle，按可观察
完整显示/原输入撤销保证迁移断言，保留默认兼容使用者测试，不删除/跳过/放宽有效断言。

1. 基线普通QWidget节点，确认旧Fluent滚条缺失、正文折叠、强调色刷新失效。补安全失败回归，
   不构造MainFrame/FluentWindow，不以QSignalSpy.at(0)空数组或跨兄弟mapTo触发原生崩溃。
2. 实现spec的明确hosted完整模式，保持default False、同reader对象和原有字段/业务信号。
   展开ContentReveal时不得先启动旧动画再以同目标非动画调用误以为已停止；用现有API在
   有效边界完成状态，不引入新的UI动画或反复重挂控件。保留64K预览/完整查询导出保护。
3. 复用SmoothScrollArea，紧凑footer，修正已证实强调色订阅/Fluent QSS覆盖问题。查明字体
   设置实际链路后只修真正缺口；保留UI/LOG独立角色、热切换后的选区/滚动/搜索/附件身份。
4. 新直接回归→相关hosted reader/字体/结果表示/抽屉几何节点。子任务只跑普通QWidget
   offscreen明确节点，不运行整份含MainFrame的test_action_result_presentation或native节点。
   root统一Cocoa/实际应用。执行改动文件Ruff、相关production Pyright、中文注释、docs links、
   git diff --check；更新UI_IMPLEMENTATION/OPERATION_RESULTS的现状事实，不改历史计数。
5. 自审，保存相对此阶段base的patch/hash manifest、实现报告（失败证明、命令、实际输出），
   冻结生产/测试/docs。禁止commit/push；不得覆盖前阶段patch/报告。

## Task 2: 独立复核与本机验收

由fresh reviewer对Task1阶段基线→不可变patch做spec+quality独立复核；root按fix-loop最多5轮，
前三轮原implementer。root只统一Cocoa，测试范围按改动消费者有界选择，不重复旧327或540。
实际main.py检查单/多任务、完整结果与附件、Fluent滚条、字号和颜色设置、原生导出取消、
外侧首击与第二击、正常及快速反向关闭；仅录ADBLab窗口、本机保存，逐帧查看无闪烁。
退出正常并恢复临时设备选择与设置，记录未运行Windows/真实双屏/打包等边界。
