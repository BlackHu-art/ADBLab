# 设备选择区展开动画实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 执行；当前会话已经授权实施与验证，不提交或推送。

**Goal:** 让既有设备选择区展开、收起平滑，保留设备操作、五行高度与共享材质。

**Architecture:** 在 DevicePicker 外增加透明裁剪容器，内部内容保持自然高度，单个 Qt 动画驱动可见高度和箭头。展开意图独立于动画可见性；宿主快照批量同步，避免反复布局。

**Tech Stack:** Python 3.11、PySide6、现有 qfluentwidgets、pytest 离屏 Qt。

**Spec:** 本会话已确认的五项方案：约 200 ms 过渡、稳定内容、同步按钮反馈、退出清理、合并布局计算。

## 修改范围与约束

- 首版生产修改限于 `gui/widgets/device_context_bar.py`；后续卡顿修复范围见下文。不改变 ADB、设备选择真源、会话及后台任务。
- 不新增依赖、全局配置或页面入口；保留五行及短窗口 45% 上限。
- 云母使用现有父级材质；不增加背景色、截图淡入或透明度效果。
- 快速点击从当前高度反向；切页和窗口隐藏立即完成收起。
- 字体、明暗主题、键盘及鼠标焦点规则不变。

## 执行与验证

- [x] 在 `tests/test_device_selector_animation.py` 补中间帧、反向点击、焦点、隐藏和尺寸变化回归，确认原实现失败。
- [x] 实现透明裁剪、展开意图、统一动画时钟及快照合并；迁移既有测试对最终几何的等待。
- [x] 先运行新测试和 `test_inline_device_selector.py`、`test_device_operation_selector.py`。
- [x] 关联主窗口设备路由及远程控制集成，检查主题、字体和正文重排；仅按实际失败扩大范围。
- [x] 同步 `docs/guides/OPERATION_RESULTS.md` 的展开交互，运行修改文件 Ruff、类型检查、中文注释、文档链接与 diff 检查。

## 审查重点

- 收起中重新展开不能被旧完成回调隐藏。
- 不允许 Tab 或点击操作收起中的设备行。
- 字号和短窗口变化更新目标高度，不将动画中间值作为自然高度。
- 关闭或切页不留下动画、可见残片或后续布局回调。
- 主窗口正文每帧 resize 的成本需要实际 Qt 页面诊断，不能仅依靠独立容器测试。

## 本轮验证记录

- 原实现的动画回归 4 项失败，均复现正文直接跳变；实现后通过。
- 新增鼠标焦点回归先复现过渡中跳到最终高度，再限定键盘焦点提前完成展开。
- 最终直接集合：`test_device_selector_animation.py`、`test_inline_device_selector.py`、
  `test_device_operation_selector.py` 共 61 passed；150% 与 200% 下新动画集各 11 passed。
- 上述直接集合在焦点细化前，与 `test_remote_selector_integration.py`、
  `test_global_device_context.py` 合并运行 198 passed；其中关联路由 139 项。
  最后两项焦点用例及对应局部调整已由最终 61 项直接集合重新验证，没有重跑无关路由。
- Windows 原生平台的云母属性与主题切页 6 passed；主窗口远程控制和应用工具的明暗、
  字号诊断 4 passed。视觉探针使用隔离设置，设备和服务为替身。
- 同条件两设备探针：再次展开的高度及列宽同步各由 7 次降至 1 次；内部列表高度保持不变。
- Ruff、相关模块 Pyright、中文注释检查通过。未改变设备命令或打包边界，未执行实机操作或打包。

## 卡顿反馈后的修复与验证

首版只确认了展开过程与最终几何，没有充分度量主窗口的逐帧响应式规划。收到实际卡顿反馈后，
使用隔离设置、替身设备的真实 MainFrame 测量，确认每次高度变化都会触发顶层 LayoutRequest，
进而递归规划 Remote 内层网格。一次展开的规划累计约 213 ms，动画仅推进 6 次，耗时约 283 ms。

修复边界：

- DeviceContextBar 成对通知过渡开始/完成；MainFrame 转交 SidePanel，组件不直接依赖业务面板。
- ResponsiveCoordinator 暂存过渡期间和此前已排队的请求，结束后按最终几何统一收敛；保留真实
  宽度、字体、主题和屏幕变更。同步 settle 不能绕过暂停，旧排队/收尾回调不能覆盖新状态。
