# 任务中心单页实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 按用户确认的设计稿实现统一紧凑列表与行内展开详情，适配主题、字号和窄窗口。

**Architecture:** 页面投影既有 Operation、ActionResult 和 RunLibrary 快照，保留来源身份及原执行器。
表头和记录共用列宽预算；同身份行原位更新。正文和归档详情复用既有阅读器；通知经页面入口定位。

**Tech Stack:** Python 3.11、PySide6、项目已安装的 qfluentwidgets。

**Spec:** 用户确认的 task-center-single-page.html 交互设计（本会话设计稿）。

## Global Constraints

- 当前 ui-design 工作区实施，不创建分支，不提交或推送。
- 单页，无分类分页、详情跳转和常驻底部消息区；搜索、类型、状态筛选作用于同一列表。
- 本次操作与已归档行明确标识；保留原存储格式、容量及任务执行/资源生命周期。
- 只按明确身份关联不同来源，不按标题、设备或相近时间推测；Operation 单调时间不当作日期。
- 主题、字体变化不重建正在阅读的控件；无页面横向滚动；按钮和表头上下对齐。
- 取消仍走 manager 与 stop_hook；确认资源退出前显示正在取消，不伪造终态。
- 复制、全文搜索、导出、附件后台核验和载入参数的原语义保持。

## Review Focus

- 后台完成、新请求或归档刷新不能抢占阅读、选区、文件目标及滚动位置。
- 最小窗口和 22pt 字号时标题省略、筛选换行、详情按钮可达，表头与行共用列宽。
- 通知定位旧请求时清除阻挡它的筛选并展开正确记录，不触发执行。
- 取消失败、重复点击、隐藏与关闭均有明确状态和定时器清理。
- 记录说明的异常级别来自子项；时间和持久化标签来自真实来源。

### Task 1: 阅读器行内模式

**Files:** gui/widgets/action_result_view.py、gui/widgets/run_results.py、tests/test_task_inline_readers.py。

**Interfaces:** ActionResultView(inline=True)、records_snapshot()、selection_changed(str)；
RunResultsWidget(detail_only=True)、present_record(RunRecord | None)。默认模式保持。

- [x] 既有阅读器测试建立基线。
- [x] 新测试先失败：行内记录不抢选、无历史导航、无自动展开；归档只显示显式传入记录。
- [x] 实现可复用模式，直接及关联测试通过。

### Task 2: 统一列表与任务路由

**Files:** gui/pages/tasks_page.py、gui/widgets/task_table.py、gui/action_feedback.py；对应任务中心测试。

**Interfaces:** TaskCenterPage.select_request(str)；present_action_result/refresh/shutdown 和 run_results 保留。

- [x] 新测试先失败：同表筛选、行内展开、取消、对齐、主题、字体、阅读保护与通知定位。
- [x] 实现共享列宽行、单个详情宿主、稳定更新及条件筛选。
- [x] 更新旧 UI 结构断言，保留其取消、字体可达性和生命周期验收意图。
- [x] 运行任务中心直接测试；因通知导航与阅读器接线变化，扩大到 action_feedback、run_results 和相关主窗口测试。

### Task 3: 文档与集成验证

**Files:** docs/guides/OPERATION_RESULTS.md、docs/project-knowledge/BUSINESS_FLOW.md。

- [x] 更新单页行为描述，不改变容量和持久化事实。
- [x] 检查修改文件 Ruff、相关生产路径 Pyright、中文注释、文档链接与 diff。
- [x] 独立审阅本轮差异；针对问题补回归并修复；离屏渲染检查明暗主题和窄宽布局。

## 实施记录

- 初始工作树干净，分支 ui-design；复用现有 checkout，依赖已安装。
- 任务 1 委派给 task_ui_audit；主任务负责统一页面、表格、接线与集成。


### 验证与交付边界

