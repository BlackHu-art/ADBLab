# 性能采集页面、方案操作与进度显示验收

日期：2026-09-06。本轮范围为性能页排布、方案按钮、共享同步弹窗生命周期及执行状态显示。
已有测试结果库、Monkey、日志过滤、云母等未提交成果均保留，不重新计入本轮修改范围。

最终状态：方案操作、布局、进度与退出验证完成。原生堆异常已通过独立图标复制复现和新回归的修复前失败／修复后通过验证闭环，未禁用 GC 或屏蔽异常。

## 确认的问题及处理

1. 用户的 `LineEdit already deleted` / `FluentInputDialog already deleted`：启用 Qt 自动删除策略后，真实确认、取消、Esc 与消息框关闭均可重现。
   同步入口在 `exec()` 前明确关闭 `WA_DeleteOnClose`，取值后由 `finally` 单一延迟释放。
2. 保存方案把仅 34 像素高的方案栏作为蒙层父级：实际弹窗为 698×34，内容被裁切。
   保存及错误提示改为所属窗口作父级，实际 720×520 的窗口范围完整容纳输入卡片。
3. 空方案下拉只有占位项：现在显示“暂无方案，请先保存”，禁用无内容的下拉、载入、删除，保留保存入口。
4. 性能配置与日志在两侧窄卡片内强制等高：改为状态、采集计划、日志与图表的全宽纵向顺序；方案单独一行，包名与常用时间参数在宽屏对齐，窄屏重排。
5. 旧 `ProgressBar` 只绘制 4 像素轨道，不绘制设置的百分比文本：参考本地 PySide6 分支的 Fluent Widgets 示例，使用带百分比的 `ProgressRing` 与单独的 `IndeterminateProgressRing`。
6. 时间估算在报告确认前最多 99%；到达计划时长后显示等待。主动停止有独立终态并保留附件；正常退出且报告确认后才完成，启动错误显示失败，停止失败仍可重试。
7. 状态图标原来使用 `QIcon(SvgIconEngine)` 定色，其复制／分离后绘制或释放可触发原生异常。异常栈确认到 `QIcon::~QIcon → QIconEngine::~QIcon → free`，不创建页面的独立 QIcon 复制探针也复现。改为 `IconWidget` 直接绘制 `ColoredFluentIcon`，保留状态颜色并避开 Python SVG engine 的 QIcon 所有权路径。新回归循环五种状态，真实绘制后复制、分离、再绘制和 GC；只恢复旧图标赋值的临时进程在此节点中止，修复后的正式实现通过。没有修改安装依赖，也没有禁用 GC、跳过有效测试或伪造退出成功。
8. 日志／图表使用两个等宽 Fluent 切换按钮，互斥选择、程序切换同步、键盘焦点与无障碍描述均保留。此前替换 SegmentedWidget 一度改变异常复现，但后续证据排除了它是根因；保留双按钮属于本次界面交互设计。

参考路径：`reference/PyQt-Fluent-Widgets/examples/gallery/app/view/status_info_interface.py`。
生产使用现有 `.venv` 依赖，没有修改参考项目或安装包，没有新增生产依赖。

## 已完成的功能验证

所有命令使用 `.venv\Scripts\python.exe`。离屏测试使用 `QT_QPA_PLATFORM=offscreen`，外部设备/命令均使用替身，方案库与设置隔离。

| 范围 | 实际结果 |
| --- | --- |
| 原性能响应式基线 | 35 passed |
| 原性能进度/状态/停止直接基线 | 8 passed，14 deselected |
| 共享弹窗、方案、性能与 Monkey 关联 | 93 passed，4 deselected |
| 最后空态、诊断列表真实存储重载、Monkey 宽窄大字号 | 15 passed，27 deselected |
| 正常 Windows 平台真实方案输入/按钮/自动删除策略 | 9 passed，25 deselected |
| 性能运行控制与关闭屏障 | 24 passed，12 deselected |
| 最终性能布局、大字号及实际日志/图表点击、键盘、双向同步、释放 | 46 passed，16.67s，退出码 0 |
| 最终进度状态、图标复制回收、隐藏页动画、阅读表面与全导航材质集成 | 26 passed，11.90s，退出码 0 |
| 正式图标修复后 Windows 原生平台原失败组合 | 11 passed，33 deselected，6.28s，退出码 0 |
| 稳定最小两个正式页面用例，每例清理后 GC | 2 passed，退出码 0 |
| 初轮三语言与业务页英文 | 29 passed |
| 最后补入空态词条后的资源/占位符/英文复验 | 4 passed |
| 源码 `main.py --self-check packaging` | 全部检查通过 |