- SidePanel 的三个预留纵向滚动条的 viewport 跳过纯高度变化，避免昂贵的横向几何检查。
- 快速反向维持同一暂停边界；键盘提前进入、隐藏、切页与关闭均释放边界。
  CloseController 在停止面板计时器之前结束设备栏动画，防止清理后重新启动布局轮询。

验证记录：

- 新增主窗口回归最初 4 failed，协调器回归最初 5 failed，关闭回归最初 1 failed，均先复现后修复。
- 协调器完整直接文件 `test_responsive_layout_controller.py`：54 passed。
- 最终动画、主窗口过渡、正文空间恢复与关闭组合：42 passed。覆盖三页、连续反向、键盘、隐藏、
  中途切换宽度/22 号字/主题及关闭。原有正文空间测试改为等待动画完成，保留全部几何断言。
- 设备选择与相关 viewport、主题字体、导航 resize 组合其余 60 项通过；上述正文空间等待问题
  在最终 42 项组合中修复并验证。总计本轮直接及关联回归 156 项通过，未触发全量测试。
- 同条件带 cProfile 的主窗口再次展开约 207 ms、13 次更新，动画期间响应式规划为零。
  Windows 原生探针开启云母时，12 号字首开、收起、再次展开的更新间隔中位数约 16–17 ms，
  均有 13 个不同正文绘制位置。22 号字独立原生进程首开也保持约 16 ms 中位间隔。
- 测量使用真实 Qt 主窗口、隔离配置和替身设备，不代表实机 ADB 操作或每台机器的帧率保证。
  首次列表创建仍有一次初始化成本，动画结束后的布局收敛也有一次性成本。
  混合场景有一次 22 号字首开帧间隔异常，独立进程和相同顺序重测均未复现，不能确定原因。
  原生复测中列表初次创建约 52 ms，结束收敛约 58–234 ms；这些成本没有计入动画帧率改善。
- 修改生产与测试文件的 Ruff、相关五个生产模块 Pyright（0 errors）、中文注释检查通过；
  项目文档链接/frontmatter 48 项及 `git diff --check` 通过。未触及运行依赖、资源与打包边界，
  不执行构建或 ADB 实机操作。

