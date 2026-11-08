# 任务抽屉与任务中心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现用户批准的共享右侧任务抽屉、统一任务列表与可靠导航状态转换。

**Architecture:** TaskCenterPage 负责唯一数据合并与阅读器；抽屉、图标仅消费不可变投影。MainFrame
负责组合、隐藏页刷新、来源导航和关闭；原资源所有者继续负责取消、停止与文件动作。

**Tech Stack:** Python 3.11、PySide6、已安装 PySide6-Fluent-Widgets、pytest、Ruff、Pyright。

**Spec:** [已确认设计](../specs/2026-11-08-task-drawer-design.md)。

## Global Constraints

- 不改变业务命令、持久化格式、设备目标、依赖、版本或发布流程；不提交或推送。
- macOS MainFrame / FluentWindow 使用 Cocoa，不能使用 offscreen 模拟原生句柄。
- 默认宽度 390 个逻辑像素；约 280 ms 的位置动画；成功图标 3000 ms。
- 未提交变更分别归属任务，不覆盖其他 agent；每个实现 agent 不再创建 subagent。
- 使用现有阅读器、缓存和资源取消路径；不增加通用命令重放，不伪造成功或停止。

## Review Focus

1. 取消受理至真实终态的空隙不得使活动数提前归零或出现绿勾。
2. 历史加载、重复终态、notes 和条目淘汰不得冒充新的成功事件。
3. 隐藏任务页仍能投影独立 Operation；筛选与已读不改变执行语义。
4. 抽屉反转、resize、窗口隐藏与关闭不产生透明帧、焦点残留或未停止 Timer。
5. 阅读器不能被列表删除、重挂或后台刷新重建；全文与归档附件仍可达。

## Task 1: 导航状态控件

**Files:** Create `gui/widgets/task_navigation.py`, `tests/test_task_navigation.py`。

**Interfaces:**

```python
@dataclass(frozen=True)
class TaskNavigationSnapshot:
    active_count: int = 0
    unread_count: int = 0
    success_event_id: str | None = None

class TaskNavigationButton(NavigationPushButton):
    def set_snapshot(self, snapshot: TaskNavigationSnapshot) -> None: ...
    def shutdown(self) -> None: ...
```

- [x] 先写优先级、重复 ID、初始终态、3000 ms 超时、新状态中断、隐藏/关闭回归并确认失败。
- [x] 实现主导航兼容绘制，保留父类背景、选中、文字和紧凑形态；Timer 仅属于控件。
- [x] 运行直接 QWidget 测试与 Lint，记录实际结果；不启动 MainFrame。
- [x] 独立评审任务实现与状态语义，不修改其他组件文件。

## Task 2: 右侧抽屉外壳

**Files:** Create `gui/widgets/task_detail_drawer.py`, `tests/test_task_detail_drawer.py`。

**Interfaces:**

```python
class TaskDetailDrawer(QWidget):
    task_requested = Signal(str)
    cancel_requested = Signal(str)
    source_requested = Signal(str)
    locate_requested = Signal(str)
    opened_changed = Signal(bool)
    closed = Signal()  # 动画完成并完全隐藏后发出，不能提前清空正在绘制的阅读器。
    def set_content(self, content: QWidget) -> None: ...
    def present(self, row: TaskRowData, *, source_label: str = "",
                archived: bool = False, source_available: bool = False,
                recent: tuple[TaskRowData, ...] = (),
                from_task_center: bool = False) -> None: ...
    def open_drawer(self, origin: QWidget | None = None, *, animated: bool = True) -> None: ...
    def close_drawer(self, *, animated: bool = True) -> None: ...
    def shutdown(self) -> None: ...
```

属性 `opened`、`selected_key`。`set_content()` 一次安装现有阅读器；抽屉不拥有业务数据或命令。

- [x] 先写开合中间帧、快速反向、宿主 resize、焦点及 hide/shutdown 回归并确认失败。
- [x] 复用 FrameAnimation；不透明表面只移动 x，持续保留同一内容 QWidget。
- [x] 运行直接普通 QWidget 测试，核对字号和主题；不启动 MainFrame。
- [x] 独立评审，重点检查清理和关到一半不再接受输入。

## Task 3: 任务页投影与统一列表

