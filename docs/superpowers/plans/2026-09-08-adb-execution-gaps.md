# ADB 执行链遗漏修复实施记录

> 按 superpowers:subagent-driven-development 分模块实施，完成后交叉审查并执行关联验证。

**Goal:** 修复本任务上一轮审查确认的 12 项执行、取消、重复查询和截图处理遗漏。

**Architecture:** 复用 CommandRunner、AdbRuntime、现有 worker 和 TaskSupervisor。只读查询传递取消和共享预算；按任务归属合并重复工作；GUI 通过信号消费后台结果。

**Tech Stack:** 项目 .venv、Python 3.11、PySide6、已安装 qfluentwidgets、pytest。

**Spec:** 当前任务上一轮的 8 组审查结论及用户“安排执行修复并验证”的授权。

## 约束与工作区

- 在当前 ui-redesign 工作区接续已验收修改；保留已有脏文件，不提交、推送、迁移或修改生产依赖。
- 不重放已发送的业务命令；传输、写操作、交互和长进程保留各自执行与清理契约。
- 对每项已复现缺陷先补失败回归，修改后验证成功、失败、取消、重复启动和关闭。
- 原生 Windows Qt 视觉测试串行；其他隔离的直接测试可并行。未触发全量条件不跑全量。
- 文档、翻译资源和包装检查由主任务集中处理，子任务只编辑约定的代码与测试。

## 分工与接口检查

| 任务 | 归属文件 | 共享边界与约束 |
| --- | --- | --- |
| 1 原生短查询取消及关闭监督 | models/adb_model.py、models/adb_advanced.py、gui/close_controller.py、core/exec.py | 只读命令显式启用取消；监督已运行短任务；不改变写操作默认语义 |
| 2 新设备能力验证优先 | core/adb_runtime.py、tests/test_adb_runtime.py | 保留唯一探测线程、状态代次、10 秒恢复节流和 0.5 秒业务等待；仅抢占只读基准 |
| 3 概览预算和刷新合并 | controllers/_device.py、models/adb_device.py | 不编辑任务 1 的模型基类；函数新增可选 timeout/cancelled；保留逐台发布与批次存储 |
| 4 应用详情和 Logcat 辅助查询 | models/app_manager_worker.py、gui/dialogs/app_manager_details.py、gui/dialogs/live_logcat_worker.py、models/base/focus_detector.py | 首载单份详情/权限快照；权限变更仍刷新；前台包探测兼容其他调用方 |
| 5 Remote 启动与截图处理 | services/remote/scrcpy_service.py、gui/panels/remote_panel.py、gui/dialogs/screenshot_viewer_*.py、gui/features/media.py | 预检共享预算与取消；图像后台解码、页内有界缓存、增量追加、监督删除 |
| 6 MobilePerf 采样与停止 | mobileperf/android/startup.py、fd.py、thread_num.py、tools/androiddevice.py 及必要新内部模块 | 周期快照按设备/包/周期隔离；保留 CSV 和 PID 重启；停止等待可唤醒 |

每个任务内部按“回归失败 → 最小修复 → 直接测试 → 关联消费者 → 静态检查”执行。任务 1 与 3 通过 CommandRunner 现有 cancelled 参数协作，不并发编辑模型基类；任务 5 的图像转换只在 GUI 线程创建 QPixmap；任务 6 不改变核心执行器接口。

## 验收清单

- [x] 1 已运行原生只读命令可取消，监督器不会在短任务仍运行时报告完成。
- [x] 2 新目标到来优先完成能力验证，不被旧原生基准拖回慢路径。
- [x] 3 概览回退共用截止时间；同拓扑刷新合并且旧查询不覆盖新结果。
- [x] 4 应用详情首载只查询一次；Logcat PID 与前台包查询执行中可取消。
- [x] 5 Remote 停止后不执行后续预检；高分辨率图有界缓存；追加不全量重建；删除受监督。
- [x] 6 MobilePerf 同周期共享 PID/status；主循环及相关采集等待可中断。
- [x] 7 交叉审查、关联集成验证、文档与必要资源自检完成。

## 执行记录

- 已复核当前工作树与测试规则。上一轮问题的代码链和替身复现作为本轮回归设计依据。
- 用户已授权执行已展示方案，沿用当前工作区；不重复审批、不创建丢失现有未提交实现的空白 checkout。


## 完成结果（2026-09-08）