最后一次交互与关闭组合命令（42 passed）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_selector_responsive_transition.py tests/test_device_selector_animation.py tests/test_main_window_layout.py::test_inline_selector_reallocates_workspace_height_and_restores_after_collapse tests/test_phase2_mainframe_shutdown_gate.py
```

## 收起卡顿与跳动的二次修复

用户反馈多个页面收起仍卡顿后，本轮改为记录真实 MainFrame 的 Paint 与正文位置，
不再只以动画回调间隔判断画面。确认以下原因：

- 缓出曲线一开始移动过快；同条件首个可见位移约 39–53 px。
- 收起末尾的终点高度尚未落到父布局，协调器已经恢复规划；最后几像素最长等待约 182 ms。
- 水平布局输入未变化时仍重复规划和应用，迟到的 LayoutRequest 还会额外开启一代。
- 展开文案导致页头按钮宽度变化；收起时禁用整个容器，让列表瞬间切为灰色。

本轮修改仅涉及设备栏、响应式协调器与网格计划缓存：

- 改用缓入缓出曲线；设备摘要不变时保持按钮宽度。收起只退出焦点链、拦截操作，保留行外观。
- 终点先落实设备栏和父布局几何，实际绘制后解除暂停。隐藏、关闭、键盘提前完成仍立即解除；
  快速反向取消上一轮待绘制释放，不让旧回调终止新过渡。
- 过渡前已稳定且水平输入完全一致时，只校验一次并同步高度快照，不重排所有网格。
  终点迟到的布局反馈沿用现有低优先级清理机制；真实宽度、字体、主题和显式请求仍正常处理。
- 每个网格仅缓存最近的正常与保守计划；每次重新测量控件，字体、样式、模式、边距、
  间距或控件尺寸变化均使缓存失效，不积累窗口拖动历史。

验证记录：

- 最终帧回归先复现父布局仍停在旧高度，补同步后通过。迟到布局反馈回归先失败，修复后通过；
  三页集成保留严格的终点一次计算、零次重新应用断言，没有放宽测试。
- 选择区原有 50 项及最终动画 20 项通过；协调器、缓存与三页集成组合 96 项通过；
  关联宽度、字体、主题、正文空间与关闭组合 35 项通过，共 201 项直接和关联测试。
- 最终动画集在 150% 与 200% 缩放下各 20 passed。
- Windows 原生平台、云母开启、12/22 号字体与两种窗口宽度下，两组探针共 8 次展开/收起。
  起步位移约 2–5 px，所有场景没有重新应用网格。此前 182 ms 的收起场景最大绘制间隔
  降至约 22 ms；本次全部场景最大间隔约 29 ms，终点没有再出现百毫秒停顿。
- 首次创建列表仍有约 50 ms 初始化成本；测量使用隔离设置、替身设备和真实 Qt 主窗口，
  不代表用户进程或所有机器的帧率保证。未启动真实 ADB、未执行全量测试或打包。
- Ruff、相关六个生产模块 Pyright、中文注释、文档链接与差异检查通过。

主要验证命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_device_selector_animation.py tests/test_inline_device_selector.py tests/test_device_operation_selector.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_selector_responsive_transition.py tests/test_responsive_layout_controller.py tests/test_responsive_plan_cache.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_responsive_panels.py::test_remote_control_real_viewport_scan_uses_group_specific_columns tests/test_responsive_panels.py::test_runtime_12_to_22_font_metrics_match_fresh_remote_panel tests/test_responsive_panels.py::test_remote_overflow_row_constraints_clear_when_viewport_grows tests/test_main_window_layout.py::test_inline_selector_reallocates_workspace_height_and_restores_after_collapse tests/test_phase2_mainframe_shutdown_gate.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_responsive_panels.py::test_feature_theme_and_font_events_each_create_one_generation tests/test_responsive_panels.py::test_real_feature_viewport_resize_uses_one_generation_and_ignores_feedback tests/test_responsive_panels.py::test_queued_remote_reflow_unregisters_bindings_and_keeps_shutdown_once
```

第一条组合在补充待绘制终点中断用例前为 67 passed；新增用例后单独复测动画文件 20 passed，
其余 50 项无需重复。探针在被 Git 忽略的 `.tmp/` 中记录，不作为平台无关的帧率阈值测试。

## 设备列表文字闪跳的后续定位

用户继续反馈，并明确闪跳发生在展开列表和文字。上一轮的正文位置与帧间隔验证没有充分覆盖
列表内部的实际绘制位置；此前的验证结论不能代表这一问题已消失。

真实主窗口的文字 Paint 记录确认：同一设备行的列宽、文字内容和滚动值不变，但收起时其位置
仍会偏移数十像素。原因是先更新裁剪层高度、后由排队事件更新设备栏高度；中间的 QVBoxLayout
会挤压或拉高页头，把整个列表的顶部锚点移走，下一轮再移回。独立选择区与真实主窗口均复现。
另外，快速反向时调整 QVariantAnimation 时长会按旧进度发出中间值，造成同步的高度往返；
仅在处理完事件之后检查最终高度，会遗漏这类错误。

修复限定在 `DeviceContextBar`：每帧同步设备栏与直接父布局，确保高度分配完成后再进入绘制；
重配动画参数时用 `QSignalBlocker` 隔离旧进度。没有固定页头高度、修改背景或改变列宽规则。

验证记录：

- 新增 `test_selector_content_stability.py`，直接观察工具栏和各设备字段的 Paint 坐标，
  并记录反向点击中的同步高度；12/22 号字体下共 10 项先失败，修复后全部通过。
- 最终选择区、主窗口三页、字体中途变更、正文空间恢复及关闭组合共 111 passed。
  150% 与 200% 缩放下，文字位置与既有动画两个文件各 30 passed。
- Windows 原生主窗口覆盖远程控制、应用工具、系统工具，明暗主题、云母开启及 12/22 号字
  共 4 组、16 次展开/收起。实际设备名称 Paint 坐标每个场景均唯一，不再出现上下回跳。