**Files:** Modify `gui/pages/tasks_page.py`, `gui/widgets/task_table.py`；新增或调整直接任务测试。

**Interfaces:** 消费 Task 1 的 `TaskNavigationSnapshot`。新增外部详情模式，保留独立组件兼容入口；
主窗口使用外部模式。提供 `detail_requested(str)`、`detail_changed(str)`、`detail_closed()`、
`navigation_snapshot_changed(object)` 信号和 `selected_key`。

```python
def select_entry(self, key: str, *, clear_filters: bool = False, mark_read: bool = True) -> bool: ...
def close_detail(self) -> None: ...
def cancel_entry(self, key: str) -> None: ...
def navigation_snapshot(self) -> TaskNavigationSnapshot: ...
def detail_row(self, key: str) -> TaskRowData | None: ...
def detail_source(self, key: str) -> str: ...
def recent_rows(self) -> tuple[TaskRowData, ...]: ...
```

`detail_source` 返回 ActionSpec.section 等稳定来源键；未知来源返回空串，不猜测设备目标。
现有 `select_request()` 保留并转至上述选择路径。`detail` 为现有固定共享阅读器。
自动反馈使用 `mark_read=False`，后续后台刷新不能把未由用户查看的异常当作已读。

- [x] 先补外部详情、筛选快照、隐藏刷新、终态去重与取消空隙测试并确认失败。
- [x] 增加四个快捷状态筛选，保留精确状态/类型/搜索、全量有界数据与归档参数操作。
- [x] 外部模式不向行内 reveal 安装阅读器；更新保留选中身份、正文和附件选择。
- [x] 全局快照仅由未筛选 `_entries` 生成；首次合并基线不发 success event，后续明确活动转
  succeeded 生成递增事件 ID；已有 ID 保持，重复刷新不能产生新完成事件。
- [x] 在已读变化后更新快照；保持取消 pending 与资源终态屏障。
- [x] 运行任务中心、列表、阅读器、筛选和有界缓存关联测试并独立评审。

## Task 4: 组合、反馈接入与验收

**Files:** Create `gui/task_feedback.py`, `tests/test_task_feedback.py`; Modify `gui/main_frame.py`, `gui/action_feedback.py`, `gui/close_controller.py`；按实际接入更新
`docs/guides/OPERATION_RESULTS.md`、`docs/project-knowledge/{UI_IMPLEMENTATION,BUSINESS_FLOW,ARCHITECTURE}.md`
及直接集成测试、语言词库、测试 marker。

- [x] 先补主窗共享抽屉、跨页图标、通知精确身份与关闭测试并确认失败。
- [x] `TaskFeedbackCoordinator` 在独立模块组织页面、内容面、导航按钮和回调，避免向 MainFrame
  继续加入详情与计时器实现；页面详情只在抽屉完全关闭后解除阅读保护。
- [x] 用 `_content_surface` 拥有唯一抽屉和页面单例阅读器；主导航安装 TaskNavigationButton。
- [x] 绑定选择、元数据、取消、来源与任务中心定位；关闭不取消，后台结果不重开或抢阅读目标。
- [x] UI 线程低频刷新隐藏任务页数据；关闭先停刷新、导航动画和抽屉，再释放资源。
- [x] 通用任务反馈进入抽屉；诊断与非任务提示仍使用已有必要提示，不做无关迁移。
- [x] 只对已有可确认业务能力呈现操作，保留文件/导出/参数复用原接线。
- [x] 直接和关联测试通过后，Ruff、受影响生产模块 Pyright、中文注释、文档与 diff 检查。
- [x] 独立整体评审，修复有效问题并定向复核；原生启动应用进行开合/反转/resize/切页/关闭验证，
  使用本机原生窗口录制核对帧，不上传用户数据。

## 执行约定

用户已明确选择多 agent 实施并授权其余安排，无需再次确认方案或实施方式。复用当前干净的
`ui-design` checkout；本次不创建工作树、安装依赖、commit 或 push。研究可并行，实施按上述
契约顺序交付；主任务组织独立评审并记录证据，不把整个项目全量测试作为每一步默认动作。

## Task 5: 持续会话 owner 与只读适配

