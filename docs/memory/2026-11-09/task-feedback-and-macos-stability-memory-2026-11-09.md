# 任务反馈、侧栏与 macOS 稳定性 — 2026-11-09

本记录接续 [基础上下文](../2026-11-08/project-context-memory-2026-11-08.md)，按根
AGENTS.md 的自动记忆授权追加。工作始于 11 月 8 日，跨日完成；当前仍在 `ui-design`，
大量已有未提交文件属于用户资产，没有执行暂存、提交或推送。日期记录是验收快照，后续应核实当前源码。

## 当前用户决定

最新要求覆盖早期抽屉方案：去掉任务列表箭头整列，以及单项结果的无意义下拉框与本机重复信息。
仅真实失败可自动打开侧栏；成功截图直接进入相册，执行时间长也不自动打开。完整历史与搜索、类型
筛选保留在任务中心，侧栏只展示当前任务；不恢复状态过滤器、侧栏历史或底部返回按钮。
用户已委托其他布局细节及多 agent 实现、评审，并明确要求实际 macOS 操作验收。

规范已读取：当前根 AGENTS.md、docs/README、基础与清理记忆，已安装的 `qt-ui-design` 和
`project-memory` skills。设计沿用 BaseStyles、FontRole、Fluent 控件与已有保存的字号；不引入新字体、
QML、依赖或全局主题状态。字体自动跟随系统与 LOG 独立字号继续生效。
当前设计及边界见 [最新设计](../../superpowers/specs/2026-11-08-task-feedback-quiet-success-design.md)、
[计划](../../superpowers/plans/2026-11-08-task-feedback-quiet-success.md)、
[操作反馈事实源](../../guides/OPERATION_RESULTS.md)和
[UI 实现](../../project-knowledge/UI_IMPLEMENTATION.md)。

## 实现接续点

- `TaskCenterPage.allows_automatic_details()` 是自动打开的唯一只读资格。普通终态 failed、含失败子项
  的 partial 以及 `_settle` 不变量可证明的请求级失败允许；运行中、成功、取消、一般注意保持安静。
  notes 仅最新条目明确 failed 且通知入口请求展示时允许，不能因旧失败让新成功重新弹出。
  Presenter 移除 500 ms 过程弹出与重复提交弹出；Coordinator 在选择、焦点和已读变化前复用同一门禁。
  手动入口和已收起请求、另一个阅读器、关闭/隐藏保护保留。
- `TaskTable` 仍由真实 QWidget 行与 SmoothScrollArea 组成，五个实际数据列；没有假箭头控件或空列。
  点击任务名/非操作区域、Enter/Space 打开；取消/停止保留原 key/revision 手势。标题为 StrongFocus，
  也是行内详情收起后的焦点锚点。表格内部滚动条才是内联阅读器的滚动宿主。
- `ActionResultView` 的 hosted 模式对 0/1 job 都不显示选择器，仍保留数据与原 job identity。
  多 job（包括同设备多命令）保留独立切换、搜索、复制、导出与附件。旧 target_names、目标数量、
  子命令与请求的状态/归属差异用必要的只读信息呈现；不以“本机”翻译文本猜测实际设备。
- 成功 Shell 仅在控制器已知格式、唯一对应目标/job 且完整输出精确一致时收紧重复消息；失败、
  附加信息和歧义保留原文。64,000 字预览和完整正文预算、全文动作未改变。
- 实机观察后追加 `RemotePanelScrcpy._poll_process()` 的有界修正：用户已请求停止且服务已确认
  进程/helper 释放时，非零信号退出只记 DEBUG 诊断，避免 watchdog 先于完成回调产生多余未读警告。
  非主动非零退出仍 failed/WARNING；真实停止失败、原资源屏障与兼容分支不变。
- `ReadingSurfaceMaterial.set_document_mode()` 只作用于当前只读正文，统一移除宿主重复底板/边线；
  默认模式、独立/诊断/内联模式及可编辑恢复仍沿原样式；不替换文档或丢失选区与滚动位置。

## 必须保留的前段稳定性修复

这些来自同一持续任务的前段，不应在后续 UI 精简中回退。

- 经用户授权，requirements/constraints 与项目 .venv 的四个 Qt 包已统一为 **6.9.1**；不是仅 macOS。
  源码 packaging 自检和 pip check 已通过，没有运行本轮 PyInstaller 正式构建。不要据此声称所有平台
  或所有 Qt item view 的原生辅助接口缺陷已修复。
- 旧 macOS 崩溃涉及 Qt 原生 item view 行列辅助对象，TaskTable 已改成真实 QObject 子控件，保留实际
  可访问按钮和文本，不重建假单元格 AX 对象。原生启动测试另修正了假 paintEvent 内同步关闭的错误夹具。
- 支持 native tracker 的 Cocoa 投屏工具栏必须无深层 QWidget parent，由既有 dock entry 生命周期清理。
  原深层 parent 首次 winId 会把工作区与八个缩放热区原生化，导致合成后的抽屉旧边线残留。
  同一变更保留 xcb 独立窗口策略，Windows 和便携分支未改；不要用全局禁用辅助功能或刷新快照替代。
  契约见 [投屏业务流程](../../project-knowledge/BUSINESS_FLOW.md)。