- 另两组原生帧时采样没有重新应用网格；收起与再次展开最大绘制间隔约 17–20 ms。
  首次展开样本最大间隔约 34 ms，仍有初次创建成本，不将这些本机采样视为帧率保证。
- Ruff、相关生产模块 Pyright、中文注释、文档链接和差异检查通过。本轮使用替身设备与隔离设置，
  未操作真实 ADB、未运行全量测试或打包。

本轮关联组合命令（111 passed）：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_selector_content_stability.py tests/test_device_selector_animation.py tests/test_inline_device_selector.py tests/test_device_operation_selector.py tests/test_selector_responsive_transition.py tests/test_main_window_layout.py::test_inline_selector_reallocates_workspace_height_and_restores_after_collapse tests/test_phase2_mainframe_shutdown_gate.py
```

## 将经验应用到设备概览连接区

用户要求把既有平滑展开方式用于“连接设备”。沿用以下已经验证的约束：内容保持自然尺寸，
只改变透明外壳的裁剪高度；逐帧提交直接父布局；反向动画从当前高度开始，重设参数期间屏蔽
旧进度信号；终点完成绘制后再恢复昂贵的工作区布局。

连接区额外处理业务与滚动边界：

- 主窗口显式启用动画，独立使用 `DeviceConnectionPanel` 仍默认即时显隐。
- 工具栏后保留固定基础间距，面板后的额外间距随动画一起裁剪，消除首次显示的 14 px 跳变。
- 动画期间只同步概览滚动高度，暂停自动跟底；二维码完全展开且实际可见后才确认显示。
- 收起立即清除秘密、使请求失效并取消任务；离页、隐藏与退出不等待视觉动画。
- 收起的最后一帧由父级绘制确认；视口外没有可绘制区域时立即释放过渡，避免永久暂停布局。
- 重开时跳过已删除的历史控件，恢复有效控件的键盘焦点策略；不会为动画把整块表单置灰。

原生窄窗口复核另发现：工具栏改为上下排列时，摘要原有的伸缩权重变为纵向，导致它先吸收
剩余高度，再随连接面板增高逐帧缩小。文字内部位置稳定，但整个面板顶部会移动。回归直接
记录实际 Paint 坐标，并覆盖 860 px 窗口及 22 号字体；工具栏只在横排时分配摘要伸缩空间。

验证记录：

- 连接区动画与原有业务共 43 项通过；新增主窗口集成 7 项及原有连接入口 13 项通过。
- 关联配对布局、真实协调器替身流程、设备概览、选择区暂停/恢复和关闭组合 85 项通过。
  窄窗工具栏修正后，集成与受影响概览节点 25 项再次通过；去重共 148 项。
- 150% 与 200% 缩放下，13 项动画回归分别通过。
- Windows 原生窗口、云母开启，1120 px/12 号字深色与 860 px/22 号字浅色两组共 6 次展开/收起。
  实际文字绘制位置保持唯一，卡片位置单向移动；帧间隔中位数约 16 ms，最大约 33 ms，
  终点收敛约 6–11 ms。这是使用隔离配置及替身设备的本机采样，不作为帧率保证。
- Ruff、三个生产模块 Pyright、中文注释、文档链接/frontmatter 和差异检查通过。
  未操作真实 ADB、未运行全量测试或打包；未修改窗口云母材质与全局字体设置。

主要增量命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_connection_expansion_animation.py tests/test_device_connection.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_connection_expansion_integration.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_global_device_context.py -k 'connection_panel or device_overview_connects'
.\.venv\Scripts\python.exe -m pytest -q tests/test_wireless_pairing_layout.py tests/test_wireless_pairing_flow.py tests/test_selector_responsive_transition.py tests/test_device_hub_page.py::test_connection_toggle_only_shows_focus_border_for_keyboard tests/test_device_hub_page.py::test_device_overview_toolbar_preserves_selected_device_disconnect tests/test_device_hub_page.py::test_device_cards_fit_actual_fonts_and_preserve_keyboard_actions tests/test_device_hub_page.py::test_expanded_details_and_copy_fit_the_scroll_owner_at_large_font tests/test_phase2_mainframe_shutdown_gate.py::test_pairing_tasks_are_registered_before_ui_and_coordinator_shutdown
```