**Files:** Create `gui/session_tasks.py`, `tests/test_session_task_projection.py`; Modify
`gui/features/performance/page.py`, `gui/features/logcat/page.py`, `gui/panels/remote_panel.py`，必要时仅在
对应 controller 的现有生命周期回调记录显示身份。不得改变原资源释放/停止算法。

- [x] 不可变 SessionTaskSnapshot：key、revision、kind、state、resource_owned、stop_enabled、
  target_labels、detail、run_id；公开 owner.task_snapshot()/request_task_stop(expected_revision)。
- [x] SessionTaskRegistry 从回调枚举当前 owners，使用弱引用；collect 只读取 UI 内存快照，必要时经现有受监督队列调度
  至多一个异步资源检查，不在 GUI 做 I/O 或等待；request_stop 重新枚举并验证 owner/revision，
  shutdown 拒绝晚请求；不增加永久 Timer/线程池，无 Controller 依赖。
- [x] 优先回归：停止中/超时/清理残留、原目标与旧 revision、镜像 preparing 取消后 launch worker
  未退出、性能旧代残留/结果收尾、Logcat join 屏障、销毁/关闭；只运行直接及关联节点。
- [x] 任务页消费与 MainFrame 接线由 Task 6 完成；本任务不改这些文件。

## Task 6: 持续会话列表与组合

**Files:** Modify `gui/pages/tasks_page.py`, `gui/task_feedback.py`, `gui/main_frame.py`,
`gui/widgets/task_table.py`, `gui/widgets/task_detail_drawer.py`及相应直接测试。

- [x] TaskCenterPage.set_session_snapshots 合入 session 行；resource_owned 控制活动筛选和全局计数，
  异常版本有界且重复轮询不重新未读；来源、目标、停止语义明确，完整日志回原页。
- [x] 停止信号携带 key/revision，路由原 owner，主窗枚举所有 registry 页面与唯一 RemotePanel，
  不创建新页面、不依赖当前设备选择；复用 coordinator 刷新节拍，无新永久 Timer。
- [x] 统一翻译/知识文档，原生命令/取消/归档语义不变；整合后独立评审与 Cocoa 原生验证。

## Task 7: 用户反馈的侧栏遮挡、输入隔离、统一样式与崩溃防护

**Files:** `gui/widgets/task_detail_drawer.py`、`gui/task_feedback.py`、必要的共享阅读器呈现动作边界、
直接 UI 测试与知识文档。代码审计见本机 ledger 的 panel-audit/macos-crash-audit 报告。

- [x] 将主题底板实际绘入父子合成画面；Light/Dark×12/22pt、完整/反转/resize/关闭中间帧核对。
- [x] 关闭中保持 pane 的 hit-test 遮挡且阻止自身业务激活，验证底层 0 次、外部正常、隐藏后恢复。
- [x] Qt accessible/programmatic 动作遵守 opened/shutdown；共享阅读器后台数据仍正常更新。
- [x] 统一已有角色字体、背景、间距与动作层级，不禁用整窗、不用透明动画掩盖问题。
- [x] 五处已知危险 QSignalSpy.at 补准确数量前置断言，保留身份/内容断言；不再调用无祖先 mapTo。
- [x] 独立评审、Qt 直接关联验证后，真实 macOS 操作与窗口录制核对背景按钮和绘制。

## 本轮验收结果（2026-11-08）

21个直接/关联测试文件按增量分组完成：540 passed、4个现有平台条件skip，未运行全仓库pytest。
Ruff、受影响生产模块Pyright、中文注释、文档链接与diff检查通过，源码packaging self-check通过。
独立组件、联合终审及用户追加遮挡/输入隔离评审均已闭环。最终macOS实际应用正常退出；
模拟器只读任务、真实Logcat持续/停止、背景按钮遮挡、窗口zoom/还原均已操作。三段本机窗口
录制共4288帧，包含完整开关和快速反转，未观察到白/黑/透明闪帧；未新增Python崩溃报告。

未运行Windows硬件、真实多设备投屏/性能采集全流程或PyInstaller构建；完整命令、逐帧指标、
原始本机录制及已知历史基线限制保留在本次本机验收记录，不将它们冒充全平台/全量通过。
当前改动保留在ui-design工作区，没有提交或推送。
