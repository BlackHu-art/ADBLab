# 当前任务检查器与持续运行图标实施计划

Spec: docs/superpowers/specs/2026-11-08-task-inspector-session-state-design.md

使用superpowers:subagent-driven-development；用户已授权多agent、自主设计/实操。
继续ui-design脏checkout，捕获当前base，保留所有旧阶段证据，无commit/push/暂存/回退。
独立UI与只读会话投影任务并行，避免改同文件；root统一Cocoa/CUA，子任务只跑普通QWidget。

## Task 1: 精简当前任务 inspector

先读spec、同workspace的前阶段报告/主题审计摘要及base。用设计判断重新整理单任务层级：
不显示历史/最近切换，不显示底部返回/定位导航；一处任务名，紧凑状态与目标，直接正文，
紧凑搜索/复制导出，参数/文件就地可见，取消/停止仍明确。完成态无大块永久底栏。
复用现有主题/字体/图标与单例reader、原按钮及动作冻结，不引入bitmap或新依赖。

生产独占：gui/widgets/task_detail_drawer.py、action_result_view.py、run_results.py、
gui/task_feedback.py。不得改TaskPage（Task2独占）、session_tasks/task_navigation/remote owner。
不改ReaderInteraction/TaskActionGesture/全局主题字体。需要新范围先给代码证据报root。
知识文档UI_IMPLEMENTATION/OPERATION_RESULTS由本task统一写，Task2只提供导航文案建议。

先给出简短设计结构并继续实施，不等待用户重复审批。安全red→green；旧测试只迁移已删除的
sidebar history/footer UI契约，保留列表/过滤/动作次数、原key/revision/关闭保护等有效断言。
新增tests/test_task_inspector.py（ui marker），相关现有drawer/reading/refinement/feedback/reader
测试范围内修改；native MainFrame节点由root跑Cocoa，严禁offscreen原生句柄。
覆盖中文/英文×12/22pt×280/390px、深浅/强调色/字体、无输出/失败/多设备/归档/持续会话，
同reader/选区/搜索/附件与外侧关闭完整手势保留。图标化工具有完整可访问名、提示与键盘焦点。
完成改动文件Ruff、production Pyright、中文注释/docslinks/diffcheck；冻结patch/hash/report。

## Task 2: 区分真实忙碌与稳定持续运行

先读spec、mirror-spinner-audit.md、base与相关owner/任务中心文档及既有测试。只读接口追加
字段按spec值与默认值实现，普通短任务busy，稳定会话静态活动标记，Remote混合准备仍busy。
独占生产：gui/widgets/task_navigation.py、gui/session_tasks.py、gui/pages/tasks_page.py、
gui/panels/remote_panel.py。不改TaskFeedback/Drawer/readers或scrcpy_service/进程ready回调。
不重构资源生命周期、key/revision/停止路由、已读版本或成功事件。共享文档只提交建议到report，
不得同时改Task1文档。Task1 UI不改TaskPage，typed readonly fields是两任务唯一公开衔接。

先补无设备/普通QWidget red（connecting→ready、混合batch、短operation、Logcat/perf、静态像素
与busy动画、隐藏/恢复/销毁、异常/成功、旧构造兼容、旧owner/revision/停止），再修最小根因。
新增tests/test_task_session_busy.py（ui marker）及相关session/nav/page既有节点。
仅自己的直接及关联测试，严禁native/CUA/启动实际镜像或设备命令。改动文件Ruff、相关Pyright、
中文注释/diffcheck；保存独立patch/hash/report冻结。不改Task1任何文件。

## Task 3: 集成复核与实际 macOS 验收

Root核对两任务delta与保护清单、合并共享文档事实，由fresh reviewer统一spec+quality+接口评审。
有问题按fix-loop原implementer前三轮修；英文footer旧P2因按钮按用户要求移除已superseded。
Cocoa按当前UI/会话投影消费者有界选择，不重跑旧327/540全历史范围。
用户已明确暂时不操作应用；root实际启动main.py，检查新布局、主题字体/Fluent滚条、外侧首击，
录ADBLab窗口本机无audio逐帧检查正常/快速反向展开收起。启动本轮独立镜像，实际ready后图标
稳定且active/停止仍正确；结束本轮会话、还原临时设置/选择并正常退出。无法完成实机时明确边界。

## 实机发现后的补充修订

原生 Cocoa 集成检查要求真实键盘焦点：搜索到复制、导出及 Space 激活必须在当前控件实例上
成立。macOS 默认键盘导航规则不能通过测试跳过或修改系统设置规避。布局中不同高度控件
按同一工具栏对齐验证，区分整数中心取整和实际跨行。

原生逐帧录制发现滑动初始帧仍有旧面板窄条残影。Task1 原实现者负责局部暴露区域与重绘
修正；保留真实控件、后台任务身份、非阻塞动画和快速反向过程，由 root 重新录制复验。

镜像实机显示准备一直未结束；scrcpy 4.1 的 INFO 标记在 POSIX 管道中缓存到退出才到达
应用。补充子任务由原 Task2 实现者负责，仅改变 ScrcpyService.start_plan 的 POSIX stdout
传输，使用标准库 PTY 触发子进程逐行交付；Windows 保留 PIPE，stderr 和原进程归属不变。
不得把进程存活或 Renderer 当作画面就绪。先用本机 libc printf 替身证明子进程存活时就绪
输出可读，再验证 EOF、失败、取消、重复启动与关闭的描述符归属；独立评审后 root 启动
真实镜像确认画面就绪、图标转为静态活动状态及停止释放。

## Task 4: 统一任务中心的记录表格

按最新用户补充移除所有任务状态筛选，保留搜索和类型。参考现有表格页面复用真正的
Fluent/Qt 表格、共享字体与主题样式，保留任务记录、行状态、详情、取消/停止和活动投影。
独占 TaskCenterPage、TaskTable 与直接任务中心测试，捕获新基线后实施；与 Task1 的
Drawer 安全区/动画修复并行，禁止交叉写入。先直接普通 QWidget 回归，再由 root 选择
关联 Cocoa 节点，独立评审后实际检查表头、记录、窄窗/大字、抽屉和原任务动作。

Task4 原生兼容修订：因公开 Qt wheel 的已知辅助功能缺陷，按最新兼容裁决调整任务表格的
局部渲染实现。保留新表格视觉，复用旧稳定行控件的身份和动作，独立评审及实机流程不省略。
Qt 四个依赖包仍按用户‘全部升级适配’统一 6.9.1；不猜测更换尚无目标修复的版本。
