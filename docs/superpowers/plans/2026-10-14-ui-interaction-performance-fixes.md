# UI 交互与显示适配修复实施计划

> 执行方式：按 `superpowers:subagent-driven-development` 分工实施，并在合并检查后完成回归。

**目标：** 按用户后续明确范围，只修复投屏侧栏、实时 Logcat、主导航字体、应用管理和设置页面，
保留主题、业务交互、设备归属和用户配置格式。

**架构：** 沿用 PySide6 控件与页面控制器。列表和日志用 GUI 事件循环中的有界批次提交，
不在后台线程修改控件，不通过 `processEvents()` 重入回填。布局只在相关字体或宽度变化时更新。

**依据：** 本会话 2026-10-14 的只读审计及用户“安排实现一下上面的修复”的授权。

## 实施和验证边界

- 在当前开发分支修改，不提交、推送、改版本或新增依赖；不连接实际设备。
- 先补回归并确认原实现失败，再修复；直接测试通过后只扩展关联消费方。
- Windows 工具窗用原生命中验证，不以 Qt 直接投递鼠标事件代替。
- 分批提交须覆盖新请求替换、过滤变化、隐藏恢复、关闭、选择及阅读位置保持。
- 字体更新须通过真实字体设置路径，覆盖 12/22 pt、窄窗及导航展开收起。

## 任务

- [x] 投屏侧栏：修正云母透明表面的输入命中，保留原生材质、非激活与焦点行为。
  修改 `remote_toolbar.py`，沿用 `remote_toolbar_material.py`；验证材质、按钮、原生窗口测试。
- [x] 主导航：普通导航项同步字体并保持布局可读。
  修改 `main_frame.py` 及必要的局部导航组件；验证 `test_main_window_layout.py`。
- [x] 应用列表：长列表分批提交，保留排序、筛选、选择、请求代次和清理语义。
  修改应用页面控制器；新增事件循环让出与取消回归，再测合成 1k/10k 项。
- [x] Logcat：积压与过滤重建分批提交，保留缓冲上限、阅读位置、跟随及换行语义。
  修改 Logcat 控制器；覆盖清空、过滤、启停、隐藏恢复和关闭的交错顺序。
- [x] 设置：同宽纯高度变化跳过整页重排；保留文案、字体、主题与展开高度刷新。
  修改 `fluent_pages.py`；验证设置字体、重排效率与展开动画。
- [x] 集成：审阅差异、运行修改文件 Lint/类型/注释检查和关联 Qt 测试，更新 UI 知识库与
  已闭环风险条目，记录实际验证范围及未验证的设备/实屏边界。

## 执行记录

- 起始工作树干净；页面任务按文件边界并行，公共测试登记与知识库由主任务维护。
- 用户收窄为以上五项；文件管理、设备概览及最大化窗口问题不在本轮修改范围。
- 新增回归先复现旧实现失败；独立复审发现动画中途换字号仍会被旧终点覆盖，补失败回归后
  改为更新展开动画终点，收起终点保持紧凑宽度。最终复审未发现新的可确认问题。

## 验证记录

使用仓库 `.venv`，GUI 行为组使用 `QT_QPA_PLATFORM=offscreen`，原生命中组使用 Windows 插件。
分组结果独立记录，不把重复跑过的节点累加成总覆盖数。

| 范围 | 实际结果 |
| --- | --- |
| 投屏侧栏直接与关联组 | 158 passed；增加状态绘制断言后，材质文件另行 17 passed |
| Windows 侧栏与跟随原生组 | 10 passed、1 skipped（前台窗口条件不可用）；150% 和 200% 命中各 2 passed |
| 应用列表及关联 11 文件 | 168 passed |
| Logcat 最终 7 文件 | 214 passed，含新增 14 例 |
| 设置、主窗口及导航绘制 5 文件 | 264 passed、3 skipped（离屏无 Windows 窗口断点/DWM）、4 个既有失败 |
| 150% / 200% 导航字体与设置新增回归 | 每种缩放 6 passed；覆盖字体 8/12/22 pt、长名称、动画中换字号及同宽高度变化 |
| 修改 Python 的 Ruff、生产代码中文注释、Pyright | 通过；Pyright 0 errors / 0 warnings，临时配置补充解释器实际系统依赖路径，未修改仓库规则或依赖 |
| 知识库链接/frontmatter、diff 空白检查 | 通过 |

既有失败为 `test_navigation_menu_uses_real_acrylic_blur` 的 4 种主题/云母组合。以 `git show
HEAD:gui/main_frame.py` 的原实现加载到独立测试进程，仍复现相同 4 例：现有生产策略关闭导航重复
亚克力模糊，而测试要求生成模糊图像。本轮未改该策略或放宽测试，已登记为风险账本 UI-08。

关联测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_manager_selection.py tests/test_app_manager_metadata.py tests/test_app_manager_icons.py tests/test_app_manager_icon_lifecycle.py tests/test_app_manager_visible_scan.py tests/test_app_manager_column_fill.py tests/test_app_manager_header_sort.py tests/test_app_manager_population.py tests/test_app_manager_visual.py tests/test_app_list_updates.py tests/test_app_detail_updates.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_live_logcat_feedback.py tests/test_live_logcat_empty_state.py tests/test_live_logcat_visual.py tests/test_live_logcat_material.py tests/test_phase2_live_logcat_gate.py tests/test_model_meta.py tests/test_live_logcat_render_batches.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_settings_reflow_efficiency.py tests/test_settings_typography.py tests/test_settings_expand_animation.py tests/test_main_window_layout.py tests/test_navigation_rendering.py
```

## 合成负载与限制

- 应用 1000 项：原一次 UI 构建约 125 ms，分批后最长约 6.3 ms。万项探针仍出现约 22–30 ms
  单片停顿，对应 Python 第 2 代垃圾回收；未通过关闭全局 GC 隐藏该开销。
- Logcat 8000 行、每行约 225 字符，独占进程各测 3 次：追加旧 65.8–67.6 ms，现每片最大
  7.6–8.2 ms；筛选旧 71.5–73.2 ms，现每片最大 11.1–11.6 ms。两类总耗时约 195–212 ms。
- 每行约 1045 字符时，追加片段最大 21.5–21.8 ms，筛选片段最大 22.6–23.5 ms，均保留完整
  8000 行，总耗时约 567–617 ms。连续阻塞减少，但总完成时间增加，不能宣称稳定达到高刷帧率。
- 未使用真实设备验证投屏拖动或真实跨屏刷新率；原生测试只证明合成工具窗的命中、缩放和既有
  窗口跟随契约。真实设备日志负载、用户屏幕上的动画观感仍需实际运行观察。
- 本轮未触发全量测试或打包验收，没有修改版本、CI、依赖，也没有提交或推送。