- 持续会话 active 与 busy 不同：实际就绪镜像仍 active=1，但环静态；准备/停止/排空才旋转。
  POSIX scrcpy stdout 的局部 PTY 保证进程存活时及时收到 Texture 就绪行，Windows 仍用 PIPE，
  不以进程存在或 Renderer 文案冒充就绪，资源仍由原 owner 与 ProcessRunner 管理。

## 本次实际验收与边界

前两批生产/UI 增量均有独立只读评审，结果 Approved，没有待处理 Important；
主动停止补充的独立评审也为 ADDRESSED / Approved，三批均无待处理 Important；
正式报告与冻结增量保存在同一材料目录。
自动反馈改动三文件和布局改动四文件（共享 TaskCenterPage）都有改动前脏树快照与冻结增量，
没有把整个工作树相对 HEAD 的差异当作本轮工作。局部产物在
`.superpowers/sdd/2026-11-08-task-feedback-quiet-success/`，此前稳定性证据在相邻
`2026-11-08-task-inspector-session-state/`；它们是本机验收材料，不能据此推断已提交。

- 直接原生 Cocoa UI 测试 **164 passed**。消费者组合 **142 passed / 5 failed** 的五个失败均为
  旧用例将内联详情按外层无滚动页面检查；改为实际表格滚动宿主，保留原完整可达性/身份断言，
  连同关联节点定向 **60 passed**。末次目标数量/请求级失败/Presenter 关联 **8 passed**。
  这是分批组合证据，不声称布局全部节点曾在最终单次运行中全绿。
- 追加的主动停止竞态回归先 **1 failed / 1 passed**，再 **7 passed / 3.53 s**；测试通过真实
  停止按钮和 Event 固定 watchdog 先到的时序，核验资源仍活动时保持归属，主动停止释放后仅诊断，
  意外退出仍警告。首次实机红点的具体消息/rc 没有保存，不能断言它由此分支产生。
  修正后再次启动实际主程序，远控页停止和任务侧栏停止各一轮，两轮 Texture 就绪后停止均
  排空至 **0 active / 0 unread**；第二轮实际进入非零退出 DEBUG 诊断分支，未生成业务警告。
  未自动打开额外侧栏，正常退出且无子进程残留。
- Qt 6.9.1 尚未执行的兼容尾部（startup/mainframe/window lifecycle/settings typography/navigation）
  **243 passed / 4 skipped**；不是全量 pytest，也不把旧版本通过数累计成当前全套通过数。
- 实际启动未注入 hook 的 main.py：刷新成功只记录，手动阅读无箭头列、无本机重复目标/单项下拉；
  真实设备截图 **651.1 ms** 成功，图片进入相册且侧栏未自动打开。不存在的无副作用 Shell 命令
  则自动展示原错误，失败单项也无选择器。外侧首击收起且来源页保留；Esc 回到实际任务标题，
  Return 可重新打开。
- 实际启动并停止镜像两轮，Texture 在进程存活时到达；就绪显示静态活动环与数字 1，停止和资源
  排空后 active=0。遮挡的停止按钮位置点击没有触发背景停止。只录制 ADBLab 主窗口，无音频、
  无桌面或独立镜像窗口；当前布局完整六轮开合录像已保存，最终像素统计见本记录完成检查。
- 本轮主程序正常退出（返回码 0），之后没有 Python 或 scrcpy 子进程。末次核对系统最新 Python
  崩溃报告仍为 **2026-11-08 21:18:07** 的前段 Qt 辅助接口问题，未生成新的报告；这不证明第三方
  Qt 的其他视图不存在缺陷。用户模拟器与既有 ADB server 是用户资源，未关闭或重启它们。

没有运行全量 pytest、Windows/Linux 原生桌面验收或 PyInstaller 分发构建。现有第三方弃用提示
没有屏蔽，其他对话清理记忆记录的无关基线问题不在本轮中顺手调整。后续验证应按测试指南增量选择。

完成检查：新布局接入后的 Cocoa 集成命令
`QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_task_feedback.py tests/test_action_feedback.py tests/test_task_feedback_review.py tests/test_task_drawer_input_isolation.py`
实际 **227 passed / 135.58 s**。当前布局录像解码 **1049 帧、6 次完整收起与 6 次完整展开、
0 个双边线帧**；可辨文字的 868 帧中标题和正文都没有空白帧。875 个避开窗角的有效帧中底部
8 逻辑像素边线连续，左侧取样画布全程像素差 0，活动环与数字 1 保持；本片未覆盖中途反向或
不同 DPI。采集端报告丢帧 0，录像不等于所有环境都不存在绘制问题。

本阶段及主动停止补充的修改文件 Ruff、七个生产模块的分批 Pyright、中文注释检查、
`git diff --check` 均通过；
文档检查在追加本记录后为 **130 份通过**。没有执行 commit/push，HEAD 仍为 `07b6f543`。
