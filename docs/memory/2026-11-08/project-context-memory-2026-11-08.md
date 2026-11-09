# ADBLab 项目记忆 — 2026-11-08

用户明确要求使用项目记忆与 Superpowers 工作流阅读当前项目，保存后续开发所需上下文。
本记录是源码核对后的日期快照，不替代知识库、当前代码或新的用户要求。

## 下次从哪里继续

先读 [AGENTS.md](../../../AGENTS.md) 和 [知识库入口](../../README.md)，再核实
`git status --short`、当前分支及相关源码。此次读取时分支为 `ui-design`，HEAD 为
`07b6f543`（支持二维码展开修复）；有大量未提交、未跟踪的代码、测试、翻译及计划。
后续不要把整棵工作树视为本次新增，也不要凭本记录推断已提交或已验收。

文档与代码不一致时核实代码；历史方案和验收数字只证明对应阶段。新增记忆按日期追加，
已有知识库事实用链接引用，避免另建一份长期漂移的架构说明。

## 已核对的项目定位与入口

- Python 3.11 桌面应用，以 Android/ADB 工具为核心；运行依赖固定 PySide6 6.8.1.1、
  Fluent Widgets 1.11.3，构建依赖为 PyInstaller 6.22.2。版本依据是
  [运行依赖](../../../requirements.txt)、[构建依赖](../../../requirements-build.txt)，
  不表示本轮完成环境或产物验收。
- 版本单一来源为 [app_metadata.py](../../../utils/app_metadata.py)。依赖继续按
  `requirements.txt`、`requirements-build.txt`、`requirements-dev.txt` 分层，使用项目 `.venv`。
- [main.py](../../../main.py) 同时承载 GUI、`--self-check`、`--mobileperf-worker`、
  `--startup-splash` 和内部 `--adblab-native-launch`；修改入口不能破坏冻结子进程协议。
  `_run_gui_session()` 在创建 QApplication 前应用缩放和客户端选择，随后加载字体、翻译及主题，
  通过启动任务与 `MainFrame.advance_startup()` 分阶段装配。

| 要修改的范围 | 优先入口与边界 |
| --- | --- |
| 主窗、导航、装配和关闭 | [MainFrame](../../../gui/main_frame.py)、[CloseController](../../../gui/close_controller.py)；主窗拥有 QtTaskSupervisor，关闭先封准入，再停止并等待资源，最后保存状态和销毁父树 |
| 信号路由和模型装配 | [Controller](../../../controllers/__init__.py)、[模型工厂](../../../controllers/model_dependencies.py)；Device/App/Testing/Advanced 四模型按一次性工厂创建，保留原属性和连接 |
| 业务用例与基础设施 | [架构](../../project-knowledge/ARCHITECTURE.md)、[模块地图](../../project-knowledge/MODULE_MAP.md)；业务在 services，命令/进程/设置在 core，Qt 适配与 worker 在 gui |
| 命令与资源归属 | [core.exec](../../../core/exec.py)、[任务监督](../../../core/tasks/supervision.py)、[操作状态](../../../services/tasks/operations.py)；短命令用 CommandRunner，受控长进程用 ProcessRunner，业务终态和资源退出分开 |
| 设备目标与功能会话 | [DeviceContext](../../../services/devices/device_context.py)、[功能会话](../../../gui/features/base.py)；选择状态不接管扫描或会话，切页不等于停止，按 feature/device/generation 保护旧会话 |
| 用户数据和工具路径 | [用户数据目录](../../../utils/user_data.py)、[工具缓存](../../../utils/runtime_tools.py)、[资源解析](../../../utils/resource_path.py)；兼容源码和冻结环境，不假定安装目录可写 |

耗时 I/O 与等待不进入 GUI 线程；设备 shell 的动态值沿用已有校验和 quote 边界。
取消、停止和 `finished` 信号不能代替原生线程 join、进程退出及自有客户端/远端义务释放。
`ProcessRunner.spawn()` 的生命周期由调用方负责，不能误当作已经自动登记到活动表。

## 当前未提交开发：任务中心与持续会话

最新方向见 [任务检查器与会话状态设计](../../superpowers/specs/2026-11-08-task-inspector-session-state-design.md)
及其 [实施计划](../../superpowers/plans/2026-11-08-task-inspector-session-state.md)。
更早的 drawer、refinement、direct-results 方案应按需求演变阅读，不能把旧控件重新加回。

- 侧栏只展示当前任务；完整列表、筛选和历史归任务中心。旧方案的最近任务切换及底部返回/
  定位导航已经被新需求替代。普通操作结果采用共享右侧阅读器，不恢复长期占位的底栏。
- 组合入口在 `MainFrame`：`TaskCenterPage(external_details=True)`、
  [SessionTaskRegistry](../../../gui/session_tasks.py)、
  [TaskFeedbackCoordinator](../../../gui/task_feedback.py)。抽屉使用
  [TaskDetailDrawer](../../../gui/widgets/task_detail_drawer.py)，复用单例 reader；
  收起抽屉不取消任务，自动反馈不抢另一任务、也不自动消费异常已读状态。
- [ActionResultView](../../../gui/widgets/action_result_view.py) 与
  [RunResultsWidget](../../../gui/widgets/run_results.py) 保留正文、参数、附件及全文动作。
  正文显示预算不等于搜索、复制、导出的全文被截断。独立组件保留原兼容显示模式。