- 任务 1：只读 model 查询共享模型关闭与调用方取消；关闭后台等待 Executor、模型池与活动短命令。写操作保留既有完成语义。原生查询取消、池任务等待与短命令监督均先复现后修复。
- 任务 2：新设备能力优先于主机/旧设备基准；收尾窗口重新消费待验证目标，后继线程先 join 前驱，禁止并行探测和旧线程覆盖新 checking。抢占、收尾、交接、关闭、epoch 由 Event 回归覆盖。
- 任务 3/4：概览共用预算并合并同拓扑刷新；后台写锁内重查代次。详情/权限首载一个快照；Logcat PID 和前台包查询可取消。精确写盘交错、真实详情页加载和权限刷新已有回归。
- 任务 5：Remote 预检共用预算且去掉附加测速；截图先展示当前解码结果，再读邻图，64 MiB 页内缓存、增量追加、隐藏页暂停读取、快照后台删除与原生 join 释放屏障。原生 Windows 测试保持原布局断言，等待后台加载及元数据重排结束。
- 任务 6：FD/线程指标共享周期快照；主循环及相关采集间隔可唤醒。交叉审查追加修复零预算误入无限等待、启动阶段预算耗尽后继续启动、间隔提前唤醒重复采集三项边界。
- 交叉审查已覆盖规格与实际调用链，审查发现的本轮阻断项均已修复。既有未提交修改保留，未提交、推送、改版本、改依赖或设备设置。

### 最终验证

以下为最后一次对应范围结果，分组之间可能包含关联覆盖，不相加声称全量测试数。

| 范围 | 结果 |
| --- | --- |
| 20 个核心/模型/关闭/查询/Logcat/Remote/MobilePerf 直接与关联文件集成 | 582 passed，30.36 秒 |
| 截图 I/O、截图批次和 Workspace 宿主关联 | 61 passed，16.49 秒 |
| 原生 Windows 截图页面及模型截图节点 | 34 passed，8.42 秒 |
| 媒体模型非截图节点 | 62 passed |
| 本轮 50 个生产/测试文件 Ruff | 通过 |
| 受影响的受控生产模块、截图模块、新 sampler 与共享状态 Pyright | 0 errors，0 warnings |
| 31 个生产文件中文注释检查 | 通过 |
| 项目知识文档链接及 frontmatter | 33 个文档通过 |
| git diff --check | 通过；只有已有换行转换提示 |

MobilePerf 旧目录并未纳入项目 Pyright include；额外扫描仍有既有类型诊断，未降低标准或扩大清债。未触发仓库全量测试条件，未跑全量 pytest；未改变打包边界，未执行 PyInstaller 构建。

核心集成命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_adb_runtime.py tests/test_adb_fast.py tests/test_qt_adb_runtime.py `
  tests/test_model_shutdown_admission.py tests/test_phase2_mainframe_shutdown_gate.py `
  tests/test_model_device.py tests/test_model_ci_controller.py tests/test_model_apps.py `
  tests/test_app_manager_selection.py tests/test_phase2_live_logcat_gate.py `
  tests/test_monkey_preparation.py tests/test_adb_injection_argv.py tests/test_multi_device_network.py `
  tests/test_mobileperf_startup_deadline.py tests/test_mobileperf_query_budget.py `
  tests/test_mobileperf_sampling.py tests/test_mobileperf_adb_execution.py `
  tests/test_model_mobileperf.py tests/test_mobileperf_monkey_lifecycle.py tests/test_remote_services.py

$env:QT_QPA_PLATFORM='windows'
.\.venv\Scripts\python.exe -m pytest -q tests/test_screenshot_page.py tests/test_model_media_adb.py -k screenshot

$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_screenshot_io.py tests/test_phase2_screenshot_gate.py tests/test_workspace_feature_host.py
```

### 当前实机抽查

复用已运行的本机 ADB 服务，3 台设备仅执行回显、系统信息等只读命令，未输出设备标识。

| 项目 | 本次测量 |
| --- | --- |
| 服务 ready 后的首个回显，含必要能力等待 | 151.8 / 198.1 / 227.5 毫秒，3 台均成功 |
| 正式设备概览查询 | 486.5 / 454.5 / 375.0 毫秒，每台返回 14 个字段 |
| 已进入原生路径的 model 只读查询取消 | 118.4 毫秒退出，cancelled=True，活动短命令归零 |

另一次在服务 ready 之前立即调用的首条命令走了原生路径，耗时 6.272 秒；这属于提前调用的冷启动边界，不计入 ready 后的数据。以上是当前设备与环境的抽查结果，不是所有命令的性能保证。未执行实机拔线、Remote 长跑或 MobilePerf 长时间采集，相关失败/停止边界由替身和真实线程回归覆盖。