- 初始直接基线：离屏 16 passed；真实 macOS 主窗口需使用 cocoa，原生布局基线 3 passed。
  offscreen 无边框 MainFrame 初始化崩溃来自既有 qframelesswindow 的 macOS 原生调用；不修改全局夹具。
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_task_center_unified.py tests/test_task_table.py tests/test_task_inline_readers.py tests/test_ui_incremental_updates.py tests/test_action_results.py tests/test_run_results.py tests/test_task_history.py tests/test_model_shutdown_admission.py tests/test_phase1_operations.py tests/test_i18n.py`：222 passed。
- `QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_action_feedback.py tests/test_shell_workflows.py`：73 passed。
- 最终原生布局关联验证：任务中心、行内宿主、结果展示、英文任务翻译与主窗口结果相关节点，26 passed。
- 独立审阅的问题已补回归并修复：归档不完整语义、逐设备取消/注意状态、兼容历史稳定序号、取消后 Operation 先移除而 ActionResult 晚到、收起后的辅助名称。
- 字体 12→22→12、窄宽与明暗主题、三语言和精确通知定位均有自动化覆盖；另检查 1100px 和 420px 的离屏渲染。
- 修改 Python 文件 Ruff、八个相关生产模块 Pyright、中文注释检查、文档链接及 diff 检查通过。
- 三语言词库按现有 lrelease/rcc zlib 流程重建；`QT_QPA_PLATFORM=offscreen .venv/bin/python main.py --self-check packaging` 通过。
- 未触发全量测试或正式打包；没有新增依赖、数据迁移、版本调整、提交或推送。Windows 原生外观与云母效果仍需实机核对。

### 后续间距与动效复核

- 用户澄清本轮要改下拉弹出和蓝色候选标记的滑动效果，并非滚轮失效；不改变原生滚动语义。
- 任务中心顶部留白 8px → 4px，筛选／计数／表格间距 12px → 6px，表头内距 6px → 4px；
  由直接几何回归覆盖明暗主题、360／900px、12／22pt。
- 修复真实操作目录中 Monkey 启停的类型归属，避免进行中的记录被 Monkey 筛选排除。
- 参数下拉工厂安装每菜单独占的动效适配器；保留普通／材质及自定义工厂、业务确认和焦点守卫。
  弹出沿用 250ms OutQuad 方向和终点，蓝条使用 180ms OutQuad；首个可见帧后推进，关闭停止。
- macOS 原生合成窗口确认弹出及键盘候选存在中间帧，预览候选不提交组合框值；
  独立审阅及探针覆盖首帧前销毁宿主、同菜单隐藏重开、无默认项、禁用项和滚动。

- 本轮离屏关联验证：`tests/test_combo_menu_motion.py tests/test_combo_menu_material.py tests/test_preset_spin_box.py tests/test_adaptive_navigation.py tests/test_task_center_spacing.py tests/test_task_center_module_effects.py tests/test_task_table.py tests/test_task_inline_readers.py tests/test_run_results_host.py` 共 73 passed；`tests/test_dropdown_material.py -k 'not settings_dropdown'` 共 24 passed。
- 新增动效测试在 cocoa 与 offscreen 各 11 passed。原生悬停通过弹层 QWindow 发送真实指针移动，等待实际 itemEntered 后验证中间帧，未手动伪造悬停或放宽选择断言。
- 原生设置下拉的宿主材质回归 `tests/test_dropdown_material.py -k settings_dropdown` 共 2 passed。
- Cocoa 原有材质样本测试的 QWidget 模拟悬停及首窗即点存在既有输入时序问题；临时禁用本轮适配器仍可复现。保持旧断言不变，材质像素与普通输入状态在默认离屏模式验证，原生动效使用上述 QWindow 输入覆盖。
- 本轮未新增生产依赖、持久化、资源或版本变化；上一轮已验证的其余脏工作树不重新纳入全量范围。Windows 原生观感仍需实机核对。
- 最终原生关联组合：`QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_combo_menu_motion.py tests/test_task_center.py tests/test_action_result_presentation.py`，30 passed；本轮修改文件 Ruff、四个生产模块 Pyright、中文注释、文档链接与 diff 检查通过。

### 筛选按钮与弹层宽度复核

- 截图问题由按钮按当前文案、菜单按最长选项的不同尺寸规则造成；另有中英文候选高度差与布局模式缓存未更新实际宽度的问题。
- 8 项状态均有生产来源，保留全部筛选；`partial` 显示简化为“部分完成”（英文 Partial），悬停及辅助说明保留“部分成功 / 结果不完整”，逐行精确状态不变。
- 两个任务筛选器局部复用 ElidingComboBox，不修改全局组合框。自然尺寸取全部翻译选项的按钮样式、48px 箭头预留及 Fluent 弹层字体/内容边界的最大值，搜索与两按钮共用高度。
- 每次缩放先落实宽度封顶再处理排布缓存；窄窗先换行，未封顶时完整显示文案，切换选项不改变按钮或搜索框几何。只对可见菜单面板验证对齐，保留原阴影留白。
- 回归先确认选择后尺寸跳动、完整文字被意外省略与 Cocoa 低 DPI 的弹层字体尺寸差，再验证修复。三语言×12/22pt、220–700px、字号往返、业务值不变及弹层对齐已覆盖。
- `QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_task_filter_sizing.py` 与 offscreen 同文件各 13 passed；原生主窗口大字号取消与窄窗附件节点另 4 passed。
- 三语言词库按现有 lrelease/rcc zlib 流程重建，旧组合说明保留；`main.py --self-check packaging` 通过。未新增依赖、迁移、版本、提交或推送。

### 顶部对齐与启动首帧复核

- 按真实设备概览、普通工作区及设置页核对，任务中心顶部恢复为统一的 8px，左右仍为 32px；内部 6px 节奏和筛选尺寸策略不变。
- Cocoa 首帧探针确认主窗先按 48px 折叠导航绘制，随后导航才占用 220px，首页卡片也沿用旧宽度。`showEvent()` 现在先提交导航宽度，再复用切页的响应式收敛入口；不增加交接等待时间。
- 新回归先确认失败，再覆盖同步／分段启动、860／1000／1120／1280px、12／22pt 和明暗主题；记录首页实际 Paint，严格比较首帧至稳定后的几何与滚动范围，共 10 组通过。
- `test_task_center_spacing.py` 以真实设备概览工具栏作对齐基准，与 `test_task_filter_sizing.py` 合计 21 项离屏通过；首页横幅的直接关联节点另 6 项通过。
- 启动、中断清理、屏幕绑定和页面过渡关联集先得到 99 passed、5 failed；运行期临时恢复旧 `showEvent()` 后，相同 5 项仍失败。4 项取样落入正在淡入的无设备卡片，已改到真实留白并保留严格像素断言；另一项用切页返回后的高度总和代替首帧，已改为真实 Paint 的控件身份、完整几何和逐祖先裁剪矩形比较。
- 最终原生增量验证：`test_home_first_paint_uses_final_navigation_and_card_geometry` 原 8 组加 `test_routes_keep_final_geometry_through_shared_content_transition` 共 12 passed；7 条功能路由的 `test_first_visible_frame_already_uses_final_responsive_layout` 加新增 1120px 启动组合共 9 passed。没有为系统概览额外增加生产布局轮次。
- Ruff、相关生产模块 Pyright、中文注释、文档链接、`git diff --check` 和源码 packaging self-check 通过。未触发全量、未运行 Windows 实机、未提交或推送。

### 任务中心标题与分层空态

- 任务路由隐藏设备栏，而 GalleryPage 只有无障碍名称，导致缺少可见标题。TaskCenterPage 现增加自身固定页头，沿用设备页头 FontRole.TITLE、左右 32px 和顶部 12px；下方正文仍保留 8px 起点，不改全局设备栏准入。
- 空态参考 Logcat 的图标、标题和次级说明层级，复用既有 Fluent 控件。无记录与筛选无匹配仍分别由 `_entries` 和可见行判断；无行时隐藏整张空表，保留搜索、筛选与计数，筛选无匹配时提供清除筛选并回到搜索输入。
- 清除筛选只合并提交一次视图刷新，不取消任务或改变设备选择。操作、活动 Operation、归档及历史来源链，未读、详情、通知定位与隐藏停表契约保持不变。
- 回归先确认标题和分层空态缺失。实际渲染又发现居中标签限宽时的换行裁切，新增实际文字边界失败断言后，改为透明居中文字组，标签铺满组宽，按真实宽度自然计算行高；短窗口由既有滚动区承接。
- 三份 TS 各新增 5 条文案，既有内容逐字节保留；三份 QM 均为 2010 finished、0 unfinished，RCC 使用既有 zlib 配置。内嵌全部 6030 条翻译和格式参数核对通过。
- 最终离屏命令：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_task_center_empty_state.py tests/test_task_center_spacing.py tests/test_task_filter_sizing.py tests/test_task_center_unified.py tests/test_task_center_module_effects.py tests/test_task_table.py tests/test_i18n.py tests/test_task_center.py::test_existing_task_rows_follow_font_round_trip_without_rebuilding`，138 passed。
- 原生任务页及大字详情关联集 13 passed；换行修复后的最终原生命令：`QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_task_center_empty_state.py tests/test_task_center.py::test_task_route_shows_one_title_without_device_controls`，14 passed，覆盖明暗、宽窄、三语言、字号往返、按钮可达与真实主窗标题。深浅空态、英文大字筛选空态和有记录列表均已渲染检查。
- 修改文件 Ruff、TaskCenterPage Pyright、中文注释、文档链接、diff 检查及源码 packaging self-check 通过。未跑全量和 Windows 实机，未新增依赖、版本、提交或推送。

