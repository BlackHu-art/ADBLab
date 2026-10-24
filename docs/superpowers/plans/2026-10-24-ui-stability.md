# 字体、布局与 Qt 退出验证记录

日期：2026-10-24。本轮接续已完成的项目重构，只处理已记录的字体、UI 布局失败、Qt 原生退出
及 APK 选框关闭验证缺口。保留前置未提交资产；不变更用户数据格式、生产依赖、版本或发布流程。

## 修改与依据

| 范围 | 根因与处理 |
| --- | --- |
| 导航字体 | Windows offscreen 已能枚举部分字体，却漏载中文 TTC；旧夹具只在字体库为空时补字体。改为仅在 Windows offscreen 会话注册系统中已有的四个字体文件，生产字体回退和原字体断言不变。 |
| 应用状态区 | 单独累加每行控件宽度低估 QGridLayout 共享列和跨列约束；改为计算真实列预算。选择计数宽度改变时重新规划，保持计数、过滤和刷新入口完整。 |
| 设置页恢复 | 新建路径标签首次尚未 polish，使用旧字体测量；后续交互才减少 3/6px。测量前 ensurePolished，保留原诊断、二维码高度及滚动恢复断言。 |
| APK 非空返回 | 同步文件框运行嵌套事件循环，返回时窗口可能已经关闭。GUI 关闭入口同步封闭 ActionResults，三个 Controller 入口复核自身关闭状态与结果准入，不重新访问 window_owner，不改变资源停止顺序。 |
| Qt 测试清理 | 文件页布局测试启动真实目录线程，却用 _close_ready 绕过关闭屏障；旧夹具销毁窗口时没有等待子线程。布局测试隔离目录事务，保留真线程及信号；共享夹具经 owner 停止、实际 join 后释放对象树。 |
| Windows 布局断言 | 异常选项组已有标题，但旧断言漏算标题并使用过期模式名集合；改为完整分组的左边界、包含关系、顺序、不重叠和文本完整检查，覆盖窗口宽度往返。 |
| Monkey 背景断言 | 固定采样点落在文字上；按真实子控件矩形扣除内容，严格比较剩余背景区域，并映射 DPR。保留悬停、禁用往返与输入底色反差；不透明底板变异仍被拒绝。 |