不同组包含重复节点，不相加作为唯一用例总数。三语言分别新增 11 个词条，原有 1306 条保留；最终各 1317 finished、0 unfinished。

主要可复查命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_fluent_dialog_contract.py tests/test_run_library_ui.py tests/test_performance_library.py tests/test_monkey_library.py -k 'not scheme_bar_and_maximum_seed_fit_supported_viewports'
.\.venv\Scripts\python.exe -m pytest -q tests/test_model_performance_launcher.py tests/test_phase2_mainframe_shutdown_gate.py -k performance
.\.venv\Scripts\python.exe -X faulthandler -m pytest -q tests/test_performance_responsive.py tests/test_feature_typography.py::test_loaded_feature_pages_refresh_fonts_and_text_constraints tests/test_feature_typography.py::test_performance_large_font_keeps_bounded_scrollable_content
.\.venv\Scripts\python.exe -X faulthandler -m pytest -q tests/test_performance_progress.py tests/test_reading_surface.py tests/test_navigation_rendering.py::test_all_navigation_pages_share_material_without_covering_reading_controls
$env:QT_QPA_PLATFORM = 'windows'
.\.venv\Scripts\python.exe -m pytest -q tests/test_fluent_dialog_contract.py tests/test_run_library_ui.py -k 'upstream_auto_delete or real_save or empty_preset'
.\.venv\Scripts\python.exe -X faulthandler -m pytest -q tests/test_performance_responsive.py -k 'cards_reflow_without or large_font_running_summary'
.\.venv\Scripts\python.exe main.py --self-check packaging
```

## 验证边界

方案操作使用真实 Qt 按钮和 `exec/done` 流程，保存使用隔离 JSON 文件；确认、取消、同名更新、删除最后一个方案与仅回填不启动均有覆盖。
共享输入框关联的新建文件/目录/重命名保留真实输入步骤，外部命令为替身。
实际 Android 性能采集和报告内容未在本轮运行；没有全量 pytest、PyInstaller 构建或正式发布。
正常 Windows 输入框截图位于 `../preset-fix-20260906/preset-dialog-after.png`；布局截图使用合成设备，未读取用户方案或抓取其他应用。

## 最终静态与视觉检查

本轮 13 个 Python 文件 Ruff 全部通过；6 个生产模块 Pyright 为 0 errors、0 warnings；生产中文注释检查通过；此前文档检查 30 篇通过；最终 `git diff --check` 退出码 0。未改动上游安装包、生产依赖或版本，也没有提交任何已有未提交修改。

真实 Qt 控件按 4 个条件分别渲染：浅色 1360×900 默认字号，深色 860×700 22 号运行状态，英文 1100×800 125% 缩放运行状态，深色 860×700 22 号 150% 缩放展开全部选项。各次进程退出码 0，布局探针 `horizontal_max=0`、`errors=[]`。已检查主表单、长状态文字、实际环形百分比、结果切换和底部动作；大字号内容通过宿主滚动到达。

可查看：

- `performance-frame-light-1360x900-font12-zh_CN-dpi1.png`
- `performance-frame-dark-860x700-font22-zh_CN-dpi1-running.png`
- `performance-frame-light-1100x800-font12-en_US-dpi1.25-running.png`
- `performance-results-light-1360x900-font12-zh_CN-dpi1.png`
- `performance-results-dark-860x700-font22-zh_CN-dpi1.5-expanded.png`

最终完整布局输出为 `../preset-fix-20260906/production-icon-fix-46.txt`，稳定最小复现修复后输出为同目录 `production-icon-fix-first2gc.txt`。同目录 `status-icon-regression-before-red.txt` 是只恢复旧图标赋值后，新增回归在副本绘制处中止的失败证据。

此前 `windows-cards-reflow-running-summary-native.log/json` 是修复前失败证据，不应当作最终通过日志。图标修复后同一 Windows 命令的工具执行结果为 11 passed、进程退出码 0；本轮进度/主题最终组合为 26 passed、进程退出码 0。完整原生检测栈保存在 `native-heap-stack-focus-late.txt`，不含联网符号或生产用户数据。

测试仍会报告现有 Fluent/无边框组件使用 Qt 弃用 API 的 DeprecationWarning；本轮未升级依赖，也未屏蔽这些警告。