### 未选择设备空态移除底板

- 已核对全部功能注册：文件管理 `devices/files`、应用管理 `apps/manager`、实时 Logcat `system/logcat`、性能采集 `system/performance` 会进入共用 `_NoDevicePage`，其余当前入口不要求设备，不会展示该底板。
- 仅将 `_NoDevicePage.card` 从 MaterialCard 改为不填充背景的 QWidget，保留字段、父子关系、居中布局、24px 内距、字体刷新、按钮和信号。关闭提示与业务卡片仍使用各自材质；未改变会话准入和设备操作。
- 原材质回归由“要求叠加白底”迁移为真实空白区域像素严格等于共享内容面，并覆盖四路由、明暗主题、无设备／候选未选及云母往返。先确认原代码像素失败，再验证修复后 8 个组合通过：`QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_card_material.py::test_no_device_pages_leave_shared_surface_uncovered`。
- 离屏直接与恢复检查 12 passed：`tests/test_workspace_device_recovery.py`，以及 `test_workspace_feature_host.py` 的 `test_small_workspace_state_messages_wrap_without_clipping`、`test_workspace_state_pages_follow_font_round_trip_and_keep_actions_reachable`、`test_workspace_host_uses_inline_lazy_device_sessions`、`test_no_device_page_retains_route_payload_for_resume`。
- 原生关联运行设置／展开卡、共享内容面、路由动画、设备概览入口和两种翻译空态，共 16 passed、2 failed。临时在内存恢复旧容器后，浅色设置卡像素用例仍相同失败；悬停用例在旧容器对照与现代码单独复核均通过，现代码离屏也通过。本轮没有改动这两项既有断言或全局卡片材质。
- 性能采集空态已分别生成并核对深浅主题原生主窗截图；标题、说明、设备按钮和页面边界完整。Ruff、workspace_features Pyright、中文注释、文档链接和 diff 检查通过。
- 本轮只触及界面容器，无入口、资源、依赖或打包边界变更；不重复此前打包自检，不触发全量。Windows 原生云母未实机验证，未提交或推送。