- `SessionTaskSnapshot` 的 `key/revision`、`resource_owned`、`stop_enabled` 与 `busy`
  有不同职责。Registry 只读枚举已存在的 Logcat/Performance/Remote owner；停止前重新核验
  原 owner 与版本，受理不等于退出，不为展示创建新页面或切换操作设备。
- [TaskNavigationButton](../../../gui/widgets/task_navigation.py) 区分活动数与忙碌数：
  稳定运行的镜像、Logcat、性能会话仍 active，但使用静态活动环；准备和阶段推进才旋转。
  原执行资源仍由各功能 owner 管理，UI 投影不接管生命周期。
- 外侧关闭、选区、搜索和菜单中的任务动作要保留完整手势和原身份保护。定位入口为
  `TaskFeedbackCoordinator`、[ReaderInteraction](../../../gui/widgets/reader_interaction.py)
  和 [TaskActionGesture](../../../gui/widgets/task_action_gesture.py)。
- 当前 [ScrcpyService](../../../services/remote/scrcpy_service.py) 变更包括 POSIX stdout
  使用私有 PTY 及时交付就绪输出，Windows 保留 PIPE；不可把进程存活或 Renderer 文案当作画面就绪。
  MobilePerf 的内存快照与后台资源探针也有变更，避免在 GUI 投影中核验原生资源。

这些是读取时的实现现状，不是本轮验证结论。重点回归入口包括
[检查器](../../../tests/test_task_inspector.py)、[会话忙碌状态](../../../tests/test_task_session_busy.py)、
[会话投影](../../../tests/test_session_task_projection.py)、
[scrcpy stdout](../../../tests/test_scrcpy_stdout.py) 及 drawer/reader 关联测试。
旧阶段的通过数不能覆盖最新 PTY、Cocoa 重绘、键盘焦点及资源释放改动。
业务与显示边界统一查 [操作结果指南](../../guides/OPERATION_RESULTS.md)。

## 已有字体与显示约束

新配置及恢复默认使用空 `font_family` 与 `ui_font_size="Auto"`，已有字体名和数字字号保留。
[Typography](../../../gui/styles/typography.py) 从 Qt GeneralFont 解析系统 pt，保留小数；
界面范围 8–22pt，异常回退 12pt，日志默认仍独立 9pt。不要将 pt 再乘 DPR 或显示缩放。
[设置卡正文](../../../gui/widgets/setting_card_layout.py) 局部禁用重复安全区扣减，
避免 macOS 首次滚入时网格负高度造成标题和说明重叠。
主题、字体、图标、响应式和焦点行为继续沿用项目体系，详见
[UI 实现](../../project-knowledge/UI_IMPLEMENTATION.md) 与
[设置数据流](../../project-knowledge/DATA_FLOW.md)。

## 构建与验证入口

详细条件以 [构建指南](../../guides/BUILD_AND_RUN.md) 和
[测试指南](../../guides/TESTING_GUIDE.md) 为准，下面是接续时的命令索引，并非本轮执行记录。

| 场景 | 入口 |
| --- | --- |
| macOS/Linux 启动 | `.venv/bin/python main.py`；Windows 对应 `.venv\Scripts\python.exe` |
| 指定测试 | `.venv/bin/python -m pytest -q <测试文件或节点>` |
| macOS 真实 MainFrame | 前缀 `QT_QPA_PLATFORM=cocoa`；offscreen/minimal 不能提供该原生桥所需句柄；普通 QWidget 测试可按指南使用 offscreen |
| 本轮 Python 变更检查 | Ruff 检查修改文件；共享类型影响时对关联生产模块跑 Pyright；生产注释用 `scripts/check_comment_language.py` |
| 源码资源边界 | `.venv/bin/python main.py --self-check packaging`；不是业务、实机或实际产物验收 |
| 已有运行工具检查 | `.venv/bin/python scripts/prepare_runtime_tools.py --check`；准备/下载与只读检查不同 |
| 冻结产物检查 | `.venv/bin/python scripts/check_build_artifacts.py frozen --executable <产物入口> --timeout 60`；不能用源码自检代替 |

Windows 沿用 PyInstaller onedir + Inno Setup；macOS 为对应架构的 onedir `.app` 与 ad-hoc
签名；CI 另有 Linux x64 onefile。平台构建、签名/公证、依赖与正式发布是不同边界，实际
执行仍遵守现有授权。普通阅读、记忆或文档新增不触发全量 pytest、完整构建或实机操作。
跨平台实机、依赖升级及分发许可等未闭环事项查 [风险账本](../../project-knowledge/RISKS_AND_DEBT.md)，
本轮没有重新裁决其状态。

## 本轮实际工作与证据边界

- 并行只读核对架构/生命周期、构建测试入口、当前未提交任务中心变更；没有修改生产代码、
  测试、配置、依赖或既有知识文档，没有提交或推送。
- 新增本记忆，并在 Codex 记忆扩展目录保存一条索引，供后续检索定位此文件；没有改写已有
  生成记忆。具体事实应回到上面的源码和权威文档复核。
- 本轮没有运行 pytest、GUI/设备操作、PyInstaller、源码或冻结产物自检；不据历史结果宣称
  当前脏工作树已经通过验收。文档校验结果见本记录追加的完成检查。

完成检查：`.venv/bin/python scripts/check_doc_links.py` 已通过（122 份文档），
`git diff --check` 已通过；另独立检查本新增记忆的所有相对链接、两份文件的换行/尾空白和
记忆索引目标，均通过。分支与 HEAD 复核仍为上述快照；既有未提交修改保持。