当前实现分别见 [UI 实现](../../project-knowledge/UI_IMPLEMENTATION.md)、
[架构中的 Controller 边界](../../project-knowledge/ARCHITECTURE.md)和
[测试隔离约定](../../guides/TESTING_GUIDE.md#隔离与替身)。

## Qt 原生退出证据

历史事件记录 `Qt6Core.dll 6.8.1.0`、`0xC0000409`、偏移 `0x267a8`。当前相同版本 DLL 在此
地址执行 `int 0x29`，此前参数为 7；函数导入及指令序列与
[Qt 6.8.1 qAbort](https://raw.githubusercontent.com/qt/qtbase/v6.8.1/src/corelib/global/qassert.cpp)
一致。该异常码可由 [Windows fast-fail](https://learn.microsoft.com/en-us/cpp/intrinsics/fastfail)
主动终止产生，不能单独解释为缓冲区损坏。

受控子进程只把 DirectoryListWorker.run 替为合成阻塞等待，不运行设备命令：旧清理路径在
测试 call 通过后、teardown 完成前收到 `QThread: Destroyed while thread is still running`，
真实退出为 `3221226505 / 0xc0000409`；先 dispose/join 的对照退出 0。修复后，响应正常取消
的同一合成线程经过真实窗口清理，call、teardown、sessionfinish 及进程退出均通过。

独立审阅补充了自动删除和未完成启动边界。清理辅助器接管 WA_DeleteOnClose 及已排队的
deleteLater；所有线程实际 join 后才在 GUI 测试 teardown 安全边界释放对象。超时保留对象并
报告失败，下一轮重试；关闭异常不绕过等待。未完成启动的 MainFrame 使用真实 abort_startup
并等待中止完成。没有修改 Qt、强制终止线程或压制致命消息。

这证明并修复了可复现的测试清理缺口；历史事件的唯一触发归因边界见
[风险与验证边界](../../project-knowledge/RISKS_AND_DEBT.md)。

## 实际验证

使用仓库 `.venv`。父进程为每组测试隔离 LOCALAPPDATA、APPDATA、三个 XDG 目录及
MOBILEPERF_LOG_DIR，并将旧设置来源指向不存在的临时文件；子进程启用 faulthandler。
保存实际命令、pytest setup/call/teardown、sessionfinish 和原生退出码；原生调查另保存 Qt 消息。

| 集合 | 结果 |
| --- | --- |
| 导航字体夹具、原字体与关联布局 | 15 + 12 passed |
| 应用状态区、选择/过滤/准入关联 | 7 + 8 + 7 passed |
| 设置恢复、新幂等回归及关键关联 | 12 + 14 passed；另重排探针最大嵌套深度为 1 |
| APK 非空关闭直接、安装/结果准入、关闭门禁、信号链 | 22 + 82 + 28 + 10 passed |
| 最终 Qt 清理辅助器及危险文件页/存储隔离关联 | 21 + 5 passed；合成线程关闭探针 1 passed |
| 修复线程清理前的原 113 项集合诊断 | 112 passed、1 个原生 Windows 插件专属 skip，进程退出 0；不单凭本次无复现判定竞态已修复 |
| 最终 Windows 原生插件集成 | 24 passed，进程退出 0；包含上述被 offscreen 跳过的节点、导航字体、应用状态区、设置恢复及背景采样 |
| Windows Monkey 断点与宽窄/字号关联 | 10 passed；背景测试 Windows、offscreen、设置 1.5 倍缩放环境参数的组分别 2 passed；最后一组日志未单独记录实际 DPR |
| 最终离屏主窗口、启动及关闭集成 | 155 passed、1 个原生 Windows 插件专属 skip；sessionfinish 与实际进程退出均为 0，该跳过节点已由 Windows 集成通过 |

表中不同集合可能包含相同节点，不把累计次数当作唯一测试数量。除明确的失败复现、旧条件
对照及列出的平台跳过外，验收组均同时核对测试结果和进程退出；收集命令或诊断脚本自身错误
不计为产品通过或新产品缺陷。既有第三方弃用警告未隐藏。

最终集成使用 `-q`，节点为：

```text
tests/test_main_window_layout.py
tests/test_model_mainframe.py::test_main_frame_init_defers_adb_bootstrap_until_ui_is_built
tests/test_model_mainframe.py::test_main_frame_signal_maps_keep_expected_coverage
tests/test_mainframe_startup.py
tests/test_adb_client_refresh.py::test_parent_shutdown_cancels_client_probe_and_rejects_late_restart
tests/test_adb_client_refresh.py::test_parent_destruction_cancels_probe_without_child_close_event
tests/test_phase2_mainframe_shutdown_gate.py::test_mainframe_two_stage_close_is_nonblocking_broadcast_first_and_idempotent
tests/test_phase2_mainframe_shutdown_gate.py::test_application_shutdown_releases_live_logcat_feature_session
```

本轮 21 个 Python 文件 Ruff、8 个生产文件中文注释检查通过。Pyright 保持仓库原规则，仅用临时
配置补齐实际解释器 sys.path，5 个 APK/关闭模块与 3 个 UI 模块均为 0 errors、0 warnings。
源文本检查覆盖 833 个文件，87 个项目知识文档的链接/frontmatter 检查通过；`git diff --check`
退出 0，仅报告前置文件的 LF/CRLF 提示。UI、APK 关闭、Qt 清理、Windows 断言四份独立审阅
均未发现剩余 Critical / Important 问题；Qt 清理审阅中发现的自动删除和部分启动问题已补回归
修复并复核。本轮相对 767 个前置路径改动 24 个既有文件、新增 3 个文件，其余前置路径哈希
不变，没有删除既有文件。

证据、原始输出、审阅报告、模块哈希及相对本轮前置脏树的差异保存在忽略目录
`.superpowers/sdd/2026-10-24-ui-stability/`；没有以相对 HEAD 的全部重构差异充当本轮修改。

## 验证边界

未触发全量 pytest、完整 PyInstaller 构建或正式发布；本轮不改变资源收集、运行依赖或数据协议。
Windows 插件自动化覆盖真实 Qt 几何及渲染，仍不替代不同显示器/DPI、真实系统 APK 文件框、
Android 安装与设备断线、打包产物长时间运行的人工验收。建议人工检查大字号窄窗口、设置展开
恢复，以及文件框打开期间退出应用；不在未授权设备上执行安装。