### 浅色材质失败用例定位与修正

- 已在当前代码复现 `test_settings_and_about_cards_follow_actual_host_material[Light]` 失败。根因是测试以“请求开启云母”的循环变量选择 alpha64，而已安装 FluentWindow 在 macOS 直接拒绝该请求，实际状态仍为 False；此时原生设置卡使用 alpha170 是正确行为。深色两条路径均为 alpha13，因此旧深色组合没有暴露此预期错误。
- 独立组件及 Cocoa 实际主窗探针均确认：浅色实色共享面 `#f7f9fc` 上的卡片为 `#fcfdfe`，单卡 render 与整窗 grab 完全一致；真实关闭材质没有重复绘制或误叠色。受控实际开启时得到旧用例期待的 `#f9fbfd`。本轮没有修改生产材质代码或其他既有设置／关于页面改动。
- 修正原回归按 `frame.isMicaEffectEnabled()` 计算期望，保留全部设置、关于及折叠标题卡的精确像素断言；增加真实可见保存目录卡片的整窗合成取样。新增 native／supported／refused × Light／Dark，受控组合只替换平台能力入口，另强断言实际开关状态，防止永远关闭也通过。
- 直接验证：`QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_card_material.py::test_settings_and_about_cards_follow_actual_host_material`，6 passed；实际主窗取样探针另 2 passed。
- 原生关联命令：`QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest -q tests/test_card_material.py tests/test_navigation_rendering.py::test_unsupported_mica_request_keeps_opaque_surfaces -k 'not settings_and_about_cards and not material_card_keeps_hover'`，11 passed。普通卡悬停与重挂节点使用既有适合 QWidget 模拟输入的 offscreen 平台，1 passed；合计 18 项材质回归通过。
- 修改测试 Ruff、文档链接及 diff 检查通过；独立审阅确认平台 mock 作用域与严格断言保持。本轮仅修改回归及验证记录，不需要生产模块 Pyright、注释检查、资源打包或全量重跑；Windows DWM 实机效果仍未验证，未提交或推送。
